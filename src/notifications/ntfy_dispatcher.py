"""
FinPlus+ Multi-Topic NTFY Push Notification Dispatcher
======================================================
Module: finplus_index_breadth.notifications.ntfy_dispatcher
Author: FinPlus+ Enterprise Infrastructure
Standard: ISO-8601, Asynchronous Multi-Topic Broadcast, Clean Financial Bulletin (No Emojis)

Broadcasts high-priority alerts to ntfy.sh topics with normal font sizing.
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
# App 1 broadcasts exclusively to Finplus-Breadth to prevent duplicating App 2's master alerts
DEFAULT_TOPICS = ["Finplus-Breadth"]


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
        click_url: Optional[str] = None,
        actions: Optional[str] = None,
    ) -> bool:
        """Sends push notification to registered topics with standard normal font size."""
        headers = {
            "Title": _safe_header_title(title),
            "Priority": str(priority),
            "Markdown": "no",
            "X-Markdown": "no",
        }
        if click_url:
            headers["Click"] = click_url
        if actions:
            headers["Actions"] = actions

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

    def send_regime_flip_alert(
        self,
        prev_label: str,
        regime_info: Dict[str, Any],
        breadth_snapshot: Dict[str, Any],
    ) -> bool:
        """Dispatches immediate notification when the Market Regime transitions."""
        now_str = datetime.datetime.now(tz=IST).strftime("%H:%M IST")
        trend = regime_info.get("trend", {})
        new_label = trend.get("label", "CHOPPY")
        score_label = trend.get("score_label", "0 / 100")

        eq_dir = regime_info.get("equities_directive", {})
        opt_dir = regime_info.get("options_directive", {})

        bm_root = breadth_snapshot.get("broad_market", {})
        bm_data = bm_root.get("broad_market", {})
        adr = bm_data.get("advance_decline_ratio", 1.0)
        adv = bm_data.get("advances", 0)
        dec = bm_data.get("declines", 0)

        vix_info = bm_root.get("vix", {})
        deriv_info = bm_root.get("derivatives", {})

        title = f"FinPlus Breadth | Regime Flip | {now_str}"

        msg_lines = [
            f"REGIME TRANSITION: {prev_label} -> {new_label} (CTI: {score_label})",
            f"Equities: {eq_dir.get('action', 'CAUTION')}",
            f"Options: {opt_dir.get('action', 'NO TRADE')}",
            f"Drivers: ADR {adr}:1 ({adv} Adv / {dec} Dec) | VIX {vix_info.get('value', 15.5):.2f} | PCR {deriv_info.get('index_options_pcr', 0.85):.2f}",
            f"Cockpit: https://finplus-index-breadth.onrender.com"
        ]

        return self.send_notification(
            title=title,
            message="\n".join(msg_lines),
            priority=4,
            click_url="https://finplus-index-breadth.onrender.com",
            actions="view, Open Cockpit, https://finplus-index-breadth.onrender.com",
        )

    def send_periodic_breadth_pulse(self, breadth_snapshot: Dict[str, Any]) -> bool:
        """Dispatches clean periodic breadth update."""
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
        nifty_chg = nifty.get("change_pct", 0.0)
        nifty_spot = nifty.get("spot_price", 24850.0)

        total_adv = broad.get("advances", nifty.get("advances", 0))
        total_dec = broad.get("declines", nifty.get("declines", 0))
        adr = broad.get("advance_decline_ratio", nifty.get("advance_decline_ratio", 1.0))

        bm_root = breadth_snapshot.get("broad_market", {})
        vix_info = bm_root.get("vix", {})
        deriv_info = bm_root.get("derivatives", {})

        title = f"FinPlus Breadth | {now_str}"

        msg_lines = [
            f"Spot: NIFTY {nifty_spot:,.0f} ({nifty_chg:+.2f}%) | Trend: {trend_label}",
            f"Equities: {equity_action}",
            f"Options: {option_action}",
            f"ADR: {adr}:1 ({total_adv} Adv / {total_dec} Dec) | Nifty > VWAP: {nifty_above:.1f}% | WABI: {nifty_wabi:+.2f}",
            f"Pillars: VIX {vix_info.get('value', 15.5):.2f} | PCR {deriv_info.get('index_options_pcr', 0.85):.2f}",
            f"Cockpit: https://finplus-index-breadth.onrender.com"
        ]

        return self.send_notification(
            title=title,
            message="\n".join(msg_lines),
            priority=3,
            click_url="https://finplus-index-breadth.onrender.com",
            actions="view, Open Cockpit, https://finplus-index-breadth.onrender.com",
        )

    def send_btst_recommendation(self, btst_result: Dict[str, Any]) -> bool:
        """Dispatches clean 3:15 PM IST BTST notification."""
        now_str = datetime.datetime.now(tz=IST).strftime("%H:%M IST")
        decision = btst_result.get("decision", "CASH_PROTECT_STANDBY")
        title = f"FinPlus BTST | {now_str} | {decision}"

        if decision == "QUALIFIED_CALL_BUY":
            nifty_opt = btst_result.get("nifty_option_recommendation", {})
            sensex_opt = btst_result.get("sensex_option_recommendation", {})
            msg_lines = [
                f"BTST: QUALIFIED CALL BUY OVERNIGHT",
                f"Nifty ATM: {nifty_opt.get('contract_symbol')} (Strike {nifty_opt.get('atm_strike')})",
                f"Sensex ATM: {sensex_opt.get('contract_symbol')} (Strike {sensex_opt.get('atm_strike')})",
                f"Rules: Max Rs 5,000 risk, exit 09:15-09:30 AM tomorrow.",
                f"Cockpit: https://finplus-index-breadth.onrender.com"
            ]
            priority = 5
        else:
            msg_lines = [
                f"BTST: 100% CASH STANDBY (NO OVERNIGHT TRADES)",
                f"Action: Maintain full cash balance overnight. Avoid holding naked options.",
                f"Cockpit: https://finplus-index-breadth.onrender.com"
            ]
            priority = 3

        return self.send_notification(
            title=title,
            message="\n".join(msg_lines),
            priority=priority,
            click_url="https://finplus-index-breadth.onrender.com",
            actions="view, Open Cockpit, https://finplus-index-breadth.onrender.com",
        )
