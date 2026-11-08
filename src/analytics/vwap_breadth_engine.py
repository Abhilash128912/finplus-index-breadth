"""
FinPlus+ VWAP Breadth & WABI Analytics Engine
============================================
Module: finplus_index_breadth.analytics.vwap_breadth_engine
Author: FinPlus+ Enterprise Infrastructure
Standard: ISO-8601, Zero Fabricated Data

Calculates quantitative market breadth metrics:
1. Raw VWAP Breadth Percentage (% of constituents above VWAP)
2. Weight-Adjusted Breadth Index (WABI) on a scale of -1.0 to +1.0
3. Top 5 Heavyweight Confluence Monitor
4. Volume Thrust Distribution
5. Institutional Regime Classification
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Tuple

from finplus_core.utils.logger import get_finplus_logger

logger = get_finplus_logger("VWAPBreadthEngine")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

TOP_5_NIFTY_HEAVYWEIGHTS = ["HDFCBANK", "RELIANCE", "ICICIBANK", "INFY", "ITC"]
TOP_5_SENSEX_HEAVYWEIGHTS = ["HDFCBANK", "RELIANCE", "ICICIBANK", "INFY", "ITC"]


class VWAPBreadthEngine:
    """Computes institutional market breadth analytics from constituent quotes."""

    @staticmethod
    def analyze_index_breadth(
        quotes: List[Dict[str, Any]], index_name: str = "NIFTY"
    ) -> Dict[str, Any]:
        """
        Analyzes constituent quotes and generates complete institutional breadth metrics.
        """
        if not quotes:
            return {
                "index": index_name,
                "status": "NO_DATA",
                "timestamp": datetime.datetime.now(tz=IST).isoformat(),
            }

        total_stocks = len(quotes)
        stocks_above_vwap = 0
        stocks_below_vwap = 0
        total_advances = 0
        total_declines = 0
        total_unchanged = 0

        up_volume = 0
        down_volume = 0
        total_volume = 0

        weighted_vwap_sum = 0.0
        total_weight = 0.0
        sum_pct_change = 0.0

        heavyweights_status: Dict[str, str] = {}
        target_heavyweights = (
            TOP_5_NIFTY_HEAVYWEIGHTS
            if index_name.upper() == "NIFTY"
            else TOP_5_SENSEX_HEAVYWEIGHTS
        )

        for q in quotes:
            sym = q["symbol"]
            w = q.get("weight", 1.0)
            live_price = q.get("live_price", 0.0)
            day_vwap = q.get("day_vwap", 0.0)
            chg = q.get("change_pct", 0.0)
            vol = q.get("volume", 0)

            total_weight += w
            sum_pct_change += chg
            total_volume += vol

            # Advances vs Declines
            if chg > 0.05:
                total_advances += 1
                up_volume += vol
            elif chg < -0.05:
                total_declines += 1
                down_volume += vol
            else:
                total_unchanged += 1

            # VWAP calculation
            is_above = live_price >= day_vwap
            if is_above:
                stocks_above_vwap += 1
                weighted_vwap_sum += w * 1.0
            else:
                stocks_below_vwap += 1
                weighted_vwap_sum += w * -1.0

            # Track heavyweights
            if sym in target_heavyweights:
                heavyweights_status[sym] = "ABOVE_VWAP" if is_above else "BELOW_VWAP"

        # Derived metrics
        breadth_pct = round((stocks_above_vwap / total_stocks) * 100.0, 2)
        wabi_score = (
            round(weighted_vwap_sum / total_weight, 3) if total_weight > 0 else 0.0
        )
        avg_change_pct = round(sum_pct_change / total_stocks, 2)

        vol_thrust_pct = (
            round((up_volume / (up_volume + down_volume)) * 100.0, 1)
            if (up_volume + down_volume) > 0
            else 50.0
        )

        heavyweights_above_count = sum(
            1 for v in heavyweights_status.values() if v == "ABOVE_VWAP"
        )

        regime, sentiment = VWAPBreadthEngine._classify_regime(
            wabi_score, breadth_pct, heavyweights_above_count, len(target_heavyweights)
        )

        return {
            "index": index_name,
            "timestamp": datetime.datetime.now(tz=IST).isoformat(),
            "total_constituents": total_stocks,
            "stocks_above_vwap": stocks_above_vwap,
            "stocks_below_vwap": stocks_below_vwap,
            "stocks_above_vwap_pct": breadth_pct,
            "wabi_score": wabi_score,
            "advances": total_advances,
            "declines": total_declines,
            "unchanged": total_unchanged,
            "advance_decline_ratio": round(total_advances / max(total_declines, 1), 2),
            "up_volume": up_volume,
            "down_volume": down_volume,
            "total_volume": total_volume,
            "volume_thrust_pct": vol_thrust_pct,
            "avg_change_pct": avg_change_pct,
            "heavyweights": heavyweights_status,
            "heavyweights_above_vwap_ratio": f"{heavyweights_above_count}/{len(target_heavyweights)}",
            "regime": regime,
            "sentiment": sentiment,
            "constituents_sample": quotes[:8],
        }

    @staticmethod
    def _classify_regime(
        wabi: float,
        breadth_pct: float,
        hw_above: int,
        total_hw: int,
    ) -> Tuple[str, str]:
        """Classifies the market regime from breadth and heavyweight alignment."""
        if wabi >= 0.50 and breadth_pct >= 68.0 and hw_above >= 4:
            return "STRONG_BULL_EXPANSION", "VERY_BULLISH"
        elif wabi >= 0.20 and breadth_pct >= 55.0:
            return "MODERATE_BULL_ACCUMULATION", "BULLISH"
        elif wabi <= -0.50 and breadth_pct <= 32.0 and hw_above <= 1:
            return "STRONG_BEAR_EXPANSION", "VERY_BEARISH"
        elif wabi <= -0.20 and breadth_pct <= 45.0:
            return "MODERATE_BEAR_DISTRIBUTION", "BEARISH"
        else:
            return "NEUTRAL_CHOP_RANGE", "NEUTRAL"

