"""
Test Suite: Market Regime Hysteresis, Confirmation, Cooldown & Pre-Market Auction Guard
======================================================================================
Verifies:
1. Multi-band hysteresis preventing boundary flip-flop wobbles.
2. Replay of 56 -> 54 -> 55 -> 56 -> 54 asserting at most one alert (zero false flips).
3. Zero alerts fired before 09:15 IST (pre-open auction), with single 09:15 sync.
4. N=3 consecutive evaluation confirmation requirement.
5. 15-minute cooldown suppression with 2+ level jump bypass.
6. State persistence across engine restarts.
"""

import datetime
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from config.regime_config import (
    STRONG_UPTREND_ENTER,
    STRONG_UPTREND_EXIT,
    UPTREND_ENTER,
    UPTREND_EXIT,
    DOWNTREND_ENTER,
    DOWNTREND_EXIT,
    STRONG_DOWNTREND_ENTER,
    STRONG_DOWNTREND_EXIT,
    REGIME_CONFIRMATION_COUNT,
    REGIME_ALERT_COOLDOWN_SECONDS,
)
from src.analytics.market_regime_engine import MarketRegimeEngine, MarketRegimeStateManager

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


@pytest.fixture
def clean_state_mgr(tmp_path):
    """Provides a clean isolated MarketRegimeStateManager using a temporary state file."""
    state_file = tmp_path / "test_regime_state.json"
    mgr = MarketRegimeStateManager(state_file=state_file, confirmation_count=3, cooldown_seconds=900)
    # Start in clean UPTREND
    mgr.current_regime = "UPTREND"
    mgr.last_alerted_regime = "UPTREND"
    mgr.last_alert_time = datetime.datetime(2026, 11, 16, 9, 30, tzinfo=IST).timestamp()
    mgr.save_state()
    return mgr


def test_01_wobble_sequence_56_54_55_56_54_zero_alerts(clean_state_mgr):
    """
    Requirement 1, 5, 7:
    Replaying 56 -> 54 -> 55 -> 56 -> 54 around the 55 boundary
    must NEVER trigger flip-flop alerts when starting in UPTREND.
    """
    mgr = clean_state_mgr
    test_time = datetime.datetime(2026, 11, 16, 10, 0, tzinfo=IST)

    sequence = [56, 54, 55, 56, 54]
    alerts_fired = 0
    regimes = []

    for score in sequence:
        test_time += datetime.timedelta(seconds=15)
        step = mgr.process_evaluation(score=score, is_divergence=False, now_dt=test_time)
        regimes.append(step["current_regime"])
        if step["should_alert"]:
            alerts_fired += 1

    # Assert that all evaluations remained strictly in UPTREND (never flipped to STRONG_UPTREND)
    assert all(r == "UPTREND" for r in regimes), f"Expected all UPTREND, got {regimes}"
    # Assert at most one alert (in fact, exactly zero alerts)
    assert alerts_fired <= 1
    assert alerts_fired == 0


def test_02_pre_market_suppression_before_0915_and_sync_at_0915(clean_state_mgr):
    """
    Requirement 4 & 7:
    Suppress alerts before 09:15 IST (pre-open auction at 9:02, 9:04, 9:10, 9:14).
    Send at most one alert at 09:15 if regime differs from last_alerted.
    """
    mgr = clean_state_mgr
    mgr.last_alerted_regime = "CHOPPY"  # Last Friday closed in CHOPPY
    mgr.current_regime = "CHOPPY"

    # Sequence during pre-open: 09:02, 09:04, 09:10, 09:14 IST with fluctuating scores
    pre_open_times = [
        (datetime.datetime(2026, 11, 16, 9, 2, tzinfo=IST), 65),
        (datetime.datetime(2026, 11, 16, 9, 4, tzinfo=IST), 62),
        (datetime.datetime(2026, 11, 16, 9, 10, tzinfo=IST), 63),
        (datetime.datetime(2026, 11, 16, 9, 14, tzinfo=IST), 64),
    ]

    pre_open_alerts = 0
    for dt, score in pre_open_times:
        step = mgr.process_evaluation(score=score, is_divergence=False, now_dt=dt)
        if step["should_alert"]:
            pre_open_alerts += 1
        assert step["suppression_reason"] == "PRE_MARKET_AUCTION"

    # Strict assertion: ZERO alerts before 09:15 IST
    assert pre_open_alerts == 0

    # At 09:15:00 IST (market opens) -> Single opening alert fired
    open_time = datetime.datetime(2026, 11, 16, 9, 15, tzinfo=IST)
    step_0915 = mgr.process_evaluation(score=65, is_divergence=False, now_dt=open_time)
    assert step_0915["should_alert"] is True
    assert step_0915["alert_reason"] == "OPENING_MARKET_SYNC"
    assert step_0915["current_regime"] == "STRONG_UPTREND"


