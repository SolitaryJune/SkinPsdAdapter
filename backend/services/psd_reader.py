from __future__ import annotations

import io
import os
import re
import zipfile
from dataclasses import dataclass
from typing import List

from PIL import Image

from .archive import is_zip_like, iter_zip_files


@dataclass
class SourceImage:
    """PSD/图片渲染后的源面板图。"""

    name: str
    panel_key: str
    image: Image.Image
    layer_count: int = 0

    def close(self) -> None:
        self.image.close()


def _guess_panel_key(name: str) -> str:
    """根据文件名推断它对应哪个面板。

    设计师给的 PSD 包通常会用 26、9、123 命名；如果无法判断，就先当 26 键处理。
    """

    stem = os.path.splitext(os.path.basename(name).lower())[0]
    if "123" in stem or "num" in stem or "number" in stem:
        return "num_9"
    if re.search(r"(^|[^0-9])26([^0-9]|$)", stem) or "py_26" in stem:
        return "py_26"
    if re.search(r"(^|[^0-9])9([^0-9]|$)", stem) or "py_9" in stem:
        return "py_9"
    return "py_26"


def _render_psd(data: bytes, name: str) -> SourceImage:
    try:
        from psd_tools import PSDImage
    except Exception as exc:  # pragma: no cover - 依赖缺失时由接口返回明确错误
        raise RuntimeError("缺少 psd-tools，无法解析 PSD。请安装 requirements.txt 或使用打包版。") from exc

    psd = PSDImage.open(io.BytesIO(data))
    try:
        image = psd.composite()
        if image is None:
            raise RuntimeError(f"{name}: PSD 没有可渲染内容")
        layer_count = sum(1 for _ in psd.descendants())
        return SourceImage(
            name=name,
            panel_key=_guess_panel_key(name),
            image=image.convert("RGBA"),
            layer_count=layer_count,
        )
    finally:
        close = getattr(psd, "close", None)
        if callable(close):
            close()


def _render_raster(data: bytes, name: str) -> SourceImage:
    with Image.open(io.BytesIO(data)) as raw:
        return SourceImage(
            name=name,
            panel_key=_guess_panel_key(name),
            image=raw.convert("RGBA"),
            layer_count=1,
        )


def load_source_images(data: bytes, filename: str) -> List[SourceImage]:
    """读取上传的 PSD、图片，或包含多个 PSD/图片的 zip。"""

    lower = filename.lower()
    sources: List[SourceImage] = []

    def add_file(name: str, payload: bytes) -> None:
        lower_name = name.lower()
        if lower_name.endswith(".psd"):
            sources.append(_render_psd(payload, name))
        elif lower_name.endswith((".png", ".jpg", ".jpeg", ".webp")):
            sources.append(_render_raster(payload, name))

    if is_zip_like(filename, data):
        try:
            for name, payload in iter_zip_files(data):
                add_file(name, payload)
        except zipfile.BadZipFile as exc:
            raise RuntimeError("上传的设计包不是有效 ZIP。") from exc
    else:
        add_file(filename, data)

    if not sources:
        raise RuntimeError("未在上传文件中找到 PSD 或 PNG/JPG/WebP 图片。")

    # 如果只有一张图，允许它兜底适配所有面板；多图时按文件名匹配 panel_key。
    return sources

