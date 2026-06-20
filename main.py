"""传话筒——AstrBot 插件：将 Bot 的文字回复渲染为 Gal 风立绘对话框。

模块化拆分说明：
  - models        数据模型与常量
  - mixin_config  配置访问、数据目录
  - mixin_persona 人格管理
  - mixin_layout  布局管理、预设、归一化
  - mixin_permissions 权限与黑白名单
  - mixin_emotions 情绪配置
  - mixin_assets  资源发现与解析
  - mixin_render  Pillow 渲染管线、绘图工具、字体、颜色
  - mixin_text    文本处理、分割、消息链工具
  - mixin_webui   WebUI 服务器与 HTTP 处理器
"""

import asyncio
import copy
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Ensure the plugin directory is on sys.path so sibling modules are importable
_PLUGIN_DIR = str(Path(__file__).resolve().parent)
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

import yaml
from aiohttp import web
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, register

# ---- Plugin metadata ----
_META_PATH = Path(__file__).with_name("metadata.yaml")
try:
    with open(_META_PATH, "r", encoding="utf-8") as f:
        _META = yaml.safe_load(f) or {}
except Exception:
    _META = {}

_PLUGIN_ID = _META.get("name", "astrbot_plugin_chuanhuatong")
_PLUGIN_AUTHOR = _META.get("author", "bvzrays")
_PLUGIN_DESC = _META.get("desc", "传话筒：将 Bot 的文字回复渲染为 Gal 风立绘对话框")
_PLUGIN_VERSION = str(_META.get("version", "2.4.2")).lstrip("vV")
_PLUGIN_REPO = _META.get("repo", "https://github.com/bvzrays/astrbot_plugin_chuanhuatong")

# ---- Mixins ----
from models import DEFAULT_LAYOUT, EmotionMeta, DEFAULT_EMOTIONS
import astrbot.api.message_components as Comp
from mixin_config import ConfigMixin
from mixin_persona import PersonaMixin
from mixin_layout import LayoutMixin
from mixin_permissions import PermissionMixin
from mixin_emotions import EmotionMixin
from mixin_assets import AssetMixin
from mixin_render import RenderMixin
from mixin_text import TextMixin
from mixin_webui import WebUIMixin


