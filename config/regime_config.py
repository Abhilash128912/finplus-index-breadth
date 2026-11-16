"""
FinPlus+ Market Regime Configuration Constants
================================================
Centralized thresholds, hysteresis bands, confirmation rules, and alert cooldown parameters.
"""

from pathlib import Path

# Hysteresis Bands: (enter_threshold, exit_threshold)
# STRONG_UPTREND: enter >= 60, exit < 50 (band 50-59 retains current)
STRONG_UPTREND_ENTER = 60
STRONG_UPTREND_EXIT = 50

# UPTREND: enter >= 25, exit < 15 (band 15-24 retains current)
UPTREND_ENTER = 25
UPTREND_EXIT = 15

# DOWNTREND: enter <= -25, exit > -15 (band -24 to -15 retains current)
DOWNTREND_ENTER = -25
DOWNTREND_EXIT = -15

# STRONG_DOWNTREND: enter <= -60, exit > -50 (band -59 to -50 retains current)
STRONG_DOWNTREND_ENTER = -60
STRONG_DOWNTREND_EXIT = -50

# Confirmation Count: consecutive evaluations required to confirm a new regime
REGIME_CONFIRMATION_COUNT = 3

# Alert Cooldown: suppress further alerts for 15 minutes unless jumping 2+ levels
REGIME_ALERT_COOLDOWN_SECONDS = 900  # 15 minutes

# Market Hours (IST)
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 15
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30

# State persistence path
DEFAULT_REGIME_STATE_PATH = Path(__file__).resolve().parent / "regime_state.json"

# Numeric level hierarchy for multi-level jump calculation
REGIME_LEVELS = {
    "STRONG_DOWNTREND": -2,
    "DOWNTREND": -1,
    "CHOPPY": 0,
    "CHOPPY_DIVERGENT": 0,
    "UPTREND": 1,
    "STRONG_UPTREND": 2,
}

REGIME_LABELS = {
    "STRONG_UPTREND": "STRONG UPTREND (ALL-PILLAR CONFLUENCE)",
    "UPTREND": "UPTREND (MODERATE BULL BIAS)",
    "CHOPPY": "CHOPPY / RANGEBOUND (SIDEWAYS)",
    "CHOPPY_DIVERGENT": "CHOPPY / DIVERGENT (NARROW BLUECHIP RALLY)",
    "DOWNTREND": "DOWNTREND (BEAR DISTRIBUTION)",
    "STRONG_DOWNTREND": "STRONG DOWNTREND (ALL-MARKET LIQUIDATION)",
}
