"""Tests for the guards that separate a measurement from a plausible fiction.

Censoring and sample gating live in the server precisely so that no caller can
skip them. These tests pin that behaviour against a purpose-built fixture, so
they hold whatever the exported snapshot happens to contain.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from funnel_calibrator import server
from funnel_calibrator.snapshot import _load, reliability_of

AS_OF = date(2026, 8, 24)


def order(order_id: int, sku: str, days_ago: int, status_id: int) -> dict:
    return {
        "order_id": order_id,
        "sku": sku,
        "created_at": (AS_OF - timedelta(days=days_ago)).isoformat(),
        "status_id": status_id,
        "amount": 1499.0,
        "manufacturer": "KORA",
        "campaign": f"{sku} | kor | CBO | 01.06.26",
        "creative": f"{sku} test",
    }


def write_fixture(tmp_path, orders: list[dict]):
    """A snapshot and economics pair on disk, wired through the environment."""
    snapshot = {
        "generated_at": "2026-08-24T12:00:00",
        "window": {"from": "2026-06-01", "to": AS_OF.isoformat()},
        "orders": orders,
    }
    economics = {
        "assumed": {
            "approval_rate": 0.65,
            "buyout_rate": 0.525,
            "return_fee_uah": 94,
            "call_centre_fee_uah": 23,
            "upsell_uah": 95,
            "goal_ratio": 0.70,
        },
        "products": {
            "TEST-1": {
                "sku": "TEST-1",
                "price_uah": 1499,
                "cogs_uah": 990,
                "usd_uah": 45.0,
                "manufacturer": "KORA",
                "economics_reliable": True,
                "source": "fixture",
            }
        },
    }
    snap_path = tmp_path / "snapshot.json"
    econ_path = tmp_path / "economics.json"
    snap_path.write_text(json.dumps(snapshot), encoding="utf-8")
    econ_path.write_text(json.dumps(economics), encoding="utf-8")
    return snap_path, econ_path


@pytest.fixture
def fixture_env(tmp_path, monkeypatch):
    def install(orders: list[dict], **env: str):
        snap_path, econ_path = write_fixture(tmp_path, orders)
        monkeypatch.setenv("FC_SNAPSHOT_PATH", str(snap_path))
        monkeypatch.setenv("FC_ECONOMICS_PATH", str(econ_path))
        monkeypatch.setenv("FC_MIN_SAMPLE", env.get("FC_MIN_SAMPLE", "30"))
        monkeypatch.setenv("FC_COHORT_MATURITY_DAYS", env.get("FC_COHORT_MATURITY_DAYS", "21"))
        # The loader memoises by path; each fixture writes a fresh file, but
        # clear anyway so a reused tmp_path cannot leak between tests.
        _load.cache_clear()

    yield install
    _load.cache_clear()


# ─── Censoring ────────────────────────────────────────────────────────


def test_immature_cohorts_are_excluded_not_counted_as_failures(fixture_env):
    """Recent orders must not be read as non-buyouts.

    Forty mature orders split 30 bought out / 10 refused is 75%. Adding forty
    orders placed yesterday — none of which can have resolved — must leave the
    rate at 75%, not halve it.
    """
    mature = [order(i, "TEST-1", 40, 12) for i in range(30)]
    mature += [order(100 + i, "TEST-1", 40, 32) for i in range(10)]
    fresh = [order(200 + i, "TEST-1", 1, 6) for i in range(40)]
    fixture_env(mature + fresh)

    result = server.measure_sku_funnel("TEST-1")
    assert result["buyout_rate"] == pytest.approx(0.75)
    assert result["resolved_orders"] == 40
    assert result["excluded_immature_cohort"] == 40
    assert result["excluded_in_flight"] == 40


def test_parcels_still_moving_are_excluded_from_the_buyout_denominator(fixture_env):
    """ "Arrived at the branch" is neither a buyout nor a refusal."""
    orders = [order(i, "TEST-1", 40, 12) for i in range(30)]
    orders += [order(100 + i, "TEST-1", 40, 32) for i in range(10)]
    orders += [order(200 + i, "TEST-1", 40, 20) for i in range(15)]  # at the branch
    fixture_env(orders)

    result = server.measure_sku_funnel("TEST-1")
    assert result["resolved_orders"] == 40
    assert result["excluded_still_moving"] == 15
    assert result["buyout_rate"] == pytest.approx(0.75)


def test_maturity_window_is_measured_against_the_snapshot_not_today(fixture_env):
    """A stored dataset cannot age into new resolutions."""
    orders = [order(i, "TEST-1", 22, 12) for i in range(35)]
    fixture_env(orders)
    result = server.measure_sku_funnel("TEST-1")
    assert result["cohort_cutoff"] == "2026-08-03"
    assert result["resolved_orders"] == 35


def test_maturity_override_changes_what_counts(fixture_env):
    """Varying one valid input must visibly change the output."""
    orders = [order(i, "TEST-1", 40, 12) for i in range(30)]
    orders += [order(100 + i, "TEST-1", 10, 32) for i in range(30)]
    fixture_env(orders)

    strict = server.measure_sku_funnel("TEST-1", maturity_days=21)
    relaxed = server.measure_sku_funnel("TEST-1", maturity_days=0)
    assert strict["resolved_orders"] == 30
    assert strict["buyout_rate"] == pytest.approx(1.0)
    assert relaxed["resolved_orders"] == 60
    assert relaxed["buyout_rate"] == pytest.approx(0.5)


# ─── Status taxonomy ──────────────────────────────────────────────────


def test_status_35_counts_as_a_refusal(fixture_env):
    """The status the business's own reporting classifies as `unknown`.

    Its 216 orders are all shipped. Dropping them reads the buyout rate far
    too high; this test fails loudly if the taxonomy is ever trimmed back.
    """
    orders = [order(i, "TEST-1", 40, 12) for i in range(30)]
    orders += [order(100 + i, "TEST-1", 40, 35) for i in range(30)]
    fixture_env(orders)

    result = server.measure_sku_funnel("TEST-1")
    assert result["refused"] == 30
    assert result["resolved_orders"] == 60
    assert result["buyout_rate"] == pytest.approx(0.5)


@pytest.mark.parametrize("refusal_status", [28, 32, 35])
def test_every_refusal_status_is_counted(fixture_env, refusal_status):
    """Refusals migrated 32 → 35 → 28; a filter on any one alone reads low."""
    orders = [order(i, "TEST-1", 40, 12) for i in range(30)]
    orders += [order(100 + i, "TEST-1", 40, refusal_status) for i in range(10)]
    fixture_env(orders)
    assert server.measure_sku_funnel("TEST-1")["refused"] == 10


def test_cancellations_stay_out_of_the_buyout_denominator(fixture_env):
    """An order cancelled on the phone never reached the post office."""
    orders = [order(i, "TEST-1", 40, 12) for i in range(30)]
    orders += [order(100 + i, "TEST-1", 40, 19) for i in range(50)]
    fixture_env(orders)

    result = server.measure_sku_funnel("TEST-1")
    assert result["resolved_orders"] == 30
    assert result["buyout_rate"] == pytest.approx(1.0)
    assert result["approval_rate"] == pytest.approx(30 / 80)


# ─── Sample gating ────────────────────────────────────────────────────


def test_thin_sample_returns_insufficient_rather_than_a_number(fixture_env):
    """Below the threshold the server declines, and says so in the payload."""
    orders = [order(i, "TEST-1", 40, 12) for i in range(8)]
    orders += [order(100 + i, "TEST-1", 40, 32) for i in range(3)]
    fixture_env(orders)

    result = server.measure_sku_funnel("TEST-1")
    assert result["reliability"] == "insufficient"
    assert result["buyout_rate"] is None
    assert result["return_rate"] is None
    assert result["resolved_orders"] == 11


def test_reliability_ladder():
    assert reliability_of(29, 30) == "insufficient"
    assert reliability_of(30, 30) == "low"
    assert reliability_of(89, 30) == "low"
    assert reliability_of(90, 30) == "high"


def test_thin_sample_makes_the_policy_decline(fixture_env):
    """The gate has to reach the recommendation, not just the measurement."""
    orders = [order(i, "TEST-1", 40, 12) for i in range(5)]
    fixture_env(orders)

    result = server.recommend_next_action(sku="TEST-1", current_cpl=1.0)
    assert result["action"] == "hold"
    assert result["diagnosis"] == "insufficient_data"

    audit = server.audit_ad_verdict(sku="TEST-1", proposed_action="scale", current_cpl=1.0)
    assert audit["verdict"] == "insufficient_data"
    assert audit["counter_recommendation"] is None


# ─── The three-way outcome split ──────────────────────────────────────


def test_empty_window_is_a_success_not_an_error(fixture_env):
    """A real product with no orders in range is data, not a failure."""
    fixture_env([order(i, "TEST-1", 40, 12) for i in range(50)])

    result = server.measure_sku_funnel("TEST-1", window_from="2026-06-01", window_to="2026-06-02")
    assert result["resolved_orders"] == 0
    assert result["reliability"] == "insufficient"
    assert result["approval_rate"] is None


def test_unknown_product_raises_naming_the_input(fixture_env):
    """A typo must never read as evidence that a product has no orders."""
    fixture_env([order(i, "TEST-1", 40, 12) for i in range(50)])

    with pytest.raises(Exception) as caught:
        server.measure_sku_funnel("TEST-9")
    assert "TEST-9" in str(caught.value)


def test_inverted_window_raises_naming_both_ends(fixture_env):
    fixture_env([order(i, "TEST-1", 40, 12) for i in range(50)])
    with pytest.raises(Exception) as caught:
        server.measure_sku_funnel("TEST-1", window_from="2026-08-01", window_to="2026-06-01")
    assert "2026-08-01" in str(caught.value)


def test_missing_snapshot_names_the_path(tmp_path, monkeypatch):
    monkeypatch.setenv("FC_SNAPSHOT_PATH", str(tmp_path / "absent.json"))
    _load.cache_clear()
    with pytest.raises(Exception) as caught:
        server.measure_sku_funnel("TEST-1")
    assert "absent.json" in str(caught.value)
    _load.cache_clear()
