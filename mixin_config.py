"""Config and directory initialization mixin for 传话筒 plugin."""

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import StarTools
from uuid import uuid4


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


class ConfigMixin:
    """Mixin providing config access, directory setup, and permission/whitelist helpers."""

    PLUGIN_ID: str = ""

    # ------------------------------------------------------------------
    # Initialization helpers (called from main __init__)
    # ------------------------------------------------------------------

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
                logger.warning("[传话筒] 创建数据目录失败(%s)，退回 fallback：%s", exc, fallback_dir)
        fallback_dir.mkdir(parents=True, exist_ok=True)
        return fallback_dir

    def _sync_whitelist_from_config(self):
        """同步配置中内置的用户ID到 whitelist.json。
        读取 cfg 中的 whitelist_users 和 blacklist_users，写入 whitelist.json。
        """
        whitelist = self._load_whitelist()
        changed = False

        whitelist_users = str(self.cfg().get("whitelist_users", "") or "").strip()
        if whitelist_users:
            for uid in [u.strip() for u in whitelist_users.split(",") if u.strip()]:
                if uid not in whitelist:
                    whitelist.add(uid)
                    changed = True

        blacklist_users = str(self.cfg().get("blacklist_users", "") or "").strip()
        if blacklist_users:
            for uid in [u.strip() for u in blacklist_users.split(",") if u.strip()]:
                if uid not in whitelist:
                    whitelist.add(uid)
                    changed = True

        if changed:
            self._save_whitelist(whitelist)

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def cfg(self):
        """Return the plugin configuration object."""
        try:
            return self._cfg_obj if isinstance(self._cfg_obj, dict) else (self._cfg_obj or {})
        except Exception:
            return {}

    def _cfg_bool(self, key: str, default: bool = True) -> bool:
        val = self.cfg().get(key, default)
        return bool(val) if not isinstance(val, str) else val.lower() in {"1", "true", "yes", "on"}

    # ------------------------------------------------------------------
    # Whitelist persistence
    # ------------------------------------------------------------------

    def _load_whitelist(self) -> set[str]:
        if not self._whitelist_file.exists():
            return set()
        try:
            raw = json.loads(self._whitelist_file.read_text(encoding="utf-8"))
            return set(raw) if isinstance(raw, list) else set()
        except Exception:
            return set()

    def _save_whitelist(self, data: set[str]) -> None:
        try:
            self._whitelist_file.write_text(
                json.dumps(sorted(data), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.error("[传话筒] 保存黑白名单失败: %s", exc)

    # ------------------------------------------------------------------
    # Permission helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_event_admin(event: AstrMessageEvent) -> bool:
        checker = getattr(event, "is_admin", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                logger.debug("[传话筒] 检查管理员权限失败", exc_info=True)
        role = getattr(event, "role", None)
        return str(role).lower() == "admin"

    def _is_group_admin(self, event: AstrMessageEvent) -> bool:
        """检查用户是否是群管理员（仅群聊有效）"""
        if event.is_private_chat():
            return False
        try:
            if event.is_admin():
                return True
        except Exception:
            pass
        try:
            raw = event.message_obj.raw_message
            if isinstance(raw, dict):
                sender = raw.get("sender", {}) or {}
                role = str(sender.get("role", "")).lower()
                if role in {"owner", "admin"}:
                    return True
        except Exception:
            pass
        try:
            if hasattr(event, "message_obj") and event.message_obj:
                sender = getattr(event.message_obj, "sender", None)
                if sender:
                    role = getattr(sender, "role", None)
                    if role and str(role).lower() in {"owner", "admin"}:
                        return True
        except Exception:
            pass
        return False

    def _check_control_permission(self, event: AstrMessageEvent) -> bool:
        """检查是否有控制权限（根据配置）"""
        permission_mode = str(self.cfg().get("control_permission", "admin_or_group_admin")).lower()
        if permission_mode == "admin":
            return self._is_event_admin(event)
        if permission_mode == "admin_or_group_admin":
            return self._is_event_admin(event) or self._is_group_admin(event)
        return True

    def _is_session_enabled(self, event) -> bool:
        """Return True if the session should render output."""
        session_id = str(getattr(event, "unified_msg_origin", "") or "")
        if not session_id:
            return True
        whitelist = self._load_whitelist()
        whitelist_mode = self._cfg_bool("whitelist_mode", False)
        if whitelist_mode:
            return session_id in whitelist
        else:
            return session_id not in whitelist

    def _enable_session(self, event) -> tuple[bool, str]:
        whitelist_mode = self._cfg_bool("whitelist_mode", False)
        whitelist = self._load_whitelist()
        session_id = str(getattr(event, "unified_msg_origin", "") or "")

        if whitelist_mode:
            if session_id not in whitelist:
                whitelist.add(session_id)
                self._save_whitelist(whitelist)
                return True, "已添加到白名单，传话筒已启用"
            else:
                return False, "已在白名单中，传话筒已启用"
        else:
            if session_id in whitelist:
                whitelist.discard(session_id)
                self._save_whitelist(whitelist)
                return True, "已从黑名单移除，传话筒已启用"
            else:
                return False, "不在黑名单中，传话筒已启用"

    def _disable_session(self, event) -> tuple[bool, str]:
        whitelist_mode = self._cfg_bool("whitelist_mode", False)
        whitelist = self._load_whitelist()
        session_id = str(getattr(event, "unified_msg_origin", "") or "")

        if whitelist_mode:
            if session_id in whitelist:
                whitelist.discard(session_id)
                self._save_whitelist(whitelist)
                return True, "已从白名单移除，传话筒已禁用"
            else:
                return False, "不在白名单中，传话筒已禁用"
        else:
            if session_id not in whitelist:
                whitelist.add(session_id)
                self._save_whitelist(whitelist)
                return True, "已添加到黑名单，传话筒已禁用"
            else:
                return False, "已在黑名单中，传话筒已禁用"

    # ------------------------------------------------------------------
    # Reusable static utility methods
    # ------------------------------------------------------------------

    @staticmethod
    def _dir_has_image(directory: Path) -> bool:
        try:
            for f in directory.iterdir():
                if f.is_file() and f.suffix.lower() in {".png", ".webp"}:
                    return True
        except Exception:
            return False
        return False

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
            final_x = canvas_w + left if left < 0 else left
            final_y = canvas_h + top if top < 0 else top
        return final_x, final_y

    @staticmethod
    def _sanitize_folder_name(raw: str, fallback: str = "default") -> str:
        name = str(raw or "").strip()
        if not name:
            return fallback
        slug = re.sub(r"[^0-9a-zA-Z_-]+", "_", name).strip("_")
        if not slug:
            return fallback
        return slug[:50]

    @staticmethod
    def _sanitize_role_name(raw: str, fallback: str = "default") -> str:
        name = str(raw or "").strip()
        if not name:
            return fallback
        slug = re.sub(r"[^0-9a-zA-Z_-]+", "_", name).strip("_")
        if not slug:
            return fallback
        return slug[:50]