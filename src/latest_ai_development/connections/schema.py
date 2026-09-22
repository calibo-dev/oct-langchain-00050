"""Connector-neutral configuration types; concrete schemas belong to plugins."""

from pydantic import BaseModel

type ConnectionConfiguration = BaseModel
type ConnectionConfigurations = dict[str, ConnectionConfiguration]
