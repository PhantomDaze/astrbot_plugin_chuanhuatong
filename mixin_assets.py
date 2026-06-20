"""Asset discovery and resolution mixin for 传话筒 plugin."""

import base64
import mimetypes
import os
import random
from pathlib import Path
from typing import Any, Dict, Optional

from astrbot.api import logger


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


class AssetMixin:
    """Mixin providing component, font, character, and background asset discovery."""

    ROLE_AUTO = "__auto__"
    ROLE_BUILTIN = "__builtin__"
    ROLE_LEGACY = "__legacy__"

    # ------------------------------------------------------------------
    # Component & font listing
    # ------------------------------------------------------------------

    def _list_components(self) -> list[str]:
        names: Dict[str, Path] = {}
        for directory in [self._component_dir, self._builtin_component_dir]:
            try:
                for f in directory.iterdir():
                    if f.is_file() and f.suffix.lower() in {".png", ".webp", ".gif"}:
                        if f.name not in names:
                            names[f.name] = f
            except Exception:
                continue
        return sorted(names.keys())

    def _resolve_component_path(self, name: str) -> str:
        if not name:
            return ""
        safe_name = Path(name).name
        for directory in [self._component_dir, self._builtin_component_dir]:
            candidate = directory / safe_name
            if candidate.exists():
                return str(candidate)
        return ""

    def _list_fonts(self) -> list[str]:
        names: Dict[str, Path] = {}
        for directory in [self._font_dir, self._builtin_font_dir]:
            try:
                for f in directory.iterdir():
                    if f.is_file() and f.suffix.lower() in {".ttf", ".ttc", ".otf"}:
                        if f.name not in names:
                            names[f.name] = f
            except Exception:
                continue
        return sorted(names.keys())

    def _resolve_font_path(self, name: str) -> Optional[str]:
        if not name:
            return None
        if os.path.isabs(name) and Path(name).exists():
            return name
        safe_name = Path(name).name
        for directory in [self._font_dir, self._builtin_font_dir]:
            candidate = directory / safe_name
            if candidate.exists():
                return str(candidate)
        return None

    # ------------------------------------------------------------------
    # Character listing & resolution
    # ------------------------------------------------------------------

    def _list_characters(self) -> list[str]:
        entries: set[str] = set()
        try:
            if self._char_dir.exists():
                for emotion_dir in self._char_dir.iterdir():
                    if not emotion_dir.is_dir():
                        continue
                    for f in emotion_dir.iterdir():
                        if f.is_file() and f.suffix.lower() in {".png", ".webp"}:
                            entries.add(f.name)
        except Exception:
            pass
        try:
            if self._user_char_dir.exists():
                for folder in self._user_char_dir.iterdir():
                    if folder.is_file():
                        if folder.suffix.lower() in {".png", ".webp"}:
                            entries.add(f"user::custom::{folder.name}")
                        continue
                    if not folder.is_dir():
                        continue
                    subdirs = [d for d in folder.iterdir() if d.is_dir()]
                    if subdirs:
                        for emo_dir in subdirs:
                            if not emo_dir.is_dir():
                                continue
                            for f in emo_dir.iterdir():
                                if f.is_file() and f.suffix.lower() in {".png", ".webp"}:
                                    entries.add(f"user::{folder.name}::{emo_dir.name}::{f.name}")
                        continue
                    for f in folder.iterdir():
                        if f.is_file() and f.suffix.lower() in {".png", ".webp"}:
                            entries.add(f"user::{self.ROLE_LEGACY}::{folder.name}::{f.name}")
                for f in self._user_char_dir.iterdir():
                    if f.is_file() and f.suffix.lower() in {".png", ".webp"}:
                        entries.add(f"user::{self.ROLE_LEGACY}::default::{f.name}")
        except Exception:
            pass
        return sorted(entries)

    def _resolve_character_file(self, name: str) -> str:
        if not name:
            return ""
        marker = "user::"
        if name.startswith(marker):
            trimmed = name[len(marker):].strip()
            parts = [p for p in trimmed.split("::") if p is not None]
            role = self.ROLE_LEGACY
            emotion = "default"
            filename = ""
            if len(parts) == 1:
                filename = parts[0]
            elif len(parts) == 2:
                emotion, filename = parts
            elif len(parts) >= 3:
                role, emotion, filename = parts[0], parts[1], parts[2]
            role_slug = self._sanitize_role_name(role or self.ROLE_LEGACY, self.ROLE_LEGACY)
            emotion_slug = self._sanitize_folder_name(emotion or "default", "default")
            filename = Path(filename or "").name
            if role_slug == self.ROLE_LEGACY:
                legacy_target = self._user_char_dir / emotion_slug / filename
                if legacy_target.exists():
                    return str(legacy_target)
                legacy_flat = self._user_char_dir / filename
                if legacy_flat.exists():
                    return str(legacy_flat)
            else:
                target = self._user_char_dir / role_slug / emotion_slug / filename
                if target.exists():
                    return str(target)
            return ""
        safe = Path(name).name
        try:
            if self._char_dir.exists():
                for emotion_dir in self._char_dir.iterdir():
                    if not emotion_dir.is_dir():
                        continue
                    candidate = emotion_dir / safe
                    if candidate.exists():
                        return str(candidate)
        except Exception:
            pass
        user_candidate = self._user_char_dir / safe
        if user_candidate.exists():
            return str(user_candidate)
        return ""

    # ------------------------------------------------------------------
    # Background listing & resolution
    # ------------------------------------------------------------------

    def _list_backgrounds(self) -> list[str]:
        entries: list[str] = []
        try:
            for f in self._bg_dir.iterdir():
                if f.is_file() and f.suffix.lower() in IMAGE_SUFFIXES:
                    entries.append(f"builtin::{f.name}")
        except Exception:
            pass
        try:
            for folder in self._user_bg_dir.iterdir():
                if not folder.is_dir():
                    continue
                for f in folder.iterdir():
                    if f.is_file() and f.suffix.lower() in IMAGE_SUFFIXES:
                        entries.append(f"user::{folder.name}::{f.name}")
        except Exception:
            logger.debug("[传话筒] 列出背景资源失败", exc_info=True)
        return sorted(entries)

    def _count_images_in_dir(self, directory: Path) -> int:
        try:
            return sum(1 for f in directory.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_SUFFIXES)
        except Exception:
            return 0

    def _list_background_groups(self) -> list[dict[str, Any]]:
        groups: list[dict[str, Any]] = []
        builtin_count = self._count_images_in_dir(self._bg_dir)
        if builtin_count:
            groups.append({"id": "builtin", "label": "内置背景", "count": builtin_count})
        try:
            for folder in sorted(self._user_bg_dir.iterdir()):
                if not folder.is_dir():
                    continue
                count = self._count_images_in_dir(folder)
                if count:
                    groups.append({
                        "id": f"user::{folder.name}",
                        "label": folder.name,
                        "count": count,
                    })
        except Exception:
            logger.debug("[传话筒] 列出背景分组失败", exc_info=True)
        return groups

    def _pick_random_asset(self, directory: Path, suffixes: set[str]) -> str:
        try:
            files = [
                str(f) for f in directory.iterdir()
                if f.is_file() and f.suffix.lower() in suffixes
            ]
        except Exception:
            files = []
        if not files:
            return ""
        return random.choice(files)

    def _pick_background_path(self, group: Optional[str] = None) -> str:
        target = (group or "__auto__").strip()
        if target and target not in {"__auto__", "__random__"}:
            if target == "builtin":
                path = self._pick_random_asset(self._bg_dir, IMAGE_SUFFIXES)
                if path:
                    return path
            elif target.startswith("user::"):
                slug = self._sanitize_folder_name(
                    target.split("::", 1)[1] if "::" in target else target, "default"
                )
                directory = self._user_bg_dir / slug
                if directory.exists():
                    path = self._pick_random_asset(directory, IMAGE_SUFFIXES)
                    if path:
                        return path
        user_dirs: list[Path] = []
        try:
            for folder in self._user_bg_dir.iterdir():
                if folder.is_dir() and self._count_images_in_dir(folder):
                    user_dirs.append(folder)
        except Exception:
            pass
        if user_dirs:
            directory = random.choice(user_dirs)
            path = self._pick_random_asset(directory, IMAGE_SUFFIXES)
            if path:
                return path
        return self._pick_random_asset(self._bg_dir, IMAGE_SUFFIXES)

    def _resolve_background_file(self, name: str) -> str:
        if not name:
            return ""
        if name.startswith("user::"):
            parts = name.split("::", 2)
            if len(parts) >= 3:
                group = self._sanitize_folder_name(parts[1], "default")
                filename = Path(parts[2]).name
                target = self._user_bg_dir / group / filename
                if target.exists():
                    return str(target)
        elif name.startswith("builtin::"):
            safe = Path(name.split("::", 1)[1]).name
            candidate = self._bg_dir / safe
            if candidate.exists():
                return str(candidate)
        safe = Path(name).name
        candidate = self._bg_dir / safe
        if candidate.exists():
            return str(candidate)
        for directory in [self._component_dir, self._builtin_component_dir]:
            candidate = directory / safe
            if candidate.exists():
                return str(candidate)
        candidate = self._user_bg_dir / safe
        if candidate.exists():
            return str(candidate)
        return ""

    # ------------------------------------------------------------------
    # Character picking (random selection by emotion + role)
    # ------------------------------------------------------------------

    def _pick_character_path(self, emotion_key: str, role: Optional[str] = None) -> str:
        role = (role or "").strip() or self.ROLE_AUTO
        if role in {self.ROLE_AUTO, "__random__"}:
            path = self._pick_auto_character(emotion_key)
            self._last_character_path = path or ""
            return path or ""
        if role == self.ROLE_BUILTIN:
            path = self._pick_builtin_character(emotion_key)
            if path:
                self._last_character_path = path
                return path
            return self._pick_auto_character(emotion_key) or ""
        if role == self.ROLE_LEGACY:
            path = self._pick_user_role_character(self.ROLE_LEGACY, emotion_key)
            if path:
                self._last_character_path = path
                return path
            return self._pick_auto_character(emotion_key) or ""
        path = self._pick_user_role_character(role, emotion_key)
        if path:
            self._last_character_path = path
            return path
        return self._pick_auto_character(emotion_key) or ""

    def _pick_auto_character(self, emotion_key: str) -> str:
        user_roles = self._discover_user_roles()
        for role_id in user_roles.keys():
            if role_id == self.ROLE_LEGACY:
                continue
            path = self._pick_user_role_character(role_id, emotion_key)
            if path:
                return path
        legacy_path = self._pick_user_role_character(self.ROLE_LEGACY, emotion_key)
        if legacy_path:
            return legacy_path
        return self._pick_builtin_character(emotion_key)

    def _pick_user_role_character(self, role: str, emotion_key: str) -> str:
        if not self._user_char_dir.exists():
            return ""
        mapping = self._emotion_meta()
        meta = mapping.get(emotion_key)
        if not meta and mapping:
            meta = next(iter(mapping.values()))
        preferred_folder = meta.folder if meta else ""
        if role == self.ROLE_LEGACY:
            if preferred_folder:
                legacy_dir = self._user_char_dir / preferred_folder
                if legacy_dir.exists():
                    path = self._pick_random_asset(legacy_dir, {".png", ".webp"})
                    if path:
                        self._last_character_path = path
                        return path
            path = self._pick_random_asset(self._user_char_dir, {".png", ".webp"})
            if path:
                self._last_character_path = path
            return path or ""
        role_dir = self._user_char_dir / role
        if not role_dir.exists():
            return ""
        candidate_dirs: list[Path] = []
        if preferred_folder:
            candidate_dirs.append(role_dir / preferred_folder)
        try:
            for sub in role_dir.iterdir():
                if sub.is_dir() and sub.name != preferred_folder:
                    candidate_dirs.append(sub)
        except Exception:
            pass
        for directory in candidate_dirs:
            if directory.exists():
                path = self._pick_random_asset(directory, {".png", ".webp"})
                if path:
                    self._last_character_path = path
                    return path
        path = self._pick_random_asset(role_dir, {".png", ".webp"})
        if path:
            self._last_character_path = path
        return path or ""

    def _pick_builtin_character(self, emotion_key: str) -> str:
        mapping = self._emotion_meta()
        meta = mapping.get(emotion_key)
        if not meta and mapping:
            meta = next(iter(mapping.values()))
        if not meta:
            return ""
        target_dir = self._char_dir / meta.folder
        if not target_dir.exists():
            target_dir.mkdir(parents=True, exist_ok=True)
        path = self._pick_random_asset(target_dir, {".png", ".webp"})
        self._last_character_path = path or ""
        return path or ""

    def _discover_user_roles(self) -> Dict[str, Any]:
        roles: Dict[str, Any] = {}
        try:
            if not self._user_char_dir.exists():
                return roles
            for item in self._user_char_dir.iterdir():
                if item.is_dir():
                    subdirs = [d for d in item.iterdir() if d.is_dir()]
                    if subdirs:
                        roles[item.name] = item
                    else:
                        has_images = any(
                            f.is_file() and f.suffix.lower() in {".png", ".webp"}
                            for f in item.iterdir()
                        )
                        if has_images:
                            roles[self.ROLE_LEGACY] = self._user_char_dir
        except Exception:
            pass
        return roles

    def _list_character_roles(self) -> list[dict[str, Any]]:
        roles: list[dict[str, Any]] = []
        builtin_emotions: set[str] = set()
        try:
            if self._char_dir.exists():
                for emotion_dir in self._char_dir.iterdir():
                    if emotion_dir.is_dir() and self._dir_has_image(emotion_dir):
                        builtin_emotions.add(emotion_dir.name)
        except Exception:
            pass
        if builtin_emotions:
            roles.append({
                "id": self.ROLE_BUILTIN,
                "label": "内置立绘",
                "source": "builtin",
                "emotions": sorted(builtin_emotions),
            })
        # NOTE: _discover_user_roles in the original returns richer metadata
        # than our simplified version. For _list_character_roles, we scan more carefully.
        legacy_emotions: set[str] = set()
        user_roles: Dict[str, dict[str, Any]] = {}
        try:
            if self._user_char_dir.exists():
                for entry in self._user_char_dir.iterdir():
                    if entry.is_dir():
                        sub_emotions: set[str] = set()
                        has_images = False
                        for child in entry.iterdir():
                            if child.is_dir():
                                if self._dir_has_image(child):
                                    sub_emotions.add(child.name)
                            elif child.is_file() and child.suffix.lower() in {".png", ".webp"}:
                                has_images = True
                        if sub_emotions:
                            user_roles[entry.name] = {"label": entry.name, "emotions": sub_emotions}
                            continue
                        if has_images:
                            legacy_emotions.add(entry.name)
                    elif entry.is_file() and entry.suffix.lower() in {".png", ".webp"}:
                        legacy_emotions.add("default")
        except Exception:
            pass
        if legacy_emotions:
            roles.append({
                "id": self.ROLE_LEGACY,
                "label": "旧版上传",
                "source": "legacy",
                "emotions": sorted(legacy_emotions),
            })
        for role_id, meta in user_roles.items():
            roles.append({
                "id": role_id,
                "label": meta.get("label", role_id),
                "source": "user",
                "emotions": sorted(meta.get("emotions", [])),
            })
        return roles

    @staticmethod
    def _dir_has_image(directory: Path) -> bool:
        try:
            for f in directory.iterdir():
                if f.is_file() and f.suffix.lower() in {".png", ".webp"}:
                    return True
        except Exception:
            return False
        return False

    # ------------------------------------------------------------------
    # Asset resolution helpers (used by rendering)
    # ------------------------------------------------------------------

    def _resolve_character_asset(self, asset: str | None, emotion: str, role: Optional[str]) -> str:
        name = str(asset or "").strip()
        if name and name not in {"__auto__", "__random__"}:
            custom = self._resolve_character_file(name)
            if custom:
                self._last_character_path = custom
                return custom
        path = self._pick_character_path(emotion, role)
        return path or ""

    def _resolve_background_asset(self, asset: str | None, group: Optional[str] = None) -> str:
        name = str(asset or "").strip()
        if name and name not in {"__auto__", "__random__"}:
            path = self._resolve_background_file(name)
            if path:
                self._last_background_path = path
                return path
        path = self._pick_background_path(group)
        self._last_background_path = path or ""
        return path or ""

    # ------------------------------------------------------------------
    # Data URL helpers
    # ------------------------------------------------------------------

    def _file_to_data_url(self, file_path: Path) -> str:
        if not file_path.exists():
            return ""
        try:
            mime, _ = mimetypes.guess_type(str(file_path))
            mime = mime or "image/png"
            data = file_path.read_bytes()
            return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        except Exception as exc:
            logger.error(f"[传话筒] 读取文件失败: {exc}")
            return ""

    def _path_to_data_url(self, path: str) -> str:
        if not path:
            return ""
        return self._file_to_data_url(Path(path))

    def _random_background_data(self, group: Optional[str] = None) -> str:
        path = self._pick_background_path(group)
        self._last_background_path = path or ""
        return self._path_to_data_url(path)

    def _random_character_data(self, emotion_key: str, role: Optional[str] = None) -> str:
        path = self._pick_character_path(emotion_key, role)
        return self._path_to_data_url(path)

    def _preview_character(self, role: Optional[str] = None) -> str:
        emotions = self._emotion_meta()
        if not emotions:
            return ""
        first_key = next(iter(emotions.keys()))
        return self._random_character_data(first_key, role)

    def _bot_name(self) -> str:
        try:
            layout = self._layout()
            name = layout.get("bot_name")
        except Exception:
            name = None
        name = str(name or "传话筒").strip()
        return name or "传话筒"