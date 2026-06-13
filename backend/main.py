from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .services.adapter import ResizeMode, SkinAdapter, SourceGridLayout, SourceGridSlot, image_to_png_bytes
from .services.ini_parser import Rect
from .services.psd_exporter import PsdLayerMode, export_adapted_psd
from .services.psd_reader import SourceImage, load_source_images
from .services.skin_parser import DEFAULT_PANEL_SELECTION, PanelLayoutBasis, PanelSizeBasis, SkinPackage, parse_skin_package


def _app_root_dir() -> Path:
    """返回程序资源根目录。

    普通源码运行时，资源在 `runtime-services/skin-psd-adapter/static`。
    PyInstaller onefile 打包后，资源会被解压到 `sys._MEIPASS/static`。
    这里统一处理，保证单个 exe 启动后仍能找到 HTML 页面。
    """

    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root)
    return Path(__file__).resolve().parents[1]


ROOT_DIR = _app_root_dir()
STATIC_DIR = ROOT_DIR / "static"

app = FastAPI(
    title="皮肤 PSD 自动适配工具",
    description="独立的本地 FastAPI 服务，用于把 PSD/图片设计稿适配到 .bds/.bdi 底包。",
    version="0.1.0",
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _split_panels(panels: str) -> List[str]:
    selected = [item.strip() for item in panels.split(",") if item.strip()]
    return selected or list(DEFAULT_PANEL_SELECTION)


def _parse_source_layout(payload: str | None) -> Optional[SourceGridLayout]:
    """解析前端传来的源图片格子。

    JSON 结构保持简单：{canvas_width, canvas_height, keyboard_rect, slots:[{panel_key,name,x,y,w,h}]}。
    所有数值都按源图片逻辑坐标理解，后端会自动缩放到实际图片像素。
    """

    if not payload:
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"源图片格子 JSON 无效: {exc}") from exc

    canvas_width = int(data.get("canvas_width") or data.get("width") or 0)
    canvas_height = int(data.get("canvas_height") or data.get("height") or 0)
    if canvas_width <= 0 or canvas_height <= 0:
        raise HTTPException(status_code=400, detail="源图片格子需要填写有效的整体宽高。")

    keyboard_payload = data.get("keyboard_rect") or {}
    keyboard_rect: Optional[Rect] = None
    if keyboard_payload:
        try:
            raw_keyboard = Rect(
                x=int(round(float(keyboard_payload.get("x", 0)))),
                y=int(round(float(keyboard_payload.get("y", 0)))),
                w=max(1, int(round(float(keyboard_payload.get("w", canvas_width))))),
                h=max(1, int(round(float(keyboard_payload.get("h", canvas_height))))),
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="源图片键盘区参数无效。") from exc
        if raw_keyboard.x < 0 or raw_keyboard.y < 0:
            raise HTTPException(status_code=400, detail="源图片键盘区坐标不能为负数。")
        if raw_keyboard.x >= canvas_width or raw_keyboard.y >= canvas_height:
            raise HTTPException(status_code=400, detail="源图片键盘区起点超出整体画布。")
        keyboard_rect = raw_keyboard.clamp(canvas_width, canvas_height)

    slots: List[SourceGridSlot] = []
    for index, item in enumerate(data.get("slots") or [], start=1):
        try:
            raw_x = int(round(float(item.get("x", 0))))
            raw_y = int(round(float(item.get("y", 0))))
            raw_w = max(1, int(round(float(item.get("w", 0)))))
            raw_h = max(1, int(round(float(item.get("h", 0)))))
            rect = Rect(
                x=raw_x,
                y=raw_y,
                w=raw_w,
                h=raw_h,
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"第 {index} 个源格子参数无效。") from exc
        if rect.x < 0 or rect.y < 0:
            raise HTTPException(status_code=400, detail=f"第 {index} 个源格子坐标不能为负数。")
        if rect.x >= canvas_width or rect.y >= canvas_height:
            raise HTTPException(status_code=400, detail=f"第 {index} 个源格子起点超出整体画布。")
        rect = rect.clamp(canvas_width, canvas_height)
        slots.append(
            SourceGridSlot(
                panel_key=str(item.get("panel_key") or ""),
                name=str(item.get("name") or f"slot{index}"),
                rect=rect,
            )
        )

    return SourceGridLayout(
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        slots=tuple(slots),
        keyboard_rect=keyboard_rect,
    )


def _close_sources(sources: List[SourceImage]) -> None:
    for source in sources:
        source.close()


async def _read_upload(upload: UploadFile) -> bytes:
    data = await upload.read()
    if not data:
        raise HTTPException(status_code=400, detail=f"{upload.filename or '上传文件'} 为空")
    return data


def _layout_signal_to_dict(signal) -> dict:
    return {
        "theme": signal.theme,
        "structure": signal.structure,
        "panel": signal.panel,
        "key_count": signal.key_count,
        "foreground_images": signal.foreground_images,
        "background_images": signal.background_images,
        "valid_til_images": signal.valid_til_images,
        "max_til_slice_count": signal.max_til_slice_count,
    }


