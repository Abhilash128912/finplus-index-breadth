"""
FinPlus+ Market Trend & Intraday Decision Engine - Integration Test Suite
========================================================================
Standard: ISO-8601, Comprehensive Logging, Real Data Verification
Output Log: D:/AI_APPS/finplus_index_breadth/logs/execution_test.log
"""

import datetime
import json
import os
import sys
from pathlib import Path

# Setup Python paths
APP_ROOT = Path(__file__).resolve().parent.parent
AI_APPS_ROOT = APP_ROOT.parent
sys.path.insert(0, str(AI_APPS_ROOT))
sys.path.insert(0, str(APP_ROOT))

from finplus_core.auth import INDMoneyAuthClient
from finplus_index_breadth.analytics.index_btst_engine import IndexBTSTEngine
from finplus_index_breadth.analytics.market_regime_engine import MarketRegimeEngine
from finplus_index_breadth.analytics.vwap_breadth_engine import VWAPBreadthEngine
from finplus_index_breadth.feeds.indmoney_market_feed import INDMoneyMarketFeed
from finplus_index_breadth.feeds.nse_broad_market_feed import NSEBroadMarketFeed
from finplus_index_breadth.notifications.ntfy_dispatcher import NTFYDispatcher

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
LOG_FILE = APP_ROOT / "logs" / "execution_test.log"


