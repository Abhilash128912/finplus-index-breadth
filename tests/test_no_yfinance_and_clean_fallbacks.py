"""
Tests ensuring complete removal of yfinance/Yahoo dependencies,
zero fabricated numeric fallbacks (>1000), and proper UNKNOWN regime handling.
"""

import ast
import datetime
import os
import sys
from pathlib import Path
import pytest

APP_ROOT = Path(__file__).resolve().parent.parent
AI_APPS_ROOT = APP_ROOT.parent
if str(AI_APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_APPS_ROOT))
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from finplus_index_breadth.analytics.market_regime_engine import MarketRegimeEngine, MarketRegimeStateManager

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
FORBIDDEN_NUMBERS = [
    24965.0, 24881.3, 23410.0, 24925.0, 1107796241968.77,
    80757.2, 24847.2, 79450.0, 24850.0
]
FORBIDDEN_PATTERNS = ["yfinance", "yf.", "finance.yahoo", "^BSESN", "^NSEI", "^INDIAVIX"]


def test_src_has_zero_yfinance_and_yahoo():
    """Verify that no file in src/ imports yfinance or contains Yahoo endpoints."""
    violations = []
    for root, _, files in os.walk(SRC_DIR):
        for f in files:
            if f.endswith(".py"):
                file_path = Path(root) / f
                content = file_path.read_text(encoding="utf-8")
                
                # Check text patterns
                for pat in FORBIDDEN_PATTERNS:
                    if pat in content:
                        violations.append(f"{file_path.name}: contains forbidden pattern '{pat}'")

                # Check AST imports
                tree = ast.parse(content, filename=str(file_path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if "yfinance" in alias.name:
                                violations.append(f"{file_path.name}:{node.lineno} imports {alias.name}")
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and "yfinance" in node.module:
                            violations.append(f"{file_path.name}:{node.lineno} imports from {node.module}")

    assert not violations, f"Found yfinance/Yahoo occurrences in src/:\n" + "\n".join(violations)


def test_src_has_zero_fallback_literals_above_1000():
    """Verify that no file in src/ uses numeric literals > 1000 as fallback defaults."""
    violations = []
    for root, _, files in os.walk(SRC_DIR):
        for f in files:
            if f.endswith(".py"):
                file_path = Path(root) / f
                content = file_path.read_text(encoding="utf-8")
                tree = ast.parse(content, filename=str(file_path))

                for node in ast.walk(tree):
                    # Check dict.get(..., <literal > 1000>)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
                        if len(node.args) >= 2:
                            default_arg = node.args[1]
                            if isinstance(default_arg, ast.Constant) and isinstance(default_arg.value, (int, float)) and default_arg.value > 1000:
                                violations.append(f"{file_path.name}:{node.lineno} uses dict.get default {default_arg.value}")
                    # Check X or <literal > 1000>
                    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
                        for val in node.values[1:]:
                            if isinstance(val, ast.Constant) and isinstance(val.value, (int, float)) and val.value > 1000:
                                violations.append(f"{file_path.name}:{node.lineno} uses bool-or default {val.value}")

    assert not violations, f"Found numeric fallback literals > 1000 in src/:\n" + "\n".join(violations)


def test_regime_unknown_when_nifty_spot_is_none(tmp_path):
    """When nifty_spot is None, regime must be UNKNOWN and alerts suppressed."""
    state_file = tmp_path / "regime_state.json"
    mgr = MarketRegimeEngine.reset_state_manager(state_file=state_file)
    mgr.current_regime = "UPTREND"

    broad_market = {
        "nifty_spot": None,
        "sensex_spot": 80100.0,
        "tick_age": 1.5,
        "data_status": "PARTIAL",
        "broad_market": {"advances": 1200, "declines": 800, "advance_decline_ratio": 1.5, "total_stocks": 2000},
    }
    nifty_breadth = {"status": "LIVE_STREAMING", "advances": 30, "declines": 20, "wabi_score": 0.2, "stocks_above_vwap_pct": 60.0}
    sensex_breadth = {"status": "LIVE_STREAMING", "advances": 18, "declines": 12, "wabi_score": 0.2}

    res = MarketRegimeEngine.evaluate_regime(nifty_breadth, sensex_breadth, broad_market=broad_market)

    assert res["regime"] == "UNKNOWN"
    assert res["trend"]["code"] == "UNKNOWN"
    assert res["data_status"] == "PARTIAL"
    assert res["should_alert"] is False
    assert res["transition"] == {}
    # State manager should NOT flip
    assert mgr.current_regime == "UPTREND"


def test_regime_unknown_when_sensex_spot_is_none(tmp_path):
    """When sensex_spot is None, regime must be UNKNOWN and alerts suppressed."""
    state_file = tmp_path / "regime_state.json"
    mgr = MarketRegimeEngine.reset_state_manager(state_file=state_file)
    mgr.current_regime = "STRONG_UPTREND"

    broad_market = {
        "nifty_spot": 25100.0,
        "sensex_spot": None,
        "tick_age": 2.0,
        "data_status": "PARTIAL",
        "broad_market": {"advances": 1400, "declines": 600, "advance_decline_ratio": 2.3, "total_stocks": 2000},
    }
    nifty_breadth = {"status": "LIVE_STREAMING", "advances": 35, "declines": 15, "wabi_score": 0.4, "stocks_above_vwap_pct": 70.0}
    sensex_breadth = {"status": "LIVE_STREAMING", "advances": 22, "declines": 8, "wabi_score": 0.4}

    res = MarketRegimeEngine.evaluate_regime(nifty_breadth, sensex_breadth, broad_market=broad_market)

    assert res["regime"] == "UNKNOWN"
    assert res["trend"]["code"] == "UNKNOWN"
    assert res["data_status"] == "PARTIAL"
    assert res["should_alert"] is False
    assert mgr.current_regime == "STRONG_UPTREND"


def test_regime_unknown_when_breadth_data_is_none(tmp_path):
    """When broad_market is None or lacks breadth, regime must be UNKNOWN."""
    state_file = tmp_path / "regime_state.json"
    mgr = MarketRegimeEngine.reset_state_manager(state_file=state_file)
    mgr.current_regime = "CHOPPY"

    nifty_breadth = {"status": "NO_DATA"}
    sensex_breadth = {"status": "NO_DATA"}

    res = MarketRegimeEngine.evaluate_regime(nifty_breadth, sensex_breadth, broad_market=None)

    assert res["regime"] == "UNKNOWN"
    assert res["trend"]["code"] == "UNKNOWN"
    assert res["data_status"] == "PARTIAL"
    assert res["should_alert"] is False
    assert mgr.current_regime == "CHOPPY"


def test_regime_unknown_when_tick_older_than_15s(tmp_path):
    """When tick age exceeds 15 seconds, regime must be UNKNOWN and status STALE."""
    state_file = tmp_path / "regime_state.json"
    mgr = MarketRegimeEngine.reset_state_manager(state_file=state_file)
    mgr.current_regime = "UPTREND"

    broad_market = {
        "nifty_spot": 25200.0,
        "sensex_spot": 82000.0,
        "tick_age": 18.4,
        "data_status": "STALE",
        "broad_market": {"advances": 1500, "declines": 500, "advance_decline_ratio": 3.0, "total_stocks": 2000},
    }
    nifty_breadth = {"status": "LIVE_STREAMING", "advances": 35, "declines": 15, "wabi_score": 0.4, "stocks_above_vwap_pct": 70.0}
    sensex_breadth = {"status": "LIVE_STREAMING", "advances": 22, "declines": 8, "wabi_score": 0.4}

    res = MarketRegimeEngine.evaluate_regime(nifty_breadth, sensex_breadth, broad_market=broad_market)

    assert res["regime"] == "UNKNOWN"
    assert res["trend"]["code"] == "UNKNOWN"
    assert res["data_status"] == "STALE"
    assert res["should_alert"] is False
    assert mgr.current_regime == "UPTREND"


def test_india_vix_none_scores_cleanly_partial_status(tmp_path):
    """
    When india_vix = None, regime scoring runs without error,
    treats VIX as unavailable (never 0 or default), sets data_status = PARTIAL,
    and regime is NOT forced to UNKNOWN because spot and breadth are valid.
    """
    state_file = tmp_path / "regime_state.json"
    mgr = MarketRegimeEngine.reset_state_manager(state_file=state_file)

    broad_market = {
        "nifty_spot": 25250.0,
        "sensex_spot": 82100.0,
        "tick_age": 1.2,
        "data_status": "OK",
        "vix": {
            "value": None,
            "change": None,
            "change_pct": None,
        },
        "broad_market": {
            "advances": 1600,
            "declines": 400,
            "advance_decline_ratio": 4.0,
            "total_stocks": 2000,
        },
        "segments": {
            "nifty_500": {"advances": 380, "declines": 120},
        },
    }
    nifty_breadth = {
        "status": "LIVE_STREAMING",
        "advances": 42,
        "declines": 8,
        "wabi_score": 0.68,
        "stocks_above_vwap_pct": 84.0,
        "volume_thrust_pct": 80.0,
        "heavyweights": {"HDFCBANK": "ABOVE_VWAP", "RELIANCE": "ABOVE_VWAP", "ICICIBANK": "ABOVE_VWAP", "INFY": "ABOVE_VWAP", "ITC": "ABOVE_VWAP"},
    }
    sensex_breadth = {
        "status": "LIVE_STREAMING",
        "advances": 26,
        "declines": 4,
        "wabi_score": 0.70,
    }

    # Evaluate with N=3 confirmation cycles
    res = None
    for _ in range(3):
        res = MarketRegimeEngine.evaluate_regime(nifty_breadth, sensex_breadth, broad_market=broad_market)

    # Must NOT be forced to UNKNOWN (spot and breadth are healthy)
    assert res["regime"] != "UNKNOWN"
    assert res["trend"]["code"] in ("UPTREND", "STRONG_UPTREND")
    # VIX is missing, so overall data_status must be PARTIAL
    assert res["data_status"] == "PARTIAL"
    assert res["metrics"]["vix_value"] is None


def test_fetch_indstocks_quote_stale_and_http_error(monkeypatch):
    """
    _fetch_indstocks_quote contract:
    - Stale tick (>15s) -> (None, None, age)
    - HTTP error -> (None, None, age)
    - No exception raised under any condition
    """
    import time
    from finplus_index_breadth.feeds.nse_broad_market_feed import NSEBroadMarketFeed
    import requests

    feed = NSEBroadMarketFeed()

    # 1. Stale tick test: cached tick is 25s old, HTTP fails
    class MockFailResp:
        status_code = 503
        def json(self):
            return {}

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: MockFailResp())

    feed._quote_time["BIDX_40000006"] = time.time() - 25.0
    feed._quote_cache["BIDX_40000006"] = {"live_price": 82000.0, "day_change_percentage": 0.5}

    spot, chg, age = feed._fetch_indstocks_quote("BIDX_40000006")
    assert spot is None
    assert chg is None
    assert age >= 25.0

    # 2. HTTP error test with no cache: must return (None, None, age) without raising
    feed._quote_time.clear()
    feed._quote_cache.clear()

    spot2, chg2, age2 = feed._fetch_indstocks_quote("BIDX_40000006")
    assert spot2 is None
    assert chg2 is None
    assert age2 >= 900.0

    # 3. Network Exception: must catch and return (None, None, age), no exception raised
    def raise_network_err(*args, **kwargs):
        raise requests.ConnectionError("Network connection reset")

    monkeypatch.setattr(requests, "get", raise_network_err)
    spot3, chg3, age3 = feed._fetch_indstocks_quote("BIDX_40000006")
    assert spot3 is None
    assert chg3 is None
    assert age3 >= 900.0


def test_regime_debug_endpoint():
    """Verify /api/regime/debug returns per-field details, per-source counters, and last source errors with zero secrets."""
    from fastapi.testclient import TestClient
    from finplus_index_breadth.api.server import app

    client = TestClient(app)
    resp = client.get("/api/regime/debug")
    assert resp.status_code == 200

    data = resp.json()
    assert "data_status" in data
    assert "fields" in data
    assert "last_errors" in data
    assert "sources" in data
    assert "background_thread_alive" in data

    # Check sources
    for src in ["indstocks_sensex", "indstocks_nifty", "nse_breadth", "vix"]:
        assert src in data["sources"], f"Missing source {src}"
        s_obj = data["sources"][src]
        assert "last_success_ts" in s_obj
        assert "last_error" in s_obj
        assert "consecutive_failures" in s_obj
        assert "token_age_seconds" in s_obj
        assert "exchange_ts" in s_obj
        assert "fetched_at" in s_obj

    fields = data["fields"]
    for req_field in ["nifty_spot", "sensex_spot", "breadth", "india_vix"]:
        assert req_field in fields, f"Missing field {req_field}"
        f_obj = fields[req_field]
        assert "value" in f_obj
        assert "source" in f_obj
        assert "tick_age" in f_obj
        assert "data_status" in f_obj

    last_errors = data["last_errors"]
    for src in ["nse_breadth", "indstocks_quotes", "vix"]:
        assert src in last_errors, f"Missing source error key {src}"


def test_stale_exchange_timestamp_marks_stale(monkeypatch):
    """
    Requirement 6: If exchange timestamp is older than 15s during market hours, mark STALE.
    """
    import time
    from email.utils import formatdate
    import requests
    from finplus_index_breadth.feeds.nse_broad_market_feed import NSEBroadMarketFeed
    import finplus_index_breadth.feeds.nse_broad_market_feed as feed_module

    feed = NSEBroadMarketFeed()

    # Mock market hours = OPEN
    monkeypatch.setattr(feed_module, "is_regular_nse_market_open", lambda *args, **kwargs: True)

    # 25 seconds ago
    old_time = time.time() - 25.0
    old_date_hdr = formatdate(old_time, usegmt=True)

    class MockOldResp:
        status_code = 200
        headers = {"Date": old_date_hdr}
        def json(self):
            return {"status": "success", "data": {"BIDX_40000006": {"live_price": 82100.0, "day_change_percentage": 0.2}}}

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: MockOldResp())

    res = feed._fetch_indstocks_quote("BIDX_40000006")
    assert res.data_status == "STALE"
    assert res.spot is None  # Stale tick returns None spot
    assert res.tick_age >= 24.0


