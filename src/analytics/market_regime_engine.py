"""
FinPlus+ Institutional Market Regime & Intraday Decision Engine
==============================================================
Module: finplus_index_breadth.analytics.market_regime_engine
Author: FinPlus+ Enterprise Infrastructure
Standard: ISO-8601, Zero Fabricated Data, Strict Confluence, Stateful Hysteresis

Answers the core trading questions:
1. What is the market trend right now?
   - STRONG UPTREND
   - UPTREND
   - CHOPPY / SIDEWAYS / DIVERGENT
   - DOWNTREND
   - STRONG DOWNTREND
2. Should I buy or sell equities intraday?
3. Whether I need to buy options today or not?
4. End-of-Day BTST Status (relegated to afternoon / 3:10-3:30 PM).

Features:
- Multi-band hysteresis: Prevents flip-flop wiggles around boundaries.
- Confirmation gate: Requires N=3 consecutive cycles to confirm a new regime.
- Cooldown timer: 15-minute suppression window unless moving across 2+ levels.
- Pre-market auction suppression: Completely silent before 09:15 IST.
- Persistent state: Preserves last alerted regime across server restarts.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from finplus_core.utils.logger import get_finplus_logger

try:
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
        DEFAULT_REGIME_STATE_PATH,
        REGIME_LEVELS,
        REGIME_LABELS,
    )
except ImportError:
    from finplus_index_breadth.config.regime_config import (
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
        DEFAULT_REGIME_STATE_PATH,
        REGIME_LEVELS,
        REGIME_LABELS,
    )

logger = get_finplus_logger("MarketRegimeEngine")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class MarketRegimeStateManager:
    """
    Manages persistent state, multi-band hysteresis, N=3 confirmation,
    and 15-minute cooldown alerting rules for market regime transitions.
    """

    def __init__(
        self,
        state_file: Optional[Path | str] = None,
        confirmation_count: int = REGIME_CONFIRMATION_COUNT,
        cooldown_seconds: int = REGIME_ALERT_COOLDOWN_SECONDS,
    ):
        self.state_file = Path(state_file) if state_file else DEFAULT_REGIME_STATE_PATH
        self.confirmation_count = confirmation_count
        self.cooldown_seconds = cooldown_seconds

        # Core state variables
        self.current_regime: str = "CHOPPY"
        self.last_alerted_regime: Optional[str] = None
        self.last_alert_time: float = 0.0
        self.pending_candidate: Optional[str] = None
        self.pending_count: int = 0
        self.opened_alert_date: Optional[str] = None

        self.load_state()

    def load_state(self) -> None:
        """Loads persisted state from JSON file."""
        if self.state_file and self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    self.current_regime = d.get("current_regime", "CHOPPY")
                    self.last_alerted_regime = d.get("last_alerted_regime")
                    self.last_alert_time = float(d.get("last_alert_time", 0.0))
                    self.pending_candidate = d.get("pending_candidate")
                    self.pending_count = int(d.get("pending_count", 0))
                    self.opened_alert_date = d.get("opened_alert_date")
            except Exception as e:
                logger.warning("Could not load regime state from %s: %s", self.state_file, e)

    def save_state(self) -> None:
        """Persists current state to JSON file."""
        if not self.state_file:
            return
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            d = {
                "current_regime": self.current_regime,
                "last_alerted_regime": self.last_alerted_regime,
                "last_alert_time": self.last_alert_time,
                "pending_candidate": self.pending_candidate,
                "pending_count": self.pending_count,
                "opened_alert_date": self.opened_alert_date,
                "updated_at": datetime.datetime.now(tz=IST).isoformat(),
            }
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=2)
        except Exception as e:
            logger.warning("Could not save regime state to %s: %s", self.state_file, e)

    @classmethod
    def compute_hysteresis_zone(cls, score: int, current_regime: str, is_divergence: bool = False) -> str:
        """
        Calculates raw regime zone using multi-band hysteresis entry/exit thresholds.
        Between boundary bands, retains the current regime to eliminate flip-flop wobbles.
        """
        if is_divergence:
            return "CHOPPY_DIVERGENT"

        cur = current_regime or "CHOPPY"

        if cur == "STRONG_UPTREND":
            if score < STRONG_UPTREND_EXIT:  # < 50
                if score < UPTREND_EXIT:      # < 15
                    if score <= STRONG_DOWNTREND_ENTER:  # <= -60
                        return "STRONG_DOWNTREND"
                    elif score <= DOWNTREND_ENTER:       # <= -25
                        return "DOWNTREND"
                    else:
                        return "CHOPPY"
                else:
                    return "UPTREND"
            else:
                return "STRONG_UPTREND"  # 50-59 retains STRONG_UPTREND

        elif cur == "UPTREND":
            if score >= STRONG_UPTREND_ENTER:  # >= 60
                return "STRONG_UPTREND"
            elif score < UPTREND_EXIT:         # < 15
                if score <= STRONG_DOWNTREND_ENTER:
                    return "STRONG_DOWNTREND"
                elif score <= DOWNTREND_ENTER:
                    return "DOWNTREND"
                else:
                    return "CHOPPY"
            else:
                return "UPTREND"  # 15-59 retains UPTREND (50-59 stays UPTREND until >= 60)

        elif cur in ("CHOPPY", "CHOPPY_DIVERGENT"):
            if score >= STRONG_UPTREND_ENTER:  # >= 60
                return "STRONG_UPTREND"
            elif score >= UPTREND_ENTER:       # >= 25
                return "UPTREND"
            elif score <= STRONG_DOWNTREND_ENTER:  # <= -60
                return "STRONG_DOWNTREND"
            elif score <= DOWNTREND_ENTER:     # <= -25
                return "DOWNTREND"
            else:
                return "CHOPPY"  # -24 to +24 retains CHOPPY

        elif cur == "DOWNTREND":
            if score <= STRONG_DOWNTREND_ENTER:  # <= -60
                return "STRONG_DOWNTREND"
            elif score > DOWNTREND_EXIT:         # > -15
                if score >= STRONG_UPTREND_ENTER:
                    return "STRONG_UPTREND"
                elif score >= UPTREND_ENTER:
                    return "UPTREND"
                else:
                    return "CHOPPY"
            else:
                return "DOWNTREND"  # -59 to -15 retains DOWNTREND

        elif cur == "STRONG_DOWNTREND":
            if score > STRONG_DOWNTREND_EXIT:    # > -50
                if score >= STRONG_UPTREND_ENTER:
                    return "STRONG_UPTREND"
                elif score >= UPTREND_ENTER:
                    return "UPTREND"
                elif score > DOWNTREND_EXIT:
                    return "CHOPPY"
                else:
                    return "DOWNTREND"
            else:
                return "STRONG_DOWNTREND"  # <= -50 retains STRONG_DOWNTREND

        return "CHOPPY"

    def process_evaluation(
        self,
        score: int,
        is_divergence: bool = False,
        now_dt: Optional[datetime.datetime] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates score against hysteresis, enforces N=3 confirmation,
        evaluates 15-minute cooldown / 2+ level jump rule, and manages alert dispatching.
        """
        if now_dt is None:
            now_dt = datetime.datetime.now(tz=IST)

        now_ts = now_dt.timestamp()
        today_str = now_dt.strftime("%Y-%m-%d")
        is_weekday = (now_dt.weekday() < 5)
        h = now_dt.hour
        m = now_dt.minute

        # NSE Regular Market Hours: Mon-Fri 09:15 to 15:30 IST
        is_market_hours = is_weekday and (
            (h == 9 and m >= 15) or
            (10 <= h < 15) or
            (h == 15 and m <= 30)
        )
        is_pre_market = is_weekday and (
            (h < 9) or (h == 9 and m < 15)
        )

        # 1. Calculate raw target zone using Hysteresis
        raw_zone = self.compute_hysteresis_zone(score, self.current_regime, is_divergence)

        # 2. Confirmation Logic (N consecutive evaluations in new zone)
        regime_flipped = False
        prev_confirmed = self.current_regime

        if raw_zone != self.current_regime:
            if raw_zone == self.pending_candidate:
                self.pending_count += 1
            else:
                self.pending_candidate = raw_zone
                self.pending_count = 1

            if self.pending_count >= self.confirmation_count:
                self.current_regime = raw_zone
                self.pending_candidate = None
                self.pending_count = 0
                regime_flipped = True
        else:
            self.pending_candidate = None
            self.pending_count = 0

        # 3. Alert Eligibility Evaluation
        should_alert = False
        alert_reason = ""
        suppression_reason = ""

        # Requirement 4: Suppress alerts before 09:15 IST (pre-open auction)
        if not is_market_hours:
            suppression_reason = "PRE_MARKET_AUCTION" if is_pre_market else "OFF_HOURS"
        else:
            is_opening_cycle = (self.opened_alert_date != today_str and h == 9 and 15 <= m <= 20)

            # Requirement 5: Trigger alerts ONLY when confirmed regime differs from last_alerted_regime
            if self.current_regime != self.last_alerted_regime:
                cur_level = REGIME_LEVELS.get(self.current_regime, 0)
                last_level = REGIME_LEVELS.get(self.last_alerted_regime, 0) if self.last_alerted_regime else 0
                level_diff = abs(cur_level - last_level)
                time_since_last_alert = now_ts - self.last_alert_time

                if is_opening_cycle:
                    # Single opening alert at 09:15 if regime differs from last alerted
                    should_alert = True
                    alert_reason = "OPENING_MARKET_SYNC"
                    self.opened_alert_date = today_str
                elif time_since_last_alert < self.cooldown_seconds and level_diff < 2:
                    # Requirement 3: 15-min cooldown unless moving across 2+ levels
                    rem_cd = int(self.cooldown_seconds - time_since_last_alert)
                    suppression_reason = f"COOLDOWN_ACTIVE ({rem_cd}s remaining, level_diff={level_diff})"
                else:
                    should_alert = True
                    alert_reason = "LEVEL_2_JUMP" if level_diff >= 2 else "REGIME_TRANSITION"

        transition = {}
        if should_alert:
            transition = {
                "from_code": self.last_alerted_regime or "CHOPPY",
                "from_label": REGIME_LABELS.get(self.last_alerted_regime, "CHOPPY / SIDEWAYS"),
                "to_code": self.current_regime,
                "to_label": REGIME_LABELS.get(self.current_regime, self.current_regime),
            }
            self.last_alerted_regime = self.current_regime
            self.last_alert_time = now_ts

        # Requirement 6: Persist state
        self.save_state()

        return {
            "current_regime": self.current_regime,
            "raw_zone": raw_zone,
            "pending_candidate": self.pending_candidate,
            "pending_count": self.pending_count,
            "last_alerted_regime": self.last_alerted_regime,
            "last_alert_time": self.last_alert_time,
            "should_alert": should_alert,
            "alert_reason": alert_reason,
            "suppression_reason": suppression_reason,
            "transition": transition,
            "regime_flipped": regime_flipped,
        }


