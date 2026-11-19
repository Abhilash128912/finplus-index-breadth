"""
Tests ensuring complete removal of yfinance/Yahoo dependencies,
zero fabricated numeric fallbacks (>1000), and proper UNKNOWN regime handling.
"""

import ast
import datetime
import os
from pathlib import Path
import pytest

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
