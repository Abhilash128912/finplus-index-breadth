# FinPlus+ Standard Operating Procedure (SOP)
## Market Trend & Intraday Trading Decision Engine (with 3:10 PM BTST Radar)

```
Document Reference : FINPLUS-SOP-APP-001
App ID             : APP-01 (finplus_index_breadth)
System Path        : D:\AI_APPS\finplus_index_breadth\
Last Stamped       : 2026-11-07T20:30:00+05:30
Author             : FinPlus+ Enterprise Infrastructure
Verified User      : Abhilash Babu
Cloud Target       : Render (Free Tier Blueprint: render.yaml)
Brand Identity     : FinPlus+ ⨁ (Healthcare / Pharmacy-grade Reliability)
Policy             : ZERO FABRICATED DATA / REAL BROKER LEDGER ONLY
Compliance         : SEBI Cash STBT Restriction Observed (BTST or 100% Cash Overnight)
```

---

### 1. Executive Summary & Core Mission

The **FinPlus+ Market Trend & Intraday Trading Decision Engine** is the institutional intelligence backbone designed to answer the three core questions every active trader faces each trading day:

1. **Overall Market Trend Regime:** Is the market in a `STRONG UPTREND`, `UPTREND`, `CHOPPY / DIVERGENT`, `DOWNTREND`, or `STRONG DOWNTREND`?
2. **Equities Intraday Directive:** *Should I buy or sell equities intraday?*
   - Gives unambiguous guidance: `BUY EQUITIES INTRADAY (LONG ON DIPS)`, `AVOID FRESH BUYS (CHOPPY WIPSAW RISK)`, or `SELL ON RISE / SHORT EQUITIES`.
3. **Options Trading Directive:** *Whether I need to buy options today or not?*
   - Protects option buyers from capital erosion: `CALL BUYING PERMITTED (CE)`, `DO NOT BUY OPTIONS TODAY (HIGH THETA DECAY / CHOP RISK)`, or `PUT BUYING PERMITTED (PE)`.
4. **End-of-Day BTST Radar:** Evaluated towards market closure (**3:10 PM – 3:30 PM IST**) to determine whether to carry index Long positions overnight or hold 100% cash.

---

### 2. Intraday Market Regime Classification Matrix

The engine combines exchange-wide participation (**2,266 actively traded NSE equities**) with benchmark bluechip momentum (**NIFTY 50 & SENSEX 30** constituents):

| Trend Regime | Broad Market ADR (2,266 Stocks) | Nifty WABI Score | Constituent % > VWAP | Heavyweights (5 Stocks) | Equities Action Directive | Options Action Directive |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **STRONG UPTREND** | $\ge 1.50 : 1$ (Broad green) | $\ge +0.45$ | $\ge 65\%$ | $\ge 4/5$ Above VWAP | **BUY EQUITIES INTRADAY** (Aggressive Longs on Dips) | **CALL BUYING PERMITTED** (High directional impulse outpaces theta) |
| **UPTREND** | $\ge 1.10 : 1$ | $\ge +0.20$ | $\ge 55\%$ | $\ge 3/5$ Above VWAP | **BUY SELECT EQUITIES** (Focus on high relative-strength leaders) | **SELECTIVE CALL BUYING** (Fast exits at intraday resistance) |
| **CHOPPY / DIVERGENT** | $< 0.85 : 1$ or Declines dominate | Any (or divergent) | Split | Mixed | **AVOID FRESH BUYS** (False breakout trap risk >70%) | **DO NOT BUY OPTIONS TODAY** (Severe theta decay & sideways chop) |
| **DOWNTREND** | $\le 0.85 : 1$ | $\le -0.20$ | $\le 45\%$ | $\le 2/5$ Above VWAP | **SELL ON RISE / SHORT** (Defensive cash, avoid long dip buys) | **SELECTIVE PUT BUYING** (Fast exits at key support) |
| **STRONG DOWNTREND** | $\le 0.60 : 1$ (Broad red) | $\le -0.45$ | $\le 35\%$ | $0 - 1/5$ Above VWAP | **AGGRESSIVE SHORTING** (100% cash / short breakdowns) | **PUT BUYING PERMITTED** (Broad liquidation rapidly expands PE) |

---

### 3. Quantitative Formulations

#### 3.1. Weight-Adjusted Breadth Index (WABI)
In a market-cap weighted index like NIFTY 50, equal-weighted breadth creates false signals. WABI solves this by weighting each constituent's VWAP sign by its official NSE index weight:

$$\text{WABI} = \frac{\sum_{i=1}^{50} \left( w_i \times \text{sign}(P_i - \text{VWAP}_i) \right)}{\sum_{i=1}^{50} w_i}$$

* $\text{WABI} \in [-1.0, +1.0]$

