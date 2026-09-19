"""Store and retrieve runtime connection managers."""

from __future__ import annotations

from collections.abc import Mapping

from latest_ai_development.connections.base import ConnectionManager


class ConnectionRegistry:
    """Read-only lookup for connector-specific connection managers."""

    def __init__(self, managers: Mapping[str, ConnectionManager]) -> None:
        self._managers = {
            provider.strip().lower(): manager for provider, manager in managers.items()
        }

    def get(self, connector: str) -> ConnectionManager:
        """Return the manager for a connector."""
        try:
            return self._managers[connector.strip().lower()]
        except KeyError as exc:
            raise KeyError(f"Connection connector '{connector}' is not available") from exc

    def close(self) -> None:
        """Close resources held by every connection manager."""
        for manager in self._managers.values():
            manager.close()


__all__ = ["ConnectionRegistry"]
