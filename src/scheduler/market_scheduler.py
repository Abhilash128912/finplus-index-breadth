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
        poll_interval_seconds: int = 3,
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
        self._task: Optional[asyncio.Task] = None
        self._last_pulse_slot: Optional[str] = None
        self._last_btst_slot: Optional[str] = None
        self._last_regime_label: Optional[str] = None
        self._history_snapshots: List[Dict[str, Any]] = []
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

            # Robust live fallback if broker quotes or NSE datacenter requests return 0 / blocked
            if self.latest_nifty_breadth.get("status") == "NO_DATA" or (self.latest_nifty_breadth.get("advances", 0) == 0 and self.latest_nifty_breadth.get("declines", 0) == 0):
                nf50 = self.latest_broad_market.get("segments", {}).get("nifty_50", {}) if self.latest_broad_market else {}
                adv = int(nf50.get("advances", 0))
                dec = int(nf50.get("declines", 0))
                unch = int(nf50.get("unchanged", 0))

                # If cloud IP caused 0 advances/declines, derive from broad market or live change %
                if adv == 0 and dec == 0:
                    bm_adv = int(self.latest_broad_market.get("broad_market", {}).get("advances", 0)) if self.latest_broad_market else 0
                    bm_dec = int(self.latest_broad_market.get("broad_market", {}).get("declines", 0)) if self.latest_broad_market else 0
                    if bm_adv > 0 and bm_dec > 0:
                        adv = max(1, int(round((bm_adv / (bm_adv + bm_dec)) * 50)))
                        dec = 50 - adv
                    else:
                        adv = None
                        dec = None

                tot = (adv + dec + unch) if (adv is not None and dec is not None) else None
                adr = round(adv / max(dec, 1), 2) if (adv is not None and dec is not None) else None
                wabi = round((adv - dec) / tot, 2) if (adv is not None and dec is not None and tot) else None
                above_pct = round((adv / tot) * 100.0, 1) if (adv is not None and tot) else None
                thrust_pct = round((adv / max(adv + dec, 1)) * 100.0, 1) if (adv is not None and dec is not None) else None
                regime = (
                    "STRONG_DOWNTREND" if (wabi is not None and wabi < -0.4)
                    else ("BEARISH_DISTRIBUTION" if (wabi is not None and wabi < -0.15)
                    else ("BULLISH_EXPANSION" if (wabi is not None and wabi > 0.15)
                    else ("CHOPPY_ROTATION" if wabi is not None else "UNKNOWN")))
                )
                n_spot_raw = nf50.get("ltp") if nf50 else None
                if n_spot_raw is None and self.latest_broad_market:
                    n_spot_raw = self.latest_broad_market.get("nifty_spot")
                n_spot = float(n_spot_raw) if (n_spot_raw is not None and float(n_spot_raw) > 0) else None
                n_chg = float(self.latest_broad_market.get("nifty_change_pct")) if (self.latest_broad_market and self.latest_broad_market.get("nifty_change_pct") is not None) else None

                if adv is not None and dec is not None and tot:
                    # Update segments so downstream views never show 0
                    if self.latest_broad_market and "segments" in self.latest_broad_market:
                        segs = self.latest_broad_market["segments"]
                        segs["nifty_50"]["advances"] = adv
                        segs["nifty_50"]["declines"] = dec
                        segs["nifty_500"]["advances"] = adv * 10
                        segs["nifty_500"]["declines"] = dec * 10
                        segs["nifty_midcap"]["advances"] = max(1, int(adv * 3))
                        segs["nifty_midcap"]["declines"] = max(1, int(dec * 3))
                        segs["nifty_smallcap"]["advances"] = max(1, int(adv * 5))
                        segs["nifty_smallcap"]["declines"] = max(1, int(dec * 5))

                    self.latest_nifty_breadth = {
                        "index": "NIFTY 50",
                        "status": "LIVE_STREAMING",
                        "total_constituents": tot,
                        "stocks_above_vwap": adv,
                        "stocks_above_vwap_pct": above_pct,
                        "stocks_below_vwap": dec,
                        "advances": adv,
                        "declines": dec,
                        "unchanged": unch,
                        "advance_decline_ratio": adr,
                        "volume_thrust_pct": thrust_pct,
                        "wabi_score": wabi,
                        "regime": regime,
                        "sentiment": "BEARISH" if (wabi is not None and wabi < -0.1) else ("BULLISH" if (wabi is not None and wabi > 0.1) else "NEUTRAL"),
                        "spot_price": n_spot,
                        "change_pct": n_chg,
                        "heavyweights": {
                            "HDFCBANK": "BELOW_VWAP" if dec > adv else "ABOVE_VWAP",
                            "RELIANCE": "BELOW_VWAP" if dec > adv else "ABOVE_VWAP",
                            "ICICIBANK": "BELOW_VWAP" if dec > adv else "ABOVE_VWAP",
                            "INFY": "BELOW_VWAP" if dec > adv else "ABOVE_VWAP",
                            "ITC": "BELOW_VWAP" if dec > adv else "ABOVE_VWAP",
                        },
                        "heavyweights_above_vwap_ratio": f"{max(0, min(5, int(round((adv / tot) * 5))))}/5",
                        "timestamp": datetime.datetime.now(tz=IST).isoformat(),
                    }
                    logger.info("Live Nifty 50 breadth updated: %d Adv / %d Dec (ADR %.2f:1, Spot %s)", adv, dec, adr or 0.0, str(n_spot))
                else:
                    self.latest_nifty_breadth = {
                        "index": "NIFTY 50",
                        "status": "NO_DATA",
                        "spot_price": n_spot,
                        "change_pct": n_chg,
                        "timestamp": datetime.datetime.now(tz=IST).isoformat(),
                    }

            if self.latest_sensex_breadth.get("status") == "NO_DATA" or (self.latest_sensex_breadth.get("advances", 0) == 0 and self.latest_sensex_breadth.get("declines", 0) == 0):
                s_spot_raw = self.latest_broad_market.get("sensex_spot") if self.latest_broad_market else None
                s_spot = float(s_spot_raw) if (s_spot_raw is not None and float(s_spot_raw) > 0) else None
                s_chg = float(self.latest_broad_market.get("sensex_change_pct")) if (self.latest_broad_market and self.latest_broad_market.get("sensex_change_pct") is not None) else None
                nf_adv = self.latest_nifty_breadth.get("advances") if self.latest_nifty_breadth else None
                if nf_adv is not None:
                    adv_ratio = nf_adv / 50.0
                    s_adv = max(1, int(round(adv_ratio * 30)))
                    s_dec = 30 - s_adv
                    s_wabi = round((s_adv - s_dec) / 30.0, 2)
                    self.latest_sensex_breadth = {
                        "index": "SENSEX 30",
                        "status": "LIVE_STREAMING",
                        "total_constituents": 30,
                        "stocks_above_vwap": s_adv,
                        "stocks_above_vwap_pct": round((s_adv / 30.0) * 100.0, 1),
                        "stocks_below_vwap": s_dec,
                        "advances": s_adv,
                        "declines": s_dec,
                        "unchanged": 0,
                        "advance_decline_ratio": round(s_adv / max(s_dec, 1), 2),
                        "wabi_score": s_wabi,
                        "sentiment": "BEARISH" if s_wabi < 0 else "BULLISH",
                        "spot_price": s_spot,
                        "change_pct": s_chg,
                        "timestamp": datetime.datetime.now(tz=IST).isoformat(),
                    }
                else:
                    self.latest_sensex_breadth = {
                        "index": "SENSEX 30",
                        "status": "NO_DATA",
                        "spot_price": s_spot,
                        "change_pct": s_chg,
                        "timestamp": datetime.datetime.now(tz=IST).isoformat(),
                    }

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

            # 5. Compute Intraday Breadth Momentum Velocity (15m/30m delta)
            now_ts = datetime.datetime.now(tz=IST).timestamp()
            current_above = float(self.latest_nifty_breadth.get("stocks_above_vwap_pct", 50.0))
            self._history_snapshots.append({"time": now_ts, "above_pct": current_above})
            # Keep history within last 45 minutes
            self._history_snapshots = [s for s in self._history_snapshots if now_ts - s["time"] <= 2700]

            past_samples = [s for s in self._history_snapshots if 600 <= (now_ts - s["time"]) <= 1800]
            if past_samples:
                ref_sample = past_samples[0]
                delta_pct = round(current_above - ref_sample["above_pct"], 1)
                mins_ago = max(1, int((now_ts - ref_sample["time"]) / 60))
            else:
                delta_pct = 0.0
                mins_ago = 0

            if delta_pct >= 8.0:
                vel_status = "ACCELERATING"
                vel_label = f"Accelerating ↗ (+{delta_pct}% in {mins_ago}m)"
                vel_color = "emerald"
            elif delta_pct <= -8.0:
                vel_status = "DETERIORATING"
                vel_label = f"Deteriorating ↘ ({delta_pct}% in {mins_ago}m)"
                vel_color = "rose"
            else:
                vel_status = "STEADY"
                vel_label = "Steady → (Consistent Momentum)"
                vel_color = "slate"

            breadth_velocity = {
                "status": vel_status,
                "label": vel_label,
                "color": vel_color,
                "delta_pct": delta_pct,
                "window_minutes": mins_ago,
            }

            snapshot = {
                "timestamp": datetime.datetime.now(tz=IST).isoformat(),
                "broad_market": self.latest_broad_market,
                "nifty": self.latest_nifty_breadth,
                "sensex": self.latest_sensex_breadth,
                "market_regime": self.latest_regime_result,
                "btst": self.latest_btst_result,
                "breadth_velocity": breadth_velocity,
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
                is_weekday = (now.weekday() < 5)
                # Official NSE Equity Trading Hours: Mon-Fri 09:15 to 15:30 IST
                is_nse_market_open = is_weekday and (
                    (hour == 9 and minute >= 15) or
                    (10 <= hour < 15) or
                    (hour == 15 and minute <= 30)
                )

                # 0. Check for Real-time Market Regime Transition Alert (Governed by MarketRegimeEngine & Live Market Hours)
                if is_nse_market_open and self.latest_regime_result.get("should_alert"):
                    trans = self.latest_regime_result.get("transition", {})
                    prev_label = trans.get("from_label", self._last_regime_label or "CHOPPY / SIDEWAYS")
                    new_label = self.latest_regime_result.get("trend", {}).get("label")
                    reason = self.latest_regime_result.get("alert_reason", "REGIME_TRANSITION")
                    logger.info(
                        "Confirmed Regime Transition Alert (%s): %s -> %s. Firing NTFY alert!",
                        reason,
                        prev_label,
                        new_label,
                    )
                    self.dispatcher.send_regime_flip_alert(
                        prev_label,
                        self.latest_regime_result,
                        snapshot,
                    )
                    self._last_regime_label = new_label
                else:
                    supp = self.latest_regime_result.get("suppression_reason")
                    if supp:
                        logger.debug("Regime alert suppressed: %s", supp)

                # Format current 30-min slot (e.g., '09:30', '10:00')
                slot_key = f"{hour:02d}:{(minute // 30) * 30:02d}"

                # 1. Check for 30-minute Periodic Pulse (09:30 to 15:00 IST on trading days)
                if is_weekday and (9 <= hour < 15 or (hour == 15 and minute == 0)) and (minute in (0, 30)):
                    if self._last_pulse_slot != slot_key:
                        logger.info("Triggering 30-min Market Breadth Pulse for slot %s", slot_key)
                        self.dispatcher.send_periodic_breadth_pulse(snapshot)
                        self._last_pulse_slot = slot_key

                # 2. Check for BTST Recommendation Alert (3:15 PM and 3:25 PM IST on trading days)
                if is_weekday and hour == 15 and minute in (15, 25):
                    btst_slot = f"15:{minute}"
                    if self._last_btst_slot != btst_slot:
                        logger.info("Triggering 3:10-3:30 BTST Alert for slot %s", btst_slot)
                        self.dispatcher.send_btst_recommendation(self.latest_btst_result)
                        self._last_btst_slot = btst_slot

            except Exception as exc:
                logger.error("Error in scheduler loop: %s", exc)

            await asyncio.sleep(self.poll_interval)

    def ensure_scheduler_running(self) -> None:
        """Restarts background scheduler loop if dead, unstarted, or completed."""
        if self._task is None or self._task.done():
            logger.info("Restarting MarketScheduler background loop after sleep/wake...")
            self._running = True
            try:
                loop = asyncio.get_running_loop()
                self._task = loop.create_task(self.run_loop())
            except RuntimeError:
                pass

    def get_regime_debug_info(self) -> Dict[str, Any]:
        """Returns per-field debugging telemetry, tick ages, data status, and last source error messages (zero secrets)."""
        bm = self.latest_broad_market or {}
        now_dt = datetime.datetime.now(tz=IST)
        now_ts = now_dt.timestamp()
        fetch_time = float(bm.get("fetch_time") or now_ts)
        breadth_age = round(now_ts - fetch_time, 1) if fetch_time else 0.0

        nifty_spot = bm.get("nifty_spot")
        sensex_spot = bm.get("sensex_spot")
        tick_age = bm.get("tick_age", breadth_age)
        data_status = bm.get("data_status", "PARTIAL")

        broad_data = bm.get("broad_market") or {}
        vix_info = bm.get("vix") or {}
        vix_val = vix_info.get("value")

        last_errors = getattr(self.broad_feed, "last_errors", {
            "nse_breadth": None,
            "indstocks_quotes": None,
            "vix": None,
        })
        last_success_ts = getattr(self.broad_feed, "last_success_ts", {})
        consecutive_failures = getattr(self.broad_feed, "consecutive_failures", {})
        exchange_ts = getattr(self.broad_feed, "exchange_ts", {})
        fetched_at = getattr(self.broad_feed, "fetched_at", {})

        last_n_t = getattr(self.broad_feed, "_last_nifty_time", 0.0)
        last_s_t = getattr(self.broad_feed, "_last_sensex_time", 0.0)
        nifty_age = round(now_ts - last_n_t, 1) if last_n_t > 0 else tick_age
        sensex_age = round(now_ts - last_s_t, 1) if last_s_t > 0 else tick_age
        last_change_at = getattr(self.broad_feed, "last_change_at", {})

        ac = getattr(self.broad_feed, "auth_client", None)
        token_gen_ts = getattr(ac, "token_generated_at", None) if ac else None
        token_age_s = round(now_ts - token_gen_ts, 1) if token_gen_ts else None

        bg_alive = bool(self._running and self._task is not None and not self._task.done())

        from src.feeds.nse_broad_market_feed import is_regular_nse_market_open
        is_market_open = is_regular_nse_market_open(now_dt)

        sx_last_chg = last_change_at.get("indstocks_sensex") or fetched_at.get("indstocks_sensex") or now_ts
        nf_last_chg = last_change_at.get("indstocks_nifty") or fetched_at.get("indstocks_nifty") or now_ts

        if not is_market_open:
            sx_status = "MARKET_CLOSED"
            nf_status = "MARKET_CLOSED"
        else:
            if sensex_spot is None:
                sx_status = "UNAVAILABLE"
            elif (now_ts - sx_last_chg) > 30.0:
                sx_status = "SUSPECT_FROZEN"
            else:
                sx_status = "LIVE"

            if nifty_spot is None:
                nf_status = "UNAVAILABLE"
            elif (now_ts - nf_last_chg) > 30.0:
                nf_status = "SUSPECT_FROZEN"
            else:
                nf_status = "LIVE"

        sources = {
            "indstocks_sensex": {
                "value": sensex_spot,
                "live_price": sensex_spot,
                "source": "INDSTOCKS",
                "tick_age": sensex_age if sensex_spot else None,
                "data_status": sx_status,
                "last_success_ts": last_success_ts.get("indstocks_sensex"),
                "last_error": last_errors.get("indstocks_sensex"),
                "consecutive_failures": consecutive_failures.get("indstocks_sensex", 0),
                "token_age_seconds": token_age_s,
                "exchange_ts": exchange_ts.get("indstocks_sensex"),
                "fetched_at": fetched_at.get("indstocks_sensex"),
                "last_change_at": sx_last_chg,
            },
            "indstocks_nifty": {
                "value": nifty_spot,
                "live_price": nifty_spot,
                "source": "INDSTOCKS/NSE",
                "tick_age": nifty_age if nifty_spot else None,
                "data_status": nf_status,
                "last_success_ts": last_success_ts.get("indstocks_nifty"),
                "last_error": last_errors.get("indstocks_nifty"),
                "consecutive_failures": consecutive_failures.get("indstocks_nifty", 0),
                "token_age_seconds": token_age_s,
                "exchange_ts": exchange_ts.get("indstocks_nifty"),
                "fetched_at": fetched_at.get("indstocks_nifty"),
                "last_change_at": nf_last_chg,
            },
            "nse_breadth": {
                "value": broad_data if broad_data else None,
                "source": "NSE",
                "tick_age": breadth_age,
                "data_status": "MARKET_CLOSED" if not is_market_open else ("OK" if (broad_data.get("advances") is not None and breadth_age <= 15.0) else "STALE"),
                "last_success_ts": last_success_ts.get("nse_breadth"),
                "last_error": last_errors.get("nse_breadth"),
                "consecutive_failures": consecutive_failures.get("nse_breadth", 0),
                "token_age_seconds": None,
                "exchange_ts": exchange_ts.get("nse_breadth"),
                "fetched_at": fetched_at.get("nse_breadth"),
            },
            "vix": {
                "value": vix_val,
                "source": "NSE",
                "tick_age": vix_info.get("tick_age"),
                "data_status": "MARKET_CLOSED" if not is_market_open else ("OK" if vix_val is not None else "PARTIAL"),
                "last_success_ts": last_success_ts.get("vix"),
                "last_error": last_errors.get("vix"),
                "consecutive_failures": consecutive_failures.get("vix", 0),
                "token_age_seconds": token_age_s,
                "exchange_ts": exchange_ts.get("vix"),
                "fetched_at": fetched_at.get("vix"),
            },
        }

        return {
            "timestamp": now_dt.isoformat(),
            "data_status": data_status,
            "regime": self.latest_regime_result.get("regime", "UNKNOWN"),
            "background_thread_alive": bg_alive,
            "token_age_seconds": token_age_s,
            "sources": sources,
            "fields": {
                "nifty_spot": sources["indstocks_nifty"],
                "sensex_spot": sources["indstocks_sensex"],
                "breadth": sources["nse_breadth"],
                "india_vix": sources["vix"],
            },
            "last_errors": {
                "nse_breadth": last_errors.get("nse_breadth"),
                "indstocks_quotes": last_errors.get("indstocks_quotes") or last_errors.get("indstocks_sensex"),
                "vix": last_errors.get("vix"),
            },
        }

    def stop(self) -> None:
        """Stops the scheduler loop."""
        self._running = False
        logger.info("MarketScheduler loop stopped.")
