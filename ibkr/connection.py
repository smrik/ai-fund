"""
Alpha Pod — IBKR Connection Manager
Handles connection lifecycle with ib_insync.
"""
from ib_insync import IB
from config.settings import IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID


class IBKRConnection:
    """Manages IBKR TWS/Gateway connection."""

    def __init__(self):
        self.ib = IB()

    def connect(self) -> IB:
        """Connect to TWS or IB Gateway. Returns the IB instance."""
        if not self.ib.isConnected():
            self.ib.connect(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT_ID)
            print(f"✓ Connected to IBKR at {IBKR_HOST}:{IBKR_PORT}")
        return self.ib

    def disconnect(self):
        """Disconnect gracefully."""
        if self.ib.isConnected():
            self.ib.disconnect()
            print("✓ Disconnected from IBKR")

    def __enter__(self):
        self.connect()
        return self.ib

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False


# Convenience: use as context manager
# with IBKRConnection() as ib:
#     positions = ib.positions()
