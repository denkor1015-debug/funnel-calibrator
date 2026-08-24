"""Unit-economics recomputation.

Given observed funnel rates for a product, recompute the CPL bounds that
follow from them:

    returns_cost = ((1 - buyout) / buyout) * return_fee
    contribution = price + upsell - cogs - returns_cost - call_centre_fee
    stop_cpl     = contribution * (approval * buyout) / usd_uah
    goal_cpl     = stop_cpl * goal_ratio

Stop CPL is the cost per lead at which profit reaches zero; Goal CPL is the
target the campaign should be optimised toward.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .snapshot import Snapshot, goal_ratio, usd_uah

# Defaults matching the business's own econ.py, used only when the economics
# file omits them. They are portfolio-wide constants — the very thing this
# server exists to replace per product — so they are never silently mixed with
# observed rates: `Calibration` records which of the two produced each bound.
FALLBACK_ASSUMED = {
    "approval_rate": 0.65,
    "buyout_rate": 0.525,
    "return_fee_uah": 94.0,
    "call_centre_fee_uah": 23.0,
    "upsell_uah": 95.0,
}


class EconomicsError(RuntimeError):
    """Price or cost inputs are missing for a product."""


@dataclass(frozen=True)
class Bounds:
    """The CPL bounds implied by one pair of funnel rates."""

    approval_rate: float
    buyout_rate: float
    returns_cost_uah: float
    call_centre_cost_uah: float
    contribution_uah: float
    stop_cpl: float
    goal_cpl: float

    @property
    def structural_loss(self) -> bool:
        """True when no cost per lead, however low, makes the product pay.

        Contribution is what is left before a single hryvnia of advertising.
        At or below zero the product loses money on every parcel collected,
        which is a finding rather than an error.
        """
        return self.contribution_uah <= 0


@dataclass(frozen=True)
class Calibration:
    sku: str
    price_uah: float
    cogs_uah: float
    usd_uah: float
    assumed: Bounds
    observed: Bounds | None
    economics_reliable: bool
    inputs_used: dict[str, Any] = field(default_factory=dict)

    @property
    def drift_pct(self) -> float | None:
        """How far the true bound sits from the one currently in use.

        Negative means the real break-even is *below* the assumed one — the
        dangerous direction, because the campaign is then being optimised
        toward a target the product cannot pay for.
        """
        if self.observed is None or self.assumed.stop_cpl == 0:
            return None
        return round(
            (self.observed.stop_cpl - self.assumed.stop_cpl) / abs(self.assumed.stop_cpl) * 100,
            1,
        )

    @property
    def target_above_breakeven(self) -> bool:
        """The failure this server exists to catch.

        The assumed *target* sitting above the true *break-even* means every
        lead bought at target loses money, while the ads dashboard shows a
        cost per lead comfortably inside its goal.
        """
        if self.observed is None:
            return False
        return self.assumed.goal_cpl > self.observed.stop_cpl


def compute_bounds(
    price_uah: float,
    cogs_uah: float,
    approval_rate: float,
    buyout_rate: float,
    *,
    return_fee_uah: float,
    call_centre_fee_uah: float,
    upsell_uah: float,
    rate_usd_uah: float,
    ratio: float,
) -> Bounds:
    """CPL bounds for one product at one pair of rates.

    Mirrors `tools/econ.py` in the business repository exactly, including the
    detail that most hand calculations get wrong: the call-centre fee is paid
    per *confirmed order*, not per parcel collected, so it scales with 1/buyout
    rather than staying constant. Holding it fixed flatters a bad buyout rate.
    """
    if not 0 < buyout_rate <= 1:
        raise ValueError(f"buyout_rate must be in (0, 1], got {buyout_rate}")
    if not 0 < approval_rate <= 1:
        raise ValueError(f"approval_rate must be in (0, 1], got {approval_rate}")
    if rate_usd_uah <= 0:
        raise ValueError(f"usd_uah must be positive, got {rate_usd_uah}")

    returns_cost = ((1 - buyout_rate) / buyout_rate) * return_fee_uah
    call_centre = (1 / buyout_rate) * call_centre_fee_uah
    contribution = price_uah + upsell_uah - cogs_uah - returns_cost - call_centre
    stop = contribution * (approval_rate * buyout_rate) / rate_usd_uah

    return Bounds(
        approval_rate=round(approval_rate, 4),
        buyout_rate=round(buyout_rate, 4),
        returns_cost_uah=round(returns_cost, 2),
        call_centre_cost_uah=round(call_centre, 2),
        contribution_uah=round(contribution, 2),
        stop_cpl=round(stop, 2),
        goal_cpl=round(stop * ratio, 2),
    )


def calibrate(
    snapshot: Snapshot,
    sku: str,
    observed_approval: float | None,
    observed_buyout: float | None,
    rate_usd_uah: float | None = None,
) -> Calibration:
    """Assumed and observed bounds for one product, side by side.

    Raises `EconomicsError` when price or cost is unknown: guessing a cost
    would produce a confident number with nothing behind it, and the whole
    point of the server is to stop exactly that.
    """
    product = snapshot.economics.get(sku)
    if product is None:
        raise EconomicsError(
            f"No price or cost on file for '{sku}'. Known products: "
            f"{len(snapshot.economics)}. Add it to the business cost history "
            "and re-export, or measure a product that has economics."
        )

    price = float(product["price_uah"])
    cogs = float(product["cogs_uah"])
    rate = rate_usd_uah or float(product.get("usd_uah") or usd_uah())
    ratio = goal_ratio()

    constants = {**FALLBACK_ASSUMED, **snapshot.assumed}
    shared = {
        "return_fee_uah": float(constants["return_fee_uah"]),
        "call_centre_fee_uah": float(constants["call_centre_fee_uah"]),
        "upsell_uah": float(constants["upsell_uah"]),
        "rate_usd_uah": rate,
        "ratio": ratio,
    }

    assumed = compute_bounds(
        price,
        cogs,
        float(constants["approval_rate"]),
        float(constants["buyout_rate"]),
        **shared,
    )

    observed = None
    if observed_approval is not None and observed_buyout is not None:
        observed = compute_bounds(price, cogs, observed_approval, observed_buyout, **shared)

    return Calibration(
        sku=sku,
        price_uah=price,
        cogs_uah=cogs,
        usd_uah=rate,
        assumed=assumed,
        observed=observed,
        economics_reliable=bool(product.get("economics_reliable")),
        inputs_used={
            "price_uah": price,
            "cogs_uah": cogs,
            "cogs_source": product.get("source"),
            "cost_effective_from": product.get("cost_effective_from"),
            "usd_uah": rate,
            "upsell_uah": shared["upsell_uah"],
            "return_fee_uah": shared["return_fee_uah"],
            "call_centre_fee_uah": shared["call_centre_fee_uah"],
            "goal_ratio": ratio,
            "assumed_approval_rate": float(constants["approval_rate"]),
            "assumed_buyout_rate": float(constants["buyout_rate"]),
        },
    )


def breakeven_buyout(
    price_uah: float,
    cogs_uah: float,
    approval_rate: float,
    target_cpl: float,
    *,
    return_fee_uah: float,
    call_centre_fee_uah: float,
    upsell_uah: float,
    rate_usd_uah: float,
) -> float | None:
    """The buyout rate at which `target_cpl` is exactly break-even.

    Answers "how much would buyout have to improve for this CPL to pay?" — a
    condition, not a forecast. Returns None when no rate in (0, 1] suffices.

    Solved by bisection rather than algebraically: stop CPL is monotonic in
    buyout over this range, and bisection keeps the relationship visible
    instead of hiding it in a rearranged quadratic.
    """
    if target_cpl <= 0:
        return None

    def stop_at(buyout: float) -> float:
        return compute_bounds(
            price_uah,
            cogs_uah,
            approval_rate,
            buyout,
            return_fee_uah=return_fee_uah,
            call_centre_fee_uah=call_centre_fee_uah,
            upsell_uah=upsell_uah,
            rate_usd_uah=rate_usd_uah,
            ratio=1.0,
        ).stop_cpl

    if stop_at(1.0) < target_cpl:
        return None

    low, high = 1e-4, 1.0
    if stop_at(low) >= target_cpl:
        return round(low, 4)
    for _ in range(60):
        mid = (low + high) / 2
        if stop_at(mid) < target_cpl:
            low = mid
        else:
            high = mid
    return round(high, 4)