#### 3.2. Broad Market Advance-Decline Ratio (ADR)
Tracks all **2,266 actively traded NSE listed equities**:

$$\text{ADR} = \frac{\text{Exchange Advances}}{\max(\text{Exchange Declines}, 1)}$$

---

### 4. End-of-Day BTST Radar (3:10 PM – 3:30 PM IST)

BTST is evaluated strictly towards market close to avoid early false signals. Because Indian SEBI cash rules prohibit STBT (short delivery), the decision is binary:

```mermaid
flowchart TD
    A["3:10 PM - 3:30 PM Scan"] --> B{"Broad Market ADR >= 1.0?<br>(All-NSE Advances >= Declines)"}
    B -->|Fail (Veto)| Z["🛑 HOLD 100% CASH OVERNIGHT<br>(Overnight Calls Strictly Disqualified)"]
    B -->|Pass| C{"Nifty WABI >= +0.40?"}
    C -->|Fail| Z
    C -->|Pass| D{"Nifty Breadth >= 65% above VWAP?"}
    D -->|Fail| Z
    D -->|Pass| E{"Top 5 Heavyweights >= 4/5 above VWAP?"}
    E -->|Fail| Z
    E -->|Pass| F{"Up-Volume Thrust >= 60%?"}
    F -->|Fail| Z
    F -->|Pass| G["🎯 BTST QUALIFIED (ATM CALLS)<br>Nifty 50-step / Sensex 100-step"]
```

---

### 5. Push Notification Schedule (`ntfy.sh/Finplus-Delta` & `Finplus-Breadth`)

| Pulse Event | Timing (IST) | Primary Focus | Payload Content |
| :--- | :--- | :--- | :--- |
| **Intraday Trend & Directives Pulse** | Every 30 Mins (09:30 to 15:00) | **Intraday Trading Decisions** | Market Trend (`Uptrend`/`Choppy`/`Downtrend`), Equities Action, Options Action, All-NSE A/D |
| **End-of-Day BTST Alert** | 3:15 PM & 3:25 PM | **Overnight Index Position** | `🎯 BTST QUALIFIED` with Exact ATM Contracts OR `🛑 HOLD 100% CASH OVERNIGHT` |

---

### 6. Deployment Topography

- **Local Machine Daemon:** `http://127.0.0.1:8000` (FastAPI + WebSocket + Desktop Floater HUD)
- **Cloud Gateway:** `https://finplus-index-breadth.onrender.com` (Render Dockerized Web Service)
- **GitHub Master Repository:** `https://github.com/Abhilash128912/finplus-index-breadth`
- **Rate Limit Optimization:** In-memory 30s cross-index quote cache eliminates duplicate API calls between NIFTY 50 and SENSEX 30 constituents.

---

### 7. Strategic Integration: App #2 (750-Stock Intraday Scanner) Synergy

```
┌─────────────────────────────────────────────────────────────────┐
│  APP #1: MACRO & SECTOR REGIME (The "Air Traffic Control")      │
│  - 2,266 NSE Exchange Gate (Macro Advance/Decline Sentiment)    │
│  - Nifty 50 & Sensex 30 WABI (Heavyweight Capital Flow)         │
│  - Verdict: [STRONG UPTREND | CHOPPY | DOWNTREND]               │
└──────────────────────────────┬──────────────────────────────────┘
                               │  Master Risk Gate (Permit/Veto)
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  APP #2: 750-STOCK INTRADAY SCANNER (The "Strike Team")         │
│  - Nifty 500 + Active F&O Equities (~92% of market turnover)    │
│  - VWAP Breakouts, Volume Surges, Sector Rotation               │
│  - Only takes trades ALIGNED with App #1's Regime               │
└─────────────────────────────────────────────────────────────────┘
```

#### 7.1. Hierarchical Alpha Principles
1. **The 70% False Breakout Filter:**
   - Over 70% of intraday individual stock breakouts fail when the broader index is in a distribution or choppy regime.
   - App #2 queries App #1 (`GET /api/regime`). If the regime is `CHOPPY / DIVERGENT` or `AVOID FRESH BUYS`, App #2 automatically vetoes long breakout signals or throttles position sizes by 50%.
2. **True Liquid Institutional Breadth Confirmation:**
   - The 2,266 NSE broad market includes ~1,500 illiquid micro-caps. The 750-stock universe represents the true institutional liquidity pool (>92% of market turnover).
   - App #2 shares an aggregate telemetry metric (e.g. `% of 750 stocks above intraday VWAP`) back to App #1 as a high-conviction market breadth multiplier.
3. **Decoupled Architecture (Zero Rate Limits):**
   - App #1 does NOT scan 750 stocks directly via REST (which would consume 50 batch requests and trigger broker rate limits).
   - App #2 executes scanning independently and passes a lightweight summary JSON via a local microservice endpoint or shared cache.

