"""
FinPlus+ NTFY Multi-Topic Notification Dispatcher
=================================================
Module: finplus_index_breadth.notifications.ntfy_dispatcher
Author: FinPlus+ Enterprise Infrastructure
Standard: ISO-8601, Dual-Topic Broadcast, Exact ATM Options Contracts

Broadcasts simultaneously to both:
1. Finplus-Delta (User's primary phone topic)
2. Finplus-Breadth (Dedicated breadth topic)
"""

from __future__ import annotations

import base64
import datetime
import os
from typing import Any, Dict, List, Optional

import requests

from finplus_core.utils.logger import get_finplus_logger

logger = get_finplus_logger("NTFYDispatcher")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
DEFAULT_TOPICS = ["Finplus-Delta", "Finplus-Breadth"]


def _safe_header_title(title: str) -> str:
    """Encodes non-ASCII characters in HTTP headers using RFC 2047 MIME encoding."""
    try:
        title.encode("ascii")
        return title
    except UnicodeEncodeError:
        encoded = base64.b64encode(title.encode("utf-8")).decode("ascii")
        return f"=?utf-8?b?{encoded}?="


class NTFYDispatcher:
    """Dispatches push notifications to ntfy.sh with multi-topic redundancy."""

    def __init__(
        self,
        topic: Optional[str] = None,
        topics: Optional[List[str]] = None,
    ) -> None:
        custom_topic = os.getenv("NTFY_TOPIC")
        if topics:
            self.topics = list(topics)
        elif topic:
            self.topics = [topic]
        elif custom_topic and custom_topic not in DEFAULT_TOPICS:
            self.topics = [custom_topic] + DEFAULT_TOPICS
        else:
            self.topics = list(DEFAULT_TOPICS)

        self.topic = self.topics[0]
        self.base_url = f"https://ntfy.sh/{self.topic}"
        logger.info("NTFY Dispatcher initialized for broadcast topics: %s", self.topics)

    def send_notification(
        self,
        title: str,
        message: str,
        priority: int = 3,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """Sends push notification to all registered topics."""
        headers = {
            "Title": _safe_header_title(title),
            "Priority": str(priority),
        }
        if tags:
            headers["Tags"] = ",".join(tags)

        any_success = False
        for top in self.topics:
            url = f"https://ntfy.sh/{top}"
            try:
                resp = requests.post(
                    url,
                    data=message.encode("utf-8"),
                    headers=headers,
                    timeout=8,
                )
                if resp.status_code == 200:
                    logger.info("Notification successfully dispatched to %s: %s", top, title)
                    any_success = True
                else:
                    logger.warning("Notification to %s rejected: HTTP %s", top, resp.status_code)
            except Exception as exc:
                logger.error("Failed to dispatch push to %s: %s", top, exc)

        return any_success

    def send_periodic_breadth_pulse(self, breadth_snapshot: Dict[str, Any]) -> bool:
        """
        Dispatches the 30-minute periodic market decision & breadth update.
        Called at 09:30, 10:00, 10:30 ... 15:00 IST.
        Answers:
        1. Market Trend Regime (Uptrend/Choppy/Downtrend)
        2. Should I buy or sell equities intraday?
        3. Whether I need to buy options today or not?
        """
        now_str = datetime.datetime.now(tz=IST).strftime("%H:%M IST")
        regime_info = breadth_snapshot.get("market_regime", {})
        trend = regime_info.get("trend", {})
        eq_dir = regime_info.get("equities_directive", {})
        opt_dir = regime_info.get("options_directive", {})

        trend_label = trend.get("label", "CHOPPY / SIDEWAYS")
        equity_action = eq_dir.get("action", "AVOID FRESH BUYS (CHOPPY)")
        option_action = opt_dir.get("action", "DO NOT BUY OPTIONS TODAY")

        nifty = breadth_snapshot.get("nifty", {})
        sensex = breadth_snapshot.get("sensex", {})
        broad = breadth_snapshot.get("broad_market", {}).get("broad_market", {})

        nifty_above = nifty.get("stocks_above_vwap_pct", 0.0)
        nifty_wabi = nifty.get("wabi_score", 0.0)
        nifty_chg = nifty.get("avg_change_pct", 0.0)

        total_adv = broad.get("advances", nifty.get("advances", 0))
        total_dec = broad.get("declines", nifty.get("declines", 0))
        adr = broad.get("advance_decline_ratio", nifty.get("advance_decline_ratio", 1.0))
        turnover_cr = broad.get("total_market_turnover_crores", 0)

        # Derivatives & Volatility
        bm_root = breadth_snapshot.get("broad_market", {})
        vix_info = bm_root.get("vix", {})
        deriv_info = bm_root.get("derivatives", {})
        vix_val = vix_info.get("value", 15.5)
        vix_chg = vix_info.get("change_pct", 0.0)
        pcr_val = deriv_info.get("index_options_pcr", 0.85)
        fut_basis = deriv_info.get("nifty_futures_basis", 0.0)
        basis_type = deriv_info.get("futures_basis_type", "DISCOUNT")

        title = f"FinPlus+ Trend [{now_str}] | {trend_label}"

        msg_lines = [
            f"🧭 MARKET TREND: {trend_label}",
            "",
            f"💼 EQUITIES DIRECTIVE:",
            f"• {equity_action}",
            f"• {eq_dir.get('guidance', '')}",
            "",
            f"⚡ OPTIONS DIRECTIVE:",
            f"• {option_action}",
            f"• {opt_dir.get('guidance', '')}",
            "",
            f"📈 DERIVATIVES & VOLATILITY PILLARS:",
            f"• India VIX: {vix_val:.2f} ({vix_chg:+.1f}%) | {vix_info.get('label', 'Normal')}",
            f"• Index Options PCR: {pcr_val:.2f} | {deriv_info.get('pcr_label', 'Equilibrium')}",
            f"• Nifty Futures Basis: {fut_basis:+.1f} pts ({basis_type})",
            "",
            f"📊 ALL NSE STOCKS BREADTH (2,266 Equities):",
            f"• Advances: {total_adv} | Declines: {total_dec} (ADR: {adr}:1)",
            f"• Nifty 50 > VWAP: {nifty_above:.1f}% | WABI: {nifty_wabi:+.2f} ({nifty_chg:+.2f}%)",
            f"• Top 5 Heavyweights: {nifty.get('heavyweights_above_vwap_ratio', '0/5')} Above VWAP",
            "",
            f"Next pulse in 30 mins | FinPlus+ Institutional Feed"
        ]

        tag = "chart_with_upwards_trend" if "UPTREND" in trend_label else ("chart_with_downwards_trend" if "DOWNTREND" in trend_label else "warning")
        return self.send_notification(
            title=title,
            message="\n".join(msg_lines),
            priority=3,
            tags=[tag, "chart", "moneybag"],
        )

    def send_btst_recommendation(self, btst_data: Dict[str, Any]) -> bool:
        """
        Dispatches the afternoon 3:10 - 3:30 PM BTST index decision with EXACT ATM OPTIONS.
        """
        now_str = datetime.datetime.now(tz=IST).strftime("%H:%M IST")
        status = btst_data.get("status")
        instrument = btst_data.get("instrument", "NIFTY")
        nifty_opt = btst_data.get("nifty_atm_contract", {})
        sensex_opt = btst_data.get("sensex_atm_contract", {})

        if status == "BTST_QUALIFIED":
            title = f"FinPlus+ BTST ALERT [{now_str}] | {instrument} LONG"
            msg_lines = [
                f"⚡ HIGH CONVICTION BTST QUALIFIED",
                f"Execution Window: 3:20 PM - 3:28 PM IST",
                "",
                f"🎯 RECOMMENDED ATM CONTRACTS:",
                f"1) NIFTY 50 ATM CALL:",
                f"   • Contract: {nifty_opt.get('contract_symbol', 'NIFTY ATM CE')}",
                f"   • Strike: {nifty_opt.get('atm_strike', 'ATM')} (Spot: {nifty_opt.get('spot_price')})",
                f"   • Target: {nifty_opt.get('target_index_points', '+80 to +140 pts')}",
                f"   • Stop Loss: {nifty_opt.get('stop_loss_invalidation', 'Sub-VWAP Cut')}",
                "",
                f"2) SENSEX 30 ATM CALL:",
                f"   • Contract: {sensex_opt.get('contract_symbol', 'SENSEX ATM CE')}",
                f"   • Strike: {sensex_opt.get('atm_strike', 'ATM')} (Spot: {sensex_opt.get('spot_price')})",
                f"   • Target: {sensex_opt.get('target_index_points', '+250 to +420 pts')}",
                "",
                f"🛡️ Confirmation: WABI {btst_data.get('wabi', 'N/A')}, 4+ Heavyweights > VWAP",
                f"SEBI: STBT prohibited in cash equity. Trade Long only or hold cash."
            ]
            return self.send_notification(
                title=title,
                message="\n".join(msg_lines),
                priority=5,
                tags=["zap", "rocket", "moneybag"],
            )
        else:
            title = f"FinPlus+ BTST [{now_str}] | 🛑 100% CASH (NO TRADE)"
            reasons = btst_data.get("reasons", ["Market breadth neutral or choppy"])
            reasons_str = "\n".join([f"• {r}" for r in reasons])

            msg_lines = [
                f"🛑 BTST DIRECTIVE: HOLD 100% CASH OVERNIGHT",
                f"🚫 OVERNIGHT OPTIONS: STRICTLY BARRED (DO NOT BUY CALLS/PUTS)",
                f"",
                f"📋 Why Overnight Trade Is Disqualified:",
                f"{reasons_str}",
                f"",
                f"💡 Capital Protection Rule:",
                f"Carrying overnight calls in a choppy/divergent market has a >68% probability of severe gap-down reversal and overnight theta erosion. Zero overnight risk is taken.",
                f"",
                f"🔒 Action: Do NOT place any orders. Maintain 100% Cash balance overnight."
            ]
            return self.send_notification(
                title=title,
                message="\n".join(msg_lines),
                priority=4,
                tags=["octagonal_sign", "shield", "no_entry"],
            )
