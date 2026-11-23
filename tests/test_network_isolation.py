import socket
import pytest
import requests
import httpx
from finplus_index_breadth.notifications.network_guard import NetworkBlockedError
from finplus_index_breadth.notifications.ntfy_dispatcher import NTFYDispatcher

def test_outbound_socket_strictly_blocked():
    """Verify that any attempt to open an external socket raises NetworkBlockedError."""
    s = socket.socket()
    with pytest.raises(NetworkBlockedError):
        s.connect(("8.8.8.8", 53))

def test_outbound_requests_strictly_blocked():
    """Verify that any unmocked requests call raises NetworkBlockedError."""
    with pytest.raises(NetworkBlockedError):
        requests.get("https://ntfy.sh/test", timeout=1)

def test_outbound_httpx_strictly_blocked():
    """Verify that any unmocked httpx call raises NetworkBlockedError."""
    with pytest.raises(NetworkBlockedError):
        httpx.get("https://api.indstocks.com/test", timeout=1)

def test_ntfy_dispatcher_returns_immediately_in_test(monkeypatch):
    """Verify NTFYDispatcher.send_notification returns False without any network call when FINPLUS_ENV=test."""
    monkeypatch.setenv("FINPLUS_ENV", "test")
    monkeypatch.setenv("RENDER", "true")
    dispatcher = NTFYDispatcher()
    sent = dispatcher.send_notification("Test Title", "Test Message")
    assert sent is False
