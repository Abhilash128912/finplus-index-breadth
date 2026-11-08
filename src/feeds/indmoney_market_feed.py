"""
FinPlus+ INDmoney Live Market Feed
=================================
Module: finplus_index_breadth.feeds.indmoney_market_feed
Author: FinPlus+ Enterprise Infrastructure
Standard: ISO-8601, Zero Fabricated Data

Fetches real-time market quotes in batches from INDstocks API for Nifty 50 and Sensex 30 constituents.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

import requests

from finplus_core.auth import INDMoneyAuthClient
from finplus_core.utils.logger import get_finplus_logger

logger = get_finplus_logger("INDMoneyMarketFeed")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class INDMoneyMarketFeed:
    """Manages real-time batch quote retrieval for Nifty 50 and Sensex 30."""

    BASE_URL = "https://api.indstocks.com"
    QUOTES_ENDPOINT = "/market/quotes/full"
    BATCH_CHUNK_SIZE = 15
    CACHE_TTL_SECONDS = 30.0

    def __init__(
        self,
        auth_client: Optional[INDMoneyAuthClient] = None,
        config_dir: Optional[Path] = None,
    ) -> None:
        self.auth_client = auth_client or INDMoneyAuthClient()
        if config_dir:
            self.config_dir = Path(config_dir)
        else:
            # Dynamically locate the config directory relative to repository root
            self.config_dir = Path(__file__).resolve().parent.parent.parent / "config"
        self.nifty_map = self._load_json(self.config_dir / "nifty50_scrip_map.json")
        self.sensex_map = self._load_json(self.config_dir / "sensex30_scrip_map.json")
        self._quote_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamp: float = 0.0

    def _load_json(self, path: Path) -> Dict[str, Any]:
        """Safely loads a JSON configuration mapping."""
        if not path.exists():
            logger.warning("Scrip mapping file %s not found.", path)
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _fetch_quote_chunk(self, scrip_codes: List[str]) -> Dict[str, Any]:
        """Fetches a single chunk of scrip codes from INDstocks with automatic retry on 429."""
        if not scrip_codes:
            return {}
        headers = self.auth_client.get_auth_headers()
        joined = ",".join(scrip_codes)
        url = f"{self.BASE_URL}{self.QUOTES_ENDPOINT}?scrip-codes={joined}"
        
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                resp = requests.get(url, headers=headers, timeout=8)
                if resp.status_code == 200:
                    payload = resp.json()
                    return payload.get("data", {})
                elif resp.status_code in (401, 403):
                    logger.warning(
                        "INDstocks token rejected (HTTP %s): %s. Triggering automatic headless TOTP authentication...",
                        resp.status_code,
                        resp.text[:120],
                    )
                    # Broker invalidated or revoked session: generate brand new token via TOTP
                    try:
                        self.auth_client.access_token = None
                        new_token = self.auth_client.generate_fresh_token(persist_to_env=True)
                        headers = {"x-api-key": self.auth_client.client_id, "access-token": new_token}
                        # Immediate retry with fresh token
                        retry_resp = requests.get(url, headers=headers, timeout=8)
                        if retry_resp.status_code == 200:
                            logger.info("Successfully authenticated via TOTP and fetched quotes!")
                            return retry_resp.json().get("data", {})
                        else:
                            logger.error("TOTP retry quote fetch returned HTTP %s: %s", retry_resp.status_code, retry_resp.text[:120])
                            return {}
                    except Exception as e:
                        logger.error("Automated TOTP re-authentication failed: %s", e)
                        return {}
                elif resp.status_code == 429:
                    if attempt < max_retries:
                        backoff = 0.6 * (attempt + 1)
                        logger.warning(
                            "Batch quotes chunk hit HTTP 429 rate limit. Retrying in %.1fs (attempt %d/%d)...",
                            backoff,
                            attempt + 1,
                            max_retries,
                        )
                        time.sleep(backoff)
                        continue
                    else:
                        logger.warning("Batch quotes chunk returned HTTP 429: %s", resp.text[:120])
                        return {}
                else:
                    logger.warning("Batch quotes chunk returned HTTP %s: %s", resp.status_code, resp.text[:120])
                    return {}
            except Exception as exc:
                if attempt < max_retries:
                    time.sleep(0.5)
                    continue
                logger.error("Failed to fetch quote chunk: %s", exc)
                return {}
        return {}

    def fetch_index_quotes(self, index_name: str = "NIFTY") -> List[Dict[str, Any]]:
        """
        Fetches live quotes for all constituents in the specified index ('NIFTY' or 'SENSEX').
        Reuses cached quotes across indices within CACHE_TTL_SECONDS to avoid rate limits.
        Returns list of constituent dictionaries with live price, day VWAP, and weight.
        """
        target_map = self.nifty_map if index_name.upper() == "NIFTY" else self.sensex_map
        if not target_map:
            logger.error("No constituent mapping available for index: %s", index_name)
            return []

        scrip_to_sym = {v["scrip_code"]: (k, v["weight"]) for k, v in target_map.items()}
        all_scrips = list(scrip_to_sym.keys())

        now = time.time()
        # Invalidate cache if expired
        if now - self._cache_timestamp > self.CACHE_TTL_SECONDS:
            self._quote_cache.clear()

        # Determine which scrip codes need to be fetched from network
        needed_scrips = [scrip for scrip in all_scrips if scrip not in self._quote_cache]

        if needed_scrips:
            for i in range(0, len(needed_scrips), self.BATCH_CHUNK_SIZE):
                chunk = needed_scrips[i : i + self.BATCH_CHUNK_SIZE]
                chunk_data = self._fetch_quote_chunk(chunk)
                self._quote_cache.update(chunk_data)
                self._cache_timestamp = time.time()
                # Polite pacing between chunks to prevent burst rate limiting
                if i + self.BATCH_CHUNK_SIZE < len(needed_scrips):
                    time.sleep(0.15)

        results: List[Dict[str, Any]] = []
        for scrip_code, (symbol, weight) in scrip_to_sym.items():
            q = self._quote_cache.get(scrip_code, {})
            if not q:
                continue

            live_price = float(q.get("live_price", 0.0))
            day_high = float(q.get("day_high", live_price))
            day_low = float(q.get("day_low", live_price))
            day_open = float(q.get("day_open", live_price))
            prev_close = float(q.get("prev_close", live_price))
            volume = int(q.get("volume", 0))
            change_pct = float(q.get("day_change_percentage", 0.0))

            # Institutional Intraday VWAP Approximation:
            # Typical Price (TP) = (High + Low + Close) / 3
            # In live sessions, TP accurately tracks intraday equilibrium
            day_vwap = round((day_high + day_low + live_price) / 3.0, 2)
            is_above_vwap = live_price >= day_vwap

            results.append({
                "symbol": symbol,
                "scrip_code": scrip_code,
                "weight": weight,
                "live_price": live_price,
                "day_vwap": day_vwap,
                "day_high": day_high,
                "day_low": day_low,
                "day_open": day_open,
                "prev_close": prev_close,
                "volume": volume,
                "change_pct": change_pct,
                "is_above_vwap": is_above_vwap,
                "spread_from_vwap_pct": round(((live_price - day_vwap) / day_vwap) * 100, 2) if day_vwap > 0 else 0.0,
            })

        logger.info(
            "Fetched %d / %d valid constituent quotes for %s (Cache: %s)",
            len(results),
            len(target_map),
            index_name,
            "HIT (0 network calls)" if not needed_scrips else f"FETCHED {len(needed_scrips)} scrips",
        )
        return results