@register(
    _PLUGIN_ID,
    _PLUGIN_AUTHOR,
    _PLUGIN_DESC,
    _PLUGIN_VERSION,
    _PLUGIN_REPO,
)
class ChuanHuaTongPlugin(
    Star,
    ConfigMixin,
    PersonaMixin,
    LayoutMixin,
    PermissionMixin,
    EmotionMixin,
    AssetMixin,
    RenderMixin,
    TextMixin,
    WebUIMixin,
):
    """传话筒——拦截所有文本回复并渲染立绘对话框。"""

    EMOTION_PATTERN = re.compile(r"&([a-zA-Z0-9_]+)&")
    ROLE_AUTO = "__auto__"
    ROLE_BUILTIN = "__builtin__"
    ROLE_LEGACY = "__legacy__"
    PLUGIN_ID = _PLUGIN_ID

    DEFAULT_EMOTIONS: list[dict[str, Any]] = copy.deepcopy(DEFAULT_EMOTIONS)
    DEFAULT_PROMPT_TEMPLATE = (
        "请在回答正文中就近插入一个情绪标签，例如 {tags}。"
        "标签写在对应句子旁即可，便于渲染立绘。标签仅包含字母、数字或下划线。"
    )
    DEFAULT_LAYOUT: Dict[str, Any] = copy.deepcopy(DEFAULT_LAYOUT)

    WEB_INDEX_PATH = Path(__file__).with_name("webui").joinpath("index.html")

    def __init__(self, context: Context, config: Optional[AstrBotConfig] = None):
        Star.__init__(self, context)

        self._cfg_obj: AstrBotConfig | dict | None = config
        self._base_dir = Path(__file__).resolve().parent

        # Builtin resource directories
        self._bg_dir = self._base_dir / str(self.cfg().get("background_dir", "background"))
        self._char_dir = self._base_dir / str(self.cfg().get("character_root", "renwulihui"))
        self._bg_dir.mkdir(parents=True, exist_ok=True)
        self._char_dir.mkdir(parents=True, exist_ok=True)
        self._builtin_component_dir = self._base_dir / "zujian"
        self._builtin_component_dir.mkdir(parents=True, exist_ok=True)
        self._builtin_font_dir = self._base_dir / "ziti"
        self._builtin_font_dir.mkdir(parents=True, exist_ok=True)

        # Data directories
        self._data_dir = self._resolve_data_dir()
        self._component_dir = self._data_dir / "zujian"
        self._component_dir.mkdir(parents=True, exist_ok=True)
        self._font_dir = self._data_dir / "fonts"
        self._font_dir.mkdir(parents=True, exist_ok=True)
        self._user_char_dir = self._data_dir / "characters"
        self._user_char_dir.mkdir(parents=True, exist_ok=True)
        self._user_bg_dir = self._data_dir / "backgrounds"
        self._user_bg_dir.mkdir(parents=True, exist_ok=True)
        self._presets_dir = self._data_dir / "presets"
        self._presets_dir.mkdir(parents=True, exist_ok=True)

        # State files
        self._current_preset_file = self._data_dir / "current_preset.json"
        self._current_preset_meta: dict[str, Any] = self._load_current_preset_meta()
        self._layout_file = self._data_dir / "layout_state.json"
        self._session_layouts_dir = self._data_dir / "session_layouts"
        self._session_layouts_dir.mkdir(parents=True, exist_ok=True)
        self._emotion_file = self._data_dir / "emotion_sets.json"
        self._whitelist_file = self._data_dir / "whitelist.json"

        # Layout state
        self._layout_lock = asyncio.Lock()
        self._layout_state = self._load_layout_state()

        # Whitelist sync
        self._sync_whitelist_from_config()

        # WebUI
        self._web_runner: Optional[web.AppRunner] = None
        self._web_site: Optional[web.TCPSite] = None
        self._web_app: Optional[web.Application] = None
        self._web_lock = asyncio.Lock()

        # Render state
        self._render_semaphore = asyncio.Semaphore(3)
        self._cached_emotions: Dict[str, EmotionMeta] = {}
        self._emotion_records: list[dict[str, Any]] = []
        self._ensure_prompt_template()
        self._last_background_path: str = ""
        self._last_character_path: str = ""
        self._cleanup_tasks: set[asyncio.Task] = set()

        logger.info("[传话筒] 数据目录：%s", self._data_dir)

    # ========================================================================
    # Lifecycle Hooks (AstrBot calls these directly — must be on the class itself)
    # ========================================================================

    async def initialize(self):
        await self._ensure_webui()
        self._emotion_meta()

    async def terminate(self):
        async with self._web_lock:
            if self._web_site:
                await self._web_site.stop()
                self._web_site = None
            if self._web_runner:
                await self._web_runner.cleanup()
                self._web_runner = None
            self._web_app = None

    # ========================================================================
    # Core Event Handlers
    # ========================================================================

    if hasattr(filter, "on_message"):

        @filter.on_message(priority=-10)
        async def handle_message_events(
            self,
            event: AstrMessageEvent,
            req: Optional[ProviderRequest] = None,
        ):
            await self._handle_preset_command(event, req)

    @filter.on_llm_request(priority=-10)
    async def inject_emotion_prompt(self, event: AstrMessageEvent, req: ProviderRequest):
        handled = await self._handle_preset_command(event, req)
        if handled:
            return
        if not self._cfg_bool("enable_emotion_prompt", False):
            return
        emotions = self._emotion_meta()
        tags = [f"&{tag}&" for tag in emotions.keys()]
        template = str(self.cfg().get("emotion_prompt_template", self.DEFAULT_PROMPT_TEMPLATE))
        instruction = template.replace("{tags}", ", ".join(tags))
        req.system_prompt = (req.system_prompt or "") + "\n" + instruction

    @filter.on_llm_response(priority=100000)
    async def get_emotion_tag(self, event: AstrMessageEvent, resp: LLMResponse):
        """保存响应对象并提取表情标签，供 on_decorating_result 使用"""
        if not self._cfg_bool("enable_render", True):
            return

        emotion_tag = None
        raw_text = ""

        for attr in ("text", "output_text", "content", "completion_text"):
            if hasattr(resp, attr):
                value = getattr(resp, attr)
                if isinstance(value, str) and value.strip():
                    raw_text = value
                    break

        if raw_text:
            emotion_tag, cleaned_text = self._emotion_from_text(raw_text)
            for attr in ("text", "output_text", "content", "completion_text"):
                if hasattr(resp, attr):
                    setattr(resp, attr, cleaned_text)

        event.set_extra("llm_resp", resp)
        if emotion_tag:
            event.set_extra("extracted_emotion_tag", emotion_tag)

    @filter.on_decorating_result(priority=-10)
    async def on_decorating_result(self, event: AstrMessageEvent):
        """在装饰结果时渲染图片"""
        session_id = event.unified_msg_origin
        persona_id = await self._resolve_current_persona_id(event, None)
        logger.debug("[传话筒] on_decorating_result 触发，会话: %s，人格: %s", session_id, persona_id)

        result = event.get_result()
        if not result:
            logger.debug("[传话筒] 未获取到结果对象，跳过处理")
            return
        chain = result.chain
        if not chain:
            logger.debug("[传话筒] 消息链为空，跳过处理")
            return

        has_non_text = False
        raw_text_parts = []

        for item in chain:
            if isinstance(item, Comp.Plain) or (hasattr(Comp, "Text") and isinstance(item, Comp.Text)):
                text = getattr(item, "text", "") or ""
                raw_text_parts.append(text)
            else:
                has_non_text = True

        resp = event.get_extra("llm_resp")
        resp_obj = resp if isinstance(resp, LLMResponse) else None

        if not self._cfg_bool("enable_render", True):
            return

        if not self._is_session_enabled(event):
            logger.debug("[传话筒] 当前会话未启用传话筒（黑白名单检查），会话: %s", session_id)
            return

        render_scope = str(self.cfg().get("render_scope", "llm_only")).lower()
        allow_non_llm = render_scope == "all_text"

        if resp_obj is None and not allow_non_llm:
            logger.debug("[传话筒] 无LLM响应且不允许非LLM文本，返回清洗后的文本")
            return

        if not has_non_text and raw_text_parts:
            raw_full_text = "".join(raw_text_parts)
            emotion = event.get_extra("extracted_emotion_tag")
            full_text = raw_full_text.strip()
            if full_text:
                logger.info(
                    "[传话筒] 触发渲染判断，情绪=%s，原始文本长度=%s，清洗后长度=%s",
                    emotion, len(raw_full_text), len(full_text),
                )
                if resp_obj is not None:
                    await self._update_conversation_history(event, full_text)

                char_limit = int(self.cfg().get("render_char_threshold", 60) or 0)
                enable_split = self._cfg_bool("split_long_text", False)

                if char_limit > 0:
                    text_len = self._count_visible_chars(full_text)
                    if text_len > char_limit:
                        if enable_split:
                            logger.info("[传话筒] 文本长度 %s 超过阈值 %s，启用分割渲染", text_len, char_limit)
                            success = await self._render_split_text(
                                full_text, emotion, event, session_id, persona_id
                            )
                            if success:
                                result.chain = []
                                logger.info("[传话筒] 分割渲染完成，会话: %s", session_id)
                                return
                            logger.warning("[传话筒] 分割渲染失败，返回清洗后的文本")
                            return
                        else:
                            logger.info("[传话筒] 文本长度 %s 超过阈值 %s，跳过渲染", text_len, char_limit)
                            return

                logger.debug("[传话筒] 开始渲染图片，会话: %s", session_id)
                image_path = await self._render_with_fallback(full_text, emotion, session_id, persona_id)
                if image_path:
                    try:
                        result.chain = [Comp.Image.fromFileSystem(image_path)]
                        self._schedule_cleanup(image_path, delay=90.0)
                        logger.info("[传话筒] 渲染成功，已替换为图片，会话: %s", session_id)
                    except Exception as exc:
                        logger.error(
                            "[传话筒] 设置图片结果失败: %s，会话: %s，保持清洗后的文本", exc, session_id
                        )
                else:
                    logger.warning("[传话筒] 渲染失败，退回纯文本，会话: %s", session_id)
        else:
            logger.debug("[传话筒] 消息链包含非文本组件或为空，跳过渲染，会话: %s", session_id)

    # ========================================================================
    # Preset Command Helpers
    # ========================================================================

    async def _handle_preset_command(
        self,
        event: AstrMessageEvent,
        req: Optional[ProviderRequest],
    ) -> bool:
        """处理预设切换命令（用于事件钩子）"""
        if hasattr(event, "is_stopped") and event.is_stopped():
            return False
        text = event.message_str or ""
        stripped = text.strip()
        if stripped and stripped[0] in {"/", "*", "／", "＊"}:
            stripped = stripped[1:].lstrip()
        if not stripped.startswith("切换预设"):
            return False
        target = stripped[len("切换预设"):].strip()
        if not self._check_control_permission(event):
            denial = "你没有权限使用此指令。"
            event.set_result(event.plain_result(denial))
            event.stop_event()
            return True
        session_id = event.unified_msg_origin
        success, message, preset_name = self._switch_preset(target, session_id)
        event.set_result(event.plain_result(message))
        event.stop_event()
        if success:
            logger.info("[传话筒] 通过指令切换预设: %s", preset_name)
        return True

    # ========================================================================
    # Commands (decorated)
    # ========================================================================

    @filter.command("切换预设")
    async def command_switch_preset(self, event: AstrMessageEvent, *preset_tokens: str):
        """切换预设（仅当前会话）。用法：/切换预设 <预设名>"""
        if not self._check_control_permission(event):
            yield event.plain_result("你没有权限使用此指令。")
            event.stop_event()
            return
        target = " ".join(preset_tokens).strip()
        if not target:
            yield event.plain_result("请提供预设名称。使用 /预设列表 查看所有可用预设。")
            event.stop_event()
            return
        session_id = event.unified_msg_origin
        success, message, preset_name = self._switch_preset(target, session_id)
        yield event.plain_result(message)
        event.stop_event()
        if success:
            logger.info("[传话筒] 通过命令切换预设: %s (会话: %s)", preset_name, session_id)

    @filter.command("预设列表")
    async def command_list_presets(self, event: AstrMessageEvent):
        """列出所有可用的预设"""
        yield event.plain_result(self._format_preset_list_message())
        event.stop_event()

    @filter.command("传话筒开启")
    async def command_chuanhuatong_enable(self, event: AstrMessageEvent):
        """在当前会话启用传话筒"""
        if not self._check_control_permission(event):
            yield event.plain_result("你没有权限使用此指令。")
            event.stop_event()
            return
        success, message = self._enable_session(event)
        yield event.plain_result(message)
        event.stop_event()

    @filter.command("传话筒关闭")
    async def command_chuanhuatong_disable(self, event: AstrMessageEvent):
        """在当前会话禁用传话筒"""
        if not self._check_control_permission(event):
            yield event.plain_result("你没有权限使用此指令。")
            event.stop_event()
            return
        success, message = self._disable_session(event)
        yield event.plain_result(message)
        event.stop_event()

    @filter.command("传话筒状态")
    async def command_chuanhuatong_status(self, event: AstrMessageEvent):
        """查询传话筒当前状态"""
        if not self._check_control_permission(event):
            yield event.plain_result("你没有权限使用此指令。")
            event.stop_event()
            return
        is_enabled = self._is_session_enabled(event)
        whitelist_mode = self._cfg_bool("whitelist_mode", False)
        mode_text = "白名单模式" if whitelist_mode else "黑名单模式"
        status_text = "已启用" if is_enabled else "已禁用"
        session_id = event.unified_msg_origin
        has_custom = self._has_session_layout(session_id)
        if has_custom:
            session_layout = self._load_session_layout(session_id)
            preset_name = session_layout.get("_preset_name") if session_layout else None
            if preset_name:
                current_preset = f"{preset_name}（会话独立配置）"
            else:
                current_preset = "自定义布局（会话独立配置）"
        else:
            current_preset = self._current_preset_name() or "自定义布局（全局配置）"
        persona_id = await self._resolve_current_persona_id(event, None)
        config_type = "会话独立配置" if has_custom else "全局配置"
        persona_binding = "未绑定"
        if persona_id:
            binding_record = self._load_persona_preset_bindings().get(
                self._normalize_persona_binding_id(persona_id)
            )
            if binding_record:
                persona_binding = str(binding_record.get("name") or binding_record.get("slug") or "未命名预设")
        message = (
            f"传话筒状态：{status_text}\n"
            f"模式：{mode_text}\n"
            f"配置类型：{config_type}\n"
            f"当前预设：{current_preset}\n"
            f"当前人格预设绑定：{persona_binding}"
        )
        yield event.plain_result(message)
        event.stop_event()
