from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple

from PIL import Image, ImageEnhance

from .ini_parser import Rect
from .psd_reader import SourceImage, SourceLayer
from .skin_parser import KeySlot, PanelLayout, SkinPackage, StyleImageRef, parse_til_slices


ResizeMode = Literal["stretch", "contain", "cover"]


@dataclass
class KeyLayer:
    """用于导出 PSD 的单个按键图层。"""

    panel_title: str
    key_name: str
    rect: Rect
    image: Image.Image


@dataclass
class PreservedSourceLayer:
    """按源 PSD 图层拆出来的适配后图层。

    这是为“导出后图层也要像原来那样”准备的：同一个源 PSD 图层会被切过所有目标键位，
    再合成回一张目标面板大小的透明层，图层名仍沿用源 PSD。
    """

    panel_title: str
    source_layer_name: str
    image: Image.Image
    visible: bool = True
    opacity: int = 255
    blend_mode: bytes | str = b"norm"
    clipping: bool = False
    group_path: Tuple[str, ...] = ()


@dataclass
class AdaptedPanel:
    """一个面板的适配结果。"""

    panel: PanelLayout
    source_name: str
    preview: Image.Image
    key_layers: List[KeyLayer] = field(default_factory=list)
    preserved_layers: List[PreservedSourceLayer] = field(default_factory=list)


@dataclass
class AdaptResult:
    """一次适配的完整结果。"""

    panels: List[AdaptedPanel]
    replacements: Dict[str, bytes]
    diagnostics: List[str]

    def close(self) -> None:
        for panel in self.panels:
            panel.preview.close()
            for layer in panel.key_layers:
                layer.image.close()
            for layer in panel.preserved_layers:
                layer.image.close()


def image_to_png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _select_source_image(sources: List[SourceImage], panel_key: str) -> SourceImage:
    for source in sources:
        if source.panel_key == panel_key:
            return source
    return sources[0]


