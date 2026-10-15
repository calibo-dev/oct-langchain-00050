"""Store and retrieve runtime LangChain agents."""

from __future__ import annotations

from collections.abc import Mapping

from latest_ai_development.agents.runtime import AgentRuntime


class AgentRegistry:
    """Read-only lookup for agents created during application startup."""

    def __init__(self, agents: Mapping[str, AgentRuntime]) -> None:
        self._agents = dict(agents)

    def get(self, name: str) -> AgentRuntime:
        """Return a runtime agent by its configured name."""
        try:
            return self._agents[name]
        except KeyError as exc:
            raise KeyError(f"Agent '{name}' is not available") from exc

    def count(self) -> int:
        """Return the number of available runtime agents."""
        return len(self._agents)


__all__ = ["AgentRegistry"]
