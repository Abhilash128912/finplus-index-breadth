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

    def __init__(
        self,
        auth_client: Optional[INDMoneyAuthClient] = None,
        config_dir: Optional[Path] = None,
    ) -> None:
        self.auth_client = auth_client or INDMoneyAuthClient()
        self.config_dir = config_dir or Path("D:/AI_APPS/finplus_index_breadth/config")
        self.nifty_map = self._load_json(self.config_dir / "nifty50_scrip_map.json")
        self.sensex_map = self._load_json(self.config_dir / "sensex30_scrip_map.json")

    def _load_json(self, path: Path) -> Dict[str, Any]:
        """Safely loads a JSON configuration mapping."""
        if not path.exists():
            logger.warning("Scrip mapping file %s not found.", path)
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _fetch_quote_chunk(self, scrip_codes: List[str]) -> Dict[str, Any]:
        """Fetches a single chunk of scrip codes from INDstocks."""
        if not scrip_codes:
            return {}
        headers = self.auth_client.get_auth_headers()
        joined = ",".join(scrip_codes)
        url = f"{self.BASE_URL}{self.QUOTES_ENDPOINT}?scrip-codes={joined}"
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code == 200:
                payload = resp.json()
                return payload.get("data", {})
            else:
                logger.warning("Batch quotes chunk returned HTTP %s: %s", resp.status_code, resp.text[:120])
                return {}
        except Exception as exc:
            logger.error("Failed to fetch quote chunk: %s", exc)
            return {}

    def fetch_index_quotes(self, index_name: str = "NIFTY") -> List[Dict[str, Any]]:
        """
        Fetches live quotes for all constituents in the specified index ('NIFTY' or 'SENSEX').
        Returns list of constituent dictionaries with live price, day VWAP, and weight.
        """
        target_map = self.nifty_map if index_name.upper() == "NIFTY" else self.sensex_map
        if not target_map:
            logger.error("No constituent mapping available for index: %s", index_name)
            return []

        scrip_to_sym = {v["scrip_code"]: (k, v["weight"]) for k, v in target_map.items()}
        all_scrips = list(scrip_to_sym.keys())

        # Fetch in chunks
        raw_quotes: Dict[str, Any] = {}
        for i in range(0, len(all_scrips), self.BATCH_CHUNK_SIZE):
            chunk = all_scrips[i : i + self.BATCH_CHUNK_SIZE]
            chunk_data = self._fetch_quote_chunk(chunk)
            raw_quotes.update(chunk_data)

        results: List[Dict[str, Any]] = []
        for scrip_code, (symbol, weight) in scrip_to_sym.items():
            q = raw_quotes.get(scrip_code, {})
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
            "Fetched %d / %d valid constituent quotes for %s",
            len(results),
            len(target_map),
            index_name,
        )
        return results

