# FinPlus+ Index Breadth & BTST Engine
**Enterprise App ID:** `APP-01`  
**Standard:** Institutional Grade • Zero Fabricated Data • Cloud Native (Render Ready)

---

## Overview
A quantitative market breadth and overnight index gap-prediction engine specialized for **NIFTY 50** and **BSE SENSEX 30**. 

Features:
* **Weight-Adjusted Breadth Index (WABI):** Real-time alignment of all 50 Nifty and 30 Sensex constituent weights against Day VWAP.
* **Top 5 Heavyweight Confluence:** Continuous tracking of HDFC Bank, Reliance, ICICI Bank, Infosys, and ITC (~38% of Nifty index).
* **Index BTST Decision Engine:** Evaluates overnight long suitability strictly between 3:10 PM and 3:30 PM IST.
* **Periodic 30-Min Push Pulses:** Dispatched to your phone via `ntfy.sh/Finplus-Breadth` (09:30, 10:00, ..., 15:00 IST).
* **Cross-Window Always-On-Top Floater:** PiP HUD pop-out staying visible over TradingView, Zerodha, and Excel.

---

## Directory Structure
```
D:\AI_APPS\finplus_index_breadth\
├── config/
│   ├── .env (Vaulted INDmoney credentials)
│   ├── nifty50_weights.json (Official 50 constituent weights)
│   ├── sensex30_weights.json (Official 30 constituent weights)
│   ├── nifty50_scrip_map.json (Mapped NSE security codes)
│   └── sensex30_scrip_map.json (Mapped BSE security codes)
├── src/
│   ├── feeds/indmoney_market_feed.py (Batch live quote fetcher)
│   ├── analytics/vwap_breadth_engine.py (WABI & VWAP calculations)
│   ├── analytics/index_btst_engine.py (Strict BTST decision matrix)
│   ├── notifications/ntfy_dispatcher.py (Mobile push sender)
│   ├── scheduler/market_scheduler.py (Background 30m / 3:15pm scheduler)
│   └── api/server.py (FastAPI gateway & WebSocket broadcast)
├── frontend/ (Institutional Dark UI with Document PiP Floater)
├── desktop_floater/ (Native Windows Tkinter always-on-top HUD)
├── docs/INDEX_BREADTH_AND_BTST_SOP.md (Complete documentation)
├── tests/test_app.py (Automated verification test suite)
├── logs/execution_test.log (Live integration audit trace)
├── render.yaml (1-click cloud deployment configuration)
├── Dockerfile & requirements.txt
```

---

## Running Locally / Testing
```bash
# 1. Run integration tests
python tests/test_app.py

# 2. Run local development server
uvicorn src.api.server:app --port 8000 --reload

# 3. Launch native desktop always-on-top floater
python desktop_floater/finplus_floater.py
```

