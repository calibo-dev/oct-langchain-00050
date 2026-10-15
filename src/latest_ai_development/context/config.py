"""Load optional context configuration without changing existing applications."""

from __future__ import annotations

from pathlib import Path

from latest_ai_development.context.runtime import ContextRuntime
from latest_ai_development.context.schema import ContextConfiguration
from latest_ai_development.core.settings import CONFIG_DIR, load_yaml_file


def load_context_configuration(path: Path | None = None) -> ContextRuntime | None:
    """Disable context when the file is absent or explicitly disabled."""
    config_path = path if path is not None else CONFIG_DIR / "context.yml"
    if not config_path.exists():
        return None
    configuration = ContextConfiguration.model_validate(load_yaml_file(config_path))
    if not configuration.runtime_context.enabled:
        return None
    return ContextRuntime(configuration.runtime_context)
