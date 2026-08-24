"""Snapshot dataset loading and cohort selection.

The snapshot is an anonymised, point-in-time export of order cohorts. It is
the server's primary data source and requires no network access at runtime.

Cohort maturity is enforced here rather than in the tools, so that every
measurement in the system shares one definition of "resolved".
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

REPO = Path(__file__).resolve().parent.parent.parent

# ─── Status taxonomy ──────────────────────────────────────────────────
#
# Every status the CRM can hold, sorted by what it says about the two outcomes
# that matter. The grouping is evidence-based rather than inherited: each
# status was checked against whether its orders carry a waybill, and against
# its month-by-month counts. See docs/design-rationale.md §5.
#
# The important case is 35 "Відмова". It is absent from the CRM's own status
# list, and the business's reporting classifies it as `unknown` — so its 216
# orders are counted nowhere. All 216 carry a waybill, and the monthly pattern
# shows refusals migrating 32 (through July) → 35 (July) → 28 (August).
# Dropping it reads the July buyout rate as 70% against a measured 52.5%.

BOUGHT_OUT = frozenset({12})

# Shipped, and the customer did not take the parcel.
REFUSED = frozenset({28, 32, 35})

# Approved by the call centre; the parcel's fate is not yet known.
IN_TRANSIT = frozenset({9, 20})

# Approved by the call centre, not yet handed to the carrier.
APPROVED_UNSHIPPED = frozenset({26, 6})

# Still with the call centre — no decision either way.
PENDING_APPROVAL = frozenset({1, 2, 3, 4, 23, 25})

# Never reached shipment. 29 "Не підійшов / Немає розміру" is the one status
# carrying a genuine reason; the rest are administrative.
CANCELLED = frozenset({13, 15, 16, 17, 18, 19, 21, 22, 24, 29, 31, 33, 34})

# Reaching any of these means the call centre confirmed the order, whatever
# happened afterwards. This is the approval numerator.
APPROVED = BOUGHT_OUT | REFUSED | IN_TRANSIT | APPROVED_UNSHIPPED

KNOWN_STATUSES = APPROVED | PENDING_APPROVAL | CANCELLED

STATUS_NAMES = {
    6: "Виготовляється",
    9: "Доставляється",
    12: "Виконано (викуплено)",
    20: "Прибув у відділення",
    26: "Прийнято (підтверджено оператором)",
    28: "Повернення назад",
    29: "Не підійшов / Немає розміру",
    32: "Відмова на пошті",
    35: "Відмова",
}

ApprovalOutcome = Literal["approved", "rejected", "pending"]
DeliveryOutcome = Literal["bought_out", "refused", "in_transit", "not_shipped"]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def cohort_maturity_days() -> int:
    return _env_int("FC_COHORT_MATURITY_DAYS", 21)


def min_sample() -> int:
    return _env_int("FC_MIN_SAMPLE", 30)


def goal_ratio() -> float:
    return _env_float("FC_GOAL_RATIO", 0.70)


def usd_uah() -> float:
    return _env_float("FC_USD_UAH", 45.0)


class SnapshotError(RuntimeError):
    """The dataset is missing, unreadable, or not shaped like a snapshot."""


@dataclass(frozen=True)
class Order:
    order_id: int | None
    sku: str
    created_at: date
    status_id: int
    amount: float
    manufacturer: str | None
    campaign: str | None
    creative: str | None

    @property
    def approval_outcome(self) -> ApprovalOutcome:
        if self.status_id in APPROVED:
            return "approved"
        if self.status_id in CANCELLED:
            return "rejected"
        return "pending"

    @property
    def delivery_outcome(self) -> DeliveryOutcome:
        if self.status_id in BOUGHT_OUT:
            return "bought_out"
        if self.status_id in REFUSED:
            return "refused"
        if self.status_id in IN_TRANSIT:
            return "in_transit"
        return "not_shipped"


@dataclass(frozen=True)
class Snapshot:
    path: Path
    generated_at: str
    window_from: date
    window_to: date
    orders: tuple[Order, ...]
    economics: dict[str, dict[str, Any]]
    assumed: dict[str, float]

    @property
    def skus(self) -> set[str]:
        """Every product the snapshot can speak about — orders or economics."""
        return {o.sku for o in self.orders} | set(self.economics)

    def as_of(self) -> date:
        """The date the snapshot was taken.

        Maturity is measured against this, never against today: a stored
        dataset cannot age into new resolutions, and pretending otherwise
        would quietly reclassify in-flight parcels as refusals.
        """
        return self.window_to


def _snapshot_path() -> Path:
    raw = os.environ.get("FC_SNAPSHOT_PATH", "data/snapshot.json")
    path = Path(raw)
    return path if path.is_absolute() else REPO / path


def _economics_path(snapshot: Path) -> Path:
    raw = os.environ.get("FC_ECONOMICS_PATH")
    if raw:
        path = Path(raw)
        return path if path.is_absolute() else REPO / path
    return snapshot.parent / "economics.json"


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        variable = "FC_SNAPSHOT_PATH" if label == "Snapshot" else "FC_ECONOMICS_PATH"
        raise SnapshotError(
            f"{label} not found at {path}. Set {variable}, or run "
            "scripts/export_snapshot.py to produce it."
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"{label} at {path} is unreadable: {exc}") from exc


@lru_cache(maxsize=4)
def _load(snapshot_path: str, economics_path: str) -> Snapshot:
    snap_file = Path(snapshot_path)
    econ_file = Path(economics_path)
    raw = _read_json(snap_file, "Snapshot")
    econ = _read_json(econ_file, "Economics")

    rows = raw.get("orders")
    if not isinstance(rows, list):
        raise SnapshotError(f"Snapshot at {snap_file} has no 'orders' array.")

    orders = []
    for row in rows:
        try:
            orders.append(
                Order(
                    order_id=row.get("order_id"),
                    sku=str(row["sku"]),
                    created_at=date.fromisoformat(row["created_at"][:10]),
                    status_id=int(row["status_id"]),
                    amount=float(row.get("amount") or 0.0),
                    manufacturer=row.get("manufacturer"),
                    campaign=row.get("campaign"),
                    creative=row.get("creative"),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SnapshotError(
                f"Snapshot row {row.get('order_id', '?')} is malformed: {exc}"
            ) from exc

    window = raw.get("window", {})
    return Snapshot(
        path=snap_file,
        generated_at=raw.get("generated_at", "unknown"),
        window_from=date.fromisoformat(window.get("from", "1970-01-01")),
        window_to=date.fromisoformat(window.get("to", "1970-01-01")),
        orders=tuple(orders),
        economics=econ.get("products", {}),
        assumed=econ.get("assumed", {}),
    )


def load_snapshot() -> Snapshot:
    """The configured snapshot, cached across calls within one process."""
    snap = _snapshot_path()
    return _load(str(snap), str(_economics_path(snap)))


@dataclass(frozen=True)
class Cohort:
    """Orders for one product over one window, split by what has resolved."""

    sku: str
    window_from: date
    window_to: date
    maturity_days: int
    cutoff: date
    mature: tuple[Order, ...]
    immature: tuple[Order, ...]

    @property
    def leads(self) -> int:
        return len(self.mature)

    @property
    def approved(self) -> int:
        return sum(1 for o in self.mature if o.approval_outcome == "approved")

    @property
    def pending(self) -> int:
        return sum(1 for o in self.mature if o.approval_outcome == "pending")

    @property
    def bought_out(self) -> int:
        return sum(1 for o in self.mature if o.delivery_outcome == "bought_out")

    @property
    def refused(self) -> int:
        return sum(1 for o in self.mature if o.delivery_outcome == "refused")

    @property
    def in_transit(self) -> int:
        return sum(1 for o in self.mature if o.delivery_outcome == "in_transit")

    @property
    def shipped_resolved(self) -> int:
        """Parcels whose fate is known — the buyout denominator."""
        return self.bought_out + self.refused

    @property
    def excluded_in_flight(self) -> int:
        """Everything set aside: young cohorts, plus parcels still moving."""
        return len(self.immature) + self.in_transit + self.pending


def select_cohort(
    snapshot: Snapshot,
    sku: str,
    window_from: date | None = None,
    window_to: date | None = None,
    maturity_days: int | None = None,
) -> Cohort:
    """Orders for one product, split into resolved and still-in-flight.

    An order placed a week ago is neither a buyout nor a return; counting it
    as a non-buyout biases the rate downward, worst on exactly the newly
    launched products where the scale-or-stop decision is being made now. The
    split happens here so that no tool can skip it.
    """
    days = cohort_maturity_days() if maturity_days is None else maturity_days
    start = window_from or snapshot.window_from
    end = window_to or snapshot.window_to
    cutoff = snapshot.as_of() - timedelta(days=days)

    mature: list[Order] = []
    immature: list[Order] = []
    for order in snapshot.orders:
        if order.sku != sku:
            continue
        if not (start <= order.created_at <= end):
            continue
        (mature if order.created_at <= cutoff else immature).append(order)

    return Cohort(
        sku=sku,
        window_from=start,
        window_to=end,
        maturity_days=days,
        cutoff=cutoff,
        mature=tuple(mature),
        immature=tuple(immature),
    )


def reliability_of(resolved: int, threshold: int | None = None) -> str:
    """`high` | `low` | `insufficient`, from the resolved sample size.

    Below the threshold the server declines to report a rate at all. Replacing
    a portfolio constant with a confident-looking number drawn from eleven
    orders swaps one false certainty for another.
    """
    limit = min_sample() if threshold is None else threshold
    if resolved < limit:
        return "insufficient"
    return "high" if resolved >= limit * 3 else "low"
