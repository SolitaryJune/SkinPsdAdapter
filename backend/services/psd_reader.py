from __future__ import annotations

import io
import os
import re
import zipfile
from dataclasses import dataclass
from typing import Any, List, Tuple

from PIL import Image

from .archive import is_zip_like, iter_zip_files
from .ini_parser import Rect


@dataclass
class SourceLayer:
    """源 PSD 中的一个可导出图层。

    `psd-tools` 对文字、智能对象、剪贴蒙版等高级对象不能做到 Photoshop 级无损编辑，
    但可以把它们按当前可见效果渲染成像素。这里保留图层名、可见状态和像素边界，
    后续导出 PSD 时就能恢复成“原来多图层列表”的形态。
    """

    name: str
    image: Image.Image
    bbox: tuple[int, int, int, int]
    visible: bool = True
    opacity: int = 255
    blend_mode: bytes | str = b"norm"
    clipping: bool = False
    group_path: Tuple[str, ...] = ()

    def close(self) -> None:
        self.image.close()

    def crop_region(self, rect: Rect) -> Image.Image:
        """从本图层裁出一个源键位区域。

        图层本身通常只是一个小 bbox，不是整张画布。为了适配时不把小装饰错误放大，
        这里先生成完整键位大小的透明画布，再把图层与键位相交的部分贴到正确相对位置。
        """

        canvas = Image.new("RGBA", (rect.w, rect.h), (0, 0, 0, 0))
        left, top, right, bottom = self.bbox
        ix1 = max(rect.x, left)
        iy1 = max(rect.y, top)
        ix2 = min(rect.right, right)
        iy2 = min(rect.bottom, bottom)
        if ix2 <= ix1 or iy2 <= iy1:
            return canvas

        crop_box = (ix1 - left, iy1 - top, ix2 - left, iy2 - top)
        piece = self.image.crop(crop_box)
        try:
            canvas.alpha_composite(piece, (ix1 - rect.x, iy1 - rect.y))
        finally:
            piece.close()
        return canvas


@dataclass
class SourceImage:
    """PSD/图片渲染后的源面板图。"""

    name: str
    panel_key: str
    image: Image.Image
    layers: List[SourceLayer]
    layer_count: int = 0

    def close(self) -> None:
        self.image.close()
        for layer in self.layers:
            layer.close()


def _guess_panel_key(name: str) -> str:
    """根据文件名推断它对应哪个面板。

    设计师给的 PSD 包通常会用 26、9、123 命名；如果无法判断，就先当 26 键处理。
    """

    stem = os.path.splitext(os.path.basename(name).lower())[0]
    if "num_9h" in stem or "num-9h" in stem:
        return "num_9h"
    if "123" in stem or "num" in stem or "number" in stem:
        return "num_9"
    if "en_26" in stem or "en-26" in stem:
        return "en_26"
    if re.search(r"(^|[^0-9])26([^0-9]|$)", stem) or "py_26" in stem:
        return "py_26"
    if "en_9" in stem or "en-9" in stem:
        return "en_9"
    if re.search(r"(^|[^0-9])9([^0-9]|$)", stem) or "py_9" in stem:
        return "py_9"
    if "hw_grid" in stem or "hand" in stem or "shouxie" in stem:
        return "hw_grid"
    if "symbol" in stem or "sym" in stem:
        return "symbol"
    if re.search(r"(^|[^a-z])bh([^a-z]|$)", stem) or "bihua" in stem:
        return "bh"
    return "py_26"


def _layer_bbox_tuple(layer) -> tuple[int, int, int, int]:
    bbox = getattr(layer, "bbox", (0, 0, 0, 0))
    try:
        left, top, right, bottom = bbox
        return int(left), int(top), int(right), int(bottom)
    except Exception:
        return 0, 0, 0, 0


def _is_group_layer(layer) -> bool:
    is_group = getattr(layer, "is_group", None)
    if callable(is_group):
        try:
            return bool(is_group())
        except Exception:
            return False
    return hasattr(layer, "__iter__")


def _layer_blend_mode(layer: Any) -> bytes | str:
    """取出 PSD 图层混合模式，并在读取异常时回退到 normal。

    `psd-tools` 会返回 `BlendMode` 枚举；导出时它能直接吃枚举、bytes 或 str。
    这里不强依赖具体类型，避免不同 psd-tools 版本之间的小差异影响解析。
    """

    blend_mode = getattr(layer, "blend_mode", b"norm")
    return blend_mode or b"norm"