def _resize_to_box(image: Image.Image, width: int, height: int, mode: ResizeMode) -> Image.Image:
    """把裁出的源按键图变成目标尺寸。

    - stretch：完全拉伸，最贴近“只改尺寸”的直觉；
    - contain：等比完整放入，四周留透明；
    - cover：等比铺满，超出部分居中裁掉。
    """

    width = max(1, int(width))
    height = max(1, int(height))
    if mode == "stretch":
        return image.resize((width, height), Image.Resampling.LANCZOS)

    src_w, src_h = image.size
    if src_w <= 0 or src_h <= 0:
        return Image.new("RGBA", (width, height), (0, 0, 0, 0))

    if mode == "contain":
        scale = min(width / src_w, height / src_h)
        resized = image.resize((max(1, round(src_w * scale)), max(1, round(src_h * scale))), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        canvas.alpha_composite(resized, ((width - resized.width) // 2, (height - resized.height) // 2))
        resized.close()
        return canvas

    scale = max(width / src_w, height / src_h)
    resized = image.resize((max(1, round(src_w * scale)), max(1, round(src_h * scale))), Image.Resampling.LANCZOS)
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    cropped = resized.crop((left, top, left + width, top + height))
    resized.close()
    return cropped


def _crop_source_key(source: SourceImage, panel: PanelLayout, key: KeySlot) -> Image.Image:
    """按目标键位的相对位置，从源 PSD 渲染图裁出对应区域。

    第一版默认设计图和目标键盘属于同一类面板，例如都为 26 键/9 键/数字键。
    因此用 `目标 VIEW_RECT / 目标面板尺寸` 映射到源图尺寸。后续如果增加“源底包 INI”，
    可以在这里替换成源布局到目标布局的 IoU 匹配。
    """

    src_w, src_h = source.image.size
    sx = src_w / max(1, panel.width)
    sy = src_h / max(1, panel.height)
    source_rect = key.rect.scaled(sx, sy).clamp(src_w, src_h)
    return source.image.crop(source_rect.to_box()).convert("RGBA")


def _make_key_art(source: SourceImage, panel: PanelLayout, key: KeySlot, dest_rect: Rect, mode: ResizeMode) -> Image.Image:
    cropped = _crop_source_key(source, panel, key)
    try:
        return _resize_to_box(cropped, dest_rect.w, dest_rect.h, mode)
    finally:
        cropped.close()


def _crop_source_layer_key(source_layer: SourceLayer, source_rect: Rect, dest_rect: Rect, mode: ResizeMode) -> Image.Image:
    """对单个源 PSD 图层执行同样的键位裁切/缩放。

    注意这里和整图裁切不同：源图层可能只覆盖键位的一小角，所以 `crop_region`
    会保持透明区域，再缩放到目标键位。这能最大程度保留每个小装饰图层的独立性。
    """

    cropped = source_layer.crop_region(source_rect)
    try:
        return _resize_to_box(cropped, dest_rect.w, dest_rect.h, mode)
    finally:
        cropped.close()


def _pressed_variant(image: Image.Image, enabled: bool) -> Image.Image:
    """生成按压态图。

    目前默认只轻微压暗，确保 HL_IMG 不会还是旧包图案。若用户希望完全一致，
    后续可以把 enabled 关掉或在接口里加选项。
    """

    if not enabled:
        return image.copy()
    alpha = image.getchannel("A")
    rgb = image.convert("RGB")
    darker = ImageEnhance.Brightness(rgb).enhance(0.88).convert("RGBA")
    darker.putalpha(alpha)
    return darker


class SkinAdapter:
    """把设计图适配到目标底包。

    这个类是核心流程：它不关心 FastAPI，也不关心 HTML，只输入解析好的皮肤和源图，
    输出预览、PSD 图层素材、以及需要写回 ZIP 的 PNG 文件。
    """

    def __init__(
        self,
        skin: SkinPackage,
        sources: List[SourceImage],
        resize_mode: ResizeMode = "stretch",
        darken_pressed: bool = True,
    ) -> None:
        self.skin = skin
        self.sources = sources
        self.resize_mode = resize_mode
        self.darken_pressed = darken_pressed
        self.diagnostics: List[str] = list(skin.diagnostics)
        self._til_cache: Dict[str, Dict[int, Rect]] = {}
        self._atlas_cache: Dict[str, Image.Image] = {}

    def close(self) -> None:
        for image in self._atlas_cache.values():
            image.close()
        self._atlas_cache.clear()

    def _get_til_slices(self, ref: StyleImageRef) -> Dict[int, Rect]:
        if ref.til_path in self._til_cache:
            return self._til_cache[ref.til_path]
        til_text = self.skin.archive.read_text(ref.til_path)
        if not til_text:
            self.diagnostics.append(f"未找到 TIL: {ref.til_path}")
            self._til_cache[ref.til_path] = {}
            return {}
        slices = parse_til_slices(til_text)
        self._til_cache[ref.til_path] = slices
        return slices

    def _get_atlas(self, path: str) -> Optional[Image.Image]:
        if path in self._atlas_cache:
            return self._atlas_cache[path]
        data = self.skin.archive.read_binary(path)
        if not data:
            self.diagnostics.append(f"未找到 PNG 图集: {path}")
            return None
        try:
            with Image.open(io.BytesIO(data)) as raw:
                image = raw.convert("RGBA")
        except Exception as exc:
            self.diagnostics.append(f"PNG 图集读取失败: {path} ({exc})")
            return None
        self._atlas_cache[path] = image
        return image

    def _paste_key_into_atlas(self, ref: StyleImageRef, key_image: Image.Image) -> None:
        slices = self._get_til_slices(ref)
        tile_rect = slices.get(ref.tile_index)
        if not tile_rect:
            self.diagnostics.append(f"{ref.til_path}: IMG{ref.tile_index} 不存在")
            return

        atlas = self._get_atlas(ref.png_path)
        if atlas is None:
            return

        tile_image = _resize_to_box(key_image, tile_rect.w, tile_rect.h, self.resize_mode)
        try:
            if ref.prop == "HL_IMG":
                pressed = _pressed_variant(tile_image, self.darken_pressed)
                try:
                    atlas.alpha_composite(pressed, (tile_rect.x, tile_rect.y))
                finally:
                    pressed.close()
            else:
                atlas.alpha_composite(tile_image, (tile_rect.x, tile_rect.y))
        finally:
            tile_image.close()

    def adapt(self) -> AdaptResult:
        adapted_panels: List[AdaptedPanel] = []

        for panel in self.skin.panels:
            source = _select_source_image(self.sources, panel.panel_key)
            preview = Image.new("RGBA", (panel.width, panel.height), (0, 0, 0, 0))
            key_layers: List[KeyLayer] = []
            preserved_layers: List[PreservedSourceLayer] = [
                PreservedSourceLayer(
                    panel_title=panel.title,
                    source_layer_name=source_layer.name,
                    image=Image.new("RGBA", (panel.width, panel.height), (0, 0, 0, 0)),
                    visible=source_layer.visible,
                    opacity=source_layer.opacity,
                    blend_mode=source_layer.blend_mode,
                    clipping=source_layer.clipping,
                    group_path=source_layer.group_path,
                )
                for source_layer in source.layers
            ]
            src_w, src_h = source.image.size
            sx = src_w / max(1, panel.width)
            sy = src_h / max(1, panel.height)

            for key in panel.keys:
                source_rect = key.rect.scaled(sx, sy).clamp(src_w, src_h)
                key_art = _make_key_art(source, panel, key, key.rect, self.resize_mode)
                preview.alpha_composite(key_art, (key.rect.x, key.rect.y))
                key_layers.append(
                    KeyLayer(
                        panel_title=panel.title,
                        key_name=key.debug_name,
                        rect=key.rect,
                        image=key_art.copy(),
                    )
                )

                for source_layer, preserved_layer in zip(source.layers, preserved_layers):
                    layer_piece = _crop_source_layer_key(source_layer, source_rect, key.rect, self.resize_mode)
                    try:
                        if layer_piece.getbbox():
                            preserved_layer.image.alpha_composite(layer_piece, (key.rect.x, key.rect.y))
                    finally:
                        layer_piece.close()

                # 写回底包时不直接用 VIEW_RECT，而是贴到 BACK_STYLE 指向的 PNG/TIL 切片里。
                for ref in key.style_refs:
                    self._paste_key_into_atlas(ref, key_art)
                key_art.close()

            adapted_panels.append(
                AdaptedPanel(
                    panel=panel,
                    source_name=source.name,
                    preview=preview,
                    key_layers=key_layers,
                    preserved_layers=preserved_layers,
                )
            )

        replacements = {
            path: image_to_png_bytes(image)
            for path, image in self._atlas_cache.items()
        }
        return AdaptResult(
            panels=adapted_panels,
            replacements=replacements,
            diagnostics=self.diagnostics,
        )
