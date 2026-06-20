"""Permissions and whitelist mixin."""

import json
from typing import Any

from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import AstrMessageEvent


class PermissionMixin:
    """Mixin providing permission checks and whitelist management."""

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
        permission_mode = str(self.cfg().get("control_permission", "admin_or_group_admin")).lower()
        if permission_mode == "admin":
            return self._is_event_admin(event)
        elif permission_mode == "admin_or_group_admin":
            if self._is_event_admin(event):
                return True
            return self._is_group_admin(event)
        return self._is_event_admin(event)

    def _load_whitelist(self) -> set[str]:
        try:
            config_list = self.cfg().get("whitelist", [])
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

    def _save_whitelist(self, whitelist: set[str], sync_to_config: bool = True):
        try:
            data = list(sorted(whitelist))
            self._whitelist_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            if sync_to_config:
                self._sync_whitelist_to_config(whitelist)
        except Exception as exc:
            logger.error("[传话筒] 保存黑白名单失败: %s", exc)

    def _sync_whitelist_to_config(self, whitelist: set[str]):
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

    def _sync_whitelist_from_config(self):
        try:
            config_list = self.cfg().get("whitelist", [])
            if isinstance(config_list, list) and config_list:
                whitelist = set(str(item) for item in config_list if item)
                if not self._whitelist_file.exists():
                    data = list(sorted(whitelist))
                    self._whitelist_file.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                else:
                    try:
                        file_data = json.loads(self._whitelist_file.read_text(encoding="utf-8"))
                        if not file_data or (isinstance(file_data, list) and len(file_data) == 0):
                            data = list(sorted(whitelist))
                            self._whitelist_file.write_text(
                                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                            )
                    except Exception:
                        data = list(sorted(whitelist))
                        self._whitelist_file.write_text(
                            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                        )
        except Exception as exc:
            logger.debug("[传话筒] 从配置同步黑白名单失败: %s", exc)

    def _is_session_enabled(self, event: AstrMessageEvent) -> bool:
        whitelist_mode = self._cfg_bool("whitelist_mode", False)
        whitelist = self._load_whitelist()
        session_id = event.unified_msg_origin
        if whitelist_mode:
            return session_id in whitelist
        else:
            return session_id not in whitelist

    def _enable_session(self, event: AstrMessageEvent) -> tuple[bool, str]:
        whitelist_mode = self._cfg_bool("whitelist_mode", False)
        whitelist = self._load_whitelist()
        session_id = event.unified_msg_origin
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

    def _disable_session(self, event: AstrMessageEvent) -> tuple[bool, str]:
        whitelist_mode = self._cfg_bool("whitelist_mode", False)
        whitelist = self._load_whitelist()
        session_id = event.unified_msg_origin
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
