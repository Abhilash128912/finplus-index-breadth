import os
import sys
import socket
from pathlib import Path
import pytest

_ROOT = Path(__file__).resolve().parent.parent
_AI_APPS = _ROOT.parent
_SRC = _ROOT / "src"

for p in [_AI_APPS, _ROOT, _SRC]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from finplus_index_breadth.notifications.network_guard import NetworkBlockedError

# Mandatory environment variables for test isolation
os.environ["FINPLUS_ENV"] = "test"
os.environ["FINPLUS_ENVIRONMENT"] = "test"

# Unset external service credentials and webhooks
_VARS_TO_UNSET = [
    "GOOGLE_SHEET_WEBHOOK_URL",
    "GSHEET_WEBHOOK_URL",
    "NTFY_TOPIC",
    "NTFY_SERVER",
    "NTFY_TOKEN",
    "NTFY_AUTH_TOKEN",
    "NTFY_BASE_URL",
    "FIREBASE_CREDENTIALS_JSON",
    "FIREBASE_CREDENTIALS_PATH",
    "FIRESTORE_PROJECT_ID",
    "INDMONEY_CLIENT_ID",
    "INDMONEY_MPIN",
    "INDMONEY_TOTP_SECRET",
    "INDMONEY_ACCESS_TOKEN",
    "DELTA_API_KEY",
    "DELTA_API_SECRET"
]
for _v in _VARS_TO_UNSET:
    os.environ.pop(_v, None)

@pytest.fixture(autouse=True)
def network_isolation_guard(monkeypatch):
    """
    Autouse fixture that:
    1. Blocks all outbound network calls (socket.connect, requests, httpx).
    2. Unsets NTFY, GOOGLE_SHEET_WEBHOOK_URL, FIRESTORE, INDMONEY, and DELTA env vars.
    3. Sets FINPLUS_ENV=test and FINPLUS_ENVIRONMENT=test.
    """
    monkeypatch.setenv("FINPLUS_ENV", "test")
    monkeypatch.setenv("FINPLUS_ENVIRONMENT", "test")
    for v in _VARS_TO_UNSET:
        monkeypatch.delenv(v, raising=False)

    # 1. Patch socket.socket.connect (allowing loopback for local asyncio pipes on Windows)
    orig_socket_connect = socket.socket.connect
    def blocked_socket_connect(self, address):
        if isinstance(address, tuple) and len(address) >= 1:
            if address[0] in ("127.0.0.1", "localhost", "::1"):
                return orig_socket_connect(self, address)
        raise NetworkBlockedError(f"Outbound socket connection blocked during test: {address}")
    monkeypatch.setattr(socket.socket, "connect", blocked_socket_connect)

    # 2. Patch requests.Session.send
    try:
        import requests
        def blocked_requests_send(self, request, **kwargs):
            raise NetworkBlockedError(f"Outbound requests call blocked during test: {request.url}")
        monkeypatch.setattr(requests.Session, "send", blocked_requests_send)
    except ImportError:
        pass

    # 3. Patch httpx.Client.send (allowing TestClient ASGITransport with testserver host)
    try:
        import httpx
        orig_httpx_send = httpx.Client.send
        def blocked_httpx_send(self, request, **kwargs):
            transport_cls = type(getattr(self, "_transport", None)).__name__
            if "TestClient" in transport_cls or request.url.host == "testserver":
                return orig_httpx_send(self, request, **kwargs)
            raise NetworkBlockedError(f"Outbound httpx call blocked during test: {request.url}")
        monkeypatch.setattr(httpx.Client, "send", blocked_httpx_send)
    except ImportError:
        pass

    yield
