"""Layout management mixin — session layout, global layout, preset management, normalization."""

import copy
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from astrbot.api import logger


class LayoutMixin:
    """Mixin providing layout management, presets, and normalization."""

    # ---- Layout resolution ----

    def _layout(
        self,
        session_id: Optional[str] = None,
        persona_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get the effective layout: session preset first, then persona preset, then global layout."""
        if session_id:
            session_layout = self._load_session_layout(session_id)
            if session_layout:
                return copy.deepcopy(session_layout)
        if persona_id:
            preset_record = self._resolve_persona_preset_record(persona_id)
            if preset_record:
                layout = copy.deepcopy(preset_record["layout"])
                layout["_preset_name"] = preset_record.get("name") or ""
                layout["_preset_slug"] = preset_record.get("slug") or ""
                layout["_preset_source"] = "persona"
                layout["_persona_id"] = self._normalize_persona_ref(persona_id)
                return layout
        return copy.deepcopy(self._layout_state)

    # ---- Session Layout ----

    def _session_layout_file(self, session_id: str) -> Path:
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

    # ---- Global Layout ----

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

    # ---- Preset Management ----

    def _sanitize_preset_name(self, name: str) -> str:
        name = str(name or "").strip()
        return re.sub(r"\s+", " ", name)

    def _sanitize_folder_name(self, name: str, default: str = "custom") -> str:
        name = str(name or "").strip()
        if not name:
            return default
        slug = re.sub(r"[^0-9a-zA-Z_-]+", "_", name).strip("_")
        if not slug:
            return default
        return slug[:50]

    def _sanitize_role_name(self, name: str, default: str = "role") -> str:
        return self._sanitize_folder_name(name, default)

    @staticmethod
    def _dir_has_image(directory: Path) -> bool:
        try:
            for f in directory.iterdir():
                if f.is_file() and f.suffix.lower() in {".png", ".webp"}:
                    return True
        except Exception:
            return False
        return False

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

    def _switch_preset(self, target: str, session_id: Optional[str] = None) -> tuple[bool, str, Optional[str]]:
        """切换预设，如果提供了session_id则保存到会话配置，否则保存到全局配置"""
        normalized = str(target or "").strip()
        if not normalized:
            return False, self._format_preset_list_message(), None
        record = self._load_preset(normalized)
        if not record:
            return False, f"未找到名为「{normalized}」的预设。\n\n{self._format_preset_list_message()}", None

        if session_id:
            preset_name = record.get("name") or normalized
            self._save_session_layout(session_id, record["layout"], preset_name)
            self._cached_emotions.clear()
            self._emotion_meta()
            logger.info("[传话筒] 切换到预设: %s (会话: %s)", preset_name, session_id)
            return True, f"已切换到预设「{preset_name}」（仅当前会话）。", preset_name

        self._set_layout_state(record["layout"])
        self._remember_current_preset(record)
        self._cached_emotions.clear()
        self._emotion_meta()
        logger.info("[传话筒] 切换到预设: %s (全局)", record.get("name") or normalized)
        return True, f"已切换到预设「{record['name']}」（全局）。", record.get("name") or normalized

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

    # ---- Layout Normalization ----

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

    @staticmethod
    def _resolve_anchor_position(canvas_w: int, canvas_h: int, anchor: str, left: int, top: int, width: int, height: int) -> tuple[int, int]:
        mode = (anchor or "left-top").lower()
        if mode == "center":
            final_x = canvas_w // 2 + left
            final_y = canvas_h // 2 + top
        elif mode == "right-bottom":
            final_x = canvas_w - width + left
            final_y = canvas_h - height + top
        else:
            if left < 0:
                final_x = canvas_w + left
            else:
                final_x = left
            if top < 0:
                final_y = canvas_h + top
            else:
                final_y = top
        return final_x, final_y
