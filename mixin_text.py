"""Text processing mixin — emotion tag removal, markdown cleanup, text splitting, chain utilities."""

import asyncio
import json
import re
from typing import Any, Optional, Tuple

from astrbot.api import logger
from astrbot.core.message.message_event_result import MessageChain
from astrbot.api.event import AstrMessageEvent

from models import PLAIN_COMPONENT_TYPES, LINEBREAK_COMPONENT


class TextMixin:
    """Mixin providing text processing, splitting, and message chain utilities."""

    # ---- Emotion Tags ----

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

    # ---- Text Splitting & Merging ----

    def _count_visible_chars(self, text: str) -> int:
        if not text:
            return 0
        return len(text.replace("\r", "").replace("\n", "").strip())

    def _smart_split_text(self, text: str, max_chars: int) -> list[str]:
        if not text or len(text) <= max_chars:
            return [text] if text else []
        chunks = []
        paragraphs = text.split('\n\n')
        current_chunk = ""
        for para in paragraphs:
            test_chunk = current_chunk + ('\n\n' if current_chunk else '') + para
            if len(test_chunk) <= max_chars:
                current_chunk = test_chunk
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = ""
                if len(para) > max_chars:
                    chunks.extend(self._sentence_split(para, max_chars))
                else:
                    current_chunk = para
        if current_chunk:
            chunks.append(current_chunk.strip())
        return chunks

    def _sentence_split(self, text: str, max_chars: int) -> list[str]:
        if not text or max_chars <= 0:
            return [text] if text else []
        pattern = r'([。！？\n])\s*'
        parts = re.split(pattern, text)
        chunks = []
        current = ""
        i = 0
        while i < len(parts):
            sentence = parts[i]
            punctuation = parts[i + 1] if i + 1 < len(parts) else ""
            full_sentence = sentence + punctuation
            if len(current) + len(full_sentence) <= max_chars:
                current += full_sentence
            else:
                if current:
                    chunks.append(current.strip())
                if len(full_sentence) > max_chars:
                    chunks.extend(self._hard_split(full_sentence, max_chars))
                    current = ""
                else:
                    current = full_sentence
            i += 2
        if current:
            chunks.append(current.strip())
        return [c for c in chunks if c]

    def _hard_split(self, text: str, max_chars: int) -> list[str]:
        if not text or len(text) <= max_chars:
            return [text] if text else []
        return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]

    def _split_text_with_emotion(
        self,
        text: str,
        max_chars: int,
        default_emotion: str
    ) -> list[Tuple[str, str]]:
        mapping = self._emotion_meta()
        emotion_positions: list[Tuple[int, str]] = []
        for match in self.EMOTION_PATTERN.finditer(text):
            emotion_key = match.group(1).lower()
            if emotion_key in mapping:
                emotion_positions.append((match.start(), emotion_key))
        clean_text = self._remove_emotion_tags(text)
        clean_text = self._remove_markdown_syntax(clean_text)
        clean_text = re.sub(r'\n{2,}', '\n', clean_text)
        lines = clean_text.split('\n')
        lines = [line.rstrip() for line in lines]
        clean_text = '\n'.join(lines)
        clean_text = clean_text.strip()
        chunks = self._smart_split_text(clean_text, max_chars)
        result = []
        current_emotion = default_emotion or next(iter(mapping.keys()), "neutral")
        char_offset = 0
        for chunk in chunks:
            chunk_start = char_offset
            chunk_end = char_offset + len(chunk)
            chunk_emotion = None
            for pos, emo in emotion_positions:
                if chunk_start <= pos < chunk_end:
                    chunk_emotion = emo
                    break
            if chunk_emotion:
                current_emotion = chunk_emotion
            result.append((chunk, current_emotion))
            char_offset = chunk_end
        return result

    async def _send_fallback_texts(
        self,
        fallback_texts: list[Tuple[int, str]],
        event: AstrMessageEvent
    ) -> None:
        for idx, chunk_text in fallback_texts:
            try:
                chain = MessageChain()
                chain.message(f"{chunk_text}\n")
                await event.send(chain)
            except Exception:
                logger.warning("[传话筒] 发送降级文本失败", exc_info=True)

    async def _render_split_text(
        self,
        text: str,
        emotion: str,
        event: AstrMessageEvent,
        session_id: Optional[str] = None,
        persona_id: Optional[str] = None,
    ) -> bool:
        char_limit = int(self.cfg().get("render_char_threshold", 60) or 0)
        if char_limit <= 0:
            char_limit = 200
        chunks_with_emotion = self._split_text_with_emotion(text, char_limit, emotion)
        if not chunks_with_emotion:
            return False
        if len(chunks_with_emotion) <= 1:
            clean_text = chunks_with_emotion[0][0]
            chunk_emotion = chunks_with_emotion[0][1] if chunks_with_emotion[0][1] else emotion
            image_path = await self._render_with_fallback(clean_text, chunk_emotion, session_id, persona_id)
            if image_path:
                try:
                    chain = MessageChain()
                    chain.file_image(image_path)
                    await event.send(chain)
                    self._schedule_cleanup(image_path, delay=90.0)
                    return True
                except Exception:
                    logger.error("[传话筒] 单块路径发送图片失败", exc_info=True)
                    return False
            return False
        logger.info("[传话筒] 分割文本为 %s 个片段进行渲染", len(chunks_with_emotion))
        rendered_images: list[str] = []
        fallback_texts: list[Tuple[int, str]] = []
        for idx, (chunk_text, chunk_emotion) in enumerate(chunks_with_emotion, 1):
            try:
                image_path = await self._render_with_fallback(chunk_text, chunk_emotion, session_id, persona_id)
                if image_path:
                    rendered_images.append(image_path)
                else:
                    fallback_texts.append((idx, chunk_text))
            except Exception as exc:
                logger.error("[传话筒] 渲染第 %s 段失败: %s", idx, exc, exc_info=True)
                fallback_texts.append((idx, chunk_text))
        if not rendered_images:
            await self._send_fallback_texts(fallback_texts, event)
            return False
        enable_merge = self._cfg_bool("merge_split_images", True)
        if enable_merge and len(rendered_images) > 1:
            max_per_batch = int(self.cfg().get("merge_max_images", 5) or 5)
            if max_per_batch <= 0:
                max_per_batch = 5
            batches = [
                rendered_images[i:i + max_per_batch]
                for i in range(0, len(rendered_images), max_per_batch)
            ]
            logger.info("[传话筒] 分 %s 批合并图片（每批最多 %s 张）", len(batches), max_per_batch)
            success_count = 0
            for batch_idx, batch in enumerate(batches, 1):
                if len(batch) == 1:
                    try:
                        chain = MessageChain()
                        chain.file_image(batch[0])
                        await event.send(chain)
                        self._schedule_cleanup(batch[0], delay=90.0)
                        success_count += 1
                    except Exception:
                        logger.error("[传话筒] 第 %s 批单图发送失败", batch_idx, exc_info=True)
                else:
                    merged_path = await asyncio.to_thread(self._merge_images_vertical, batch)
                    if merged_path:
                        try:
                            chain = MessageChain()
                            chain.file_image(merged_path)
                            await event.send(chain)
                            for path in batch:
                                self._schedule_cleanup(path, delay=5.0)
                            self._schedule_cleanup(merged_path, delay=90.0)
                            success_count += 1
                        except Exception:
                            logger.error("[传话筒] 第 %s 批合并图发送失败", batch_idx, exc_info=True)
                    else:
                        logger.warning("[传话筒] 第 %s 批合并失败，逐张发送", batch_idx)
                        for path in batch:
                            try:
                                chain = MessageChain()
                                chain.file_image(path)
                                await event.send(chain)
                                self._schedule_cleanup(path, delay=90.0)
                                success_count += 1
                            except Exception:
                                logger.error("[传话筒] 第 %s 批逐图发送失败", batch_idx, exc_info=True)
            await self._send_fallback_texts(fallback_texts, event)
            logger.info("[传话筒] 合并图片发送完成")
            return success_count > 0
        for image_path in rendered_images:
            try:
                chain = MessageChain()
                chain.file_image(image_path)
                await event.send(chain)
                self._schedule_cleanup(image_path, delay=90.0)
            except Exception:
                logger.error("[传话筒] 逐图发送失败", exc_info=True)
        await self._send_fallback_texts(fallback_texts, event)
        return len(rendered_images) > 0

    # ---- Message Chain Utilities ----

    def _chain_to_plain_text(self, chain: list[Any]) -> Optional[str]:
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

    def _extract_llm_text(self, resp) -> str:
        for attr in ("text", "output_text", "content"):
            value = getattr(resp, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        result_chain = getattr(resp, "result_chain", None)
        if result_chain and getattr(result_chain, "chain", None):
            text = self._chain_to_plain_text(result_chain.chain)
            if text:
                return text
        return ""

    def _extract_user_plaintext(self, event: AstrMessageEvent, req) -> str:
        candidates: list[str] = []
        for attr in ("plain_text", "text", "message", "content"):
            val = getattr(event, attr, None)
            if isinstance(val, str):
                candidates.append(val)
        chain = getattr(event, "message_chain", None)
        if isinstance(chain, list):
            parsed = self._chain_to_plain_text(chain)
            if parsed:
                candidates.append(parsed)
        if req:
            for attr in ("input_text", "user_input", "query", "prompt", "text"):
                val = getattr(req, attr, None)
                if isinstance(val, str):
                    candidates.append(val)
        for text in candidates:
            if text and text.strip():
                return text.strip()
        return ""

    async def _update_conversation_history(self, event: AstrMessageEvent, cleaned_text: str):
        try:
            umo = event.unified_msg_origin
            conv_mgr = self.context.conversation_manager
            curr_cid = await conv_mgr.get_curr_conversation_id(umo)
            if not curr_cid:
                return
            conversation = await conv_mgr.get_conversation(umo, curr_cid, create_if_not_exists=False)
            if not conversation or not conversation.history:
                return
            try:
                history = json.loads(conversation.history) if isinstance(conversation.history, str) else conversation.history
                if not isinstance(history, list) or not history:
                    return
                last_msg = history[-1]
                if isinstance(last_msg, dict) and last_msg.get("role") == "assistant":
                    original_content = last_msg.get("content", "")
                    if original_content != cleaned_text:
                        last_msg["content"] = cleaned_text
                        await conv_mgr.update_conversation(umo, curr_cid, history=history)
                        logger.debug("[传话筒] 已更新对话历史，移除表情标签")
            except Exception as e:
                logger.debug("[传话筒] 更新对话历史失败: %s", e)
        except Exception as e:
            logger.debug("[传话筒] 清理对话历史中的表情标签失败: %s", e)
