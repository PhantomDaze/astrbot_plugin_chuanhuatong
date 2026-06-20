"""Emotion configuration mixin."""

import copy
import json
import re
from typing import Any, Dict, Optional

from astrbot.api import logger

from models import EmotionMeta, DEFAULT_EMOTIONS


class EmotionMixin:
    """Mixin providing emotion configuration methods."""

    def _read_emotion_file(self) -> Optional[list[dict[str, Any]]]:
        if not self._emotion_file.exists():
            return None
        try:
            data = json.loads(self._emotion_file.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else None
        except Exception:
            logger.debug("[传话筒] 读取情绪配置失败，使用默认配置。", exc_info=True)
            return None

    def _write_emotion_file(self, records: list[dict[str, Any]]):
        try:
            self._emotion_file.write_text(
                json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.error("[传话筒] 写入情绪配置失败: %s", exc)

    def _normalize_emotion_records(self, records: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        source = records or []
        for item in source:
            if not isinstance(item, dict):
                continue
            raw_key = str(item.get("key") or "").strip()
            key = re.sub(r"[^0-9a-zA-Z_]+", "_", raw_key).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            folder = self._sanitize_folder_name(str(item.get("folder") or key), key or "neutral")
            label = str(item.get("label") or raw_key or key).strip() or key
            color = str(item.get("color") or "#FFFFFF").strip() or "#FFFFFF"
            enabled = bool(item.get("enabled", True))
            normalized.append({
                "key": key,
                "folder": folder,
                "label": label,
                "color": color,
                "enabled": enabled,
            })
        if not normalized:
            normalized = copy.deepcopy(DEFAULT_EMOTIONS)
        if not any(entry.get("enabled") for entry in normalized):
            normalized[0]["enabled"] = True
        return normalized

    def _persist_emotion_sets(self, records: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        normalized = self._normalize_emotion_records(records)
        self._write_emotion_file(normalized)
        logger.info(
            "[传话筒] 情绪配置已写入，共 %s 个标签（启用 %s 个）",
            len(normalized),
            sum(1 for item in normalized if item.get("enabled")),
        )
        return normalized

    def _load_emotion_sets(self) -> Dict[str, EmotionMeta]:
        records = self._read_emotion_file()
        if records is None:
            src = self.cfg().get("emotion_sets")
            if isinstance(src, list) and src:
                records = src
                logger.info("[传话筒] 从配置加载 %s 个情绪标签", len(records))
            else:
                records = copy.deepcopy(DEFAULT_EMOTIONS)
                logger.info("[传话筒] 使用内置默认情绪标签")
        records = self._persist_emotion_sets(records)
        self._emotion_records = records
        prepared: Dict[str, EmotionMeta] = {}
        enabled_keys: list[str] = []
        for item in records:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            if not key:
                continue
            folder = str(item.get("folder") or "").strip() or key
            meta = EmotionMeta(
                key=key,
                folder=folder,
                label=str(item.get("label") or key),
                color=str(item.get("color") or "#FFFFFF"),
                enabled=bool(item.get("enabled", True)),
            )
            prepared[key] = meta
            if meta.enabled:
                enabled_keys.append(key)
        if not prepared:
            for item in DEFAULT_EMOTIONS:
                meta = EmotionMeta(**item)
                prepared[meta.key] = meta
                if meta.enabled:
                    enabled_keys.append(meta.key)
        if not enabled_keys:
            first_key = next(iter(prepared))
            meta = prepared[first_key]
            prepared[first_key] = EmotionMeta(
                key=meta.key,
                folder=meta.folder,
                label=meta.label,
                color=meta.color,
                enabled=True,
            )
        return {k: v for k, v in prepared.items() if v.enabled}

    def _emotion_meta(self) -> Dict[str, EmotionMeta]:
        if not self._cached_emotions:
            self._cached_emotions = self._load_emotion_sets()
        return self._cached_emotions.copy()

    def _emotion_payload(self) -> list[dict[str, Any]]:
        if not self._emotion_records:
            self._emotion_meta()
        return copy.deepcopy(self._emotion_records)

    def _emotion_from_text(self, text: str) -> tuple[str, str]:
        """从文本中提取情绪标签并返回清理后的文本"""
        mapping = self._emotion_meta()
        matches = self.EMOTION_PATTERN.findall(text)
        selected: Optional[str] = None
        if matches:
            for raw in matches:
                key = raw.lower()
                if selected is None and key in mapping:
                    selected = key
        cleaned = self._remove_emotion_tags(text)
        default_key = str(self.cfg().get("default_emotion", "")).lower()
        if not default_key or default_key not in mapping:
            default_key = next(iter(mapping.keys()))
        return (selected or default_key), cleaned
