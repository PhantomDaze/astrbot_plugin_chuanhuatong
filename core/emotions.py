"""Emotion tag loading, persistence, removal, and resolution."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from astrbot.api import logger

from core.utils import sanitize_folder_name


class EmotionManager:
    """Manage emotion sets, tag parsing, and text cleaning."""

    EMOTION_PATTERN = re.compile(r"&([a-zA-Z0-9_]+)&")

    DEFAULT_EMOTIONS: list[dict[str, Any]] = [
        {"key": "neutral", "folder": "shy", "label": "平静", "color": "#A9C5FF", "enabled": True},
        {"key": "happy", "folder": "happy", "label": "开心", "color": "#FFC857", "enabled": True},
        {"key": "sad", "folder": "sad", "label": "低落", "color": "#7DA1FF", "enabled": True},
        {"key": "shy", "folder": "shy", "label": "害羞", "color": "#F9C5D1", "enabled": True},
        {"key": "surprise", "folder": "surprise", "label": "惊讶", "color": "#F5E960", "enabled": True},
        {"key": "angry", "folder": "sad", "label": "生气", "color": "#FF8A8A", "enabled": True},
    ]

    def __init__(self, emotion_file: Path, cfg_getter) -> None:
        self._emotion_file = emotion_file
        self._cfg_getter = cfg_getter
        self._cached_emotions: Dict[str, EmotionMeta] = {}
        self._emotion_records: list[dict[str, Any]] = []

    def read_file(self) -> Optional[list[dict[str, Any]]]:
        if not self._emotion_file.exists():
            return None
        try:
            data = json.loads(self._emotion_file.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else None
        except Exception:
            logger.debug("[传话筒] 读取情绪配置失败，使用默认配置。", exc_info=True)
            return None

    def write_file(self, records: list[dict[str, Any]]) -> None:
        try:
            self._emotion_file.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.error("[传话筒] 写入情绪配置失败: %s", exc)

    def normalize_records(self, records: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
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
            folder = sanitize_folder_name(str(item.get("folder") or key), key or "neutral")
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
            normalized = copy.deepcopy(self.DEFAULT_EMOTIONS)
        if not any(entry.get("enabled") for entry in normalized):
            normalized[0]["enabled"] = True
        return normalized

    def persist(self, records: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        normalized = self.normalize_records(records)
        self.write_file(normalized)
        logger.info(
            "[传话筒] 情绪配置已写入，共 %s 个标签（启用 %s 个）",
            len(normalized),
            sum(1 for item in normalized if item.get("enabled")),
        )
        return normalized

    def load(self) -> Dict[str, EmotionMeta]:
        records = self.read_file()
        if records is None:
            src = self._cfg_getter().get("emotion_sets")
            if isinstance(src, list) and src:
                records = src
                logger.info("[传话筒] 从配置加载 %s 个情绪标签", len(records))
            else:
                records = copy.deepcopy(self.DEFAULT_EMOTIONS)
                logger.info("[传话筒] 使用内置默认情绪标签")
        records = self.persist(records)
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
            for item in self.DEFAULT_EMOTIONS:
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

    def meta(self) -> Dict[str, EmotionMeta]:
        if not self._cached_emotions:
            self._cached_emotions = self.load()
        return self._cached_emotions.copy()

    def payload(self) -> list[dict[str, Any]]:
        if not self._emotion_records:
            self.meta()
        return copy.deepcopy(self._emotion_records)

    def remove_tags(self, text: str) -> str:
        if not text:
            return text
        cleaned = self.EMOTION_PATTERN.sub("", text)
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        lines = cleaned.split("\n")
        cleaned_lines = [line.strip() for line in lines]
        while cleaned_lines and not cleaned_lines[0]:
            cleaned_lines.pop(0)
        while cleaned_lines and not cleaned_lines[-1]:
            cleaned_lines.pop()
        cleaned = "\n".join(cleaned_lines)
        return cleaned

    def remove_markdown(self, text: str) -> str:
        if not text:
            return text
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'__(.+?)__', r'\1', text)
        text = re.sub(r'_(.+?)_', r'\1', text)
        text = re.sub(r'`([^`]+)`', r'\1', text)
        text = re.sub(r'```[\s\S]*?```', '', text)
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
        text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', r'\1', text)
        text = re.sub(r'~~(.+?)~~', r'\1', text)
        text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
        text = re.sub(r'^[\s]*[-*+]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^[\s]*\d+\.\s+', '', text, flags=re.MULTILINE)
        return text

    def from_text(self, text: str) -> Tuple[str, str]:
        mapping = self.meta()
        matches = self.EMOTION_PATTERN.findall(text)
        selected: Optional[str] = None
        if matches:
            for raw in matches:
                key = raw.lower()
                if selected is None and key in mapping:
                    selected = key
        cleaned = self.remove_tags(text)
        default_key = str(self._cfg_getter().get("default_emotion", "")).lower()
        if not default_key or default_key not in mapping:
            default_key = next(iter(mapping.keys()))
        return (selected or default_key), cleaned
