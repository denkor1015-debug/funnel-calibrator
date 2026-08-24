"""The output half of every tool contract, pinned.

Two failures these guard against, both of which are silent until someone runs
the server for real:

* **Drift.** A tool grows a field, or renames one, and the declared type no
  longer describes what comes back. The published schema then lies, which is
  worse than having none — a caller validates against it and passes.
* **A reintroduced `NotRequired`.** The MCP SDK marks every property of an
  output schema as required. A key declared optional therefore produces a
  schema the server's own successful responses fail, and the tool call comes
  back an error. It looks like a data problem and is not one.

The tests validate real payloads rather than fixtures, so they exercise the
same path the agent does.
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from funnel_calibrator import server
from funnel_calibrator.contracts import (
    ActionRecommendation,
    AuditVerdict,
    BreakevenCondition,
    CalibrationBounds,
    FunnelMeasurement,
    SkuCoverage,
)

# A product with a healthy sample, so the payloads are fully populated.
SKU = "21-154"
CPL = 1.63


def _payloads() -> list[tuple[str, type, dict]]:
    """One real response per tool, paired with the type that describes it."""
    return [
        ("measure_sku_funnel", FunnelMeasurement, server.measure_sku_funnel(sku=SKU)),
        ("recalibrate_cpl_bounds", CalibrationBounds, server.recalibrate_cpl_bounds(sku=SKU)),
        (
            "recommend_next_action",
            ActionRecommendation,
            server.recommend_next_action(sku=SKU, current_cpl=CPL),
        ),
        (
            "audit_ad_verdict",
            AuditVerdict,
            server.audit_ad_verdict(sku=SKU, proposed_action="scale", current_cpl=CPL),
        ),
        ("list_covered_skus", SkuCoverage, server.list_covered_skus(min_orders=50)),
    ]


@pytest.mark.parametrize(
    "name,declared,payload", _payloads(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_payload_matches_its_declared_type(name: str, declared: type, payload: dict) -> None:
    TypeAdapter(declared).validate_python(payload)


@pytest.mark.parametrize(
    "name,declared,payload", _payloads(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_no_undeclared_or_missing_keys(name: str, declared: type, payload: dict) -> None:
    """Pydantic ignores extra keys; a published schema does not tolerate drift."""
    schema = TypeAdapter(declared).json_schema()
    assert set(payload) == set(schema["properties"]), (
        f"{name}: response keys and declared keys disagree — "
        f"only in response: {sorted(set(payload) - set(schema['properties']))}, "
        f"only declared: {sorted(set(schema['properties']) - set(payload))}"
    )


@pytest.mark.parametrize(
    "declared",
    [FunnelMeasurement, CalibrationBounds, ActionRecommendation, AuditVerdict, SkuCoverage],
    ids=lambda t: t.__name__,
)
def test_every_field_is_required(declared: type) -> None:
    """No `NotRequired` may creep back in — see this module's docstring."""
    schema = TypeAdapter(declared).json_schema()
    optional = set(schema["properties"]) - set(schema.get("required", []))
    assert not optional, (
        f"{declared.__name__} declares {sorted(optional)} as optional. The MCP SDK "
        "requires every property, so the tool would return an error instead of a "
        "result. Use `X | None` and always emit the key."
    )


def test_output_schema_is_not_vacuous() -> None:
    """The state this work started from: a schema that described nothing."""
    for _, declared, _ in _payloads():
        schema = TypeAdapter(declared).json_schema()
        assert len(schema.get("properties", {})) >= 5


def test_breakeven_condition_present_only_for_a_price_remedy() -> None:
    """The one conditional payload, checked in both of its states."""
    priced = server.recommend_next_action(sku="1826", current_cpl=3.0)
    assert priced["action"] == "reprice"
    TypeAdapter(BreakevenCondition).validate_python(priced["breakeven_condition"])

    other = server.recommend_next_action(sku=SKU, current_cpl=CPL)
    assert other["action"] != "reprice"
    assert other["breakeven_condition"] is None, (
        "The key must be present and null rather than absent, or the schema "
        "the SDK publishes will not match the response."
    )


def test_thin_sample_still_fills_every_evidence_key() -> None:
    """The early returns skip the collapse and spike tests but not the keys."""
    thin = server.recommend_next_action(sku="2659", current_cpl=2.0)
    for key in ("approval_collapsed", "buyout_collapsed", "spike_over_goal_pct"):
        assert key in thin["evidence"]


def test_declared_types_reject_a_wrong_shape() -> None:
    """A guard that fails on everything is not a guard."""
    broken = server.measure_sku_funnel(sku=SKU)
    broken["reliability"] = "probably fine"
    with pytest.raises(ValidationError):
        TypeAdapter(FunnelMeasurement).validate_python(broken)
