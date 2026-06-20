"""Text processing mixin for 传话筒 plugin."""

import re
from typing import Any, Optional, Tuple

import astrbot.api.message_components as Comp


PLAIN_COMPONENT_TYPES = tuple(
    getattr(Comp, name)
    for name in ("Plain", "Text")
    if hasattr(Comp, name)
)
LINEBREAK_COMPONENT = getattr(Comp, "LineBreak", None)


class TextMixin:
    """Mixin providing text cleaning: emotion tag removal, markdown stripping,
    emotion extraction, and message chain utilities."""

    EMOTION_PATTERN = re.compile(r"&([a-zA-Z0-9_]+)&")

    def _remove_emotion_tags(self, text: str) -> str:
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

    def _remove_markdown_syntax(self, text: str) -> str:
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

    def _emotion_from_text(self, text: str) -> Tuple[str, str]:
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

    def _chain_to_plain_text(self, chain) -> Optional[str]:
        if not chain:
            return None
        builder: list[str] = []
        for seg in chain:
            if PLAIN_COMPONENT_TYPES and isinstance(seg, PLAIN_COMPONENT_TYPES):
                builder.append(getattr(seg, "text", "") or "")
            elif LINEBREAK_COMPONENT and isinstance(seg, LINEBREAK_COMPONENT):
                builder.append("\n")
            elif hasattr(seg, "text") and seg.__class__.__name__.lower() in {"plain", "text"}:
                builder.append(getattr(seg, "text", "") or "")
            else:
                return None
        text = "".join(builder).strip()
        return text if text else None