def test_03_hysteresis_bands_enter_and_exit_all_regimes(clean_state_mgr):
    """
    Requirement 1:
    Verifies hysteresis bands across all regimes:
    - STRONG_UPTREND: enter >= 60, exit < 50
    - UPTREND: enter >= 25, exit < 15
    - DOWNTREND: enter <= -25, exit > -15
    - STRONG_DOWNTREND: enter <= -60, exit > -50
    """
    mgr = clean_state_mgr

    # 1. From UPTREND, score 59 must NOT enter STRONG_UPTREND (needs >= 60)
    assert mgr.compute_hysteresis_zone(59, "UPTREND") == "UPTREND"
    assert mgr.compute_hysteresis_zone(60, "UPTREND") == "STRONG_UPTREND"

    # 2. Once in STRONG_UPTREND, score 50 must NOT exit (needs < 50)
    assert mgr.compute_hysteresis_zone(50, "STRONG_UPTREND") == "STRONG_UPTREND"
    assert mgr.compute_hysteresis_zone(49, "STRONG_UPTREND") == "UPTREND"

    # 3. From CHOPPY, score 24 must NOT enter UPTREND (needs >= 25)
    assert mgr.compute_hysteresis_zone(24, "CHOPPY") == "CHOPPY"
    assert mgr.compute_hysteresis_zone(25, "CHOPPY") == "UPTREND"

    # 4. Once in UPTREND, score 15 must NOT exit to CHOPPY (needs < 15)
    assert mgr.compute_hysteresis_zone(15, "UPTREND") == "UPTREND"
    assert mgr.compute_hysteresis_zone(14, "UPTREND") == "CHOPPY"

    # 5. From CHOPPY, score -24 must NOT enter DOWNTREND (needs <= -25)
    assert mgr.compute_hysteresis_zone(-24, "CHOPPY") == "CHOPPY"
    assert mgr.compute_hysteresis_zone(-25, "CHOPPY") == "DOWNTREND"

    # 6. Once in DOWNTREND, score -15 must NOT exit to CHOPPY (needs > -15)
    assert mgr.compute_hysteresis_zone(-15, "DOWNTREND") == "DOWNTREND"
    assert mgr.compute_hysteresis_zone(-14, "DOWNTREND") == "CHOPPY"

    # 7. From DOWNTREND, score -59 must NOT enter STRONG_DOWNTREND (needs <= -60)
    assert mgr.compute_hysteresis_zone(-59, "DOWNTREND") == "DOWNTREND"
    assert mgr.compute_hysteresis_zone(-60, "DOWNTREND") == "STRONG_DOWNTREND"

    # 8. Once in STRONG_DOWNTREND, score -50 must NOT exit (needs > -50)
    assert mgr.compute_hysteresis_zone(-50, "STRONG_DOWNTREND") == "STRONG_DOWNTREND"
    assert mgr.compute_hysteresis_zone(-49, "STRONG_DOWNTREND") == "DOWNTREND"


def test_04_confirmation_requires_3_consecutive_cycles(clean_state_mgr):
    """
    Requirement 2:
    A regime change is accepted only after N=3 consecutive evaluations in the new zone.
    """
    mgr = clean_state_mgr
    mgr.current_regime = "UPTREND"
    test_time = datetime.datetime(2026, 11, 16, 10, 30, tzinfo=IST)

    # Evaluation 1 in new zone (score 65)
    s1 = mgr.process_evaluation(score=65, is_divergence=False, now_dt=test_time)
    assert s1["current_regime"] == "UPTREND"  # Not yet confirmed
    assert s1["pending_count"] == 1
    assert s1["pending_candidate"] == "STRONG_UPTREND"

    # Evaluation 2 in new zone
    test_time += datetime.timedelta(seconds=15)
    s2 = mgr.process_evaluation(score=64, is_divergence=False, now_dt=test_time)
    assert s2["current_regime"] == "UPTREND"
    assert s2["pending_count"] == 2

    # Evaluation 3 in new zone (N=3 met!)
    test_time += datetime.timedelta(seconds=15)
    s3 = mgr.process_evaluation(score=63, is_divergence=False, now_dt=test_time)
    assert s3["current_regime"] == "STRONG_UPTREND"  # Confirmed!
    assert s3["pending_count"] == 0

    # Test Wobble Reset: If score drops back before N=3, pending count resets
    test_time += datetime.timedelta(seconds=15)
    # Score 48 -> raw_zone is UPTREND (< 50)
    w1 = mgr.process_evaluation(score=48, is_divergence=False, now_dt=test_time)
    assert w1["current_regime"] == "STRONG_UPTREND"
    assert w1["pending_count"] == 1
    assert w1["pending_candidate"] == "UPTREND"

    # Next cycle jumps back into STRONG_UPTREND (score 62)
    test_time += datetime.timedelta(seconds=15)
    w2 = mgr.process_evaluation(score=62, is_divergence=False, now_dt=test_time)
    assert w2["current_regime"] == "STRONG_UPTREND"
    assert w2["pending_count"] == 0
    assert w2["pending_candidate"] is None


