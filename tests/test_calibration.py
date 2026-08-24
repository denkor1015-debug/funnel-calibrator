"""Unit tests for CPL recomputation.

The property that matters: worse observed rates must produce strictly lower
CPL bounds. A regression here would silently restore the open-loop behaviour
the server exists to correct.
"""

from __future__ import annotations

import pytest

from funnel_calibrator.calibration import breakeven_buyout, compute_bounds

# The worked example from docs/design-rationale.md: article 17-252, a real
# product. Every number in this file traces back to it.
PRICE = 1499.0
COGS = 990.0
SHARED = {
    "return_fee_uah": 94.0,
    "call_centre_fee_uah": 23.0,
    "upsell_uah": 95.0,
    "rate_usd_uah": 45.0,
    "ratio": 0.70,
}


def bounds(approval: float, buyout: float, **override):
    return compute_bounds(PRICE, COGS, approval, buyout, **{**SHARED, **override})


def test_matches_the_business_formula_at_assumed_rates():
    """Assumed rates must reproduce the figure the business already steers by."""
    result = bounds(0.65, 0.525)
    assert result.returns_cost_uah == pytest.approx(85.05, abs=0.01)
    assert result.call_centre_cost_uah == pytest.approx(43.81, abs=0.01)
    assert result.contribution_uah == pytest.approx(475.14, abs=0.05)
    assert result.stop_cpl == pytest.approx(3.60, abs=0.01)
    assert result.goal_cpl == pytest.approx(2.52, abs=0.01)


def test_worse_rates_produce_strictly_lower_bounds():
    """The core property. Both rates, independently and together."""
    baseline = bounds(0.65, 0.525)

    worse_buyout = bounds(0.65, 0.37)
    assert worse_buyout.stop_cpl < baseline.stop_cpl
    assert worse_buyout.goal_cpl < baseline.goal_cpl

    worse_approval = bounds(0.53, 0.525)
    assert worse_approval.stop_cpl < baseline.stop_cpl

    both = bounds(0.53, 0.37)
    assert both.stop_cpl < worse_buyout.stop_cpl
    assert both.stop_cpl < worse_approval.stop_cpl


def test_bounds_are_monotonic_in_buyout():
    """No local reversal anywhere in the plausible range."""
    rates = [0.30 + 0.02 * step for step in range(30)]
    stops = [bounds(0.65, rate).stop_cpl for rate in rates]
    assert stops == sorted(stops)


def test_call_centre_fee_scales_with_buyout():
    """The detail hand calculations get wrong.

    The fee is paid per confirmed order, not per parcel collected, so a worse
    buyout rate spreads the same fee over fewer collections. Holding it
    constant flatters a bad rate — which is how the 37%-buyout example in the
    design rationale was originally overstated at $2.14 instead of $2.04.
    """
    assumed = bounds(0.65, 0.525)
    observed = bounds(0.65, 0.37)
    assert observed.call_centre_cost_uah > assumed.call_centre_cost_uah
    assert observed.call_centre_cost_uah == pytest.approx(62.16, abs=0.01)
    assert observed.contribution_uah == pytest.approx(382.0, abs=1.0)
    assert observed.stop_cpl == pytest.approx(2.04, abs=0.01)
    assert observed.goal_cpl == pytest.approx(1.43, abs=0.01)


def test_the_failure_the_server_exists_to_catch():
    """At 37% buyout the assumed *target* sits above the true *break-even*."""
    assumed = bounds(0.65, 0.525)
    observed = bounds(0.65, 0.37)
    assert assumed.goal_cpl > observed.stop_cpl


def test_structural_loss_is_a_finding_not_an_error():
    """A product priced below its own costs is reported, never raised."""
    result = compute_bounds(790.0, 900.0, 0.65, 0.525, **SHARED)
    assert result.structural_loss is True
    assert result.contribution_uah < 0


@pytest.mark.parametrize(
    "approval,buyout",
    [(0.0, 0.5), (0.5, 0.0), (1.5, 0.5), (0.5, 1.5), (-0.1, 0.5)],
)
def test_rates_outside_the_unit_interval_are_rejected(approval, buyout):
    with pytest.raises(ValueError):
        bounds(approval, buyout)


def test_zero_exchange_rate_is_rejected():
    with pytest.raises(ValueError):
        bounds(0.65, 0.525, rate_usd_uah=0.0)


def test_breakeven_buyout_is_a_condition_not_a_forecast():
    """The rate at which a given CPL would just pay for itself."""
    shared = {k: v for k, v in SHARED.items() if k != "ratio"}
    target = 3.00
    required = breakeven_buyout(PRICE, COGS, 0.65, target, **shared)
    assert required is not None
    # Feeding the answer back through the formula must land on the target.
    check = bounds(0.65, required)
    assert check.stop_cpl == pytest.approx(target, abs=0.02)


def test_breakeven_buyout_returns_none_when_unreachable():
    """A cost per lead no buyout rate can justify is said so, not approximated."""
    shared = {k: v for k, v in SHARED.items() if k != "ratio"}
    assert breakeven_buyout(PRICE, COGS, 0.65, 99.0, **shared) is None
