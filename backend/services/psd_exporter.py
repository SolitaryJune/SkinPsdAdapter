from __future__ import annotations

import io
import re
from typing import Literal

from .adapter import AdaptResult


PsdLayerMode = Literal["source_layers", "panel_layers", "key_layers"]


def _safe_layer_name(name: str, max_length: int = 80) -> str:
    cleaned = re.sub(r"[\r\n\t]+", " ", name).strip()
    return cleaned[:max_length] or "Layer"


def _append_pixel_layer(
    parent,
    pixel_layer_cls,
    image,
    name: str,
    top: int,
    left: int,
    *,
    visible: bool = True,
    opacity: int = 255,
    blend_mode: bytes | str = b"norm",
    clipping: bool = False,
) -> None:
    """创建并追加一个 PSD 像素图层。

    `psd-tools` 的 `layer.name` setter 会同时写旧版 Pascal 名称和 Unicode 名称块。
    这一步很重要：中文图层名如果只写旧版字段，在部分 PSD 读写场景里会乱码或保存失败。
    """

    layer = pixel_layer_cls.frompil(
        image,
        parent,
        "Layer",
        top=top,
        left=left,
    )
    layer.name = _safe_layer_name(name, max_length=255)
    layer.visible = visible
    layer.opacity = max(0, min(255, int(opacity)))
    layer.blend_mode = blend_mode or b"norm"
    layer.clipping = bool(clipping)
    parent.append(layer)


def _new_group(psd, group_cls, name: str):
    """新建一个面板文件夹，并用 Unicode 名称保存中文路径/标题。"""

    group = group_cls.new(parent=psd, name="Group", open_folder=True)
    group.name = _safe_layer_name(name, max_length=255)
    return group


def _parent_for_group_path(root_parent, group_cls, group_cache: dict[tuple[int, tuple[str, ...]], object], group_path: tuple[str, ...]):
    """按源 PSD 文件夹路径创建/复用导出文件夹。

    `source_layers` 需要尽量像原稿的图层面板；叶子层之外的组目录不能完全丢掉。
    这里用 root parent 的 id 区分不同面板，避免 dark/light 两套面板复用到同一个组对象。
    """

    parent = root_parent
    current_path: tuple[str, ...] = ()
    for group_name in group_path:
        current_path += (group_name,)
        cache_key = (id(root_parent), current_path)
        if cache_key not in group_cache:
            group_cache[cache_key] = _new_group(parent, group_cls, group_name)
        parent = group_cache[cache_key]
    return parent


def export_adapted_psd(result: AdaptResult, mode: PsdLayerMode = "source_layers") -> bytes:
    """导出重建版 PSD。

    `source_layers` 模式会尽量保留源 PSD 的图层列表：每个源图层先单独适配到目标键位，
    再以原图层名写入新 PSD。它仍是像素重建，不承诺保留智能对象、文字矢量、图层样式，
    但图层数量、命名和顺序会比“面板层/按键层”更接近绘图软件里的原文件。
    """

    try:
        from psd_tools import PSDImage
        from psd_tools.api.layers import Group, PixelLayer
    except Exception as exc:  # pragma: no cover - 依赖缺失时由接口返回明确错误
        raise RuntimeError("缺少 psd-tools，无法导出 PSD。请安装 requirements.txt 或使用打包版。") from exc

    if not result.panels:
        raise RuntimeError("没有可导出的面板。")

    spacing = 24 if len(result.panels) > 1 else 0
    width = max(panel.panel.width for panel in result.panels)
    height = sum(panel.panel.height for panel in result.panels) + spacing * max(0, len(result.panels) - 1)

    psd = PSDImage.new("RGBA", (width, height), color=(0, 0, 0, 0))
    y_offset = 0
    try:
        use_panel_groups = mode == "source_layers" and len(result.panels) > 1
        group_cache: dict[tuple[int, tuple[str, ...]], object] = {}
        for adapted_panel in result.panels:
            if mode == "source_layers":
                panel_parent = _new_group(psd, Group, adapted_panel.panel.title) if use_panel_groups else psd
                for source_layer in adapted_panel.preserved_layers:
                    layer_parent = _parent_for_group_path(panel_parent, Group, group_cache, source_layer.group_path)
                    _append_pixel_layer(
                        layer_parent,
                        PixelLayer,
                        source_layer.image,
                        source_layer.source_layer_name,
                        top=y_offset,
                        left=0,
                        visible=source_layer.visible,
                        opacity=source_layer.opacity,
                        blend_mode=source_layer.blend_mode,
                        clipping=source_layer.clipping,
                    )
            elif mode == "panel_layers":
                _append_pixel_layer(
                    psd,
                    PixelLayer,
                    adapted_panel.preview,
                    f"{adapted_panel.panel.title} - {adapted_panel.source_name}",
                    top=y_offset,
                    left=0,
                )
            else:
                for index, key_layer in enumerate(adapted_panel.key_layers, start=1):
                    _append_pixel_layer(
                        psd,
                        PixelLayer,
                        key_layer.image,
                        f"{adapted_panel.panel.panel_key}-{index}-{key_layer.key_name}",
                        top=y_offset + key_layer.rect.y,
                        left=key_layer.rect.x,
                    )
            y_offset += adapted_panel.panel.height + spacing

        buffer = io.BytesIO()
        psd.save(buffer)
        return buffer.getvalue()
    finally:
        close = getattr(psd, "close", None)
        if callable(close):
            close()
