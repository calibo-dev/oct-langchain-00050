"""Store and retrieve runtime LangChain tools."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


class ToolRegistry:
    """Read-only lookup for tools created during application startup."""

    def __init__(self, tools: Mapping[str, Any]) -> None:
        self._tools = dict(tools)

    def get(self, names: Iterable[str]) -> tuple[Any, ...]:
        """Return runtime tools in the requested order."""
        try:
            return tuple(self._tools[name] for name in names)
        except KeyError as exc:
            raise KeyError(f"Tool '{exc.args[0]}' is not available") from exc

    def contains(self, name: str) -> bool:
        """Return whether a runtime tool is available."""
        return name in self._tools

    def count(self) -> int:
        """Return the number of available runtime tools."""
        return len(self._tools)


__all__ = ["ToolRegistry"]
