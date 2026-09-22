"""Pydantic schemas for dynamically configured Snowflake tools."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from latest_ai_development.tools.schema import BaseToolDefinition


class SnowflakeToolDefinition(BaseToolDefinition):
    """One Snowflake tool mapped to a reusable connection by name."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    connector: Literal["snowflake"]


__all__ = ["SnowflakeToolDefinition"]