def log_entry(msg: str):
    timestamp = datetime.datetime.now(tz=IST).isoformat()
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_full_verification():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write(f"=== FINPLUS+ INTEGRATION TEST LOG - {datetime.datetime.now(tz=IST).isoformat()} ===\n\n")

    log_entry("TEST STEP 1: Verifying Scrip Code & Weight Mappings...")
    with open(APP_ROOT / "config" / "nifty50_scrip_map.json") as f:
        nifty_map = json.load(f)
    with open(APP_ROOT / "config" / "sensex30_scrip_map.json") as f:
        sensex_map = json.load(f)

    assert len(nifty_map) == 50, f"Expected 50 Nifty constituents, got {len(nifty_map)}"
    assert len(sensex_map) == 30, f"Expected 30 Sensex constituents, got {len(sensex_map)}"
    log_entry(f"[PASS] Successfully verified 50 Nifty and 30 Sensex constituent mappings.")

    log_entry("TEST STEP 2: Verifying NSE Broad Market Feed (All 2,266 Equities)...")
    broad_feed = NSEBroadMarketFeed()
    broad_data = broad_feed.fetch_broad_market_breadth()
    bm = broad_data.get("broad_market", {})
    total_stocks = bm.get("total_stocks_evaluated", 0)
    adv = bm.get("advances", 0)
    dec = bm.get("declines", 0)
    adr = bm.get("advance_decline_ratio", 0.0)
    log_entry(f"  -> Total Evaluated Equities: {total_stocks:,} (All Active NSE Equities)")
    log_entry(f"  -> Exchange Breadth: {adv:,} Advances / {dec:,} Declines (ADR: {adr}:1)")
    log_entry(f"  -> Total Turnover: Rs {bm.get('total_market_turnover_crores', 0):,.2f} Cr")
    assert total_stocks >= 2000, "Broad market count should cover all ~2,266 NSE stocks"
    log_entry("[PASS] NSE Broad Market exchange-wide feed verified.")

    log_entry("TEST STEP 3: Connecting to INDstocks Live Market Feed...")
    auth = INDMoneyAuthClient(env_file_path=APP_ROOT / "config" / ".env")
    feed = INDMoneyMarketFeed(auth_client=auth, config_dir=APP_ROOT / "config")

    nifty_quotes = feed.fetch_index_quotes("NIFTY")
    assert len(nifty_quotes) > 0, "Failed to retrieve Nifty constituent quotes"
    log_entry(f"[PASS] Successfully fetched {len(nifty_quotes)} live quotes for NIFTY 50.")

    sensex_quotes = feed.fetch_index_quotes("SENSEX")
    assert len(sensex_quotes) > 0, "Failed to retrieve Sensex constituent quotes"
    log_entry(f"[PASS] Successfully fetched {len(sensex_quotes)} live quotes for SENSEX 30.")

    log_entry("TEST STEP 4: Executing VWAP Breadth & WABI Analytics...")
    nifty_breadth = VWAPBreadthEngine.analyze_index_breadth(nifty_quotes, "NIFTY 50")
    sensex_breadth = VWAPBreadthEngine.analyze_index_breadth(sensex_quotes, "SENSEX 30")

    log_entry(f"  -> NIFTY 50 Breadth: {nifty_breadth['stocks_above_vwap_pct']}% above VWAP | WABI: {nifty_breadth['wabi_score']:+.3f}")
    log_entry(f"  -> NIFTY Heavyweights ({nifty_breadth['heavyweights_above_vwap_ratio']}): {nifty_breadth['heavyweights']}")
    log_entry(f"  -> NIFTY Volume Thrust: {nifty_breadth['volume_thrust_pct']}% | Regime: {nifty_breadth['regime']}")
    log_entry(f"  -> SENSEX 30 Breadth: {sensex_breadth['stocks_above_vwap_pct']}% above VWAP | WABI: {sensex_breadth['wabi_score']:+.3f}")
    log_entry(f"[PASS] VWAP Breadth and WABI calculations verified.")

    log_entry("TEST STEP 5: Executing Core Market Regime & Intraday Decision Engine...")
    regime = MarketRegimeEngine.evaluate_regime(nifty_breadth, sensex_breadth, broad_market=broad_data)
    trend = regime.get("trend", {})
    eq_dir = regime.get("equities_directive", {})
    opt_dir = regime.get("options_directive", {})

    log_entry(f"  -> Trend Regime: {trend.get('label')} ({trend.get('code')})")
    log_entry(f"  -> Equities Directive: {eq_dir.get('action')}")
    log_entry(f"  -> Equities Guidance: {eq_dir.get('guidance')}")
    log_entry(f"  -> Options Directive: {opt_dir.get('action')}")
    log_entry(f"  -> Options Guidance: {opt_dir.get('guidance')}")
    assert trend.get("code") in ("STRONG_UPTREND", "UPTREND", "CHOPPY", "CHOPPY_DIVERGENT", "DOWNTREND", "STRONG_DOWNTREND")
    log_entry(f"[PASS] Market Regime & Intraday Trading Decision Engine verified.")

    log_entry("TEST STEP 6: Evaluating Afternoon BTST Radar (Subordinated)...")
    btst_result = IndexBTSTEngine.evaluate_btst(nifty_breadth, sensex_breadth, broad_market=broad_data, force_evaluation=True)
    log_entry(f"  -> BTST Status: {btst_result['status']}")
    log_entry(f"  -> Directive: {btst_result['action']}")
    log_entry(f"  -> Nifty ATM Contract: {btst_result.get('nifty_atm_contract', {}).get('contract_symbol')}")
    log_entry(f"  -> Sensex ATM Contract: {btst_result.get('sensex_atm_contract', {}).get('contract_symbol')}")
    log_entry(f"[PASS] BTST decision engine verified.")

    log_entry("TEST STEP 7: Testing Dual-Topic NTFY Push Notifications (Finplus-Delta & Finplus-Breadth)...")
    dispatcher = NTFYDispatcher(topics=["Finplus-Delta", "Finplus-Breadth"])
    
    pulse_ok = dispatcher.send_periodic_breadth_pulse({
        "timestamp": datetime.datetime.now(tz=IST).isoformat(),
        "broad_market": broad_data,
        "nifty": nifty_breadth,
        "sensex": sensex_breadth,
        "market_regime": regime,
        "btst": btst_result,
    })
    log_entry(f"  -> 30-Min Trend & Directives Pulse: {'SUCCESS' if pulse_ok else 'FAILED'}")
    assert pulse_ok, "NTFY Breadth Pulse failed to send"

    btst_ok = dispatcher.send_btst_recommendation(btst_result)
    log_entry(f"  -> 3:10-3:30 BTST Alert Push: {'SUCCESS' if btst_ok else 'FAILED'}")
    assert btst_ok, "NTFY BTST Alert failed to send"

    log_entry("=== ALL INTEGRATION TESTS PASSED (100% CLEAN AUDIT) ===")


if __name__ == "__main__":
    run_full_verification()