def _foreground_detection_to_dict(detection) -> dict | None:
    if not detection:
        return None
    return {
        "type": detection.type,
        "confidence": detection.confidence,
        "normal_score": detection.normal_score,
        "sticker_score": detection.sticker_score,
        "css_file_count": detection.css_file_count,
        "reason": detection.reason,
        "normal_layouts": [_layout_signal_to_dict(item) for item in detection.normal_layouts],
        "sticker_layouts": [_layout_signal_to_dict(item) for item in detection.sticker_layouts],
        "path_candidates": [
            {
                "theme": item.theme,
                "structure": item.structure,
                "port": item.port,
                "res": item.res,
            }
            for item in detection.path_candidates
        ],
    }


def _summarize_skin(skin: SkinPackage) -> dict:
    return {
        "themes": skin.themes,
        "diagnostics": skin.diagnostics,
        "foreground_detection": _foreground_detection_to_dict(skin.foreground_detection),
        "panels": [
            {
                "theme": panel.theme or "default",
                "panel_key": panel.panel_key,
                "ini_path": panel.ini_path,
                "size": [panel.width, panel.height],
                "size_note": panel.size_note,
                "layout_note": panel.layout_note,
                "key_count": len(panel.keys),
                "sample_keys": [
                    key.debug_name
                    for key in sorted(panel.keys, key=lambda item: (item.rect.y, item.rect.x))[:12]
                ],
                "keys": [
                    {
                        "name": key.debug_name,
                        "section": key.section,
                        "x": key.rect.x,
                        "y": key.rect.y,
                        "w": key.rect.w,
                        "h": key.rect.h,
                    }
                    for key in sorted(panel.keys, key=lambda item: (item.rect.y, item.rect.x))
                ],
                "atlas_count": len({ref.png_path for key in panel.keys for ref in key.style_refs}),
            }
            for panel in skin.panels
        ],
    }


def _build_result(
    design_data: bytes,
    design_name: str,
    package_data: bytes,
    package_name: str,
    panel_keys: List[str],
    resize_mode: ResizeMode,
    size_basis: PanelSizeBasis,
    layout_basis: PanelLayoutBasis,
    include_pressed: bool,
    darken_pressed: bool,
    source_layout: Optional[SourceGridLayout] = None,
):
    """统一构建适配结果。

    四个接口都走同一条解析/适配路径，避免“预览是好的、导出又走另一套逻辑”的不一致。
    调用方负责在使用完成后关闭 result、adapter、sources、archive。
    """

    sources = load_source_images(design_data, design_name)
    skin = parse_skin_package(
        data=package_data,
        filename=package_name,
        panel_keys=panel_keys,
        include_pressed=include_pressed,
        size_basis=size_basis,
        layout_basis=layout_basis,
    )
    if not skin.panels:
        _close_sources(sources)
        skin.archive.close()
        raise HTTPException(status_code=400, detail="底包中没有解析到可适配面板。")

    adapter = SkinAdapter(
        skin=skin,
        sources=sources,
        resize_mode=resize_mode,
        darken_pressed=darken_pressed,
        source_layout=source_layout,
    )
    result = adapter.adapt()
    return sources, skin, adapter, result


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "skin-psd-adapter"}


