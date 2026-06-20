"""Whitelist/blacklist and session enable/disable control."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent


class SessionController:
    """Manage whitelist/blacklist mode and per-session enable state."""

    def __init__(self, cfg_getter, whitelist_file: Path, cfg_obj: Any) -> None:
        self._cfg_getter = cfg_getter
        self._whitelist_file = whitelist_file
        self._cfg_obj = cfg_obj

    def is_event_admin(self, event: AstrMessageEvent) -> bool:
        checker = getattr(event, "is_admin", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                logger.debug("[传话筒] 检查管理员权限失败", exc_info=True)
        role = getattr(event, "role", None)
        return str(role).lower() == "admin"

    def is_group_admin(self, event: AstrMessageEvent) -> bool:
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

    def check_control_permission(self, event: AstrMessageEvent) -> bool:
        permission_mode = str(self._cfg_getter().get("control_permission", "admin_or_group_admin")).lower()
        if permission_mode == "admin":
            return self.is_event_admin(event)
        elif permission_mode == "admin_or_group_admin":
            if self.is_event_admin(event):
                return True
            return self.is_group_admin(event)
        return self.is_event_admin(event)

    def load_whitelist(self) -> set[str]:
        try:
            config_list = self._cfg_getter().get("whitelist", [])
            if isinstance(config_list, list) and config_list:
                return set(str(item) for item in config_list if item)
        except Exception:
            pass

        if not self._whitelist_file.exists():
            return set()
        try:
            data = json.loads(self._whitelist_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return set(str(item) for item in data)
            elif isinstance(data, dict):
                return set(str(item) for item in data.get("list", []))
        except Exception:
            logger.debug("[传话筒] 读取黑白名单失败", exc_info=True)
        return set()

    def save_whitelist(self, whitelist: set[str], sync_to_config: bool = True) -> None:
        try:
            data = list(sorted(whitelist))
            self._whitelist_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            if sync_to_config:
                self._sync_to_config(whitelist)
        except Exception as exc:
            logger.error("[传话筒] 保存黑白名单失败: %s", exc)

    def _sync_to_config(self, whitelist: set[str]) -> None:
        try:
            if isinstance(self._cfg_obj, AstrBotConfig):
                self._cfg_obj["whitelist"] = list(sorted(whitelist))
                if hasattr(self._cfg_obj, "save_config"):
                    try:
                        self._cfg_obj.save_config()
                    except Exception:
                        pass
        except Exception as exc:
            logger.debug("[传话筒] 同步黑白名单到配置失败: %s", exc)

    def sync_from_config(self) -> None:
        try:
            config_list = self._cfg_getter().get("whitelist", [])
            if isinstance(config_list, list) and config_list:
                whitelist = set(str(item) for item in config_list if item)
                if not self._whitelist_file.exists():
                    data = list(sorted(whitelist))
                    self._whitelist_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                else:
                    try:
                        file_data = json.loads(self._whitelist_file.read_text(encoding="utf-8"))
                        if not file_data or (isinstance(file_data, list) and len(file_data) == 0):
                            data = list(sorted(whitelist))
                            self._whitelist_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception:
                        data = list(sorted(whitelist))
                        self._whitelist_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug("[传话筒] 从配置同步黑白名单失败: %s", exc)

    def is_session_enabled(self, event: AstrMessageEvent) -> bool:
        whitelist_mode = bool(self._cfg_getter().get("whitelist_mode", False))
        whitelist = self.load_whitelist()
        session_id = event.unified_msg_origin

        if whitelist_mode:
            return session_id in whitelist
        else:
            return session_id not in whitelist

    def enable_session(self, event: AstrMessageEvent) -> tuple[bool, str]:
        whitelist_mode = bool(self._cfg_getter().get("whitelist_mode", False))
        whitelist = self.load_whitelist()
        session_id = event.unified_msg_origin

        if whitelist_mode:
            if session_id in whitelist:
                return False, "当前会话已在白名单中，无需重复启用。"
            whitelist.add(session_id)
            self.save_whitelist(whitelist)
            return True, "已在当前会话启用传话筒（白名单模式）。"
        else:
            if session_id not in whitelist:
                return False, "当前会话未在黑名单中，无需启用。"
            whitelist.remove(session_id)
            self.save_whitelist(whitelist)
            return True, "已在当前会话启用传话筒（已从黑名单移除）。"

    def disable_session(self, event: AstrMessageEvent) -> tuple[bool, str]:
        whitelist_mode = bool(self._cfg_getter().get("whitelist_mode", False))
        whitelist = self.load_whitelist()
        session_id = event.unified_msg_origin

        if whitelist_mode:
            if session_id not in whitelist:
                return False, "当前会话未在白名单中，无需禁用。"
            whitelist.remove(session_id)
            self.save_whitelist(whitelist)
            return True, "已在当前会话禁用传话筒（已从白名单移除）。"
        else:
            if session_id in whitelist:
                return False, "当前会话已在黑名单中，无需重复禁用。"
            whitelist.add(session_id)
            self.save_whitelist(whitelist)
            return True, "已在当前会话禁用传话筒（已加入黑名单）。"