def test_error_returns_none_with_no_cached_value(monkeypatch):
    """
    Requirement 6: Never return a cached price on error. On any failure return None and set last_error.
    """
    import requests
    from finplus_index_breadth.feeds.nse_broad_market_feed import NSEBroadMarketFeed

    feed = NSEBroadMarketFeed()

    # Seed previous successful quote
    feed.last_success_ts["indstocks_sensex"] = 1000.0

    class MockErrResp:
        status_code = 500
        headers = {}
        text = "Internal Server Error"
        def json(self):
            return {}

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: MockErrResp())

    res = feed._fetch_indstocks_quote("BIDX_40000006")
    assert res.spot is None
    assert res.change_pct is None
    assert feed.last_errors["indstocks_sensex"] == "HTTP 500"
    assert feed.consecutive_failures["indstocks_sensex"] >= 1


def test_outside_market_hours_marks_market_closed(monkeypatch):
    """
    Requirement 6: Outside market hours, mark MARKET_CLOSED, not STALE.
    """
    import requests
    from finplus_index_breadth.feeds.nse_broad_market_feed import NSEBroadMarketFeed
    import finplus_index_breadth.feeds.nse_broad_market_feed as feed_module

    feed = NSEBroadMarketFeed()

    # Mock market hours = CLOSED
    monkeypatch.setattr(feed_module, "is_regular_nse_market_open", lambda *args, **kwargs: False)

    class MockOkResp:
        status_code = 200
        headers = {}
        def json(self):
            return {"status": "success", "data": {"BIDX_40000006": {"live_price": 82100.0, "day_change_percentage": 0.2}}}

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: MockOkResp())

    res = feed._fetch_indstocks_quote("BIDX_40000006")
    assert res.data_status == "MARKET_CLOSED"

