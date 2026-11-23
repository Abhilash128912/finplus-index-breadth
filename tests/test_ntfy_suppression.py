import os
import pytest
from unittest.mock import patch, MagicMock
from src.notifications.ntfy_dispatcher import NTFYDispatcher

def test_ntfy_suppression_when_not_on_render(monkeypatch, caplog):
    """
    Verifies that all NTFY sends in finplus_index_breadth are blocked when RENDER is unset.
    - Local runs return False and execute zero network requests.
    - Logs 'NTFY suppressed (not on Render)' at most once per hour.
    """
    import logging
    monkeypatch.delenv("FINPLUS_ENV", raising=False)
    monkeypatch.delenv("FINPLUS_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("RENDER_SERVICE_ID", raising=False)

    dispatcher = NTFYDispatcher()

    with patch("requests.post") as mock_post, caplog.at_level(logging.INFO):
        # 1. First send: suppressed and logged
        res1 = dispatcher.send_notification("Test Alert 1", "Body 1")
        assert res1 is False
        assert mock_post.call_count == 0
        assert "NTFY suppressed (not on Render)" in caplog.text

        # 2. Second send within 1 hour: suppressed but NOT logged again
        caplog.clear()
        res2 = dispatcher.send_notification("Test Alert 2", "Body 2")
        assert res2 is False
        assert mock_post.call_count == 0
        assert "NTFY suppressed (not on Render)" not in caplog.text

def test_ntfy_allowed_when_on_render(monkeypatch):
    """Verifies that NTFY dispatches normally when RENDER is set."""
    monkeypatch.delenv("FINPLUS_ENV", raising=False)
    monkeypatch.delenv("FINPLUS_ENVIRONMENT", raising=False)
    monkeypatch.setenv("RENDER", "true")
    dispatcher = NTFYDispatcher()

    mock_resp = MagicMock(status_code=200)
    with patch("requests.post", return_value=mock_resp) as mock_post:
        res = dispatcher.send_notification("Test Cloud Alert", "Body Cloud")
        assert res is True
        assert mock_post.call_count >= 1

def test_regime_flip_suppressed_outside_market_hours(monkeypatch):
    """Verifies that regime flip alerts are strictly blocked outside Mon-Fri 09:15-15:30 IST."""
    import datetime
    monkeypatch.delenv("FINPLUS_ENV", raising=False)
    monkeypatch.delenv("FINPLUS_ENVIRONMENT", raising=False)
    monkeypatch.setenv("RENDER", "true")
    dispatcher = NTFYDispatcher()

    regime_info = {"trend": {"label": "CHOPPY", "score_label": "0 / 100"}}
    snapshot = {"broad_market": {"broad_market": {}}}

    # Case 1: 5:30 AM IST (Monday morning) -> Blocked
    early_monday = datetime.datetime(2026, 11, 16, 5, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    with patch("datetime.datetime") as mock_dt, patch("requests.post") as mock_post:
        mock_dt.now.return_value = early_monday
        res = dispatcher.send_regime_flip_alert("BEARISH", regime_info, snapshot)
        assert res is False
        assert mock_post.call_count == 0

    # Case 2: Sunday afternoon -> Blocked
    sunday = datetime.datetime(2026, 11, 15, 14, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    with patch("datetime.datetime") as mock_dt, patch("requests.post") as mock_post:
        mock_dt.now.return_value = sunday
        res = dispatcher.send_regime_flip_alert("BEARISH", regime_info, snapshot)
        assert res is False
        assert mock_post.call_count == 0

    # Case 3: Tuesday 10:30 AM IST -> Allowed
    market_hours = datetime.datetime(2026, 11, 17, 10, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    with patch("datetime.datetime") as mock_dt, patch("requests.post", return_value=MagicMock(status_code=200)) as mock_post:
        mock_dt.now.return_value = market_hours
        res = dispatcher.send_regime_flip_alert("BEARISH", regime_info, snapshot)
        assert res is True
        assert mock_post.call_count >= 1

