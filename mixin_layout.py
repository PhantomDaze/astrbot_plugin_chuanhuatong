"""Layout, preset, persona, and session management mixin for 传话筒 plugin."""

import copy
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.provider import ProviderRequest

from models import DEFAULT_LAYOUT


class LayoutMixin:
    """Mixin providing layout normalization, preset management,
    persona bindings, and session-specific layout handling."""

    PLUGIN_ID: str = ""
    DEFAULT_LAYOUT = DEFAULT_LAYOUT

    # ------------------------------------------------------------------
    # Layout normalization
    # ------------------------------------------------------------------

    def _normalize_layout(self, layout: Dict[str, Any]) -> Dict[str, Any]:
        data = copy.deepcopy(self.DEFAULT_LAYOUT)
        for key, value in (layout or {}).items():
            if key == "text_overlays":
                continue
            if key in data and value is not None:
                data[key] = value
        data["text_overlays"] = self._normalize_overlays((layout or {}).get("text_overlays"))
        if "background_group" not in data or not data.get("background_group"):
            data["background_group"] = "__auto__"
        if "character_fit_mode" not in data or not data.get("character_fit_mode"):
            data["character_fit_mode"] = "fixed_width"
        if "character_uniform_height" not in data:
            data["character_uniform_height"] = 620
        if "character_align_bottom" not in data:
            data["character_align_bottom"] = True
        if "character_top" not in data:
            data["character_top"] = 0
        return data

    def _convert_legacy_layout(self, legacy: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(legacy, dict) or not legacy:
            return copy.deepcopy(self.DEFAULT_LAYOUT)
        data = copy.deepcopy(self.DEFAULT_LAYOUT)
        for key in data.keys():
            if key in legacy and legacy[key] is not None:
                data[key] = legacy[key]
        data["text_overlays"] = legacy.get("text_overlays", [])
        return data

    def _normalize_overlays(self, overlays_raw) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        if not isinstance(overlays_raw, list):
            overlays_raw = []
        for item in overlays_raw:
            if not isinstance(item, dict):
                continue
            overlay_id = str(item.get("id") or uuid4().hex)
            layer_type = str(item.get("type", "text")).lower()
            if layer_type == "converted_text":
                layer_type = "text"
            if layer_type not in {"text", "image", "glass"}:
                layer_type = "text"
            try:
                left = int(float(item.get("left", 0)))
                top = int(float(item.get("top", 0)))
                width = max(20, int(float(item.get("width", 200))))
                height = max(20, int(float(item.get("height", 60))))
                font_size = max(8, int(float(item.get("font_size", 28))))
                stroke_width = max(0, int(float(item.get("stroke_width", 0))))
                z_index = int(item.get("z_index", 300))
            except Exception:
                left, top, width, height, font_size, stroke_width, z_index = 0, 0, 200, 60, 28, 0, 300
            color = str(item.get("color") or "#FFFFFF")
            stroke_color = str(item.get("stroke_color") or "#000000")
            bold = bool(item.get("bold", True))
            visible = bool(item.get("visible", True))
            opacity = float(item.get("opacity", 1.0))
            image_name = str(item.get("image") or "").strip()
            font_name = str(item.get("font") or "").strip()
            normalized.append(
                {
                    "id": overlay_id,
                    "type": layer_type,
                    "text": str(item.get("text", "")).strip(),
                    "image": image_name,
                    "font": font_name,
                    "left": left,
                    "top": top,
                    "width": width,
                    "height": height,
                    "font_size": font_size,
                    "color": color,
                    "stroke_width": stroke_width,
                    "stroke_color": stroke_color,
                    "bold": bold,
                    "z_index": z_index,
                    "visible": visible,
                    "opacity": max(0.0, min(1.0, opacity)),
                }
            )
        return normalized

    # ------------------------------------------------------------------
    # Global layout state
    # ------------------------------------------------------------------

    def _load_layout_state(self) -> Dict[str, Any]:
        if self._layout_file.exists():
            try:
                data = json.loads(self._layout_file.read_text(encoding="utf-8"))
                return self._normalize_layout(data)
            except Exception:
                logger.warning("[传话筒] 无法读取自定义布局，使用默认布局。")
        legacy = self.cfg().get("text_layout") or {}
        state = self._normalize_layout(self._convert_legacy_layout(legacy))
        self._save_layout_state(state)
        return state

    def _save_layout_state(self, layout: Dict[str, Any]):
        try:
            self._layout_file.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.error("[传话筒] 写入布局文件失败: %s", exc)

    def _reset_layout_state(self) -> Dict[str, Any]:
        state = self._normalize_layout(copy.deepcopy(self.DEFAULT_LAYOUT))
        self._save_layout_state(state)
        self._layout_state = state
        return state

    def _set_layout_state(self, layout: Dict[str, Any]):
        normalized = self._normalize_layout(layout)
        self._layout_state = normalized
        self._save_layout_state(normalized)

    # ------------------------------------------------------------------
    # Session layout
    # ------------------------------------------------------------------

    def _session_layout_file(self, session_id: str) -> Path:
        import hashlib
        safe_id = hashlib.md5(session_id.encode('utf-8')).hexdigest()
        return self._session_layouts_dir / f"{safe_id}.json"

    def _load_session_layout(self, session_id: str) -> Optional[Dict[str, Any]]:
        layout_file = self._session_layout_file(session_id)
        if not layout_file.exists():
            return None
        try:
            data = json.loads(layout_file.read_text(encoding="utf-8"))
            preset_name = data.get("_preset_name")
            normalized = self._normalize_layout(data)
            if preset_name:
                normalized["_preset_name"] = preset_name
            return normalized
        except Exception:
            logger.debug("[传话筒] 读取会话布局失败: %s", session_id, exc_info=True)
            return None

    def _save_session_layout(self, session_id: str, layout: Dict[str, Any], preset_name: Optional[str] = None):
        layout_file = self._session_layout_file(session_id)
        try:
            normalized = self._normalize_layout(layout)
            if preset_name:
                normalized["_preset_name"] = preset_name
            layout_file.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("[传话筒] 已保存会话布局: %s", session_id)
        except Exception as exc:
            logger.error("[传话筒] 保存会话布局失败: %s", exc)

    def _has_session_layout(self, session_id: str) -> bool:
        layout_file = self._session_layout_file(session_id)
        return layout_file.exists()

    # ------------------------------------------------------------------
    # Preset management
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_preset_name(name: str) -> str:
        name = str(name or "").strip()
        return re.sub(r"\s+", " ", name)

    def _preset_slug(self, name: str) -> str:
        base = re.sub(r"[^0-9a-zA-Z_-]+", "-", name.strip().lower())
        base = base.strip("-_")[:60]
        return base or uuid4().hex

    def _preset_file(self, slug: str) -> Path:
        safe = re.sub(r"[^0-9a-zA-Z_-]+", "-", slug.strip().lower()) or uuid4().hex
        return self._presets_dir / f"{safe}.json"

    def _read_preset_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            if not isinstance(data.get("layout"), dict):
                return None
            data.setdefault("name", file_path.stem)
            data.setdefault("slug", file_path.stem)
            data["_path"] = file_path
            return data
        except Exception:
            logger.warning("[传话筒] 读取预设文件失败: %s", file_path)
            return None

    def _list_presets(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        try:
            for file_path in sorted(self._presets_dir.glob("*.json")):
                record = self._read_preset_file(file_path)
                if not record:
                    continue
                records.append({
                    "name": record.get("name"),
                    "slug": record.get("slug"),
                    "saved_at": record.get("saved_at"),
                })
        except Exception as exc:
            logger.debug("[传话筒] 列出预设失败: %s", exc)
        return records

    def _find_preset(self, identifier: str) -> Optional[Dict[str, Any]]:
        key = str(identifier or "").strip().lower()
        if not key:
            return None
        direct = self._preset_file(key)
        if direct.exists():
            record = self._read_preset_file(direct)
            if record:
                return record
        for file_path in self._presets_dir.glob("*.json"):
            record = self._read_preset_file(file_path)
            if not record:
                continue
            slug = str(record.get("slug") or "").lower()
            name = str(record.get("name") or "").lower()
            if key in {slug, name}:
                return record
        return None

    def _save_preset(self, name: str, layout: Dict[str, Any]) -> dict[str, Any]:
        cleaned_name = self._sanitize_preset_name(name)
        normalized = self._normalize_layout(layout)
        existing = self._find_preset(cleaned_name)
        slug = (existing or {}).get("slug") or self._preset_slug(cleaned_name or uuid4().hex)
        path = self._preset_file(slug)
        payload = {
            "name": cleaned_name or slug,
            "slug": slug,
            "saved_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "layout": normalized,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def _load_preset(self, identifier: str) -> Optional[Dict[str, Any]]:
        record = self._find_preset(identifier)
        if not record:
            return None
        layout = self._normalize_layout(record.get("layout") or {})
        return {
            "name": record.get("name"),
            "slug": record.get("slug"),
            "saved_at": record.get("saved_at"),
            "layout": layout,
        }

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
            self._current_preset_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            logger.debug("[传话筒] 写入当前预设记录失败", exc_info=True)

    def _current_preset_name(self) -> str:
        return str(self._current_preset_meta.get("name") or "")

    def _format_preset_list_message(self) -> str:
        presets = self._list_presets()
        current_name = self._current_preset_name()
        current_slug = str(self._current_preset_meta.get("slug") or "")
        lines = ["预设列表："]
        if current_name:
            lines.append(f"当前预设：{current_name}")
        else:
            lines.append("当前预设：自定义布局（未绑定预设）")
        if not presets:
            lines.append("暂未保存任何预设。")
            return "\n".join(lines)
        lines.append("可用预设：")
        for idx, info in enumerate(presets, start=1):
            name = str(info.get("name") or "").strip() or "未命名预设"
            slug = str(info.get("slug") or "").strip()
            marker = "（当前）" if slug and slug == current_slug else ""
            updated = str(info.get("saved_at") or "").strip()
            lines.append(f"{idx}. {name}{marker}" + (f" - {updated}" if updated else ""))
        lines.append("使用 /切换预设 预设名称 即可切换。")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Persona management
    # ------------------------------------------------------------------

    def _persona_preset_config_key(self) -> str:
        return "persona_preset_bindings"

    def _load_persona_preset_bindings(self) -> dict[str, dict[str, Any]]:
        raw = self.cfg().get(self._persona_preset_config_key(), [])
        raw_bindings = raw
        if isinstance(raw, dict):
            raw_bindings = raw.get("bindings") if "bindings" in raw else raw

        bindings: dict[str, dict[str, Any]] = {}
        if isinstance(raw_bindings, list):
            for entry in raw_bindings:
                if not isinstance(entry, dict):
                    continue
                persona_key = self._normalize_persona_ref(entry.get("persona_id") or entry.get("persona") or entry.get("id"))
                if not persona_key:
                    continue
                name = str(entry.get("name") or "").strip()
                slug = str(entry.get("slug") or "").strip()
                if not name and not slug:
                    continue
                bindings[persona_key] = {"name": name, "slug": slug}
        elif isinstance(raw_bindings, dict):
            for persona_id, preset in raw_bindings.items():
                persona_key = self._normalize_persona_ref(persona_id)
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

        legacy_file = self._data_dir / "persona_presets.json"
        if not bindings and legacy_file.exists():
            try:
                data = json.loads(legacy_file.read_text(encoding="utf-8"))
                legacy_bindings = data.get("bindings") if isinstance(data, dict) else data
                if isinstance(legacy_bindings, list):
                    for entry in legacy_bindings:
                        if not isinstance(entry, dict):
                            continue
                        persona_key = self._normalize_persona_ref(entry.get("persona_id") or entry.get("persona") or entry.get("id"))
                        if not persona_key:
                            continue
                        name = str(entry.get("name") or "").strip()
                        slug = str(entry.get("slug") or "").strip()
                        if not name and not slug:
                            continue
                        bindings[persona_key] = {"name": name, "slug": slug}
                elif isinstance(legacy_bindings, dict):
                    for persona_id, preset in legacy_bindings.items():
                        persona_key = self._normalize_persona_ref(persona_id)
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
                    self._save_persona_preset_bindings(bindings)
            except Exception:
                logger.debug("[传话筒] 读取旧版人格预设绑定失败", exc_info=True)
        return bindings

    def _save_persona_preset_bindings(self, bindings: dict[str, dict[str, Any]]):
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
            payload = payload_bindings
            if isinstance(self._cfg_obj, AstrBotConfig):
                self._cfg_obj[self._persona_preset_config_key()] = payload
                if hasattr(self._cfg_obj, "save_config"):
                    try:
                        self._cfg_obj.save_config()
                    except Exception:
                        pass
            elif isinstance(self._cfg_obj, dict):
                self._cfg_obj[self._persona_preset_config_key()] = payload
        except Exception as exc:
            logger.error("[传话筒] 保存人格预设绑定失败: %s", exc)

    @staticmethod
    def _normalize_persona_ref(persona_ref) -> str:
        return str(persona_ref or "").strip()

    def _get_persona_manager_record(self, persona_ref: str):
        persona_key = self._normalize_persona_ref(persona_ref)
        if not persona_key:
            return None
        persona_mgr = getattr(self.context, "persona_manager", None)
        if persona_mgr is None:
            return None
        getter = getattr(persona_mgr, "get_persona_v3_by_id", None)
        if callable(getter):
            try:
                persona = getter(persona_key)
                if persona:
                    return persona
            except Exception:
                logger.debug("[传话筒] 通过 ID 读取人格失败: %s", persona_key, exc_info=True)
        personas = getattr(persona_mgr, "personas_v3", None) or []
        for persona in personas:
            try:
                if isinstance(persona, dict):
                    candidate_id = str(persona.get("persona_id") or "").strip()
                    candidate_name = str(persona.get("name") or "").strip()
                else:
                    candidate_id = str(getattr(persona, "persona_id", "") or "").strip()
                    candidate_name = str(getattr(persona, "name", "") or "").strip()
                if persona_key in {candidate_id, candidate_name}:
                    return persona
            except Exception:
                continue
        return None

    def _persona_display_name(self, persona_ref) -> str:
        persona_key = self._normalize_persona_ref(persona_ref)
        if not persona_key:
            return ""
        persona = self._get_persona_manager_record(persona_key)
        if persona is None:
            return persona_key
        try:
            if isinstance(persona, dict):
                return str(persona.get("name") or persona.get("persona_id") or persona_key)
            return str(getattr(persona, "name", None) or getattr(persona, "persona_id", None) or persona_key)
        except Exception:
            return persona_key

    def _list_personas(self) -> list[dict[str, Any]]:
        personas: list[dict[str, Any]] = [
            {"id": "default", "label": "默认人格 (default)"}
        ]
        seen = {"default"}
        persona_mgr = getattr(self.context, "persona_manager", None)
        records = []
        if persona_mgr is not None:
            records = list(getattr(persona_mgr, "personas_v3", []) or [])
        for persona in records:
            try:
                if isinstance(persona, dict):
                    persona_id = str(persona.get("persona_id") or persona.get("name") or "").strip()
                    label = str(persona.get("name") or persona_id or "").strip() or persona_id
                else:
                    persona_id = str(getattr(persona, "persona_id", "") or getattr(persona, "name", "") or "").strip()
                    label = str(getattr(persona, "name", None) or persona_id or "").strip() or persona_id
            except Exception:
                continue
            if not persona_id or persona_id in seen:
                continue
            seen.add(persona_id)
            personas.append({"id": persona_id, "label": label or persona_id})
        return personas

    def _persona_binding_records(self) -> list[dict[str, Any]]:
        bindings = self._load_persona_preset_bindings()
        records: list[dict[str, Any]] = []
        for persona_id in sorted(bindings.keys()):
            entry = bindings.get(persona_id) or {}
            preset_name = str(entry.get("name") or "").strip()
            slug = str(entry.get("slug") or "").strip()
            records.append({
                "persona_id": persona_id,
                "persona_label": self._persona_display_name(persona_id) or persona_id,
                "preset_name": preset_name or slug,
                "preset_slug": slug,
            })
        return records

    def _normalize_persona_binding_id(self, persona_ref) -> str:
        persona_key = self._normalize_persona_ref(persona_ref)
        if not persona_key:
            return ""
        if persona_key in {"default", "_chatui_default_"}:
            return persona_key
        persona = self._get_persona_manager_record(persona_key)
        if persona is None:
            return persona_key
        try:
            if isinstance(persona, dict):
                return str(persona.get("persona_id") or persona_key).strip() or persona_key
            return str(getattr(persona, "persona_id", None) or persona_key).strip() or persona_key
        except Exception:
            return persona_key

    def _resolve_persona_preset_record(self, persona_ref) -> Optional[Dict[str, Any]]:
        persona_key = self._normalize_persona_binding_id(persona_ref)
        if not persona_key:
            return None
        bindings = self._load_persona_preset_bindings()
        binding = bindings.get(persona_key)
        if not binding:
            return None
        candidate = str(binding.get("slug") or binding.get("name") or "").strip()
        if not candidate:
            return None
        record = self._load_preset(candidate)
        if record:
            return record
        fallback_name = str(binding.get("name") or "").strip()
        if fallback_name and fallback_name != candidate:
            return self._load_preset(fallback_name)
        return None

    def _set_persona_preset_binding(self, persona_ref: str, preset_identifier: str) -> tuple[bool, str, Optional[str]]:
        persona_key = self._normalize_persona_binding_id(persona_ref)
        if not persona_key:
            return False, "请提供有效的人格 ID。", None
        record = self._load_preset(preset_identifier)
        if not record:
            return False, f"未找到名为「{preset_identifier}」的预设。", None
        bindings = self._load_persona_preset_bindings()
        bindings[persona_key] = {"name": record.get("name") or preset_identifier, "slug": record.get("slug") or ""}
        self._save_persona_preset_bindings(bindings)
        return True, f"已将人格「{self._persona_display_name(persona_key)}」绑定到预设「{record.get('name') or preset_identifier}」。", record.get("name") or preset_identifier

    def _clear_persona_preset_binding(self, persona_ref: str) -> tuple[bool, str]:
        persona_key = self._normalize_persona_binding_id(persona_ref)
        if not persona_key:
            return False, "请提供有效的人格 ID。"
        bindings = self._load_persona_preset_bindings()
        if persona_key not in bindings:
            return False, f"人格「{self._persona_display_name(persona_key)}」当前没有绑定预设。"
        bindings.pop(persona_key, None)
        self._save_persona_preset_bindings(bindings)
        return True, f"已解除人格「{self._persona_display_name(persona_key)}」的预设绑定。"

    def _format_persona_preset_bindings_message(self) -> str:
        bindings = self._load_persona_preset_bindings()
        lines = ["人格预设绑定："]
        if not bindings:
            lines.append("暂未绑定任何人格预设。")
            lines.append("用法：/人格预设绑定 <人格ID> <预设名>")
            return "\n".join(lines)
        for idx, persona_id in enumerate(sorted(bindings.keys()), start=1):
            entry = bindings.get(persona_id) or {}
            preset_name = str(entry.get("name") or entry.get("slug") or "").strip() or "未命名预设"
            lines.append(f"{idx}. {self._persona_display_name(persona_id)} -> {preset_name}")
        lines.append("用法：/人格预设绑定 <人格ID> <预设名>；/人格预设解绑 <人格ID>")
        return "\n".join(lines)

    def _persona_id_for_binding(self, persona_id: str) -> str:
        return self._normalize_persona_binding_id(persona_id)

    async def _resolve_current_persona_id(
        self,
        event: AstrMessageEvent,
        request: Optional[ProviderRequest] = None,
    ) -> str:
        persona_id = ""
        try:
            conversation_persona_id = None
            if request and getattr(request, "conversation", None):
                conversation_persona_id = getattr(request.conversation, "persona_id", None)
            if conversation_persona_id is None:
                curr_cid = await self.context.conversation_manager.get_curr_conversation_id(event.unified_msg_origin)
                if curr_cid:
                    conversation = await self.context.conversation_manager.get_conversation(
                        event.unified_msg_origin,
                        curr_cid,
                    )
                    if conversation:
                        conversation_persona_id = getattr(conversation, "persona_id", None)
            persona_mgr = getattr(self.context, "persona_manager", None)
            if persona_mgr is not None:
                resolver = getattr(persona_mgr, "resolve_selected_persona", None)
                if callable(resolver):
                    provider_settings = (
                        self.context.get_config(umo=event.unified_msg_origin).get("provider_settings", {})
                        or {}
                    )
                    resolved = await resolver(
                        umo=event.unified_msg_origin,
                        conversation_persona_id=conversation_persona_id,
                        platform_name=event.get_platform_name(),
                        provider_settings=provider_settings,
                    )
                    if isinstance(resolved, (tuple, list)) and resolved:
                        persona_id = str(resolved[0] or "").strip()
                        if len(resolved) >= 4 and resolved[3]:
                            persona_id = "_chatui_default_"
            if not persona_id and conversation_persona_id:
                persona_id = str(conversation_persona_id).strip()
        except Exception:
            logger.debug("[传话筒] 解析当前人格失败", exc_info=True)
        return persona_id

    # ------------------------------------------------------------------
    # Layout resolution for rendering
    # ------------------------------------------------------------------

    def _layout(
        self,
        session_id: Optional[str] = None,
        persona_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resolve effective layout considering session and persona bindings."""
        # 1. session-specific layout (highest priority)
        if session_id:
            session_layout = self._load_session_layout(session_id)
            if session_layout:
                return copy.deepcopy(session_layout)

        # 2. persona preset binding
        if persona_id:
            preset_record = self._resolve_persona_preset_record(persona_id)
            if preset_record:
                layout = copy.deepcopy(preset_record["layout"])
                layout["_preset_name"] = preset_record.get("name") or ""
                layout["_preset_slug"] = preset_record.get("slug") or ""
                layout["_preset_source"] = "persona"
                layout["_persona_id"] = self._normalize_persona_ref(persona_id)
                return layout

        # 3. global layout
        return copy.deepcopy(self._layout_state)