def test_05_cooldown_and_level_2_jump_bypass(clean_state_mgr):
    """
    Requirement 3:
    15-minute cooldown suppresses 1-level transitions.
    Transitions across 2+ regime levels bypass the cooldown.
    """
    mgr = clean_state_mgr
    t0 = datetime.datetime(2026, 11, 16, 10, 0, tzinfo=IST)

    # Initial alert fired at 10:00 for STRONG_UPTREND (+2)
    mgr.last_alert_time = t0.timestamp()
    mgr.last_alerted_regime = "STRONG_UPTREND"
    mgr.current_regime = "STRONG_UPTREND"

    # 1. 5 minutes later (T+300s): Dropping 1 level to UPTREND (+1)
    # After 3 consecutive evaluations of score 40
    t_5m = t0 + datetime.timedelta(minutes=5)
    mgr.process_evaluation(40, False, t_5m)
    mgr.process_evaluation(40, False, t_5m + datetime.timedelta(seconds=15))
    s_drop1 = mgr.process_evaluation(40, False, t_5m + datetime.timedelta(seconds=30))

    assert s_drop1["current_regime"] == "UPTREND"
    # Suppressed by 15-minute cooldown because level_diff = 1 (2 - 1)
    assert s_drop1["should_alert"] is False
    assert "COOLDOWN_ACTIVE" in s_drop1["suppression_reason"]

    # 2. 7 minutes later (T+420s): Plunge directly to STRONG_DOWNTREND (-2)
    # Level difference: from STRONG_UPTREND (+2) to STRONG_DOWNTREND (-2) = 4 levels!
    t_7m = t0 + datetime.timedelta(minutes=7)
    mgr.process_evaluation(-70, False, t_7m)
    mgr.process_evaluation(-70, False, t_7m + datetime.timedelta(seconds=15))
    s_plunge = mgr.process_evaluation(-70, False, t_7m + datetime.timedelta(seconds=30))

    assert s_plunge["current_regime"] == "STRONG_DOWNTREND"
    # Bypasses cooldown because level_diff >= 2!
    assert s_plunge["should_alert"] is True
    assert s_plunge["alert_reason"] == "LEVEL_2_JUMP"


def test_06_state_persistence_across_restart(tmp_path):
    """
    Requirement 6:
    State persists to JSON so restart does not re-fire alerts.
    """
    state_file = tmp_path / "persist_test.json"
    mgr1 = MarketRegimeStateManager(state_file=state_file)

    t_now = datetime.datetime(2026, 11, 16, 11, 0, tzinfo=IST)
    # Confirm a regime
    for _ in range(3):
        mgr1.process_evaluation(score=65, is_divergence=False, now_dt=t_now)

    assert mgr1.current_regime == "STRONG_UPTREND"
    assert mgr1.last_alerted_regime == "STRONG_UPTREND"

    # Simulate restart by creating a brand new manager instance pointing to same file
    mgr2 = MarketRegimeStateManager(state_file=state_file)
    assert mgr2.current_regime == "STRONG_UPTREND"
    assert mgr2.last_alerted_regime == "STRONG_UPTREND"
    assert mgr2.last_alert_time == mgr1.last_alert_time

    # Subsequent evaluation does NOT re-alert
    step = mgr2.process_evaluation(score=65, is_divergence=False, now_dt=t_now + datetime.timedelta(seconds=30))
    assert step["should_alert"] is False
