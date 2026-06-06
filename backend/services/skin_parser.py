from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

from .archive import SkinArchive
from .ini_parser import (
    Rect,
    extract_style_ids,
    find_section_case_insensitive,
    parse_ini,
    parse_rect,
    sorted_numbered_sections,
)


STYLE_IMAGE_PROPS = ("NM_IMG", "HL_IMG")


@dataclass(frozen=True)
class StyleImageRef:
    """default.css 里 STYLExx -> PNG/TIL 切片的引用。"""

    style_id: int
    prop: str
    basename: str
    tile_index: int
    png_path: str
    til_path: str


@dataclass
class KeySlot:
    """一个目标键位。

    rect 是 INI 的 VIEW_RECT，style_refs 是 BACK_STYLE 通过 default.css 找到的真实图集切片。
    这里不只保留有 CENTER 的字母键，因为删除、空格、侧边栏这些功能键也需要被设计图覆盖。
    """

    section: str
    rect: Rect
    center: str = ""
    back_style: str = ""
    fore_style: str = ""
    style_refs: List[StyleImageRef] = field(default_factory=list)

    @property
    def debug_name(self) -> str:
        return self.center or self.section


@dataclass
class PanelLayout:
    """一个主题里的一个键盘面板，例如 dark/port/py_26.ini。"""

    theme: str
    panel_key: str
    ini_path: str
    res_path: str
    width: int
    height: int
    keys: List[KeySlot]

    @property
    def title(self) -> str:
        return f"{self.theme or 'default'} / {self.panel_key}"


@dataclass
class SkinPackage:
    archive: SkinArchive
    themes: List[str]
    panels: List[PanelLayout]
    diagnostics: List[str] = field(default_factory=list)


DEFAULT_PANEL_FILES: Dict[str, str] = {
    "py_26": "py_26.ini",
    "py_9": "py_9.ini",
    "num_9": "num_9.ini",
}


def detect_themes(paths: Sequence[str]) -> List[str]:
    """检测 light/dark/default 主题。

    .bds 通常是 dark/port，.bdi 常见 skin/dark/skin/port；如果没有主题目录，就按默认主题处理。
    """

    themes: List[str] = []
    for path in paths:
        lower = path.lower()
        if (lower.startswith("light/") or "/light/" in lower) and "light" not in themes:
            themes.append("light")
        if (lower.startswith("dark/") or "/dark/" in lower) and "dark" not in themes:
            themes.append("dark")
    return themes or [""]


def find_skin_paths(paths: Sequence[str], theme: str) -> Dict[str, str]:
    """从包内路径推断 port/res 根目录。"""

    patterns = [
        f"{theme}/port/" if theme else "port/",
        f"skin/{theme}/skin/port/" if theme else "skin/port/",
        f"{theme}/skin/port/" if theme else "skin/port/",
        "port/",
    ]
    opposite_theme = "dark" if theme == "light" else ("light" if theme == "dark" else "")
    base_path = ""

    for pattern in patterns:
        pattern_lower = pattern.lower()
        for path in paths:
            lower = path.lower()
            if pattern_lower not in lower:
                continue
            if opposite_theme and f"/{opposite_theme}/" in f"/{lower}":
                continue
            index = lower.find(pattern_lower)
            base_path = path[: index + len(pattern) - len("port/")]
            break
        if base_path:
            break

    return {
        "port": f"{base_path}port/",
        "res": f"{base_path}res/",
    }


def _get_panel_size(ini: Dict[str, Dict[str, str]], key_rects: Iterable[Rect]) -> tuple[int, int]:
    panel = find_section_case_insensitive(ini, "PANEL") or {}
    size_rect = parse_rect(f"0,0,{panel.get('SIZE', '')}") if panel.get("SIZE") else None
    if size_rect:
        return size_rect.w, size_rect.h

    max_right = 0
    max_bottom = 0
    for rect in key_rects:
        max_right = max(max_right, rect.right)
        max_bottom = max(max_bottom, rect.bottom)
    return max(max_right, 1080), max(max_bottom, 595)


def _is_full_panel_key(rect: Rect, width: int, height: int, center: str) -> bool:
    """过滤整面板背景占位键。

    贴纸底包通常有 KEY1=0,0,1080,595，用来挂背景图；它不是可切割按键。
    """

    if center:
        return False
    return abs(rect.x) <= 1 and abs(rect.y) <= 1 and rect.w >= width * 0.9 and rect.h >= height * 0.85


def _style_section(css: Dict[str, Dict[str, str]], style_id: int) -> Optional[Dict[str, str]]:
    return find_section_case_insensitive(css, f"STYLE{style_id}")


def _parse_style_image_value(value: object) -> Optional[tuple[str, int]]:
    """解析 `NM_IMG=26,1` 这样的图集引用。"""

    parts = str(value or "").split(",")
    if not parts:
        return None
    basename = parts[0].strip().strip("'\"").replace("\\", "/")
    basename = os.path.splitext(basename)[0]
    if not basename:
        return None

    index = 0
    if len(parts) > 1:
        match = re.search(r"\d+", parts[1])
        if match:
            index = int(match.group(0))
    return (basename, index) if index > 0 else None


