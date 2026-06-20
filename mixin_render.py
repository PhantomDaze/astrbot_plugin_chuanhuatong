"""Rendering mixin — Pillow pipeline, drawing helpers, font utils, color parsing, image merge."""

import asyncio
import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from astrbot.api import logger
from PIL import Image, ImageDraw, ImageFilter, ImageFont


class RenderMixin:
    """Mixin providing Pillow rendering pipeline, drawing helpers, font utilities, and color parsing."""

    # ---- Rendering Pipeline ----

    async def _render_with_fallback(
        self,
        text: str,
        emotion: str,
        session_id: Optional[str] = None,
        persona_id: Optional[str] = None,
    ) -> Optional[str]:
        try:
            return await asyncio.to_thread(
                self._render_pillow_panel, text, emotion, session_id, persona_id
            )
        except Exception as exc:
            logger.error("[传话筒] Pillow 渲染异常: %s", exc, exc_info=True)
            return None

    def _render_pillow_panel(
        self,
        text: str,
        emotion: str,
        session_id: Optional[str] = None,
        persona_id: Optional[str] = None,
    ) -> Optional[str]:
        layout = self._layout(session_id, persona_id)
        width = int(layout.get("canvas_width", 1280))
        height = int(layout.get("canvas_height", 720))
        bg_color = self._hex_or_rgba(layout.get("background_color", "#05060A"))
        canvas = Image.new("RGBA", (width, height), bg_color)

        bg_group = layout.get("background_group")
        bg_path = self._resolve_background_asset(layout.get("background_asset"), bg_group)
        if bg_path:
            try:
                bg_img = Image.open(bg_path).convert("RGBA").resize((width, height), Image.LANCZOS)
                canvas.alpha_composite(bg_img)
            except Exception:
                logger.debug("[传话筒] 背景加载失败", exc_info=True)

        draw = ImageDraw.Draw(canvas)

        layers: list[tuple[int, dict[str, Any]]] = []
        char_path = self._resolve_character_asset(
            layout.get("character_asset"),
            emotion,
            layout.get("character_role"),
        )
        if char_path:
            layers.append((int(layout.get("character_z_index", 150)), {"kind": "character", "path": char_path}))
        layers.append((int(layout.get("textbox_z_index", 200)), {"kind": "textbox", "text": text}))
        for overlay in layout.get("text_overlays", []):
            layers.append((int(overlay.get("z_index", 300)), {"kind": overlay.get("type", "text"), "overlay": overlay}))
        layers.sort(key=lambda item: item[0])

        for _, layer in layers:
            kind = layer.get("kind")
            if kind == "character":
                self._draw_character_layer(canvas, layer.get("path"), layout)
            elif kind == "textbox":
                self._draw_textbox_layer(canvas, layout, layer.get("text", ""))
            elif kind == "text":
                self._draw_overlay_text(canvas, layer.get("overlay"))
            elif kind == "glass":
                self._draw_glass_layer(canvas, layer.get("overlay"))
            elif kind == "image":
                self._draw_overlay_image(canvas, layer.get("overlay"))

        tmp = tempfile.NamedTemporaryFile(prefix="tranhua_", suffix=".jpeg", delete=False)
        quality = int(self.cfg().get("image_quality", 85) or 85)
        quality = max(1, min(100, quality))
        canvas.convert("RGB").save(tmp.name, format="JPEG", quality=quality, optimize=False)
        return tmp.name

    # ---- Cleanup ----

    def _cleanup_temp_file(self, path: Optional[str]):
        if not path:
            return
        try:
            os.remove(path)
        except FileNotFoundError:
            return
        except Exception as exc:
            logger.debug("[传话筒] 删除临时文件失败: %s", exc)

    async def _delayed_cleanup(self, path: str, delay: float = 30.0):
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        self._cleanup_temp_file(path)

    def _schedule_cleanup(self, path: Optional[str], delay: float = 30.0):
        if not path:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._cleanup_temp_file(path)
            return
        task = loop.create_task(self._delayed_cleanup(path, delay))
        self._cleanup_tasks.add(task)

        def _remove(_):
            self._cleanup_tasks.discard(task)

        task.add_done_callback(_remove)

    # ---- Pillow Drawing Helpers ----

    def _draw_character_layer(self, canvas: Image.Image, path: Optional[str], layout: Dict[str, Any]):
        if not path:
            return
        try:
            img = Image.open(path).convert("RGBA")
            fit_mode = str(layout.get("character_fit_mode", "fixed_width")).lower()
            align_bottom = layout.get("character_align_bottom", True)

            if fit_mode == "uniform_height":
                target_h = max(1, int(layout.get("character_uniform_height", 620)))
                ratio = target_h / max(1, img.height)
                target_w = max(1, int(img.width * ratio))
            else:
                target_w = max(1, int(layout.get("character_width", 520)))
                ratio = target_w / max(1, img.width)
                target_h = max(1, int(img.height * ratio))

            img = img.resize((target_w, target_h), Image.LANCZOS)

            anchor = layout.get("character_anchor", "left-top")
            left_raw = int(layout.get("character_left", 40))

            if align_bottom:
                bottom_raw = int(layout.get("character_bottom", 0))
                if anchor == "center":
                    final_x = canvas.width // 2 + left_raw
                    final_y = canvas.height // 2 - target_h // 2 - bottom_raw
                elif anchor == "right-bottom":
                    final_x = canvas.width - target_w + left_raw
                    final_y = canvas.height - target_h - bottom_raw
                else:
                    final_x = canvas.width + left_raw if left_raw < 0 else left_raw
                    if bottom_raw >= 0:
                        final_y = canvas.height - target_h - bottom_raw
                    else:
                        final_y = canvas.height - target_h + abs(bottom_raw)
            else:
                top_raw = int(layout.get("character_top", 0))
                if anchor == "center":
                    final_x = canvas.width // 2 + left_raw
                    final_y = canvas.height // 2 - target_h // 2 + top_raw
                elif anchor == "right-bottom":
                    final_x = canvas.width - target_w + left_raw
                    final_y = canvas.height - target_h + top_raw
                else:
                    final_x = canvas.width + left_raw if left_raw < 0 else left_raw
                    if top_raw >= 0:
                        final_y = top_raw
                    else:
                        final_y = top_raw

            canvas.alpha_composite(img, (final_x, final_y))
        except Exception:
            logger.debug("[传话筒] 立绘渲染失败", exc_info=True)

    def _draw_textbox_layer(self, canvas: Image.Image, layout: Dict[str, Any], text: str):
        anchor = layout.get("box_anchor", "left-top")
        box_left = int(layout.get("box_left", 520))
        box_top = int(layout.get("box_top", 160))
        box_width = max(20, int(layout.get("box_width", 640)))
        box_height = max(20, int(layout.get("box_height", 340)))
        padding = max(0, int(layout.get("padding", 28)))
        stroke_width = max(0, int(layout.get("text_stroke_width", 0)))
        stroke_color = self._hex_or_rgba(layout.get("text_stroke_color", "#000000"))

        if anchor == "center":
            final_left = canvas.width // 2 + box_left
            final_top = canvas.height // 2 + box_top
        elif anchor == "right-bottom":
            final_left = canvas.width - box_width + box_left
            final_top = canvas.height - box_height + box_top
        else:
            final_left = canvas.width + box_left if box_left < 0 else box_left
            final_top = canvas.height + box_top if box_top < 0 else box_top

        font = self._load_font(layout.get("font_size", 30), preferred=layout.get("body_font"))
        text_area_w = max(10, box_width - padding * 2)
        wrapped = self._wrap_text(text, font, max(10, text_area_w))
        spacing = max(0, int(font.size * (float(layout.get("line_height", 1.6)) - 1)))
        self._draw_rich_text(
            canvas,
            (final_left + padding, final_top + padding),
            wrapped,
            font,
            self._hex_or_rgba(layout.get("text_color", "#FFFFFF")),
            stroke_width=stroke_width,
            stroke_fill=stroke_color,
            spacing=spacing,
        )

    def _draw_rich_text(
        self,
        canvas: Image.Image,
        position: tuple[int, int],
        text: str,
        font: ImageFont.ImageFont,
        fill: tuple[int, int, int, int],
        stroke_width: int = 0,
        stroke_fill: tuple[int, int, int, int] = (0, 0, 0, 255),
        spacing: int = 0,
    ):
        if not text:
            return
        draw = ImageDraw.Draw(canvas)
        fallback_fonts = self._system_font_candidates(getattr(font, "size", 30))
        x, y = position
        line_gap = max(0, int(spacing))
        for line in text.replace("\r", "").split("\n"):
            if line:
                line_height = self._draw_text_line(
                    draw,
                    (x, y),
                    line,
                    font,
                    fallback_fonts,
                    fill,
                    stroke_width=stroke_width,
                    stroke_fill=stroke_fill,
                )
            else:
                ascent, descent = self._font_metrics(font)
                line_height = ascent + descent
            y += line_height + line_gap

    def _draw_overlay_text(self, canvas: Image.Image, overlay: Optional[Dict[str, Any]]):
        if not overlay or not overlay.get("visible", True):
            return
        text_val = overlay.get("text", "")
        if not text_val:
            return
        left = int(overlay.get("left", 0))
        top = int(overlay.get("top", 0))
        width_o = max(10, int(overlay.get("width", 200)))
        font = self._load_font(overlay.get("font_size", 26), preferred=overlay.get("font"), bold=overlay.get("bold", True))
        text_tip = self._wrap_text(text_val, font, width_o)
        stroke_width = max(0, int(overlay.get("stroke_width", 0)))
        stroke_color = self._hex_or_rgba(overlay.get("stroke_color", "#000000"))
        self._draw_rich_text(
            canvas,
            (left, top),
            text_tip,
            font,
            self._hex_or_rgba(overlay.get("color", "#FFFFFF")),
            stroke_width=stroke_width,
            stroke_fill=stroke_color,
        )

    def _draw_glass_layer(self, canvas: Image.Image, overlay: Optional[Dict[str, Any]]):
        if not overlay or not overlay.get("visible", True):
            return
        left = int(overlay.get("left", 0))
        top = int(overlay.get("top", 0))
        width_o = max(20, int(overlay.get("width", 200)))
        height_o = max(20, int(overlay.get("height", 60)))
        radius_raw = int(overlay.get("radius", 8))
        radius = max(0, min(radius_raw, min(width_o, height_o) // 2))
        blur_strength = max(2, int(overlay.get("glass_strength", 12)))
        opacity = float(overlay.get("opacity", 1.0))
        bg_color = self._parse_rgba(overlay.get("bg_color", "rgba(255,255,255,0.1)"))
        rect = (left, top, left + width_o, top + height_o)
        region = canvas.crop(rect)
        region = region.filter(ImageFilter.GaussianBlur(blur_strength))
        overlay_img = Image.new("RGBA", (width_o, height_o), bg_color)
        region = Image.alpha_composite(region, overlay_img)
        mask = Image.new("L", (width_o, height_o), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle((0, 0, width_o, height_o), radius=radius, fill=255)
        if opacity < 1.0:
            alpha = region.split()[3].point(lambda a: int(a * max(0.0, min(1.0, opacity))))
            region.putalpha(alpha)
        canvas.paste(region, (left, top), mask)

    def _draw_overlay_image(self, canvas: Image.Image, overlay: Optional[Dict[str, Any]]):
        if not overlay or not overlay.get("visible", True):
            return
        image_name = overlay.get("image")
        path = self._resolve_component_path(image_name)
        if not path:
            return
        try:
            img = Image.open(path).convert("RGBA")
            width_o = int(overlay.get("width", img.width))
            height_o = int(overlay.get("height", img.height))
            if width_o > 0 and height_o > 0:
                img = img.resize((width_o, height_o), Image.LANCZOS)
            opacity = float(overlay.get("opacity", 1.0))
            if opacity < 1.0:
                alpha = img.split()[3].point(lambda a: int(a * max(0.0, min(1.0, opacity))))
                img.putalpha(alpha)
            left = int(overlay.get("left", 0))
            top = int(overlay.get("top", 0))
            canvas.alpha_composite(img, (left, top))
        except Exception:
            logger.debug("[传话筒] 自定义组件渲染失败", exc_info=True)

    # ---- Image Merge ----

    def _merge_images_vertical(
        self,
        image_paths: list[str],
        gap: int = 10,
        background_color: Optional[str] = None
    ) -> Optional[str]:
        if not image_paths:
            return None
        if len(image_paths) == 1:
            return image_paths[0]
        images = []
        try:
            for p in image_paths:
                images.append(Image.open(p))
            max_width = max(img.width for img in images)
            total_height = sum(img.height for img in images) + gap * (len(images) - 1)
            if background_color:
                bg_color = self._hex_or_rgba(background_color)[:3]
            else:
                bg_color = (0, 0, 0)
            merged = Image.new("RGB", (max_width, total_height), bg_color)
            y_offset = 0
            for img in images:
                if img.mode != "RGB":
                    img_converted = img.convert("RGB")
                else:
                    img_converted = img
                x_offset = (max_width - img_converted.width) // 2
                merged.paste(img_converted, (x_offset, y_offset))
                y_offset += img.height + gap
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpeg") as f:
                out_path = f.name
            quality = int(self.cfg().get("image_quality", 85) or 85)
            quality = max(1, min(100, quality))
            merged.save(out_path, "JPEG", quality=quality, optimize=False)
            logger.debug("[传话筒] 图片合并完成: %s 张 -> %s", len(images), out_path)
            return out_path
        except Exception as exc:
            logger.error("[传话筒] 图片合并失败: %s", exc)
            return None
        finally:
            for img in images:
                try:
                    img.close()
                except Exception:
                    pass

    # ---- Font & Text Utilities ----

    def _load_font(self, size: int, preferred: Optional[str] = None, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        font_path = str(self.cfg().get("font_path") or "").strip()
        candidates: list[str] = []
        if preferred:
            resolved = self._resolve_font_path(preferred)
            if resolved:
                candidates.append(resolved)
        if font_path:
            resolved = self._resolve_font_path(font_path)
            if resolved:
                candidates.append(resolved)
        if os.name == "nt":
            candidates.extend([
                "C:/Windows/Fonts/msyh.ttc",
                "C:/Windows/Fonts/msyh.ttf",
                "C:/Windows/Fonts/simhei.ttf",
                "C:/Windows/Fonts/seguiemj.ttf",
            ])
        else:
            candidates.extend([
                "/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/Hiragino Sans GB.ttc",
                "/System/Library/Fonts/Apple Color Emoji.ttc",
                "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ])
        for path in candidates:
            if not path:
                continue
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
        return ImageFont.load_default()

    @lru_cache(maxsize=16)
    def _system_font_candidates(self, size: int) -> tuple[ImageFont.ImageFont, ...]:
        candidates: list[ImageFont.ImageFont] = []
        if os.name == "nt":
            paths = [
                "C:/Windows/Fonts/seguiemj.ttf",
                "C:/Windows/Fonts/msyh.ttc",
                "C:/Windows/Fonts/simhei.ttf",
                "C:/Windows/Fonts/msgothic.ttc",
            ]
        else:
            paths = [
                "/System/Library/Fonts/Apple Color Emoji.ttc",
                "/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/Hiragino Sans GB.ttc",
                "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
        for path in paths:
            try:
                candidates.append(ImageFont.truetype(path, size=size))
            except Exception:
                continue
        if not candidates:
            candidates.append(ImageFont.load_default())
        return tuple(candidates)

    def _glyph_uses_font(self, font: ImageFont.ImageFont, char: str) -> bool:
        if not char or char.isspace():
            return True
        try:
            bbox = font.getbbox(char)
            if not bbox:
                return False
            return (bbox[2] - bbox[0]) > 0 and (bbox[3] - bbox[1]) > 0
        except Exception:
            try:
                return bool(font.getmask(char).getbbox())
            except Exception:
                return False

    def _font_for_char(self, primary: ImageFont.ImageFont, char: str, fallback_fonts: tuple[ImageFont.ImageFont, ...]) -> ImageFont.ImageFont:
        if self._glyph_uses_font(primary, char):
            return primary
        for fallback in fallback_fonts:
            if fallback is primary:
                continue
            if self._glyph_uses_font(fallback, char):
                return fallback
        return primary

    def _text_clusters(self, text: str) -> list[str]:
        import unicodedata
        clusters: list[str] = []
        if not text:
            return clusters
        current = ""
        join_next = False
        for char in text:
            if not current:
                current = char
                join_next = char == "‍"
                continue
            if join_next:
                current += char
                join_next = char == "‍"
                continue
            category = unicodedata.category(char)
            if char == "‍" or category in {"Mn", "Me", "Cf"} or "︀" <= char <= "️" or "\U0001F3FB" <= char <= "\U0001F3FF":
                current += char
                join_next = char == "‍"
                continue
            clusters.append(current)
            current = char
            join_next = char == "‍"
        if current:
            clusters.append(current)
        return clusters

    def _font_metrics(self, font: ImageFont.ImageFont) -> tuple[int, int]:
        try:
            ascent, descent = font.getmetrics()
            return int(ascent), int(descent)
        except Exception:
            size = int(getattr(font, "size", 30) or 30)
            return size, max(1, size // 4)

    def _split_text_runs(
        self,
        text: str,
        primary: ImageFont.ImageFont,
        fallback_fonts: tuple[ImageFont.ImageFont, ...],
    ) -> list[tuple[str, ImageFont.ImageFont]]:
        runs: list[tuple[str, ImageFont.ImageFont]] = []
        if not text:
            return runs
        current_font: Optional[ImageFont.ImageFont] = None
        current_text = ""
        for cluster in self._text_clusters(text):
            char_font = self._font_for_char(primary, cluster, fallback_fonts)
            if current_font is char_font:
                current_text += cluster
                continue
            if current_text:
                runs.append((current_text, current_font or primary))
            current_font = char_font
            current_text = cluster
        if current_text:
            runs.append((current_text, current_font or primary))
        return runs

    def _draw_text_line(
        self,
        draw: ImageDraw.ImageDraw,
        position: tuple[int, int],
        text: str,
        primary: ImageFont.ImageFont,
        fallback_fonts: tuple[ImageFont.ImageFont, ...],
        fill: tuple[int, int, int, int],
        stroke_width: int = 0,
        stroke_fill: tuple[int, int, int, int] = (0, 0, 0, 255),
    ) -> int:
        runs = self._split_text_runs(text, primary, fallback_fonts)
        if not runs:
            return 0
        metrics = [self._font_metrics(font) for _, font in runs]
        line_ascent = max(ascent for ascent, _ in metrics)
        line_descent = max(descent for _, descent in metrics)
        x, y = position
        cursor_x = x
        for (run_text, run_font), (ascent, _) in zip(runs, metrics):
            run_y = y + (line_ascent - ascent)
            draw.text(
                (cursor_x, run_y),
                run_text,
                font=run_font,
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill,
            )
            cursor_x += int(round(self._measure_text_width(draw, run_text, run_font)))
        return line_ascent + line_descent

    def _measure_text_width(self, draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> float:
        if not text:
            return 0.0
        try:
            return float(draw.textlength(text, font=font))
        except Exception:
            try:
                bbox = draw.textbbox((0, 0), text, font=font)
                return float(bbox[2] - bbox[0]) if bbox else 0.0
            except Exception:
                return 0.0

    def _wrap_text(self, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
        if not text:
            return ""
        fallback_fonts = self._system_font_candidates(getattr(font, "size", 30))
        draw = ImageDraw.Draw(Image.new("RGBA", (max_width, 10)))
        lines: list[str] = []
        for paragraph in text.splitlines():
            if not paragraph:
                lines.append("")
                continue
            current = ""
            current_width = 0.0
            for char in paragraph:
                char_font = self._font_for_char(font, char, fallback_fonts)
                char_width = self._measure_text_width(draw, char, char_font)
                if current and current_width + char_width > max_width:
                    lines.append(current)
                    current = char
                    current_width = self._measure_text_width(draw, char, char_font)
                else:
                    current += char
                    current_width += char_width
            if current:
                lines.append(current)
        return "\n".join(lines)

    # ---- Color Parsing ----

    def _parse_rgba(self, value: str) -> tuple[int, int, int, int]:
        value = (value or "").strip().lower()
        if value.startswith("rgba"):
            nums = value[value.find("(") + 1:value.find(")")].split(",")
            r, g, b = [int(float(nums[i])) for i in range(3)]
            a = float(nums[3]) if len(nums) > 3 else 1
            return (r, g, b, int(a * 255))
        return self._hex_or_rgba(value)

    def _hex_or_rgba(self, value: str) -> tuple[int, int, int, int]:
        value = (value or "#FFFFFF").strip()
        if value.startswith("#") and len(value) in {4, 7}:
            if len(value) == 4:
                value = "#" + "".join(ch * 2 for ch in value[1:])
            r = int(value[1:3], 16)
            g = int(value[3:5], 16)
            b = int(value[5:7], 16)
            return (r, g, b, 255)
        return (255, 255, 255, 255)