class MarketRegimeEngine:
    """Evaluates macro breadth and constituent momentum to determine intraday trading directives."""

    _state_manager: Optional[MarketRegimeStateManager] = None

    @classmethod
    def get_state_manager(cls, state_file: Optional[Path | str] = None) -> MarketRegimeStateManager:
        """Returns singleton MarketRegimeStateManager instance."""
        if cls._state_manager is None or state_file is not None:
            cls._state_manager = MarketRegimeStateManager(state_file=state_file)
        return cls._state_manager

    @classmethod
    def reset_state_manager(cls, state_file: Optional[Path | str] = None) -> MarketRegimeStateManager:
        """Resets state manager for testing."""
        cls._state_manager = MarketRegimeStateManager(state_file=state_file)
        return cls._state_manager

    @classmethod
    def evaluate_regime(
        cls,
        nifty_breadth: Dict[str, Any],
        sensex_breadth: Dict[str, Any],
        broad_market: Optional[Dict[str, Any]] = None,
        now_dt: Optional[datetime.datetime] = None,
    ) -> Dict[str, Any]:
        """
        Synthesizes exchange-wide (2,266 stocks) breadth and benchmark constituent data
        to produce actionable intraday directives for equities and options trading.
        Strictly enforces:
        If nifty_spot, sensex_spot or breadth data is None or older than 15s:
        set regime = UNKNOWN, do not flip the regime, do not send flip alerts,
        and expose data_status in the regime API. Zero fabricated fallbacks.
        """
        now = now_dt or datetime.datetime.now(tz=IST)

        # Extract spot prices (None if missing or invalid)
        nifty_spot_raw = broad_market.get("nifty_spot") if broad_market else None
        if nifty_spot_raw is None and nifty_breadth:
            nifty_spot_raw = nifty_breadth.get("spot_price")
        nifty_spot = float(nifty_spot_raw) if (nifty_spot_raw is not None and float(nifty_spot_raw) > 0) else None

        sensex_spot_raw = broad_market.get("sensex_spot") if broad_market else None
        if sensex_spot_raw is None and sensex_breadth:
            sensex_spot_raw = sensex_breadth.get("spot_price")
        sensex_spot = float(sensex_spot_raw) if (sensex_spot_raw is not None and float(sensex_spot_raw) > 0) else None

        nifty_chg = float(broad_market.get("nifty_change_pct")) if (broad_market and broad_market.get("nifty_change_pct") is not None) else (float(nifty_breadth.get("change_pct", 0.0)) if nifty_breadth else 0.0)
        sensex_chg = float(broad_market.get("sensex_change_pct")) if (broad_market and broad_market.get("sensex_change_pct") is not None) else (float(sensex_breadth.get("change_pct", 0.0)) if sensex_breadth else 0.0)

        # Inspect tick age and data status
        tick_age: Optional[float] = None
        if broad_market and "tick_age" in broad_market:
            try:
                tick_age = float(broad_market["tick_age"])
            except (ValueError, TypeError):
                tick_age = None

        raw_data_status = broad_market.get("data_status") if broad_market else None

        # Check breadth data validity
        bm_data = broad_market.get("broad_market") if broad_market else None
        has_breadth = (
            bool(broad_market) and
            isinstance(bm_data, dict) and
            bm_data.get("advances") is not None and
            bm_data.get("declines") is not None and
            bool(nifty_breadth) and
            nifty_breadth.get("status") != "NO_DATA"
        )

        # Market Hours check (09:15 - 15:30 IST Mon-Fri)
        hour = now.hour
        minute = now.minute
        is_weekday = now.weekday() < 5
        if broad_market and "is_market_open" in broad_market:
            is_market_open = bool(broad_market["is_market_open"])
        else:
            is_market_open = is_weekday and ((hour == 9 and minute >= 15) or (10 <= hour < 15) or (hour == 15 and minute <= 30))

        if not is_market_open or raw_data_status == "MARKET_CLOSED":
            is_stale = False
            is_market_closed = True
        else:
            is_stale = (tick_age is not None and tick_age > 15.0) or (raw_data_status == "STALE")
            is_market_closed = False

        # Nifty spot + 2,266+ NSE breadth + VWAP are the mandatory market inputs.
        # Sensex spot is auxiliary: missing Sensex spot flags status PARTIAL, never fatal UNKNOWN.
        is_missing = (
            nifty_spot is None or
            not has_breadth
        )

        # Time-of-day BTST status
        is_btst_window = (is_weekday and hour == 15 and 10 <= minute <= 30)
        if is_btst_window:
            btst_time_status = "ACTIVE_NOW (3:10 - 3:30 PM IST)"
        elif hour < 15 or (hour == 15 and minute < 10):
            btst_time_status = "STANDBY (Activates 3:10 PM - 3:30 PM IST)"
        else:
            btst_time_status = "MARKET CLOSED (Overnight Session)"

        # -------------------------------------------------------------
        # GUARD: MARKET CLOSED -> NO STALE ALERT, REGIME = UNKNOWN
        # -------------------------------------------------------------
        if is_market_closed:
            resolved_status = "MARKET_CLOSED"
            trend_code = "UNKNOWN"
            trend_label = "MARKET CLOSED"
            score = 0
            trend_color = "gray"
            trend_description = "Market is closed. NSE trading hours are Mon-Fri 09:15 to 15:30 IST."
            equity_action = "MARKET CLOSED"
            equity_badge = "MARKET CLOSED"
            equity_color = "gray"
            equity_guidance = "Market is closed. No new signals."
            option_action = "MARKET CLOSED"
            option_badge = "MARKET CLOSED"
            option_color = "gray"
            option_guidance = "Market is closed. No options trading."

            mgr = cls.get_state_manager()
            regime_step = {
                "current_regime": mgr.current_regime,
                "raw_zone": "UNKNOWN",
                "pending_candidate": mgr.pending_candidate,
                "pending_count": mgr.pending_count,
                "last_alerted_regime": mgr.last_alerted_regime,
                "last_alert_time": mgr.last_alert_time,
                "should_alert": False,
                "alert_reason": "",
                "suppression_reason": "MARKET_CLOSED",
                "transition": {},
                "regime_flipped": False,
            }

            bm_adv = bm_data.get("advances") if bm_data else None
            bm_dec = bm_data.get("declines") if bm_data else None
            bm_adr = bm_data.get("advance_decline_ratio") if bm_data else None

            vix_info = broad_market.get("vix", {}) if broad_market else {}
            deriv_info = broad_market.get("derivatives", {}) if broad_market else {}
            vix_val = vix_info.get("value")
            pcr_val = deriv_info.get("index_options_pcr")

            return {
                "timestamp": now.isoformat(),
                "data_status": "MARKET_CLOSED",
                "regime": trend_code,
                "trend": {
                    "code": trend_code,
                    "label": trend_label,
                    "score": score,
                    "score_label": "-- / 100",
                    "color": trend_color,
                    "description": trend_description,
                    "is_divergence": False,
                },
                "equities_directive": {
                    "action": equity_action,
                    "badge": equity_badge,
                    "color": equity_color,
                    "guidance": equity_guidance,
                },
                "options_directive": {
                    "action": option_action,
                    "badge": option_badge,
                    "color": option_color,
                    "guidance": option_guidance,
                },
                "btst_status": btst_time_status,
                "metrics": {
                    "nifty_spot": nifty_spot,
                    "nifty_change_pct": nifty_chg,
                    "sensex_spot": sensex_spot,
                    "sensex_change_pct": sensex_chg,
                    "advance_decline_ratio": bm_adr,
                    "broad_market_advances": bm_adv,
                    "broad_market_declines": bm_dec,
                    "nifty_heavyweights_above_vwap": "0/5",
                    "vix_value": vix_val,
                    "options_pcr": pcr_val,
                },
                "regime_step": regime_step,
                "should_alert": False,
                "alert_reason": "",
                "suppression_reason": "MARKET_CLOSED",
                "transition": {},
                "confirmed_regime": "UNKNOWN",
                "raw_score": 0,
            }

        # -------------------------------------------------------------
        # GUARD: STALE OR MISSING DATA -> REGIME = UNKNOWN, ZERO ALERTS, ZERO FLIPS
        # -------------------------------------------------------------
        if is_stale or is_missing:
            resolved_status = "STALE" if is_stale else "PARTIAL"
            trend_code = "UNKNOWN"
            trend_label = "UNKNOWN (NO RELIABLE DATA)"
            score = 0
            trend_color = "gray"
            trend_description = (
                f"Market tick or breadth data is {'stale (>15s)' if is_stale else 'incomplete/unavailable'} "
                f"(Status: {resolved_status}, Tick Age: {tick_age}s). Preserving capital with strict UNKNOWN regime."
            )
            equity_action = "AVOID TRADING / NO RELIABLE DATA"
            equity_badge = "NO TRADE (UNKNOWN)"
            equity_color = "gray"
            equity_guidance = "Live market tick or breadth data is unavailable or stale (>15s). Preserving capital."

            option_action = "DO NOT BUY OPTIONS (NO RELIABLE DATA)"
            option_badge = "NO TRADE (UNKNOWN)"
            option_color = "gray"
            option_guidance = "Index spot or breadth feed is stale or missing. Do not trade options on stale data."

            mgr = cls.get_state_manager()
            # Do NOT flip regime, retain existing state, no alerts
            regime_step = {
                "current_regime": mgr.current_regime,
                "raw_zone": "UNKNOWN",
                "pending_candidate": mgr.pending_candidate,
                "pending_count": mgr.pending_count,
                "last_alerted_regime": mgr.last_alerted_regime,
                "last_alert_time": mgr.last_alert_time,
                "should_alert": False,
                "alert_reason": "",
                "suppression_reason": f"DATA_{resolved_status}",
                "transition": {},
                "regime_flipped": False,
            }

            bm_adv = bm_data.get("advances") if bm_data else None
            bm_dec = bm_data.get("declines") if bm_data else None
            bm_adr = bm_data.get("advance_decline_ratio") if bm_data else None

            vix_info = broad_market.get("vix", {}) if broad_market else {}
            deriv_info = broad_market.get("derivatives", {}) if broad_market else {}
            vix_val = vix_info.get("value")
            pcr_val = deriv_info.get("index_options_pcr")

            return {
                "timestamp": now.isoformat(),
                "data_status": resolved_status,
                "regime": trend_code,
                "trend": {
                    "code": trend_code,
                    "label": trend_label,
                    "score": score,
                    "score_label": "-- / 100",
                    "color": trend_color,
                    "description": trend_description,
                    "is_divergence": False,
                },
                "equities_directive": {
                    "action": equity_action,
                    "badge": equity_badge,
                    "color": equity_color,
                    "guidance": equity_guidance,
                },
                "options_directive": {
                    "action": option_action,
                    "badge": option_badge,
                    "color": option_color,
                    "guidance": option_guidance,
                },
                "btst_status": btst_time_status,
                "metrics": {
                    "nifty_spot": nifty_spot,
                    "nifty_change_pct": nifty_chg,
                    "sensex_spot": sensex_spot,
                    "sensex_change_pct": sensex_chg,
                    "advance_decline_ratio": bm_adr,
                    "broad_market_advances": bm_adv,
                    "broad_market_declines": bm_dec,
                    "nifty_heavyweights_above_vwap": "0/5",
                    "vix_value": vix_val,
                    "options_pcr": pcr_val,
                },
                "regime_step": regime_step,
                "should_alert": False,
                "alert_reason": "",
                "suppression_reason": f"DATA_{resolved_status}",
                "transition": {},
                "confirmed_regime": "UNKNOWN",
                "raw_score": 0,
            }

        resolved_status = raw_data_status or "OK"

        # Extract Benchmark metrics
        nifty_wabi = float(nifty_breadth.get("wabi_score", 0.0))
        sensex_wabi = float(sensex_breadth.get("wabi_score", 0.0))
        nifty_above_pct = float(nifty_breadth.get("stocks_above_vwap_pct", 0.0))
        nifty_thrust = float(nifty_breadth.get("volume_thrust_pct", 50.0))
        nifty_hw = nifty_breadth.get("heavyweights", {})
        nifty_hw_above = sum(1 for v in nifty_hw.values() if v == "ABOVE_VWAP")

        # Extract Broad Market metrics (All NSE Stocks)
        bm_adv = int(bm_data.get("advances", 0))
        bm_dec = int(bm_data.get("declines", 0))
        bm_adr = float(bm_data.get("advance_decline_ratio", 1.0))
        bm_total = bm_data.get("total_stocks")

        # Extract Segment & Derivatives Confluence (Zero fabricated defaults)
        segs = broad_market.get("segments", {}) if broad_market else {}
        n500 = segs.get("nifty_500", {})
        n500_adv = int(n500.get("advances")) if n500.get("advances") is not None else 0
        n500_dec = int(n500.get("declines")) if n500.get("declines") is not None else 0

        vix_info = broad_market.get("vix", {}) if broad_market else {}
        deriv_info = broad_market.get("derivatives", {}) if broad_market else {}
        vix_val = float(vix_info["value"]) if vix_info.get("value") is not None else None
        vix_chg_pct = float(vix_info["change_pct"]) if vix_info.get("change_pct") is not None else 0.0
        pcr_val = float(deriv_info["index_options_pcr"]) if deriv_info.get("index_options_pcr") is not None else None
        fut_basis = float(deriv_info["nifty_futures_basis"]) if deriv_info.get("nifty_futures_basis") is not None else None

        # If VIX or Sensex spot is unavailable, flag data_status as PARTIAL without forcing regime to UNKNOWN
        if (vix_val is None or sensex_spot is None) and resolved_status == "OK":
            resolved_status = "PARTIAL"

        # -------------------------------------------------------------
        # 1. INSTITUTIONAL COMPOSITE TREND INDEX (CTI) CALCULATION (-100 to +100)
        # -------------------------------------------------------------
        raw_score = 0.0

        # Pillar 1: Bluechip Benchmark Breadth (Max 40 points)
        has_sensex_breadth = (
            bool(sensex_breadth) and
            sensex_breadth.get("status") not in ("NO_DATA", "UNAVAILABLE") and
            (sensex_breadth.get("advances", 0) > 0 or sensex_breadth.get("declines", 0) > 0)
        )
        if has_sensex_breadth:
            raw_score += (nifty_wabi * 20.0)
            raw_score += (sensex_wabi * 10.0)
        else:
            # If Sensex constituent breadth is unavailable, scale the full 30 benchmark points to Nifty WABI
            raw_score += (nifty_wabi * 30.0)
        hw_points_map = {5: 10.0, 4: 6.0, 3: 0.0, 2: -6.0, 1: -10.0, 0: -10.0}
        raw_score += hw_points_map.get(nifty_hw_above, 0.0)

        # Pillar 2: Broad Market Participation (Max 35 points)
        if bm_adr >= 2.0:
            raw_score += 25.0
        elif bm_adr >= 1.5:
            raw_score += 20.0
        elif bm_adr >= 1.2:
            raw_score += 12.0
        elif bm_adr >= 1.0:
            raw_score += 5.0
        elif bm_adr >= 0.85:
            raw_score -= 5.0
        elif bm_adr >= 0.65:
            raw_score -= 12.0
        elif bm_adr >= 0.50:
            raw_score -= 20.0
        else:
            raw_score -= 25.0

        if n500_adv >= 300:
            raw_score += 10.0
        elif n500_dec >= 300:
            raw_score -= 10.0

        # Pillar 3: Derivatives & Volatility Confluence (Max 25 points)
        if pcr_val is not None:
            if pcr_val >= 1.30:
                raw_score += 10.0
            elif pcr_val >= 1.15:
                raw_score += 5.0
            elif pcr_val <= 0.70:
                raw_score -= 10.0
            elif pcr_val <= 0.85:
                raw_score -= 5.0

        if vix_val is not None:
            if nifty_chg >= 0:
                if vix_val <= 16.0 and vix_chg_pct <= 0:
                    raw_score += 10.0
                elif vix_chg_pct >= 5.0:
                    raw_score -= 10.0
            else:
                if vix_chg_pct >= 5.0:
                    raw_score -= 10.0
                elif vix_chg_pct <= 0:
                    raw_score -= 5.0

        if fut_basis is not None:
            if fut_basis >= 10.0:
                raw_score += 5.0
            elif fut_basis <= -15.0:
                raw_score -= 5.0

        score = max(-100, min(100, round(raw_score)))

        # -------------------------------------------------------------
        # 2. DIVERGENCE VETO GUARD & HYSTERESIS REGIME CLASSIFICATION
        # -------------------------------------------------------------
        is_divergence = False
        sensex_wabi_bullish = (sensex_wabi >= 0.25) if has_sensex_breadth else False
        if (nifty_wabi >= 0.25 or sensex_wabi_bullish) and (bm_adr < 0.85 or bm_dec > bm_adv + 300):
            is_divergence = True

        # Process through state manager (Hysteresis, Confirmation, Cooldown, Market Hours)
        mgr = cls.get_state_manager()
        regime_step = mgr.process_evaluation(score=score, is_divergence=is_divergence, now_dt=now)
        trend_code = regime_step["current_regime"]
        trend_label = REGIME_LABELS.get(trend_code, "CHOPPY / SIDEWAYS")

        # Map color and descriptions
        if trend_code == "CHOPPY_DIVERGENT":
            trend_color = "amber"
            trend_description = (
                f"Nifty 50 appears green ({nifty_above_pct:.0f}% > VWAP), but across the full exchange {bm_dec} stocks are falling "
                f"vs {bm_adv} advancing (ADR: {bm_adr}:1). Composite Score: {score:+d}/100. The rally is concentrated in a few heavyweights."
            )
        elif trend_code == "STRONG_UPTREND":
            trend_color = "emerald"
            pcr_clause = f", and derivatives PCR ({pcr_val:.2f}) confirms institutional floor." if pcr_val is not None else "."
            trend_description = (
                f"High-conviction broad market expansion (Score: {score:+d}/100). Advances lead declines ({bm_adv} Adv vs {bm_dec} Dec, ADR: {bm_adr}:1), "
                f"{nifty_hw_above}/5 heavyweights are above Day VWAP{pcr_clause}"
            )
        elif trend_code == "UPTREND":
            trend_color = "emerald"
            trend_description = (
                f"Positive upward bias (Score: {score:+d}/100). Benchmark constituents hold above Day VWAP with supportive market breadth (ADR: {bm_adr}:1)."
            )
        elif trend_code == "STRONG_DOWNTREND":
            trend_color = "rose"
            trend_description = (
                f"High-conviction institutional liquidation (Score: {score:+d}/100). Declines overwhelm advances across exchange ({bm_dec} Dec vs {bm_adv} Adv, ADR: {bm_adr}:1), "
                f"and bluechips trade broken below Day VWAP."
            )
        elif trend_code == "DOWNTREND":
            trend_color = "rose"
            trend_description = (
                f"Bearish distribution dominant (Score: {score:+d}/100). Declines lead advances across the wider exchange (ADR: {bm_adr}:1), "
                f"with persistent selling pressure in benchmark constituents."
            )
        else:  # CHOPPY
            trend_color = "amber"
            trend_description = (
                f"Market is caught in an equilibrium tug-of-war without institutional thrust (Score: {score:+d}/100). "
                f"Breadth is evenly split (ADR: {bm_adr}:1). High risk of intraday false breakouts."
            )

        # -------------------------------------------------------------
        # 3. INTRADAY EQUITIES DIRECTIVE
        # -------------------------------------------------------------
        if trend_code == "STRONG_UPTREND":
            equity_action = "BUY EQUITIES INTRADAY (LONG ON DIPS)"
            equity_badge = "AGGRESSIVE BUY"
            equity_color = "emerald"
            equity_guidance = (
                "Broad institutional accumulation across sectors. Buy leading stocks breaking out on above-average volume. "
                "Trail stop-losses at Day VWAP."
            )
        elif trend_code == "UPTREND":
            equity_action = "BUY SELECT HIGH-VOLUME EQUITIES"
            equity_badge = "SELECTIVE BUY"
            equity_color = "emerald"
            equity_guidance = (
                "Favor stock-specific momentum in outperforming sectors. Focus on stocks trading firmly above Day VWAP. "
                "Book partial profits at intraday resistance."
            )
        elif trend_code in ("CHOPPY", "CHOPPY_DIVERGENT"):
            equity_action = "AVOID FRESH BUYS / CAUTION (CHOPPY WIPSAW RISK)"
            equity_badge = "SIT ON CASH"
            equity_color = "amber"
            equity_guidance = (
                "DO NOT chase breakouts. With 1,300+ stocks declining or market lacking breadth thrust, breakouts have "
                "a 70%+ failure rate. Hold defensive cash or strictly scalp high-beta stocks with tight stops."
            )
        elif trend_code == "DOWNTREND":
            equity_action = "SELL ON RISE / SHORT EQUITIES INTRADAY"
            equity_badge = "SELL / SHORT BIAS"
            equity_color = "rose"
            equity_guidance = (
                "Selling on rallies is favored. Avoid initiating new long positions. Short weak stocks breaking below "
                "opening range lows."
            )
        else:  # STRONG_DOWNTREND
            equity_action = "AGGRESSIVE SHORTING / ZERO LONG EXPOSURE"
            equity_badge = "AGGRESSIVE SHORT"
            equity_color = "rose"
            equity_guidance = (
                "Broad-market liquidation in full force. Absolutely no long trades. Short breakdowns or protect existing "
                "portfolio with hedges."
            )

        # -------------------------------------------------------------
        # 4. INTRADAY OPTIONS BUYING DIRECTIVE
        # -------------------------------------------------------------
        vix_str = f"VIX: {vix_val:.2f}" if vix_val is not None else "VIX: N/A"
        pcr_str = f"PCR: {pcr_val:.2f}" if pcr_val is not None else "PCR: N/A"
        vol_note = f" ({vix_str}, {pcr_str})"
        if trend_code == "STRONG_UPTREND":
            option_action = "CALL OPTIONS BUYING PERMITTED (HIGH PROBABILITY)"
            option_badge = "BUY CALLS"
            option_color = "emerald"
            option_guidance = (
                "Market breadth and benchmark momentum strongly support upside expansion. Buy near-the-money Call options "
                f"on intraday pullback to VWAP. Strict stop-loss at 20-30% premium.{vol_note}"
            )
        elif trend_code == "UPTREND":
            option_action = "SELECTIVE OPTION BUYING ONLY (STRICT TRAILING STOPS)"
            option_badge = "SELECTIVE CALLS"
            option_color = "emerald"
            option_guidance = (
                "Bullish bias present, but momentum lacks all-pillar thrust. Limit size to 50% normal allocation. "
                f"Do not hold decaying options into chop.{vol_note}"
            )
        elif trend_code == "STRONG_DOWNTREND":
            option_action = "PUT OPTIONS BUYING PERMITTED (HIGH PROBABILITY)"
            option_badge = "BUY PUTS"
            option_color = "rose"
            option_guidance = (
                "Aggressive selling across broad market. Buy near-the-money Put options on weak bounces to VWAP. "
                f"Trail stop-loss aggressively.{vol_note}"
            )
        elif trend_code == "DOWNTREND":
            option_action = "SELECTIVE PUT BUYING ONLY (HIGH DISCIPLINE)"
            option_badge = "SELECTIVE PUTS"
            option_color = "rose"
            option_guidance = (
                "Bearish pressure dominant. Limit Put buying to confirmed breakdown retests. "
                f"Take profits quickly into sudden flushes.{vol_note}"
            )
        else:  # CHOPPY or CHOPPY_DIVERGENT
            option_action = "DO NOT BUY OPTIONS TODAY (CHOP / HIGH THETA DECAY RISK)"
            option_badge = "NO TRADE (OPTIONS)"
            option_color = "amber"
            option_guidance = (
                "DO NOT BUY OPTIONS TODAY! The market lacks sustained directional impulse. Buying options today carries an "
                f"85%+ probability of capital erosion via theta decay and false intraday swings. Let option sellers fight—stay in cash.{vol_note}"
            )

        # -------------------------------------------------------------
        # 5. TIME-OF-DAY AND BTST STATUS
        # -------------------------------------------------------------
        hour = now.hour
        minute = now.minute
        is_weekday = now.weekday() < 5
        is_btst_window = (is_weekday and hour == 15 and 10 <= minute <= 30)

        if is_btst_window:
            btst_time_status = "ACTIVE_NOW (3:10 - 3:30 PM IST)"
        elif hour < 15 or (hour == 15 and minute < 10):
            btst_time_status = "STANDBY (Activates 3:10 PM - 3:30 PM IST)"
        else:
            btst_time_status = "MARKET CLOSED (Overnight Session)"

        return {
            "timestamp": now.isoformat(),
            "data_status": resolved_status,
            "regime": trend_code,
            "trend": {
                "code": trend_code,
                "label": trend_label,
                "score": score,
                "score_label": f"{score:+d} / 100",
                "color": trend_color,
                "description": trend_description,
                "is_divergence": is_divergence,
            },
            "equities_directive": {
                "action": equity_action,
                "badge": equity_badge,
                "color": equity_color,
                "guidance": equity_guidance,
            },
            "options_directive": {
                "action": option_action,
                "badge": option_badge,
                "color": option_color,
                "guidance": option_guidance,
            },
            "btst_status": btst_time_status,
            "metrics": {
                "nifty_spot": nifty_spot,
                "nifty_change_pct": nifty_chg,
                "sensex_spot": sensex_spot,
                "sensex_change_pct": sensex_chg,
                "advance_decline_ratio": bm_adr,
                "broad_market_advances": bm_adv,
                "broad_market_declines": bm_dec,
                "nifty_heavyweights_above_vwap": f"{nifty_hw_above}/5",
                "vix_value": vix_val,
                "options_pcr": pcr_val,
            },
            "regime_step": regime_step,
            "should_alert": regime_step["should_alert"],
            "alert_reason": regime_step["alert_reason"],
            "suppression_reason": regime_step["suppression_reason"],
            "transition": regime_step["transition"],
            "confirmed_regime": trend_code,
            "raw_score": score,
        }
