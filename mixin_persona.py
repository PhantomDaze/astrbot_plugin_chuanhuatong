"""Persona management mixin."""

import json
from typing import Any, Dict, Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.provider import ProviderRequest


class PersonaMixin:
    """Mixin providing persona management methods."""

    def _persona_preset_config_key(self) -> str:
        return "persona_preset_bindings"

    def _load_persona_preset_bindings(self) -> dict[str, dict[str, Any]]:
        raw: Any = self.cfg().get(self._persona_preset_config_key(), [])
        raw_bindings: Any = raw
        if isinstance(raw, dict):
            raw_bindings = raw.get("bindings") if "bindings" in raw else raw

        bindings: dict[str, dict[str, Any]] = {}
        if isinstance(raw_bindings, list):
            for entry in raw_bindings:
                if not isinstance(entry, dict):
                    continue
                persona_key = self._normalize_persona_ref(
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
                        persona_key = self._normalize_persona_ref(
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
            payload: list[dict[str, Any]] = payload_bindings
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

    def _normalize_persona_ref(self, persona_ref: str | None) -> str:
        return str(persona_ref or "").strip()

    def _get_persona_manager_record(self, persona_ref: str) -> Any:
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

    def _persona_display_name(self, persona_ref: str | None) -> str:
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
        records: list[Any] = []
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

    def _normalize_persona_binding_id(self, persona_ref: str | None) -> str:
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

    def _resolve_persona_preset_record(self, persona_ref: str | None) -> Optional[Dict[str, Any]]:
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
        bindings[persona_key] = {
            "name": record.get("name") or preset_identifier,
            "slug": record.get("slug") or "",
        }
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

    def _persona_id_for_binding(self, persona_id: str) -> str:
        return self._normalize_persona_binding_id(persona_id)
