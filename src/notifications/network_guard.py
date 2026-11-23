"""
Institutional Network Isolation Guard for FinPlus Ecosystem.
Ensures zero test leakage to external networks, brokers, webhooks, or notification sinks.
"""

class NetworkBlockedError(RuntimeError):
    """Raised when an unauthorized outbound network call is attempted during testing."""
    pass
