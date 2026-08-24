"""Output contracts for the MCP tools.

The input half of every contract comes free: a tool's signature is typed, so
MCP publishes a full input schema with constraints, defaults and descriptions.
The output half does not. A tool annotated `-> dict[str, Any]` publishes

    {"additionalProperties": true, "title": "…DictOutput"}

which is a schema in name only — it tells a caller nothing about what came
back, and nothing can be validated against it.

These TypedDicts are that missing half. Declaring them makes the server
publish a real output schema per tool and return structured content beside the
JSON, so a caller can check a response instead of trusting it. Field meanings
live in `docs/tool-contracts.md`; `tests/test_contracts.py` keeps the two from
drifting apart.

Every key is always present, and optionality is carried by `X | None`. That
is partly a contract decision — `None` is an answer here, and "buyout rate is
null" means "measured, sample too thin to report", which is a finding rather
than a gap — and partly forced: the MCP SDK marks every property of a
published output schema as required, so a `NotRequired` key produces a schema
the server's own responses fail to validate against. A caller can therefore
rely on the key set never changing between calls.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from .policy import Action, Confidence, Diagnosis
from .snapshot import Reliability

__all__ = [
    "AuditEvidence",
    "AuditVerdict",
    "CalibrationBounds",
    "FunnelMeasurement",
    "ActionRecommendation",
    "SkuCoverage",
]

# `from` is a Python keyword, so this one needs the functional form.
Window = TypedDict("Window", {"from": str, "to": str})


class FunnelMeasurement(TypedDict):
    """What `measure_sku_funnel` returns: observation, never interpretation."""

    sku: str
    window: Window
    approval_rate: float | None
    buyout_rate: float | None
    return_rate: float | None
    leads: int
    approved: int
    shipped_resolved: int
    bought_out: int
    refused: int
    resolved_orders: int
    excluded_in_flight: int
    excluded_immature_cohort: int
    excluded_still_moving: int
    excluded_awaiting_call: int
    maturity_days: int
    cohort_cutoff: str
    min_sample: int
    reliability: Reliability
    snapshot_generated_at: str


class EconomicsInputs(TypedDict):
    """Every number the bounds were computed from.

    Published so a caller can trace a Stop CPL back to the price and cost it
    rests on without opening the dataset.
    """

    price_uah: float
    cogs_uah: float
    cogs_source: str | None
    cost_effective_from: str | None
    usd_uah: float
    upsell_uah: float
    return_fee_uah: float
    call_centre_fee_uah: float
    goal_ratio: float
    assumed_approval_rate: float
    assumed_buyout_rate: float


class ObservedRates(TypedDict):
    approval: float | None
    buyout: float | None


class CalibrationBounds(TypedDict):
    """What `recalibrate_cpl_bounds` returns."""

    sku: str
    rate_source: Literal["caller", "measured"]
    reliability: Reliability
    resolved_orders: int
    stop_cpl_assumed: float
    goal_cpl_assumed: float
    stop_cpl_observed: float | None
    goal_cpl_observed: float | None
    contribution_uah: float
    contribution_uah_assumed: float
    drift_pct: float | None
    target_above_breakeven: bool
    structural_loss: bool
    economics_reliable: bool
    observed_rates: ObservedRates
    inputs_used: EconomicsInputs


class Evidence(TypedDict):
    """The numeric chain behind a recommendation.

    The last three keys are `None` when the diagnosis tree returned before
    reaching them — on insufficient data and on structural loss, both of which
    are settled without ever testing for a rate collapse or an auction spike.
    """

    current_cpl: float
    stop_cpl_assumed: float
    goal_cpl_assumed: float
    stop_cpl_observed: float | None
    goal_cpl_observed: float | None
    contribution_uah: float | None
    observed_approval: float | None
    observed_buyout: float | None
    assumed_approval: float
    assumed_buyout: float
    margin_at_current_cpl: float | None
    reliability: Reliability
    economics_reliable: bool
    approval_collapsed: bool | None
    buyout_collapsed: bool | None
    spike_over_goal_pct: float | None


class AuditEvidence(Evidence):
    """The same chain, plus what was proposed and who proposed it.

    Separate from `Evidence` because only the audit has an outside proposal to
    record; folding these into the base type would oblige every recommendation
    to carry two permanently null fields.
    """

    proposed_action: Action
    source: str | None


class BreakevenCondition(TypedDict):
    """A condition, not a forecast — see the `note` field it ships with."""

    required_buyout_rate: float | None
    observed_buyout_rate: float
    points_needed: float | None
    note: str


class ActionRecommendation(TypedDict):
    """What `recommend_next_action` returns.

    `measurement` is embedded whole rather than summarised: the recommendation
    is only as good as the sample under it, and a caller that has the action
    without the sample size can act on noise.
    """

    sku: str
    action: Action
    diagnosis: Diagnosis
    rationale: str
    evidence: Evidence
    confidence: Confidence
    priority: int
    measurement: FunnelMeasurement
    breakeven_condition: BreakevenCondition | None


class AuditVerdict(TypedDict):
    """What `audit_ad_verdict` returns.

    `counter_recommendation` is `None` when the proposal is supported — there
    is nothing to counter — and also on `insufficient_data`, where declining to
    rule is itself the finding.
    """

    sku: str
    verdict: Literal["supported", "contradicted", "insufficient_data"]
    proposed_action: Action
    evidence: AuditEvidence
    counter_recommendation: Action | None
    reliability: Reliability
    rationale: str


class SkuRow(TypedDict):
    sku: str
    orders: int
    manufacturer: str | None
    has_economics: bool


class SkuCoverage(TypedDict):
    """What `list_covered_skus` returns."""

    snapshot_generated_at: str
    window: Window
    total_orders: int
    status_taxonomy: dict[str, str]
    products: list[SkuRow]
