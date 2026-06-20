"""Persona binding and resolution logic."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from astrbot.api import logger


class PersonaManager:
    """Manage persona-preset bindings and persona lookups."""

    def __init__(self, data_dir: Path, cfg_getter, persona_mgr_getter) -> None:
        self._data_dir = data_dir
        self._cfg_getter = cfg_getter
        self._persona_mgr_getter = persona_mgr_getter
        self._legacy_file = data_dir / "persona_presets.json"

    def persona_preset_config_key(self) -> str:
        return "persona_preset_bindings"

    def load_bindings(self) -> dict[str, dict[str, Any]]:
        raw: Any = self._cfg_getter().get(self.persona_preset_config_key(), [])
        raw_bindings: Any = raw
        if isinstance(raw, dict):
            raw_bindings = raw.get("bindings") if "bindings" in raw else raw

        bindings: dict[str, dict[str, Any]] = {}
        if isinstance(raw_bindings, list):
            for entry in raw_bindings:
                if not isinstance(entry, dict):
                    continue
                persona_key = self._normalize_ref(
                    entry.get("persona_id") or entry.get("persona") or entry.get("id")
                )
                if not persona_key:
                    continue
                name = str(entry.get("name") or "").strip()
                slug = str(entry.get("slug") or "").strip()
                if not name and not slug:
                    continue
                bindings[persona_key] = {"name": name, "slug": slug}
        elif isinstance(raw_bindings, dict):
            for persona_id, preset in raw_bindings.items():
                persona_key = self._normalize_ref(persona_id)
                if not persona_key:
                    continue
                if isinstance(preset, dict):
                    name = str(preset.get("name") or "").strip()
                    slug = str(preset.get("slug") or "").strip()
                else:
                    name = str(preset or "").strip()
                    slug = ""
                if not name and not slug:
                    continue
                bindings[persona_key] = {"name": name, "slug": slug}

        if not bindings and self._legacy_file.exists():
            try:
                data = json.loads(self._legacy_file.read_text(encoding="utf-8"))
                legacy_bindings = data.get("bindings") if isinstance(data, dict) else data
                if isinstance(legacy_bindings, list):
                    for entry in legacy_bindings:
                        if not isinstance(entry, dict):
                            continue
                        persona_key = self._normalize_ref(
                            entry.get("persona_id") or entry.get("persona") or entry.get("id")
                        )
                        if not persona_key:
                            continue
                        name = str(entry.get("name") or "").strip()
                        slug = str(entry.get("slug") or "").strip()
                        if not name and not slug:
                            continue
                        bindings[persona_key] = {"name": name, "slug": slug}
                elif isinstance(legacy_bindings, dict):
                    for persona_id, preset in legacy_bindings.items():
                        persona_key = self._normalize_ref(persona_id)
                        if not persona_key:
                            continue
                        if isinstance(preset, dict):
                            name = str(preset.get("name") or "").strip()
                            slug = str(preset.get("slug") or "").strip()
                        else:
                            name = str(preset or "").strip()
                            slug = ""
                        if not name and not slug:
                            continue
                        bindings[persona_key] = {"name": name, "slug": slug}
                if bindings:
                    self.save_bindings(bindings)
            except Exception:
                logger.debug("[传话筒] 读取旧版人格预设绑定失败", exc_info=True)
        return bindings

    def save_bindings(self, bindings: dict[str, dict[str, Any]]) -> None:
        try:
            payload_bindings: list[dict[str, Any]] = []
            for persona_id in sorted(bindings.keys()):
                entry = bindings.get(persona_id) or {}
                cleaned_entry = {
                    "persona_id": str(persona_id).strip(),
                    "name": str(entry.get("name") or "").strip(),
                    "slug": str(entry.get("slug") or "").strip(),
                }
                cleaned_entry = {k: v for k, v in cleaned_entry.items() if v}
                if cleaned_entry.get("persona_id"):
                    payload_bindings.append(cleaned_entry)
            payload: list[dict[str, Any]] = payload_bindings
            cfg = self._cfg_getter()
            if hasattr(cfg, "__setitem__"):
                cfg[self.persona_preset_config_key()] = payload
                if hasattr(cfg, "save_config"):
                    try:
                        cfg.save_config()
                    except Exception:
                        logger.debug("[传话筒] 保存配置失败", exc_info=True)
        except Exception:
            logger.debug("[传话筒] 保存人格预设绑定失败", exc_info=True)

    def _normalize_ref(self, persona_ref: str | None) -> str:
        if not persona_ref:
            return ""
        return str(persona_ref).strip().lower()

    def normalize_binding_id(self, persona_ref: str | None) -> str:
        return self._normalize_ref(persona_ref)

    def get_persona_record(self, persona_ref: str) -> Any:
        persona_key = self._normalize_ref(persona_ref)
        if not persona_key:
            return None
        try:
            persona_mgr = self._persona_mgr_getter()
            if not persona_mgr:
                return None
            getter = getattr(persona_mgr, "get_persona_v3_by_id", None)
            if callable(getter):
                try:
                    return getter(persona_key)
                except Exception:
                    pass
            for attr in ("personas", "all_personas", "list_personas"):
                container = getattr(persona_mgr, attr, None)
                if container:
                    try:
                        if isinstance(container, dict):
                            for k, v in container.items():
                                if str(k).lower() == persona_key:
                                    return v
                        else:
                            for item in container:
                                pid = getattr(item, "id", None) or getattr(item, "persona_id", None)
                                if pid and str(pid).lower() == persona_key:
                                    return item
                    except Exception:
                        continue
        except Exception:
            pass
        return None

    def display_name(self, persona_ref: str | None) -> str:
        persona_key = self._normalize_ref(persona_ref)
        if not persona_key:
            return ""
        persona = self.get_persona_record(persona_key)
        if persona:
            for attr in ("name", "title", "display_name"):
                val = getattr(persona, attr, None)
                if val:
                    return str(val)
            if isinstance(persona, dict):
                for key in ("name", "title", "display_name"):
                    if key in persona and persona[key]:
                        return str(persona[key])
        return persona_key
