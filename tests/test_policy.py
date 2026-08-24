"""Tests for the diagnosis tree.

The property that matters here is not accuracy — the data cannot establish
causation — but *discrimination*. Two products can present the identical
symptom, a missed target, and need opposite remedies. A tree that collapsed
them into one recommendation would be worse than no recommendation, because
cutting the price of a product with a targeting problem makes it worse.
"""

from __future__ import annotations

from funnel_calibrator.calibration import calibrate
from funnel_calibrator.policy import recommend
from funnel_calibrator.snapshot import Snapshot

PRODUCT = {
    "sku": "TEST-1",
    "price_uah": 1499,
    "cogs_uah": 990,
    "usd_uah": 45.0,
    "economics_reliable": True,
}

ASSUMED = {
    "approval_rate": 0.65,
    "buyout_rate": 0.525,
    "return_fee_uah": 94,
    "call_centre_fee_uah": 23,
    "upsell_uah": 95,
}


def snapshot(price: float = 1499, cogs: float = 990) -> Snapshot:
    from datetime import date

    return Snapshot(
        path=None,  # type: ignore[arg-type]
        generated_at="test",
        window_from=date(2026, 6, 1),
        window_to=date(2026, 8, 24),
        orders=(),
        economics={"TEST-1": {**PRODUCT, "price_uah": price, "cogs_uah": cogs}},
        assumed=dict(ASSUMED),
    )


def advise(
    approval: float,
    buyout: float,
    current_cpl: float,
    *,
    price: float = 1499,
    cogs: float = 990,
    reliability: str = "high",
    **signals,
):
    calibration = calibrate(snapshot(price, cogs), "TEST-1", approval, buyout)
    return recommend(
        calibration,
        current_cpl,
        approval,
        buyout,
        assumed_approval=ASSUMED["approval_rate"],
        assumed_buyout=ASSUMED["buyout_rate"],
        reliability=reliability,
        **signals,
    )


def test_identical_symptom_opposite_remedies():
    """The reason `recommend_next_action` exists.

    Both products miss their target. One has cheap leads that fail on the
    phone; the other has leads that confirm and then fail at the post office.
    The remedies must not be the same.
    """
    traffic = advise(approval=0.35, buyout=0.55, current_cpl=1.20)
    offer = advise(approval=0.66, buyout=0.35, current_cpl=1.20)

    assert traffic.action == "new_creative"
    assert traffic.diagnosis == "traffic_quality"
    assert offer.action == "reprice"
    assert offer.diagnosis == "offer_mismatch"
    assert traffic.action != offer.action


def test_structural_loss_outranks_every_other_diagnosis():
    """No cost per lead rescues a product priced below its own costs."""
    result = advise(approval=0.65, buyout=0.52, current_cpl=0.01, price=790, cogs=900)
    assert result.action == "full_stop"
    assert result.diagnosis == "structural_loss"
    assert result.priority == 1


def test_contested_auction_needs_a_competitor_and_persistence():
    """A one-day spike is noise; a held spike with a rival is a signal."""
    spiked = {"approval": 0.65, "buyout": 0.53, "current_cpl": 6.0}

    alone = advise(**spiked)
    assert alone.action == "stop"

    brief = advise(**spiked, competitor_active=True, cpl_trend_days=1)
    assert brief.action == "stop"

    sustained = advise(**spiked, competitor_active=True, cpl_trend_days=5)
    assert sustained.action == "pause_retry"
    assert sustained.diagnosis == "contested_auction"


def test_scale_requires_room_beneath_the_target_not_break_even():
    """Break-even is where profit is zero — not a place to buy more traffic."""
    calibration = calibrate(snapshot(), "TEST-1", 0.65, 0.525)
    assert calibration.observed is not None
    goal = calibration.observed.goal_cpl
    stop = calibration.observed.stop_cpl

    assert advise(0.65, 0.525, goal - 0.10).action == "scale"
    between = advise(0.65, 0.525, (goal + stop) / 2)
    assert between.action == "hold"
    assert advise(0.65, 0.525, stop + 0.10).action == "stop"


def test_insufficient_sample_declines_rather_than_guessing():
    result = advise(0.65, 0.525, 1.0, reliability="insufficient")
    assert result.action == "hold"
    assert result.diagnosis == "insufficient_data"
    assert result.confidence == "high"  # certain that it cannot say


def test_confidence_never_outranks_the_sample():
    strong = advise(0.65, 0.525, 1.0, reliability="high")
    thin = advise(0.65, 0.525, 1.0, reliability="low")
    assert strong.confidence == "high"
    assert thin.confidence == "medium"
    assert strong.action == thin.action


def test_fatigue_is_caught_before_the_product_is_written_off():
    result = advise(
        0.65,
        0.525,
        2.90,
        creative_frequency=3.1,
        creative_ctr_trend=-0.4,
    )
    assert result.action == "refresh_creative"
    assert result.diagnosis == "creative_fatigue"
