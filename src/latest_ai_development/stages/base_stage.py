from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseStage(ABC):
    """
    Base class for all workflow stages.

    Enforces a consistent interface for stage execution.
    """

    @abstractmethod
    def invoke(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """
        Execute the stage.

        Each stage must implement this method.
        """
        pass
