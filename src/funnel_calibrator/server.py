"""MCP server entrypoint.

Exposes the calibration toolset over stdio. Runs as a process separate from
the agent; see README for independent start instructions.

Four tools, split by the kind of claim each makes: what happened, what it
implies for the bounds, what to do about it, and whether an outside proposal
survives contact with the evidence.

Every tool is read-only over the local snapshot. The server opens no network
connection and writes nothing.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from . import __version__
from .calibration import (
    EconomicsError,
    breakeven_buyout,
    calibrate,
)
from .contracts import (
    ActionRecommendation,
    AuditEvidence,
    AuditVerdict,
    BreakevenCondition,
    CalibrationBounds,
    FunnelMeasurement,
    SkuCoverage,
    SkuRow,
)
from .policy import COMPATIBLE, recommend
from .snapshot import (
    STATUS_NAMES,
    Snapshot,
    SnapshotError,
    load_snapshot,
    min_sample,
    reliability_of,
    select_cohort,
)

server = MCPServer(
    name="funnel-calibrator",
    version=__version__,
    instructions=(
        "Calibrates cash-on-delivery advertising decisions against measured "
        "funnel performance. In this business the outcome of an ad is known "
        "two to four weeks after the spend, so targets are set from "
        "portfolio-wide constants that individual products violate. Measure "
        "the product first, recalibrate its bounds, then judge any decision "
        "against the corrected numbers rather than the assumed ones."
    ),
)

READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}

ACTIONS = (
    "scale",
    "hold",
    "pause_retry",
    "stop",
    "full_stop",
    "reprice",
    "new_creative",
    "refresh_creative",
)


# ─── Shared argument handling ─────────────────────────────────────────
#
# Every failure below names the offending input. An agent that receives
# "unknown product" without being told which product it asked about cannot
# tell a typo from a genuinely absent record.


def _snapshot() -> Snapshot:
    try:
        return load_snapshot()
    except SnapshotError as exc:
        raise ToolError(str(exc)) from exc


def _require_sku(snapshot: Snapshot, sku: str) -> str:
    code = (sku or "").strip()
    if not code:
        raise ToolError("`sku` is required and cannot be empty.")
    if code not in snapshot.skus:
        near = sorted(s for s in snapshot.skus if s.startswith(code[:3]))[:5]
        hint = f" Closest codes in the snapshot: {', '.join(near)}." if near else ""
        raise ToolError(
            f"Unknown product code '{code}'. The snapshot holds "
            f"{len(snapshot.skus)} products.{hint}"
        )
    return code


def _parse_window(
    snapshot: Snapshot, window_from: str | None, window_to: str | None
) -> tuple[date, date]:
    def parse(value: str | None, label: str, fallback: date) -> date:
        if not value:
            return fallback
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ToolError(f"`{label}` must be an ISO date (YYYY-MM-DD); got '{value}'.") from exc

    start = parse(window_from, "window_from", snapshot.window_from)
    end = parse(window_to, "window_to", snapshot.window_to)
    if start > end:
        raise ToolError(
            f"`window_from` ({start}) is after `window_to` ({end}); "
            "the window is empty by construction."
        )
    return start, end


def _measure(
    snapshot: Snapshot,
    sku: str,
    window_from: str | None = None,
    window_to: str | None = None,
    maturity_days: int | None = None,
) -> FunnelMeasurement:
    """The measurement every other tool builds on."""
    if maturity_days is not None and not 0 <= maturity_days <= 90:
        raise ToolError(f"`maturity_days` must be between 0 and 90; got {maturity_days}.")

    start, end = _parse_window(snapshot, window_from, window_to)
    cohort = select_cohort(snapshot, sku, start, end, maturity_days)

    approval_base = cohort.leads
    buyout_base = cohort.shipped_resolved
    reliability = reliability_of(buyout_base)

    approval_rate = (
        round(cohort.approved / approval_base, 4) if approval_base >= min_sample() else None
    )
    buyout_rate = (
        round(cohort.bought_out / buyout_base, 4) if reliability != "insufficient" else None
    )
    return_rate = round(cohort.refused / buyout_base, 4) if reliability != "insufficient" else None

    return {
        "sku": sku,
        "window": {"from": start.isoformat(), "to": end.isoformat()},
        "approval_rate": approval_rate,
        "buyout_rate": buyout_rate,
        "return_rate": return_rate,
        "leads": approval_base,
        "approved": cohort.approved,
        "shipped_resolved": buyout_base,
        "bought_out": cohort.bought_out,
        "refused": cohort.refused,
        "resolved_orders": buyout_base,
        "excluded_in_flight": cohort.excluded_in_flight,
        "excluded_immature_cohort": len(cohort.immature),
        "excluded_still_moving": cohort.in_transit,
        "excluded_awaiting_call": cohort.pending,
        "maturity_days": cohort.maturity_days,
        "cohort_cutoff": cohort.cutoff.isoformat(),
        "min_sample": min_sample(),
        "reliability": reliability,
        "snapshot_generated_at": snapshot.generated_at,
    }


# ─── Tools ────────────────────────────────────────────────────────────


@server.tool(
    title="Measure a product's funnel",
    description=(
        "Measure the observed call-centre approval, post-office buyout, and "
        "return rates for one product over a date window, counting only order "
        "cohorts old enough to have resolved. Use this before any decision "
        "that depends on approval or buyout rates, instead of assuming the "
        "portfolio-wide 65% approval and 52.5% buyout. Returns rates together "
        "with sample size and a reliability flag, and returns null rates with "
        "reliability 'insufficient' rather than a number when the resolved "
        "sample is too small to support a conclusion. Read-only."
    ),
    annotations=READ_ONLY,
)
def measure_sku_funnel(
    sku: Annotated[
        str, Field(description="Product code as it appears in the snapshot, e.g. 21-183")
    ],
    window_from: Annotated[
        str | None,
        Field(description="ISO date YYYY-MM-DD; defaults to the snapshot start"),
    ] = None,
    window_to: Annotated[
        str | None,
        Field(description="ISO date YYYY-MM-DD; defaults to the snapshot date"),
    ] = None,
    maturity_days: Annotated[
        int | None,
        Field(
            description=(
                "Days an order must be old before it counts as resolved. "
                "Defaults to FC_COHORT_MATURITY_DAYS (21). Range 0–90."
            ),
            ge=0,
            le=90,
        ),
    ] = None,
) -> FunnelMeasurement:
    snapshot = _snapshot()
    code = _require_sku(snapshot, sku)
    return _measure(snapshot, code, window_from, window_to, maturity_days)


@server.tool(
    title="Recalibrate CPL bounds",
    description=(
        "Recompute Stop CPL (the cost per lead at which profit reaches zero) "
        "and Goal CPL (the optimisation target) for one product from its own "
        "measured funnel rates instead of portfolio-wide assumptions, and "
        "report the drift against the baseline currently in use. Measures the "
        "product itself when observed rates are not supplied. Use whenever a "
        "cost-per-lead target is being set, defended, or questioned. Flags the "
        "case where the assumed target sits above the true break-even, which "
        "is invisible in the ads dashboard. Read-only."
    ),
    annotations=READ_ONLY,
)
def recalibrate_cpl_bounds(
    sku: Annotated[str, Field(description="Product code, e.g. 21-183")],
    observed_approval: Annotated[
        float | None,
        Field(
            description="Measured approval rate 0–1; measured on demand when omitted",
            gt=0,
            le=1,
        ),
    ] = None,
    observed_buyout: Annotated[
        float | None,
        Field(
            description="Measured buyout rate 0–1; measured on demand when omitted",
            gt=0,
            le=1,
        ),
    ] = None,
    usd_uah: Annotated[
        float | None,
        Field(description="Hryvnia per US dollar; defaults to the product's rate", gt=0),
    ] = None,
    window_from: Annotated[
        str | None, Field(description="ISO date, used only when measuring on demand")
    ] = None,
    window_to: Annotated[
        str | None, Field(description="ISO date, used only when measuring on demand")
    ] = None,
) -> CalibrationBounds:
    snapshot = _snapshot()
    code = _require_sku(snapshot, sku)

    measurement = _measure(snapshot, code, window_from, window_to)
    approval = observed_approval if observed_approval is not None else measurement["approval_rate"]
    buyout = observed_buyout if observed_buyout is not None else measurement["buyout_rate"]
    supplied = observed_approval is not None or observed_buyout is not None

    try:
        result = calibrate(snapshot, code, approval, buyout, usd_uah)
    except EconomicsError as exc:
        raise ToolError(str(exc)) from exc
    except ValueError as exc:
        raise ToolError(f"Invalid rate for '{code}': {exc}") from exc

    observed = result.observed
    return {
        "sku": code,
        "rate_source": "caller" if supplied else "measured",
        "reliability": measurement["reliability"],
        "resolved_orders": measurement["resolved_orders"],
        "stop_cpl_assumed": result.assumed.stop_cpl,
        "goal_cpl_assumed": result.assumed.goal_cpl,
        "stop_cpl_observed": observed.stop_cpl if observed else None,
        "goal_cpl_observed": observed.goal_cpl if observed else None,
        "contribution_uah": observed.contribution_uah
        if observed
        else result.assumed.contribution_uah,
        "contribution_uah_assumed": result.assumed.contribution_uah,
        "drift_pct": result.drift_pct,
        # The finding the whole server exists for: optimising toward a target
        # the product cannot pay for, while the dashboard looks healthy.
        "target_above_breakeven": result.target_above_breakeven,
        "structural_loss": bool(observed and observed.structural_loss),
        "economics_reliable": result.economics_reliable,
        "observed_rates": {"approval": approval, "buyout": buyout},
        "inputs_used": result.inputs_used,
    }


@server.tool(
    title="Recommend the next advertising action",
    description=(
        "Diagnose why a product is underperforming and return the matching "
        "remedy. Given the product's measured funnel, its current cost per "
        "lead, and optional competitor and creative signals, identifies the "
        "likeliest failure mode — structural loss, contested auction, traffic "
        "quality, offer or price mismatch, creative fatigue, or a weak offer — "
        "and returns the action that fits it. Use when a campaign misses its "
        "target and the cause is not yet established, because cheap leads that "
        "fail on the call and leads that fail at the post office need opposite "
        "remedies. Returns action 'hold' with diagnosis 'insufficient_data' "
        "rather than guessing when the sample is too small. Read-only."
    ),
    annotations=READ_ONLY,
)
def recommend_next_action(
    sku: Annotated[str, Field(description="Product code, e.g. 21-183")],
    current_cpl: Annotated[float, Field(description="Current cost per lead in USD", ge=0)],
    cpl_trend_days: Annotated[
        int | None,
        Field(description="Days the current cost per lead has held", ge=0, le=365),
    ] = None,
    competitor_active: Annotated[
        bool | None,
        Field(description="Whether a known competitor is bidding on this product"),
    ] = None,
    creative_frequency: Annotated[
        float | None,
        Field(description="Meta frequency for the running creative", ge=0),
    ] = None,
    creative_ctr_trend: Annotated[
        float | None,
        Field(description="Change in click-through rate; negative means falling"),
    ] = None,
    window_from: Annotated[str | None, Field(description="ISO date")] = None,
    window_to: Annotated[str | None, Field(description="ISO date")] = None,
) -> ActionRecommendation:
    if current_cpl < 0:
        raise ToolError(f"`current_cpl` cannot be negative; got {current_cpl}.")

    snapshot = _snapshot()
    code = _require_sku(snapshot, sku)
    measurement = _measure(snapshot, code, window_from, window_to)

    try:
        result = calibrate(snapshot, code, measurement["approval_rate"], measurement["buyout_rate"])
    except EconomicsError as exc:
        raise ToolError(str(exc)) from exc

    suggestion = recommend(
        result,
        current_cpl,
        measurement["approval_rate"],
        measurement["buyout_rate"],
        assumed_approval=result.inputs_used["assumed_approval_rate"],
        assumed_buyout=result.inputs_used["assumed_buyout_rate"],
        reliability=measurement["reliability"],
        cpl_trend_days=cpl_trend_days,
        competitor_active=competitor_active,
        creative_frequency=creative_frequency,
        creative_ctr_trend=creative_ctr_trend,
    )

    payload: ActionRecommendation = {
        "sku": code,
        "action": suggestion.action,
        "diagnosis": suggestion.diagnosis,
        "rationale": suggestion.rationale,
        "evidence": suggestion.evidence,
        "confidence": suggestion.confidence,
        "priority": suggestion.priority,
        "measurement": measurement,
        # Present on every response, null unless the remedy is a price
        # change — the published schema requires the key either way.
        "breakeven_condition": None,
    }

    # Where the remedy is a price change, say what would have to become true
    # for it to pay — a condition, never a forecast. The data evidences the
    # price/buyout relationship only weakly, and a predicted rate would
    # overstate it.
    if suggestion.action == "reprice" and result.observed:
        required = breakeven_buyout(
            result.price_uah,
            result.cogs_uah,
            result.observed.approval_rate,
            current_cpl,
            return_fee_uah=result.inputs_used["return_fee_uah"],
            call_centre_fee_uah=result.inputs_used["call_centre_fee_uah"],
            upsell_uah=result.inputs_used["upsell_uah"],
            rate_usd_uah=result.usd_uah,
        )
        condition: BreakevenCondition = {
            "required_buyout_rate": required,
            "observed_buyout_rate": result.observed.buyout_rate,
            "points_needed": (
                round((required - result.observed.buyout_rate) * 100, 1)
                if required is not None
                else None
            ),
            "note": (
                "A condition, not a prediction. The buyout rate would have to "
                "reach this level for the current cost per lead to break even; "
                "whether a price change achieves it is not something this "
                "dataset can say."
            ),
        }
        payload["breakeven_condition"] = condition
    return payload


@server.tool(
    title="Audit a proposed advertising decision",
    description=(
        "Test an advertising decision that originated elsewhere — a daily "
        "watchdog report, an operator's judgement, a note in the decision "
        "journal — against this product's recalibrated economics. Returns "
        "'supported', 'contradicted', or 'insufficient_data', together with "
        "the numeric chain that produced the verdict and a counter-"
        "recommendation where the proposal is contradicted. Use before acting "
        "on any recommendation this server did not itself produce. Read-only."
    ),
    annotations=READ_ONLY,
)
def audit_ad_verdict(
    sku: Annotated[str, Field(description="Product code, e.g. 21-183")],
    proposed_action: Annotated[
        Literal[
            "scale",
            "hold",
            "pause_retry",
            "stop",
            "full_stop",
            "reprice",
            "new_creative",
            "refresh_creative",
        ],
        Field(description="The decision being proposed"),
    ],
    current_cpl: Annotated[
        float, Field(description="Cost per lead the proposal is based on, USD", ge=0)
    ],
    source: Annotated[
        str | None,
        Field(description="Where the proposal came from, for the audit record"),
    ] = None,
    competitor_active: Annotated[
        bool | None, Field(description="Whether a competitor is bidding on this product")
    ] = None,
    cpl_trend_days: Annotated[
        int | None, Field(description="Days the cost per lead has held", ge=0, le=365)
    ] = None,
) -> AuditVerdict:
    if proposed_action not in ACTIONS:
        raise ToolError(
            f"Unrecognised `proposed_action` '{proposed_action}'. "
            f"Accepted values: {', '.join(ACTIONS)}."
        )
    if current_cpl < 0:
        raise ToolError(f"`current_cpl` cannot be negative; got {current_cpl}.")

    own = recommend_next_action(
        sku=sku,
        current_cpl=current_cpl,
        competitor_active=competitor_active,
        cpl_trend_days=cpl_trend_days,
    )

    evidence: AuditEvidence = dict(own["evidence"])  # type: ignore[assignment]
    evidence["proposed_action"] = proposed_action
    evidence["source"] = source

    if own["diagnosis"] == "insufficient_data":
        return {
            "sku": own["sku"],
            "verdict": "insufficient_data",
            "proposed_action": proposed_action,
            "evidence": evidence,
            "counter_recommendation": None,
            "reliability": own["measurement"]["reliability"],
            "rationale": (
                "This product has too few resolved orders to judge the "
                "proposal either way. Declining to rule is the finding: the "
                "proposal is neither endorsed nor overturned."
            ),
        }

    supported = own["action"] in COMPATIBLE.get(proposed_action, {proposed_action})
    return {
        "sku": own["sku"],
        "verdict": "supported" if supported else "contradicted",
        "proposed_action": proposed_action,
        "evidence": evidence,
        "counter_recommendation": None if supported else own["action"],
        "reliability": own["measurement"]["reliability"],
        "rationale": (
            f"Evidence indicates '{own['action']}' ({own['diagnosis']}). "
            + (
                f"The proposal '{proposed_action}' is consistent with that. "
                if supported
                else f"The proposal '{proposed_action}' is not. "
            )
            + own["rationale"]
        ),
    }


@server.tool(
    title="List products the snapshot can answer for",
    description=(
        "List the product codes present in the loaded snapshot, with their "
        "order counts and whether price and cost data exist for them. Use to "
        "resolve a product code before measuring, or to see what the dataset "
        "covers. Read-only."
    ),
    annotations=READ_ONLY,
)
def list_covered_skus(
    min_orders: Annotated[
        int, Field(description="Only list products with at least this many orders", ge=0)
    ] = 1,
) -> SkuCoverage:
    snapshot = _snapshot()
    counts: dict[str, int] = {}
    for order in snapshot.orders:
        counts[order.sku] = counts.get(order.sku, 0) + 1

    rows: list[SkuRow] = [
        {
            "sku": sku,
            "orders": total,
            "manufacturer": (snapshot.economics.get(sku) or {}).get("manufacturer"),
            "has_economics": sku in snapshot.economics,
        }
        for sku, total in sorted(counts.items(), key=lambda kv: -kv[1])
        if total >= min_orders
    ]
    return {
        "snapshot_generated_at": snapshot.generated_at,
        "window": {
            "from": snapshot.window_from.isoformat(),
            "to": snapshot.window_to.isoformat(),
        },
        "total_orders": len(snapshot.orders),
        "status_taxonomy": {str(k): v for k, v in STATUS_NAMES.items()},
        "products": rows,
    }


def main() -> None:
    """Start the MCP server on stdio."""
    server.run("stdio")


if __name__ == "__main__":
    main()
