"""YAML configuration loader with environment variable substitution.

Loads `configs/config.yaml` relative to the project root.
Supports `${VAR}` and `${VAR:default}` substitution from os.environ.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

__all__ = ["load_config", "Config"]


# Pattern: ${VAR} or ${VAR:default}
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}")


def _sub_env(value: str) -> str:
    """Substitute ${VAR} and ${VAR:default} in a string."""
    def replacer(m: re.Match) -> str:
        var_name = m.group(1)
        default = m.group(2)
        return os.environ.get(var_name, default if default is not None else m.group(0))
    return _ENV_PATTERN.sub(replacer, value)


def _walk_sub(v: Any) -> Any:
    """Recursively substitute env vars in a YAML structure."""
    if isinstance(v, str):
        return _sub_env(v)
    if isinstance(v, dict):
        return {k: _walk_sub(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_walk_sub(item) for item in v]
    return v


def _find_config() -> Path:
    """Find the config file.

    Searches (in order):
    1. LUSTRE_CONFIG environment variable
    2. ./configs/config.yaml (CWD)
    3. ./configs/config.example.yaml (CWD, fallback for dev)
    4. ~/.lustre/config.yaml
    """
    if env_path := os.environ.get("LUSTRE_CONFIG"):
        p = Path(env_path)
        if p.exists():
            return p

    for name in ("configs/config.yaml", "configs/config.example.yaml"):
        p = Path(name)
        if p.exists():
            return p

    home_config = Path.home() / ".lustre" / "config.yaml"
    if home_config.exists():
        return home_config

    raise FileNotFoundError(
        "config not found. Set LUSTRE_CONFIG env var, "
        "place config at ./configs/config.yaml or ~/.lustre/config.yaml"
    )


class Config:
    """Loaded and validated configuration.

    Accessed as e.g. `config.agents["code"]["model_name"]`.
    """

    __slots__ = ("_raw", "_system", "_agents", "_message_bus", "_tools")

    def __init__(self, data: dict[str, Any]) -> None:
        self._raw = data
        self._system: dict[str, Any] | None = None
        self._agents: dict[str, Any] | None = None
        self._message_bus: dict[str, Any] | None = None
        self._tools: dict[str, Any] | None = None

    def __getitem__(self, key: str) -> Any:
        return self._raw[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._raw.get(key, default)

    @property
    def system(self) -> dict[str, Any]:
        if self._system is None:
            self._system = self._raw.get("system", {})
        return self._system

    @property
    def agents(self) -> dict[str, Any]:
        if self._agents is None:
            self._agents = self._raw.get("agents", {})
        return self._agents

    @property
    def message_bus(self) -> dict[str, Any]:
        if self._message_bus is None:
            self._message_bus = self._raw.get("message_bus", {})
        return self._message_bus

    @property
    def tools(self) -> dict[str, Any]:
        if self._tools is None:
            self._tools = self._raw.get("tools", {})
        return self._tools

    @property
    def version(self) -> str:
        return self.system.get("version", "0.0.0")


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_config: Config | None = None


def load_config() -> Config:
    """Load and return the singleton Config object."""
    global _config
    if _config is None:
        path = _find_config()
        with open(path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        _config = Config(_walk_sub(raw))
    return _config


def reload_config() -> Config:
    """Force reload the configuration (useful in tests)."""
    global _config
    _config = None
    return load_config()
