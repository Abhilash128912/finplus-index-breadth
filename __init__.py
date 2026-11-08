"""
FinPlus+ Index Breadth & BTST Engine
====================================
Package: finplus_index_breadth
Standard: ISO-8601, PEP 8, Zero Fabricated Data
"""

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from .src import analytics, feeds, notifications, scheduler, api

# Alias subpackages for flexible importing across container & local runtimes
sys.modules["finplus_index_breadth.analytics"] = analytics
sys.modules["finplus_index_breadth.feeds"] = feeds
sys.modules["finplus_index_breadth.notifications"] = notifications
sys.modules["finplus_index_breadth.scheduler"] = scheduler
sys.modules["finplus_index_breadth.api"] = api

__all__ = ["analytics", "feeds", "notifications", "scheduler", "api"]
