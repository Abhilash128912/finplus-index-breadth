# Changelog - FinPlus+ Index Breadth & BTST Engine

All notable changes to the **FinPlus+ Market Trend & Intraday Trading Decision Engine** (`APP-01`) are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.5.0] - 2026-11-08 (12:44 IST) - Commit `HEAD`
### Added
- **Real-Time Regime Flip Instant NTFY Alerts:** Automated trigger that compares the current regime with the previous regime on every cycle. If the market trend shifts (e.g. from `UPTREND` to `CHOPPY_DIVERGENT`), it instantly fires a Priority 4/5 push alert to `Finplus-Delta` and `Finplus-Breadth` with direct "Open Cockpit" tap action buttons.
- **Intraday Breadth Momentum Velocity:** Rolling 15m/30m trailing window computing $\Delta\text{Stocks Above VWAP}$. Surfaces `Accelerating ↗`, `Deteriorating ↘`, or `Steady →` as an early warning signal before the index spot chart breaks down.
- **Sectoral Leadership & Rotation Radar:** Real-time ranking of the top 7 NSE sectoral indices (Bank, IT, Auto, Pharma, FMCG, Metal, Energy) identifying the current market leader and laggard.
- **Web Dashboard Ribbons:** Added live `Velocity` pill on the Hero trend card and an interactive `Sector Rotation` ribbon displaying live sector percentage changes.

---

## [1.4.0] - 2026-11-08 (12:30 IST) - Commit `8a38031`
### Added
- **Institutional Composite Trend Index (CTI):** Replaced brittle single-threshold `if/elif` ladders with a normalized multi-pillar mathematical scoring engine ranging from $-100$ (Extreme Liquidation) to $+100$ (Broad Bull Expansion).
- **Three-Pillar Balanced Weighting:**
  - *Pillar 1: Bluechip Benchmark Breadth (Max ±40 pts)*: Integrates Nifty 50 WABI, Sensex 30 WABI cross-index confluence, and Top 5 heavyweights.
  - *Pillar 2: Broad Market Participation (Max ±35 pts)*: Combines 2,266 All-NSE ADR with Nifty 500 advance/decline volume breadth.
  - *Pillar 3: Derivatives & Volatility Confluence (Max ±25 pts)*: Integrates Index Options PCR, India VIX intraday momentum ($\Delta\text{VIX}$), and Nifty Futures Basis (Premium/Discount).
- **Master Divergence Veto Guard:** If Bluechip WABI is positive ($\ge +0.25$) but All-NSE declines dominate the exchange ($\text{ADR} < 0.85$ or Declines $> \text{Advances} + 300$), automatically forces `CHOPPY / DIVERGENT (NARROW BLUECHIP RALLY)` to protect capital against artificial 5-heavyweight manipulation traps.
- **Live CTI Score Badge:** Displayed directly on the web dashboard hero card (e.g. `CTI SCORE: -6 / 100`).

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