def _layer_opacity(layer: Any) -> int:
    """读取 Photoshop 图层不透明度，取值范围固定在 0-255。"""

    try:
        return max(0, min(255, int(getattr(layer, "opacity", 255))))
    except Exception:
        return 255


def _layer_clipping(layer: Any) -> bool:
    """读取剪贴蒙版标记。

    保留这个标记后，导出 PSD 的图层面板会继续显示向下剪贴的小箭头，
    更贴近用户截图里的“从选区/剪贴”类图层结构。
    """

    try:
        return bool(getattr(layer, "clipping", False))
    except Exception:
        return False


def _layer_pixel_image(layer: Any, width: int, height: int, visible: bool) -> Image.Image:
    """读取单个 PSD 图层自己的像素。

    不能用 `layer.composite()` 作为默认方案，因为它会把剪贴层、蒙版和部分效果一起合成，
    导致导出时“上面的剪贴图层内容跑到下面的基底层”。`topil()` 更接近原图层自身像素；
    如果遇到文字/形状等无法直接取像素的图层，再回退到 composite 的当前视觉效果。
    """

    rendered = None
    converted = None
    try:
        topil = getattr(layer, "topil", None)
        rendered = topil() if callable(topil) else None
        if rendered is None:
            rendered = layer.composite(layer_filter=lambda _: True)
        converted = rendered.convert("RGBA") if rendered is not None else Image.new("RGBA", (width, height), (0, 0, 0, 0))
        result = converted
        converted = None
        return result
    finally:
        if converted is not None:
            converted.close()
        if rendered is not None:
            close = getattr(rendered, "close", None)
            if callable(close):
                close()


def _collect_psd_layers(psd) -> List[SourceLayer]:
    """按 PSD 原始顺序收集叶子图层。

    这里有意不把所有图层提前合并；用户希望导出的 PSD 图层列表仍像绘图软件里那样分层。
    组图层会递归展开；叶子层会保留名称、显隐、透明度、混合模式和剪贴关系。
    """

    layers: List[SourceLayer] = []

    def walk(container, group_path: Tuple[str, ...] = ()) -> None:
        for layer in container:
            if _is_group_layer(layer):
                group_name = str(getattr(layer, "name", "") or "Group")
                walk(layer, group_path + (group_name,))
                continue

            left, top, right, bottom = _layer_bbox_tuple(layer)
            width = max(1, right - left)
            height = max(1, bottom - top)
            visible = bool(getattr(layer, "visible", True))
            converted = _layer_pixel_image(layer, width, height, visible)
            layers.append(
                SourceLayer(
                    name=str(getattr(layer, "name", "") or "Layer"),
                    image=converted,
                    bbox=(left, top, left + converted.width, top + converted.height),
                    visible=visible,
                    opacity=_layer_opacity(layer),
                    blend_mode=_layer_blend_mode(layer),
                    clipping=_layer_clipping(layer),
                    group_path=group_path,
                )
            )

    walk(psd)
    return layers


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
        source_layers = _collect_psd_layers(psd)
        if not source_layers:
            # 极少数 PSD 只能合成整图时，仍给“保留源图层”模式一个兜底层。
            source_layers = [
                SourceLayer(
                    name=os.path.splitext(os.path.basename(name))[0] or "Merged",
                    image=image.convert("RGBA"),
                    bbox=(0, 0, image.width, image.height),
                    visible=True,
                    opacity=255,
                    blend_mode=b"norm",
                    clipping=False,
                )
            ]
        return SourceImage(
            name=name,
            panel_key=_guess_panel_key(name),
            image=image.convert("RGBA"),
            layers=source_layers,
            layer_count=len(source_layers) or layer_count,
        )
    finally:
        close = getattr(psd, "close", None)
        if callable(close):
            close()


def _render_raster(data: bytes, name: str) -> SourceImage:
    with Image.open(io.BytesIO(data)) as raw:
        image = raw.convert("RGBA")
        return SourceImage(
            name=name,
            panel_key=_guess_panel_key(name),
            image=image,
            layers=[
                SourceLayer(
                    name=os.path.splitext(os.path.basename(name))[0] or "Image",
                    image=image.copy(),
                    bbox=(0, 0, image.width, image.height),
                    visible=True,
                    opacity=255,
                    blend_mode=b"norm",
                    clipping=False,
                )
            ],
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