@app.post("/api/analyze")
async def analyze(
    design_file: UploadFile = File(...),
    base_package: UploadFile = File(...),
    panels: str = Form(",".join(DEFAULT_PANEL_SELECTION)),
    size_basis: PanelSizeBasis = Form("auto"),
    layout_basis: PanelLayoutBasis = Form("ini"),
    include_pressed: bool = Form(True),
    source_layout: str = Form(""),
) -> JSONResponse:
    design_data = await _read_upload(design_file)
    package_data = await _read_upload(base_package)
    sources: List[SourceImage] = []
    skin: SkinPackage | None = None
    try:
        sources = load_source_images(design_data, design_file.filename or "design")
        skin = parse_skin_package(
            data=package_data,
            filename=base_package.filename or "skin.bds",
            panel_keys=_split_panels(panels),
            include_pressed=include_pressed,
            size_basis=size_basis,
            layout_basis=layout_basis,
        )
        return JSONResponse(
            {
                "sources": [
                    {
                        "name": source.name,
                        "panel_key": source.panel_key,
                        "size": list(source.image.size),
                        "layer_count": source.layer_count,
                    }
                    for source in sources
                ],
                "skin": _summarize_skin(skin),
            }
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        _close_sources(sources)
        if skin:
            skin.archive.close()


@app.post("/api/source-info")
async def source_info(
    design_file: UploadFile = File(...),
) -> JSONResponse:
    """只解析设计稿尺寸。

    浏览器能直接读取 PNG/JPG/WebP 的像素尺寸，但 PSD/PSD zip 需要后端用 psd-tools 渲染后
    才知道真实画布大小。这个接口给“识别图片尺寸”按钮单独使用，不要求先选择底包。
    """

    design_data = await _read_upload(design_file)
    sources: List[SourceImage] = []
    try:
        sources = load_source_images(design_data, design_file.filename or "design")
        return JSONResponse(
            {
                "sources": [
                    {
                        "name": source.name,
                        "panel_key": source.panel_key,
                        "size": list(source.image.size),
                        "layer_count": source.layer_count,
                    }
                    for source in sources
                ],
            }
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        _close_sources(sources)


@app.post("/api/preview")
async def preview(
    design_file: UploadFile = File(...),
    base_package: UploadFile = File(...),
    panels: str = Form(",".join(DEFAULT_PANEL_SELECTION)),
    resize_mode: ResizeMode = Form("stretch"),
    size_basis: PanelSizeBasis = Form("auto"),
    layout_basis: PanelLayoutBasis = Form("ini"),
    include_pressed: bool = Form(True),
    darken_pressed: bool = Form(True),
    source_layout: str = Form(""),
) -> JSONResponse:
    design_data = await _read_upload(design_file)
    package_data = await _read_upload(base_package)
    sources = skin = adapter = result = None
    try:
        sources, skin, adapter, result = _build_result(
            design_data=design_data,
            design_name=design_file.filename or "design",
            package_data=package_data,
            package_name=base_package.filename or "skin.bds",
            panel_keys=_split_panels(panels),
            resize_mode=resize_mode,
            size_basis=size_basis,
            layout_basis=layout_basis,
            include_pressed=include_pressed,
            darken_pressed=darken_pressed,
            source_layout=_parse_source_layout(source_layout),
        )
        previews = []
        for panel_result in result.panels:
            png_bytes = image_to_png_bytes(panel_result.preview)
            previews.append(
                {
                    "title": panel_result.panel.title,
                    "source": panel_result.source_name,
                    "width": panel_result.panel.width,
                    "height": panel_result.panel.height,
                    "data_url": "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii"),
                }
            )
        return JSONResponse(
            {
                "previews": previews,
                "replaced_files": sorted(result.replacements.keys()),
                "diagnostics": result.diagnostics,
            }
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if result:
            result.close()
        if adapter:
            adapter.close()
        if sources:
            _close_sources(sources)
        if skin:
            skin.archive.close()


@app.post("/api/export-psd")
async def export_psd(
    design_file: UploadFile = File(...),
    base_package: UploadFile = File(...),
    panels: str = Form(",".join(DEFAULT_PANEL_SELECTION)),
    resize_mode: ResizeMode = Form("stretch"),
    size_basis: PanelSizeBasis = Form("auto"),
    layout_basis: PanelLayoutBasis = Form("ini"),
    include_pressed: bool = Form(True),
    darken_pressed: bool = Form(True),
    layer_mode: PsdLayerMode = Form("source_layers"),
    source_layout: str = Form(""),
) -> Response:
    design_data = await _read_upload(design_file)
    package_data = await _read_upload(base_package)
    sources = skin = adapter = result = None
    try:
        sources, skin, adapter, result = _build_result(
            design_data=design_data,
            design_name=design_file.filename or "design",
            package_data=package_data,
            package_name=base_package.filename or "skin.bds",
            panel_keys=_split_panels(panels),
            resize_mode=resize_mode,
            size_basis=size_basis,
            layout_basis=layout_basis,
            include_pressed=include_pressed,
            darken_pressed=darken_pressed,
            source_layout=_parse_source_layout(source_layout),
        )
        payload = export_adapted_psd(result, mode=layer_mode)
        return Response(
            payload,
            media_type="image/vnd.adobe.photoshop",
            headers={"Content-Disposition": 'attachment; filename="skin_auto_adapt.psd"'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if result:
            result.close()
        if adapter:
            adapter.close()
        if sources:
            _close_sources(sources)
        if skin:
            skin.archive.close()


@app.post("/api/export-package")
async def export_package(
    design_file: UploadFile = File(...),
    base_package: UploadFile = File(...),
    panels: str = Form(",".join(DEFAULT_PANEL_SELECTION)),
    resize_mode: ResizeMode = Form("stretch"),
    size_basis: PanelSizeBasis = Form("auto"),
    layout_basis: PanelLayoutBasis = Form("ini"),
    include_pressed: bool = Form(True),
    darken_pressed: bool = Form(True),
    source_layout: str = Form(""),
) -> Response:
    design_data = await _read_upload(design_file)
    package_data = await _read_upload(base_package)
    sources = skin = adapter = result = None
    try:
        sources, skin, adapter, result = _build_result(
            design_data=design_data,
            design_name=design_file.filename or "design",
            package_data=package_data,
            package_name=base_package.filename or "skin.bds",
            panel_keys=_split_panels(panels),
            resize_mode=resize_mode,
            size_basis=size_basis,
            layout_basis=layout_basis,
            include_pressed=include_pressed,
            darken_pressed=darken_pressed,
            source_layout=_parse_source_layout(source_layout),
        )
        if not result.replacements:
            raise HTTPException(status_code=400, detail="没有生成任何可替换 PNG。")
        payload = skin.archive.write_replaced(result.replacements)
        ext = Path(base_package.filename or "skin.bds").suffix or ".bds"
        return Response(
            payload,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="skin_auto_adapt{ext}"'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if result:
            result.close()
        if adapter:
            adapter.close()
        if sources:
            _close_sources(sources)
        if skin:
            skin.archive.close()
