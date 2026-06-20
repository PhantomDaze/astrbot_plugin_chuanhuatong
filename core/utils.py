"""Pure utility helpers with no side effects."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def sanitize_preset_name(name: str) -> str:
    """Sanitize preset name for safe filesystem use."""
    name = re.sub(r"[^\w\-]", "_", name.strip())
    return name or "custom"


def sanitize_folder_name(name: str, default: str = "custom") -> str:
    """Sanitize folder name, allow only safe characters."""
    name = re.sub(r"[^\w\-]", "_", name.strip())
    return name or default


def sanitize_role_name(name: str, default: str = "role") -> str:
    """Sanitize role name for character directories."""
    name = re.sub(r"[^\w\-]", "_", name.strip())
    return name or default


def dir_has_image(directory: Path) -> bool:
    """Check if directory contains at least one image file."""
    if not directory.exists() or not directory.is_dir():
        return False
    suffixes = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    return any(p.suffix.lower() in suffixes for p in directory.iterdir())


def parse_rgba(value: str) -> Tuple[int, int, int, int]:
    """Parse hex or rgba string to (r, g, b, a) tuple."""
    value = value.strip()
    if value.startswith("#"):
        value = value[1:]
        if len(value) == 6:
            r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
            return (r, g, b, 255)
        if len(value) == 8:
            r, g, b, a = (
                int(value[0:2], 16),
                int(value[2:4], 16),
                int(value[4:6], 16),
                int(value[6:8], 16),
            )
            return (r, g, b, a)
    if value.startswith("rgba"):
        match = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)", value)
        if match:
            r, g, b = int(match.group(1)), int(match.group(2)), int(match.group(3))
            a = int(float(match.group(4)) * 255) if match.group(4) else 255
            return (r, g, b, a)
    return (0, 0, 0, 255)


def hex_or_rgba(value: str) -> Tuple[int, int, int, int]:
    """Alias for parse_rgba for backward compatibility."""
    return parse_rgba(value)


def resolve_anchor_position(
    canvas_w: int,
    canvas_h: int,
    anchor: str,
    left: int,
    top: int,
    width: int,
    height: int,
) -> Tuple[int, int]:
    """Resolve absolute position from anchor-relative coordinates."""
    anchor = anchor or "left-top"
    if anchor == "center":
        return (canvas_w // 2 + left - width // 2, canvas_h // 2 + top - height // 2)
    if anchor == "right-bottom":
        return (canvas_w - left - width, canvas_h - top - height)
    # default: left-top
    return (left, top)
