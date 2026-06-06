from __future__ import annotations

import io
import re
from typing import Literal

from PIL import Image

from .adapter import AdaptResult


PsdLayerMode = Literal["panel_layers", "key_layers"]


def _safe_layer_name(name: str, max_length: int = 80) -> str:
    cleaned = re.sub(r"[\r\n\t]+", " ", name).strip()
    return cleaned[:max_length] or "Layer"


def export_adapted_psd(result: AdaptResult, mode: PsdLayerMode = "panel_layers") -> bytes:
    """导出重建版 PSD。

    这里导出的是“重建 PSD”：图层像素来自适配后的结果，不承诺保留原 PSD 的智能对象、
    矢量文字和图层样式。这个限制比伪装成无损编辑更诚实，也更适合自动改尺寸场景。
    """

    try:
        from psd_tools import PSDImage
        from psd_tools.api.layers import PixelLayer
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
        for adapted_panel in result.panels:
            if mode == "panel_layers":
                layer = PixelLayer.frompil(
                    adapted_panel.preview,
                    psd,
                    _safe_layer_name(f"{adapted_panel.panel.title} - {adapted_panel.source_name}"),
                    top=y_offset,
                    left=0,
                )
                psd.append(layer)
            else:
                for index, key_layer in enumerate(adapted_panel.key_layers, start=1):
                    layer = PixelLayer.frompil(
                        key_layer.image,
                        psd,
                        _safe_layer_name(f"{adapted_panel.panel.panel_key}-{index}-{key_layer.key_name}"),
                        top=y_offset + key_layer.rect.y,
                        left=key_layer.rect.x,
                    )
                    psd.append(layer)
            y_offset += adapted_panel.panel.height + spacing

        buffer = io.BytesIO()
        psd.save(buffer)
        return buffer.getvalue()
    finally:
        close = getattr(psd, "close", None)
        if callable(close):
            close()

