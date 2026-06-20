"""Core configuration access and basic helpers."""

from __future__ import annotations

from typing import Any, Dict, Optional

from astrbot.api import AstrBotConfig


class ConfigAccessor:
    """Safe typed access to AstrBotConfig."""

    def __init__(self, config: Optional[AstrBotConfig] = None) -> None:
        self._config = config or {}

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self._config.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self._config.get(key, default))
        except (TypeError, ValueError):
            return default

    def get_str(self, key: str, default: str = "") -> str:
        value = self._config.get(key, default)
        return str(value) if value is not None else default

    def get_dict(self, key: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        value = self._config.get(key, default or {})
        return value if isinstance(value, dict) else (default or {})

    def raw(self) -> Dict[str, Any]:
        return dict(self._config) if hasattr(self._config, "keys") else {}
