from __future__ import annotations

import base64
import sys
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .services.adapter import ResizeMode, SkinAdapter, image_to_png_bytes
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


def _close_sources(sources: List[SourceImage]) -> None:
    for source in sources:
        source.close()


async def _read_upload(upload: UploadFile) -> bytes:
    data = await upload.read()
    if not data:
        raise HTTPException(status_code=400, detail=f"{upload.filename or '上传文件'} 为空")
    return data


def _summarize_skin(skin: SkinPackage) -> dict:
    return {
        "themes": skin.themes,
        "diagnostics": skin.diagnostics,
        "panels": [
            {
                "theme": panel.theme or "default",
                "panel_key": panel.panel_key,
                "ini_path": panel.ini_path,
                "size": [panel.width, panel.height],
                "size_note": panel.size_note,
                "layout_note": panel.layout_note,
                "key_count": len(panel.keys),
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
    size_basis: PanelSizeBasis = Form("default"),
    layout_basis: PanelLayoutBasis = Form("ini"),
    include_pressed: bool = Form(True),
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


@app.post("/api/preview")
async def preview(
    design_file: UploadFile = File(...),
    base_package: UploadFile = File(...),
    panels: str = Form(",".join(DEFAULT_PANEL_SELECTION)),
    resize_mode: ResizeMode = Form("stretch"),
    size_basis: PanelSizeBasis = Form("default"),
    layout_basis: PanelLayoutBasis = Form("ini"),
    include_pressed: bool = Form(True),
    darken_pressed: bool = Form(True),
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
    size_basis: PanelSizeBasis = Form("default"),
    layout_basis: PanelLayoutBasis = Form("ini"),
    include_pressed: bool = Form(True),
    darken_pressed: bool = Form(True),
    layer_mode: PsdLayerMode = Form("source_layers"),
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
    size_basis: PanelSizeBasis = Form("default"),
    layout_basis: PanelLayoutBasis = Form("ini"),
    include_pressed: bool = Form(True),
    darken_pressed: bool = Form(True),
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
