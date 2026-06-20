"""Core configuration mixin — init helpers, cfg, data dir."""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from astrbot.api import AstrBotConfig, logger
from astrbot.api.star import StarTools

from models import DEFAULT_PROMPT_TEMPLATE


class ConfigMixin:
    """Mixin providing core config access and data directory resolution."""

    def cfg(self) -> Dict[str, Any]:
        try:
            return self._cfg_obj if isinstance(self._cfg_obj, dict) else (self._cfg_obj or {})
        except Exception:
            return {}

    def _cfg_bool(self, key: str, default: bool) -> bool:
        val = self.cfg().get(key, default)
        return bool(val) if not isinstance(val, str) else val.lower() in {"1", "true", "yes", "on"}

    def _resolve_data_dir(self) -> Path:
        """优先使用 StarTools 数据目录，失败时退回到 AstrBot/data/plugin_data 下。"""
        fallback_dir = self._base_dir.parent.parent / "plugin_data" / self.PLUGIN_ID
        try:
            preferred_raw = StarTools.get_data_dir(self.PLUGIN_ID)
        except Exception:
            preferred_raw = None
        if preferred_raw:
            preferred_path = Path(preferred_raw)
            try:
                preferred_path.mkdir(parents=True, exist_ok=True)
                return preferred_path
            except Exception as exc:
                logger.warning(
                    "[传话筒] 创建数据目录失败(%s)，退回 fallback：%s", exc, fallback_dir
                )
        fallback_dir.mkdir(parents=True, exist_ok=True)
        return fallback_dir

    def _ensure_prompt_template(self):
        if not isinstance(self._cfg_obj, dict):
            return
        template = self._cfg_obj.get("emotion_prompt_template")
        if template:
            return
        self._cfg_obj["emotion_prompt_template"] = DEFAULT_PROMPT_TEMPLATE
        saver = getattr(self._cfg_obj, "save_config", None)
        if callable(saver):
            try:
                saver()
            except Exception as exc:
                logger.debug("[传话筒] 写入默认情绪提示失败: %s", exc)

    def _load_current_preset_meta(self) -> dict[str, Any]:
        if not self._current_preset_file.exists():
            return {}
        try:
            return json.loads(self._current_preset_file.read_text(encoding="utf-8"))
        except Exception:
            logger.debug("[传话筒] 读取当前预设记录失败", exc_info=True)
            return {}

    def _remember_current_preset(self, record: Optional[dict[str, Any]]):
        if not record:
            self._current_preset_meta = {}
            try:
                if self._current_preset_file.exists():
                    self._current_preset_file.unlink()
            except Exception:
                logger.debug("[传话筒] 清理当前预设记录失败", exc_info=True)
            return
        payload = {
            "name": record.get("name"),
            "slug": record.get("slug"),
            "saved_at": record.get("saved_at"),
        }
        self._current_preset_meta = payload
        try:
            self._current_preset_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            logger.debug("[传话筒] 写入当前预设记录失败", exc_info=True)

    def _current_preset_name(self) -> str:
        return str(self._current_preset_meta.get("name") or "")

    def _bot_name(self) -> str:
        try:
            layout = self._layout()
            name = layout.get("bot_name")
        except Exception:
            name = None
        name = str(name or "传话筒").strip()
        return name or "传话筒"
