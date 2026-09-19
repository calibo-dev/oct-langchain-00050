"""Shared protocol implemented by connector-specific connection managers."""

from __future__ import annotations

from typing import Protocol


class ConnectionManager(Protocol):
    """Minimal lifecycle interface required by the connection registry."""

    def close(self) -> None:
        """Close every cached connection."""
        ...