def _resolve_resource_path(archive: SkinArchive, res_path: str, basename: str, ext: str) -> str:
    candidates = [
        f"{res_path}{basename}{ext}",
        f"{res_path}{os.path.basename(basename)}{ext}",
        f"{basename}{ext}",
        f"{os.path.basename(basename)}{ext}",
    ]
    for candidate in candidates:
        matched = archive.find_path(candidate)
        if matched:
            return matched
    # 没找到也返回最可能的路径，后续写诊断；这样不会在解析阶段直接中断。
    return candidates[0]


def _style_refs_for_key(
    archive: SkinArchive,
    css: Dict[str, Dict[str, str]],
    res_path: str,
    back_style: str,
    include_pressed: bool,
) -> List[StyleImageRef]:
    refs: List[StyleImageRef] = []
    for style_id in extract_style_ids(back_style):
        style = _style_section(css, style_id)
        if not style:
            continue
        for prop in STYLE_IMAGE_PROPS:
            if prop == "HL_IMG" and not include_pressed:
                continue
            parsed = _parse_style_image_value(style.get(prop))
            if not parsed:
                continue
            basename, tile_index = parsed
            refs.append(
                StyleImageRef(
                    style_id=style_id,
                    prop=prop,
                    basename=basename,
                    tile_index=tile_index,
                    png_path=_resolve_resource_path(archive, res_path, basename, ".png"),
                    til_path=_resolve_resource_path(archive, res_path, basename, ".til"),
                )
            )
    return refs


def parse_til_slices(til_text: str) -> Dict[int, Rect]:
    """把 .til 文件里的 IMGn/SOURCE_RECT 解析成切片坐标。"""

    til_ini = parse_ini(til_text)
    slices: Dict[int, Rect] = {}
    for section in sorted_numbered_sections(til_ini, "IMG"):
        rect = parse_rect(til_ini[section].get("SOURCE_RECT"))
        if not rect:
            continue
        index = int(re.sub(r"\D", "", section) or "0")
        if index > 0:
            slices[index] = rect
    return slices


def parse_panel_layout(
    archive: SkinArchive,
    theme: str,
    panel_key: str,
    ini_name: str,
    skin_paths: Dict[str, str],
    css: Dict[str, Dict[str, str]],
    include_pressed: bool,
) -> Optional[PanelLayout]:
    ini_path = f"{skin_paths['port']}{ini_name}"
    ini_text = archive.read_text(ini_path)
    if not ini_text:
        return None
    ini = parse_ini(ini_text)

    raw_keys: List[tuple[str, Rect, Dict[str, str]]] = []
    for section in sorted_numbered_sections(ini, "KEY"):
        values = ini[section]
        rect = parse_rect(values.get("VIEW_RECT"))
        if rect:
            raw_keys.append((section, rect, values))

    width, height = _get_panel_size(ini, (item[1] for item in raw_keys))
    keys: List[KeySlot] = []
    for section, rect, values in raw_keys:
        center = str(values.get("CENTER", "")).strip().strip("'\"")
        if _is_full_panel_key(rect, width, height, center):
            continue
        refs = _style_refs_for_key(
            archive=archive,
            css=css,
            res_path=skin_paths["res"],
            back_style=str(values.get("BACK_STYLE", "")),
            include_pressed=include_pressed,
        )
        # 没有图集引用的装饰配置先跳过；后续如果要处理纯背景或候选栏，可在这里扩展。
        if not refs:
            continue
        keys.append(
            KeySlot(
                section=section,
                rect=rect,
                center=center,
                back_style=str(values.get("BACK_STYLE", "")),
                fore_style=str(values.get("FORE_STYLE", "")),
                style_refs=refs,
            )
        )

    if not keys:
        return None
    return PanelLayout(
        theme=theme,
        panel_key=panel_key,
        ini_path=archive.find_path(ini_path) or ini_path,
        res_path=skin_paths["res"],
        width=width,
        height=height,
        keys=keys,
    )


def parse_skin_package(
    data: bytes,
    filename: str,
    panel_keys: Optional[Sequence[str]] = None,
    include_pressed: bool = True,
) -> SkinPackage:
    """解析目标底包，返回适配所需的面板和图集引用。"""

    archive = SkinArchive(data, filename)
    diagnostics: List[str] = []
    panels: List[PanelLayout] = []
    selected = list(panel_keys or DEFAULT_PANEL_FILES.keys())
    themes = detect_themes(archive.paths)

    for theme in themes:
        skin_paths = find_skin_paths(archive.paths, theme)
        css_text = archive.read_text(f"{skin_paths['res']}default.css")
        if not css_text:
            diagnostics.append(f"{theme or 'default'}: 未找到 default.css")
            continue
        css = parse_ini(css_text)

        for panel_key in selected:
            ini_name = DEFAULT_PANEL_FILES.get(panel_key, f"{panel_key}.ini")
            panel = parse_panel_layout(
                archive=archive,
                theme=theme,
                panel_key=panel_key,
                ini_name=ini_name,
                skin_paths=skin_paths,
                css=css,
                include_pressed=include_pressed,
            )
            if panel:
                panels.append(panel)
            else:
                diagnostics.append(f"{theme or 'default'}: {ini_name} 未找到可替换按键")

    return SkinPackage(archive=archive, themes=themes, panels=panels, diagnostics=diagnostics)

