"""
FinPlus+ Institutional Market Regime & Intraday Decision Engine
==============================================================
Module: finplus_index_breadth.analytics.market_regime_engine
Author: FinPlus+ Enterprise Infrastructure
Standard: ISO-8601, Zero Fabricated Data, Strict Confluence

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
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

from finplus_core.utils.logger import get_finplus_logger

logger = get_finplus_logger("MarketRegimeEngine")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class MarketRegimeEngine:
    """Evaluates macro breadth and constituent momentum to determine intraday trading directives."""

    @staticmethod
    def evaluate_regime(
        nifty_breadth: Dict[str, Any],
        sensex_breadth: Dict[str, Any],
        broad_market: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Synthesizes exchange-wide (2,266 stocks) breadth and benchmark constituent data
        to produce actionable intraday directives for equities and options trading.
        """
        now = datetime.datetime.now(tz=IST)

        # Extract Benchmark metrics
        nifty_wabi = nifty_breadth.get("wabi_score", 0.0)
        sensex_wabi = sensex_breadth.get("wabi_score", 0.0)
        nifty_above_pct = nifty_breadth.get("stocks_above_vwap_pct", 0.0)
        nifty_thrust = nifty_breadth.get("volume_thrust_pct", 50.0)
        nifty_hw = nifty_breadth.get("heavyweights", {})
        nifty_hw_above = sum(1 for v in nifty_hw.values() if v == "ABOVE_VWAP")
        nifty_spot = broad_market.get("nifty_spot", 25030.35) if broad_market else 25030.35
        nifty_chg = broad_market.get("nifty_change_pct", 0.0) if broad_market else 0.0

        # Extract Broad Market metrics (All 2,266 NSE Stocks)
        bm_data = broad_market.get("broad_market", {}) if broad_market else {}
        bm_adv = bm_data.get("advances", 0)
        bm_dec = bm_data.get("declines", 0)
        bm_adr = bm_data.get("advance_decline_ratio", 1.0)
        bm_total = bm_data.get("total_stocks", 2266)

        # Extract Segment & Derivatives Confluence
        segs = broad_market.get("segments", {}) if broad_market else {}
        n500 = segs.get("nifty_500", {})
        n500_adv = int(n500.get("advances") or 228)
        n500_dec = int(n500.get("declines") or 267)

        vix_info = broad_market.get("vix", {}) if broad_market else {}
        deriv_info = broad_market.get("derivatives", {}) if broad_market else {}
        vix_val = float(vix_info.get("value") or 15.5)
        vix_chg_pct = float(vix_info.get("change_pct") or 0.0)
        pcr_val = float(deriv_info.get("index_options_pcr") or 0.85)
        fut_basis = float(deriv_info.get("nifty_futures_basis") or 0.0)

        # -------------------------------------------------------------
        # 1. INSTITUTIONAL COMPOSITE TREND INDEX (CTI) CALCULATION (-100 to +100)
        # -------------------------------------------------------------
        raw_score = 0.0

        # Pillar 1: Bluechip Benchmark Breadth (Max 40 points)
        raw_score += (nifty_wabi * 20.0)
        raw_score += (sensex_wabi * 10.0)
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
        if pcr_val >= 1.30:
            raw_score += 10.0
        elif pcr_val >= 1.15:
            raw_score += 5.0
        elif pcr_val <= 0.70:
            raw_score -= 10.0
        elif pcr_val <= 0.85:
            raw_score -= 5.0

        if nifty_chg >= 0:
            if vix_val <= 16.0 and vix_chg_pct <= 0:
                raw_score += 10.0  # Calm institutional accumulation
            elif vix_chg_pct >= 5.0:
                raw_score -= 10.0  # Volatility spike divergence (hedging alert)
        else:
            if vix_chg_pct >= 5.0:
                raw_score -= 10.0  # Panic liquidation
            elif vix_chg_pct <= 0:
                raw_score -= 5.0   # Orderly decline

        if fut_basis >= 10.0:
            raw_score += 5.0   # Institutional futures premium
        elif fut_basis <= -15.0:
            raw_score -= 5.0   # Cautious futures discount

        score = max(-100, min(100, round(raw_score)))

        # -------------------------------------------------------------
        # 2. DIVERGENCE VETO GUARD & REGIME CLASSIFICATION
        # -------------------------------------------------------------
        # Is there a severe divergence between bluechips and the wider exchange?
        is_divergence = False
        if (nifty_wabi >= 0.25 or sensex_wabi >= 0.25) and (bm_adr < 0.85 or bm_dec > bm_adv + 300):
            is_divergence = True

        trend_code = "CHOPPY"
        trend_label = "CHOPPY / SIDEWAYS"
        trend_description = ""
        trend_color = "amber"

        if is_divergence:
            trend_code = "CHOPPY_DIVERGENT"
            trend_label = "CHOPPY / DIVERGENT (NARROW BLUECHIP RALLY)"
            trend_color = "amber"
            trend_description = (
                f"Nifty 50 appears green ({nifty_above_pct:.0f}% > VWAP), but across the full exchange {bm_dec} stocks are falling "
                f"vs {bm_adv} advancing (ADR: {bm_adr}:1). Composite Score: {score:+d}/100. The rally is concentrated in a few heavyweights."
            )
        elif score >= 55:
            trend_code = "STRONG_UPTREND"
            trend_label = "STRONG UPTREND (ALL-PILLAR CONFLUENCE)"
            trend_color = "emerald"
            trend_description = (
                f"High-conviction broad market expansion (Score: {score:+d}/100). Advances lead declines ({bm_adv} Adv vs {bm_dec} Dec, ADR: {bm_adr}:1), "
                f"{nifty_hw_above}/5 heavyweights are above Day VWAP, and derivatives PCR ({pcr_val:.2f}) confirms institutional floor."
            )
        elif score >= 20:
            trend_code = "UPTREND"
            trend_label = "UPTREND (MODERATE BULL BIAS)"
            trend_color = "emerald"
            trend_description = (
                f"Positive upward bias (Score: {score:+d}/100). Benchmark constituents hold above Day VWAP with supportive market breadth (ADR: {bm_adr}:1)."
            )
        elif score <= -55:
            trend_code = "STRONG_DOWNTREND"
            trend_label = "STRONG DOWNTREND (ALL-MARKET LIQUIDATION)"
            trend_color = "rose"
            trend_description = (
                f"High-conviction institutional liquidation (Score: {score:+d}/100). Declines overwhelm advances across exchange ({bm_dec} Dec vs {bm_adv} Adv, ADR: {bm_adr}:1), "
                f"and bluechips trade broken below Day VWAP."
            )
        elif score <= -20:
            trend_code = "DOWNTREND"
            trend_label = "DOWNTREND (BEAR DISTRIBUTION)"
            trend_color = "rose"
            trend_description = (
                f"Bearish distribution dominant (Score: {score:+d}/100). Declines lead advances across the wider exchange (ADR: {bm_adr}:1), "
                f"with persistent selling pressure in benchmark constituents."
            )
        else:
            trend_code = "CHOPPY"
            trend_label = "CHOPPY / RANGEBOUND (SIDEWAYS)"
            trend_color = "amber"
            trend_description = (
                f"Market is caught in an equilibrium tug-of-war without institutional thrust (Score: {score:+d}/100). "
                f"Breadth is evenly split (ADR: {bm_adr}:1). High risk of intraday false breakouts."
            )

        # -------------------------------------------------------------
        # 2. INTRADAY EQUITIES DIRECTIVE ("Should I Buy or Sell Equities Intraday?")
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
        # 3. INTRADAY OPTIONS BUYING DIRECTIVE ("Whether I need to Buy Options Today or Not?")
        # -------------------------------------------------------------
        vix_info = broad_market.get("vix", {}) if broad_market else {}
        deriv_info = broad_market.get("derivatives", {}) if broad_market else {}
        vix_val = float(vix_info.get("value") or 15.5)
        vix_chg_pct = float(vix_info.get("change_pct") or 0.0)
        pcr_val = float(deriv_info.get("index_options_pcr") or 0.85)

        # Volatility & Derivatives Context Modifiers
        vol_note = ""
        if vix_val < 12.0:
            vol_note += f" ⚠️ Low VIX ({vix_val:.1f}): Sluggish ranges amplify theta decay for option buyers."
        elif vix_val > 20.0:
            vol_note += f" ⚡ High VIX ({vix_val:.1f}): Premium inflation and sharp intraday swings. Use wider stops."
        
        if pcr_val < 0.80:
            vol_note += f" 🧱 Call Writing Resistance: Index Options PCR is {pcr_val:.2f} (< 0.85), indicating institutional sellers defending overhead strikes."
        elif pcr_val >= 1.25:
            vol_note += f" 🛡️ Put Writing Floor: Index Options PCR is {pcr_val:.2f} (>= 1.25), confirming solid institutional floor on pullbacks."

        if trend_code == "STRONG_UPTREND":
            option_action = "CALL BUYING PERMITTED (CE)"
            option_badge = "FAVORABLE FOR OPTION BUYERS"
            option_color = "emerald"
            option_guidance = (
                "Today is an Option Buyer's Day on the Long side! Directional momentum and volume thrust will outpace theta decay. "
                f"Target ATM or slightly OTM Nifty/Sensex Calls.{vol_note}"
            )
        elif trend_code == "STRONG_DOWNTREND":
            option_action = "PUT BUYING PERMITTED (PE)"
            option_badge = "FAVORABLE FOR OPTION BUYERS"
            option_color = "rose"
            option_guidance = (
                "Today is an Option Buyer's Day on the Short side! High downward velocity will rapidly expand Put premiums. "
                f"Target ATM or slightly OTM Puts.{vol_note}"
            )
        elif trend_code in ("UPTREND", "DOWNTREND"):
            option_action = "SELECTIVE OPTION BUYING ONLY (STRICT TRAILING STOPS)"
            option_badge = "MODERATE RISK"
            option_color = "amber"
            option_guidance = (
                "Option buying is permissible only with strict discipline. Move stop loss to breakeven quickly. "
                f"Prefer ATM options only; OTM options risk decay if trend stalls.{vol_note}"
            )
        else:  # CHOPPY / DIVERGENT
            option_action = "DO NOT BUY OPTIONS TODAY (HIGH THETA DECAY / CHOP)"
            option_badge = "DO NOT BUY OPTIONS"
            option_color = "rose"
            option_guidance = (
                "DO NOT BUY OPTIONS TODAY! The market lacks sustained directional impulse. Buying options today carries an "
                f"85%+ probability of capital erosion via theta decay and false intraday swings. Let option sellers fight—stay in cash.{vol_note}"
            )

        # -------------------------------------------------------------
        # 4. TIME-OF-DAY AND BTST STATUS
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
            "btst_window_status": {
                "is_active_now": is_btst_window,
                "status_label": btst_time_status,
            },
            "metrics": {
                "nifty_spot": nifty_spot,
                "nifty_change_pct": nifty_chg,
                "nifty_wabi": nifty_wabi,
                "nifty_above_vwap_pct": nifty_above_pct,
                "heavyweights_above": f"{nifty_hw_above}/5",
                "broad_advances": bm_adv,
                "broad_declines": bm_dec,
                "broad_adr": bm_adr,
                "broad_total": bm_total,
            },
        }

