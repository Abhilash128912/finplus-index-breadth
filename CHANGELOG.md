# Changelog - FinPlus+ Index Breadth & BTST Engine

All notable changes to the **FinPlus+ Market Trend & Intraday Trading Decision Engine** (`APP-01`) are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.3.0] - 2026-11-08 (12:12 IST) - Commit `f5e2c47`
### Added
- **India VIX Volatility Analytics:** Real-time ingestion of India VIX from official NSE exchange feed. Classifies volatility into *Low Volatility (Theta Bleed)* ($<12.0$), *Normal Momentum Sweet Spot* ($12.0-16.5$), *Elevated Volatility* ($16.5-21.0$), and *Event Risk* ($>21.0$).
- **Index Options Put-Call Ratio (PCR):** Real-time tracking of exchange-wide Index Options PCR (0.85) to detect whether Put writers are providing support or Call writers are mounting overhead supply resistance.
- **Nifty Futures Basis & Discount/Premium:** Automated tracking of Nifty near-month futures LTP vs Spot LTP (spread points) and futures open interest.
- **Derivatives & Volatility Radar Panel:** Modern glassmorphism UI card in `frontend/index.html` displaying live VIX, Index PCR, and Futures Basis.
- **Enhanced NTFY Pulses:** Added dedicated `📈 DERIVATIVES & VOLATILITY PILLARS` section to 30-min periodic push alerts.

---

## [1.2.0] - 2026-11-08 (11:56 IST) - Commit `94b9110`
### Fixed
- **Strict Options Barring on Choppy / Cash Days:** Eliminated confusing "standby" ATM Call contracts when BTST is disqualified.
- **Capital Protection Rule Enforcement:** When market breadth is choppy or in a distribution regime, `primary_option_contract` is set to `None`, locked with a red security banner, and completely barred in NTFY push notifications.

---

## [1.1.0] - 2026-11-08 (11:49 IST) - Commit `1b2e3bc`
### Performance
- **Asynchronous Worker Thread Offloading:** Refactored blocking HTTP calls (`requests.get` to NSE India and INDstocks) to execute inside `asyncio.to_thread`.
- **Instant Port Binding:** Server startup is non-blocking; Uvicorn binds port 8000/10000 in $<0.1\text{s}$, eliminating Render gateway timeouts on cold start.

---

## [1.0.1] - 2026-11-08 (11:11 IST) - Commit `bfc5a07`
### Fixed
- **Cross-Index Smart Cache (HTTP 429 Elimination):** Leveraged 100% overlap between Nifty 50 and Sensex 30 constituent scrips. Cached quotes for 30 seconds so SENSEX 30 requires 0 network calls, eliminating INDstocks burst rate limit warnings.
- **Request Pacing & Retry Backoff:** Added 150ms chunk pacing and exponential backoff retry on HTTP 429.

---

## [1.0.0] - 2026-11-07 (20:30 IST) - Commit `b25551b`
### Initial Release
- **All-NSE Listed Equities Feed:** Ingests live data for all 2,266 actively traded NSE stocks (₹1.10L Cr turnover, Advance/Decline ratio).
- **Weight-Adjusted Breadth Index (WABI):** VWAP-aligned institutional breadth for Nifty 50 and Sensex 30.
- **5 Heavyweight Confluence:** Real-time tracking of HDFC Bank, Reliance, ICICI Bank, Infosys, and ITC.
- **3:10 PM BTST Binary Radar:** Strict 5-gate institutional model with mandatory Broad Market Veto Gate.
- **Dual-Topic NTFY Dispatcher:** Dispatches to `Finplus-Delta` and `Finplus-Breadth`.
- **Dockerized Cloud Deployment:** Configured for Render cloud deployment.

