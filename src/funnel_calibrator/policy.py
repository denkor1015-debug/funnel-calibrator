"""Failure-mode diagnosis and action recommendation.

A product missing its CPL target is not one problem but several, each with a
different remedy. Cheap leads that fail to convert on the phone indicate a
targeting or creative problem; leads that convert but fail at the post office
indicate an offer or price problem. Recommending the wrong remedy is worse
than recommending none.

This module maps observed evidence to a diagnosis, and a diagnosis to an
action, keeping that mapping explicit and inspectable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .calibration import Calibration

Action = Literal[
    "scale",
    "hold",
    "pause_retry",
    "stop",
    "full_stop",
    "reprice",
    "new_creative",
    "refresh_creative",
]

Diagnosis = Literal[
    "insufficient_data",
    "structural_loss",
    "contested_auction",
    "traffic_quality",
    "offer_mismatch",
    "creative_fatigue",
    "weak_offer_or_creative",
    "healthy",
]

# How far a product's own rate must fall below the portfolio assumption before
# the gap counts as a signal rather than sampling noise. Eight points is close
# to the spread between the two call-centre operators the business has used,
# so anything smaller cannot be told apart from a change of staff.
RATE_COLLAPSE_MARGIN = 0.08

# A contested auction shows up as a sustained CPL spike, not a single bad day.
CONTESTED_SPIKE = 0.40
CONTESTED_MIN_DAYS = 3

# Meta's own fatigue threshold for a cold audience.
FATIGUE_FREQUENCY = 2.5


Confidence = Literal["high", "medium", "low"]

_CONFIDENCE_ORDER: tuple[Confidence, ...] = ("low", "medium", "high")


@dataclass(frozen=True)
class Recommendation:
    action: Action
    diagnosis: Diagnosis
    rationale: str
    evidence: dict[str, Any]
    confidence: Confidence
    priority: int


def _capped(confidence: Confidence, reliability: str) -> Confidence:
    """Confidence can never outrank the sample it rests on.

    A rule can be certain about its own logic and still be reading a thin
    sample. Reporting `high` on a `low`-reliability measurement would hide
    exactly the uncertainty the reliability flag exists to expose.
    """
    if reliability != "low":
        return confidence
    ceiling = "medium"
    if _CONFIDENCE_ORDER.index(confidence) <= _CONFIDENCE_ORDER.index(ceiling):
        return confidence
    return ceiling


def _margin_at(calibration: Calibration, current_cpl: float) -> float | None:
    """Headroom between the true break-even bound and what is being paid.

    Positive means the product still pays at this cost per lead.
    """
    if calibration.observed is None:
        return None
    return round(calibration.observed.stop_cpl - current_cpl, 2)


def recommend(
    calibration: Calibration,
    current_cpl: float,
    observed_approval: float | None,
    observed_buyout: float | None,
    *,
    assumed_approval: float,
    assumed_buyout: float,
    reliability: str,
    cpl_trend_days: int | None = None,
    competitor_active: bool | None = None,
    creative_frequency: float | None = None,
    creative_ctr_trend: float | None = None,
) -> Recommendation:
    """Diagnose a product, with confidence held to what the sample supports."""
    result = _diagnose(
        calibration,
        current_cpl,
        observed_approval,
        observed_buyout,
        assumed_approval=assumed_approval,
        assumed_buyout=assumed_buyout,
        reliability=reliability,
        cpl_trend_days=cpl_trend_days,
        competitor_active=competitor_active,
        creative_frequency=creative_frequency,
        creative_ctr_trend=creative_ctr_trend,
    )
    # Declining to answer is the one verdict a thin sample cannot weaken.
    if result.diagnosis == "insufficient_data":
        return result
    capped = _capped(result.confidence, reliability)
    if capped == result.confidence:
        return result
    return Recommendation(
        action=result.action,
        diagnosis=result.diagnosis,
        rationale=result.rationale,
        evidence=result.evidence,
        confidence=capped,
        priority=result.priority,
    )


def _diagnose(
    calibration: Calibration,
    current_cpl: float,
    observed_approval: float | None,
    observed_buyout: float | None,
    *,
    assumed_approval: float,
    assumed_buyout: float,
    reliability: str,
    cpl_trend_days: int | None = None,
    competitor_active: bool | None = None,
    creative_frequency: float | None = None,
    creative_ctr_trend: float | None = None,
) -> Recommendation:
    """Map evidence to a diagnosis, and the diagnosis to an action.

    Order matters. The tests run cheapest-to-refute first: a structural loss
    cannot be fixed by any advertising change, so it must be caught before any
    recommendation about creative or price is reached.
    """
    observed = calibration.observed
    evidence: dict[str, Any] = {
        "current_cpl": current_cpl,
        "stop_cpl_assumed": calibration.assumed.stop_cpl,
        "goal_cpl_assumed": calibration.assumed.goal_cpl,
        "stop_cpl_observed": observed.stop_cpl if observed else None,
        "goal_cpl_observed": observed.goal_cpl if observed else None,
        "contribution_uah": observed.contribution_uah if observed else None,
        "observed_approval": observed_approval,
        "observed_buyout": observed_buyout,
        "assumed_approval": assumed_approval,
        "assumed_buyout": assumed_buyout,
        "margin_at_current_cpl": _margin_at(calibration, current_cpl),
        "reliability": reliability,
        "economics_reliable": calibration.economics_reliable,
        # Seeded null and overwritten below once the tree gets that far. The
        # two early returns settle without ever testing for a collapse or a
        # spike, and the published output schema requires the keys to be there
        # either way — a caller can rely on the key set, not just the values.
        "approval_collapsed": None,
        "buyout_collapsed": None,
        "spike_over_goal_pct": None,
    }

    # 1 · No measurement worth the name. Decline rather than guess.
    if observed is None or reliability == "insufficient":
        return Recommendation(
            action="hold",
            diagnosis="insufficient_data",
            rationale=(
                "Too few resolved orders to measure this product's own rates. "
                "Holding on the portfolio assumption is the honest position: "
                "a rate drawn from this sample would be noise presented as "
                "signal."
            ),
            evidence=evidence,
            confidence="high",
            priority=3,
        )

    # 2 · Contribution ≤ 0. No cost per lead rescues this; check it first.
    if observed.structural_loss:
        return Recommendation(
            action="full_stop",
            diagnosis="structural_loss",
            rationale=(
                f"Contribution is {observed.contribution_uah:.0f} ₴ before any "
                "advertising spend, so every parcel collected loses money. "
                "This is a price or cost problem, and no cost per lead fixes "
                "it."
            ),
            evidence=evidence,
            confidence="high",
            priority=1,
        )

    over_stop = current_cpl > observed.stop_cpl
    over_goal = current_cpl > observed.goal_cpl
    approval_collapsed = observed_approval is not None and (
        observed_approval < assumed_approval - RATE_COLLAPSE_MARGIN
    )
    buyout_collapsed = observed_buyout is not None and (
        observed_buyout < assumed_buyout - RATE_COLLAPSE_MARGIN
    )
    evidence["approval_collapsed"] = approval_collapsed
    evidence["buyout_collapsed"] = buyout_collapsed

    # 3 · Contested auction. The spike must be both large and sustained, and
    # the competitor must be on this product — the business's own analysis
    # showed the collision is per-SKU, not account-wide.
    spike = current_cpl / observed.goal_cpl - 1 if observed.goal_cpl > 0 else 0.0
    evidence["spike_over_goal_pct"] = round(spike * 100, 1)
    if (
        competitor_active
        and spike >= CONTESTED_SPIKE
        and (cpl_trend_days or 0) >= CONTESTED_MIN_DAYS
    ):
        return Recommendation(
            action="pause_retry",
            diagnosis="contested_auction",
            rationale=(
                f"Cost per lead is {spike:.0%} above target and has held for "
                f"{cpl_trend_days} days with a known competitor on this "
                "product. The auction is the problem, not the offer — pausing "
                "and retrying costs less than rebuilding a product that works."
            ),
            evidence=evidence,
            confidence="medium",
            priority=2,
        )

    # 4 · Cheap leads that do not convert on the phone. Price is not the
    # lever here; a price cut would make a targeting problem more expensive.
    if approval_collapsed and not over_stop:
        return Recommendation(
            action="new_creative",
            diagnosis="traffic_quality",
            rationale=(
                f"Leads are affordable ({current_cpl:.2f} against a break-even "
                f"of {observed.stop_cpl:.2f}), but only "
                f"{observed_approval:.0%} confirm on the call against an "
                f"assumed {assumed_approval:.0%}. Cheap leads with weak intent "
                "are a creative and audience problem, not a price problem."
            ),
            evidence=evidence,
            confidence="medium",
            priority=2,
        )

    # 5 · Leads convert but parcels are not collected. The mirror image, and
    # the reason these two are separated rather than both called "underperforming".
    if buyout_collapsed:
        return Recommendation(
            action="reprice",
            diagnosis="offer_mismatch",
            rationale=(
                f"Only {observed_buyout:.0%} of parcels are collected against "
                f"an assumed {assumed_buyout:.0%}, while the call centre "
                "confirms normally. The gap opens after the customer has "
                "already said yes — price band, sizing, or an expectation the "
                "landing page sets and the parcel does not meet."
            ),
            evidence=evidence,
            confidence="medium",
            priority=1 if over_stop else 2,
        )

    # 6 · Fatigue: the cost is drifting up on a worn creative, before the
    # product itself is the problem.
    if (
        over_goal
        and creative_frequency is not None
        and creative_frequency >= FATIGUE_FREQUENCY
        and (creative_ctr_trend is None or creative_ctr_trend < 0)
    ):
        return Recommendation(
            action="refresh_creative",
            diagnosis="creative_fatigue",
            rationale=(
                f"Frequency has reached {creative_frequency:.1f} with cost per "
                "lead drifting above target and click-through falling. The "
                "audience has seen this creative; refresh it before writing "
                "off the product."
            ),
            evidence=evidence,
            confidence="medium",
            priority=3,
        )

    # 7 · Above the true break-even with no other explanation.
    if over_stop:
        return Recommendation(
            action="stop",
            diagnosis="weak_offer_or_creative",
            rationale=(
                f"Cost per lead {current_cpl:.2f} is above this product's true "
                f"break-even of {observed.stop_cpl:.2f}, with approval and "
                "buyout both near assumption and no competitor signal. Nothing "
                "in the funnel explains the price of a lead — stop, then "
                "autopsy the creative."
            ),
            evidence=evidence,
            confidence="high",
            priority=1,
        )

    # 8 · Healthy. Scale only with room beneath the target, not merely beneath
    # break-even: break-even is where the profit is zero.
    if current_cpl <= observed.goal_cpl:
        return Recommendation(
            action="scale",
            diagnosis="healthy",
            rationale=(
                f"Cost per lead {current_cpl:.2f} sits at or below the "
                f"recalibrated target of {observed.goal_cpl:.2f}, with "
                f"{observed.contribution_uah:.0f} ₴ contribution per parcel "
                "collected. There is room to buy more of this."
            ),
            evidence=evidence,
            confidence="high",
            priority=3,
        )

    return Recommendation(
        action="hold",
        diagnosis="healthy",
        rationale=(
            f"Cost per lead {current_cpl:.2f} is above the target "
            f"{observed.goal_cpl:.2f} but still below break-even "
            f"{observed.stop_cpl:.2f}. The product pays, with no margin for "
            "error — hold rather than scale."
        ),
        evidence=evidence,
        confidence="medium",
        priority=3,
    )


# Which recommendations a proposed action is consistent with. `audit_ad_verdict`
# compares an outside proposal against what the evidence supports, so it needs
# to know that "stop" and "full_stop" agree in direction while "scale" and
# "stop" do not.
COMPATIBLE: dict[str, set[str]] = {
    "scale": {"scale"},
    "hold": {"hold", "scale"},
    "pause_retry": {"pause_retry", "hold", "refresh_creative"},
    "stop": {"stop", "full_stop"},
    "full_stop": {"full_stop"},
    "reprice": {"reprice", "full_stop"},
    "new_creative": {"new_creative", "refresh_creative"},
    "refresh_creative": {"refresh_creative", "new_creative", "hold"},
}
