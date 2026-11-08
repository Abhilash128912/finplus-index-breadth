"""
FinPlus+ Market Background Scheduler & Broadcaster
=================================================
Module: finplus_index_breadth.scheduler.market_scheduler
Author: FinPlus+ Enterprise Infrastructure
Standard: ISO-8601, Asynchronous, Zero Fabricated Data

Integrates All NSE Stocks Broad Market Feed, Nifty 50, Sensex 30, and Exact ATM BTST Options.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any, Callable, Dict, List, Optional

from finplus_core.utils.logger import get_finplus_logger
from finplus_index_breadth.analytics.index_btst_engine import IndexBTSTEngine
from finplus_index_breadth.analytics.market_regime_engine import MarketRegimeEngine
from finplus_index_breadth.analytics.vwap_breadth_engine import VWAPBreadthEngine
from finplus_index_breadth.feeds.indmoney_market_feed import INDMoneyMarketFeed
from finplus_index_breadth.feeds.nse_broad_market_feed import NSEBroadMarketFeed
from finplus_index_breadth.notifications.ntfy_dispatcher import NTFYDispatcher

logger = get_finplus_logger("MarketScheduler")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class MarketScheduler:
    """Orchestrates periodic market polling, breadth computation, and NTFY alerting."""

    def __init__(
        self,
        feed: Optional[INDMoneyMarketFeed] = None,
        broad_feed: Optional[NSEBroadMarketFeed] = None,
        dispatcher: Optional[NTFYDispatcher] = None,
        poll_interval_seconds: int = 25,
    ) -> None:
        self.feed = feed or INDMoneyMarketFeed()
        self.broad_feed = broad_feed or NSEBroadMarketFeed()
        self.dispatcher = dispatcher or NTFYDispatcher()
        self.poll_interval = poll_interval_seconds

        self.latest_broad_market: Dict[str, Any] = {}
        self.latest_nifty_breadth: Dict[str, Any] = {}
        self.latest_sensex_breadth: Dict[str, Any] = {}
        self.latest_regime_result: Dict[str, Any] = {}
        self.latest_btst_result: Dict[str, Any] = {}

        self._running = False
        self._last_pulse_slot: Optional[str] = None
        self._last_btst_slot: Optional[str] = None
        self._listeners: List[Callable[[Dict[str, Any]], None]] = []

    def register_listener(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Registers a callback for WebSocket streaming."""
        self._listeners.append(callback)

    def refresh_breadth(self) -> Dict[str, Any]:
        """Performs a synchronous breadth refresh cycle across ALL NSE stocks and constituents."""
        try:
            # 1. Fetch exchange-wide broad market breadth (ALL NSE Stocks)
            self.latest_broad_market = self.broad_feed.fetch_broad_market_breadth()

            # 2. Fetch all 50 Nifty constituents & 30 Sensex constituents
            nifty_quotes = self.feed.fetch_index_quotes("NIFTY")
            sensex_quotes = self.feed.fetch_index_quotes("SENSEX")

            self.latest_nifty_breadth = VWAPBreadthEngine.analyze_index_breadth(
                nifty_quotes, "NIFTY 50"
            )
            self.latest_sensex_breadth = VWAPBreadthEngine.analyze_index_breadth(
                sensex_quotes, "SENSEX 30"
            )

            # 3. Evaluate Market Trend Regime & Intraday Trading Directives (Core Engine)
            self.latest_regime_result = MarketRegimeEngine.evaluate_regime(
                self.latest_nifty_breadth,
                self.latest_sensex_breadth,
                broad_market=self.latest_broad_market,
            )

            # 4. Evaluate End-of-Day BTST state (Evaluates for 3:10 - 3:30 PM)
            self.latest_btst_result = IndexBTSTEngine.evaluate_btst(
                self.latest_nifty_breadth,
                self.latest_sensex_breadth,
                broad_market=self.latest_broad_market,
            )

            snapshot = {
                "timestamp": datetime.datetime.now(tz=IST).isoformat(),
                "broad_market": self.latest_broad_market,
                "nifty": self.latest_nifty_breadth,
                "sensex": self.latest_sensex_breadth,
                "market_regime": self.latest_regime_result,
                "btst": self.latest_btst_result,
            }

            # Broadcast to listeners (WebSocket)
            for cb in self._listeners:
                try:
                    cb(snapshot)
                except Exception:
                    pass

            return snapshot

        except Exception as exc:
            logger.error("Error during breadth refresh cycle: %s", exc)
            return {"status": "ERROR", "message": str(exc)}

    async def run_loop(self) -> None:
        """Main asynchronous polling and dispatching loop."""
        self._running = True
        logger.info("MarketScheduler background loop started.")

        while self._running:
            try:
                # Offload blocking HTTP requests (NSE scrape + INDstocks batch quotes) to worker thread
                snapshot = await asyncio.to_thread(self.refresh_breadth)
                now = datetime.datetime.now(tz=IST)
                hour = now.hour
                minute = now.minute

                # Format current 30-min slot (e.g., '09:30', '10:00')
                slot_key = f"{hour:02d}:{(minute // 30) * 30:02d}"

                # 1. Check for 30-minute Periodic Pulse (09:30 to 15:00 IST)
                if (9 <= hour < 15 or (hour == 15 and minute == 0)) and (minute in (0, 30)):
                    if self._last_pulse_slot != slot_key:
                        logger.info("Triggering 30-min Market Breadth Pulse for slot %s", slot_key)
                        self.dispatcher.send_periodic_breadth_pulse(snapshot)
                        self._last_pulse_slot = slot_key

                # 2. Check for BTST Recommendation Alert (3:15 PM and 3:25 PM IST)
                if hour == 15 and minute in (15, 25):
                    btst_slot = f"15:{minute}"
                    if self._last_btst_slot != btst_slot:
                        logger.info("Triggering 3:10-3:30 BTST Alert for slot %s", btst_slot)
                        self.dispatcher.send_btst_recommendation(self.latest_btst_result)
                        self._last_btst_slot = btst_slot

            except Exception as exc:
                logger.error("Error in scheduler loop: %s", exc)

            await asyncio.sleep(self.poll_interval)

    def stop(self) -> None:
        """Stops the scheduler loop."""
        self._running = False
        logger.info("MarketScheduler loop stopped.")
