from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Literal, Optional, Sequence

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
PanelSizeBasis = Literal["default", "image"]


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
    size_note: str = ""

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
    "en_26": "en_26.ini",
    "py_9": "py_9.ini",
    "en_9": "en_9.ini",
    "bh": "bh.ini",
    "num_9": "num_9.ini",
    "num_9h": "num_9h.ini",
    "symbol": "symbol.ini",
    "hw_grid": "hw_grid.ini",
}

DEFAULT_PANEL_SELECTION = list(DEFAULT_PANEL_FILES.keys())


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


def _parse_size(value: object) -> Optional[tuple[int, int]]:
    """解析 `1080,595` 这种 SIZE 值。

    `parse_rect` 需要四段数字，所以 SIZE 要单独处理。这里和小程序前端一样只认正数宽高，
    解析失败时让上层继续回落到 gen.ini、KEY 最大边界或默认尺寸。
    """

    match = re.search(r"(\d+)\s*,\s*(\d+)", str(value or ""))
    if not match:
        return None
    width = int(match.group(1))
    height = int(match.group(2))
    return (width, height) if width > 0 and height > 0 else None


def _get_ini_size(ini: Dict[str, Dict[str, str]], section: str, key: str = "SIZE") -> Optional[tuple[int, int]]:
    values = find_section_case_insensitive(ini, section) or {}
    return _parse_size(values.get(key))


def _read_png_size(archive: SkinArchive, path: str) -> Optional[tuple[int, int]]:
    """读取 PNG IHDR 宽高，用于“以图片为准”的画布口径。

    小程序前端读 PNG 尺寸时也只看头部字段，不需要完整解码图片；这样兼容性和速度都更稳。
    """

    data = archive.read_binary(path)
    if not data or len(data) < 24:
        return None
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _get_primary_atlas_size(archive: SkinArchive, refs: Sequence[StyleImageRef]) -> Optional[tuple[int, int]]:
    """从 BACK_STYLE 引用里取面积最大的 PNG 尺寸。

    贴纸/前景页面会用 BACK_STYLE 主图集判断 595/641 这类冲突。这里按 PNG 面积排序，
    可以覆盖常态图和按压态图尺寸不一致的老包。
    """

    seen: set[str] = set()
    sizes: List[tuple[int, int]] = []
    for ref in refs:
        key = ref.png_path.lower()
        if key in seen:
            continue
        seen.add(key)
        size = _read_png_size(archive, ref.png_path)
        if size:
            sizes.append(size)
    if not sizes:
        return None
    return max(sizes, key=lambda item: item[0] * item[1])


def _get_panel_size(
    ini: Dict[str, Dict[str, str]],
    key_rects: Iterable[tuple[Rect, str]],
    gen_ini: Dict[str, Dict[str, str]],
    image_size: Optional[tuple[int, int]],
    size_basis: PanelSizeBasis,
) -> tuple[int, int, str]:
    """按小程序前端规则解析面板键盘区尺寸。

    默认口径：
    1. 当前面板 [PANEL].SIZE；
    2. gen.ini [PANEL].SIZE；
    3. PNG 图集实际尺寸；
    4. KEY 的 VIEW_RECT 最大范围；
    5. 兜底 1080x595。

    如果传入 PNG 实际尺寸且发现 INI 里有 `0,0,1080,595` 这类整面板 KEY，默认会把
    `1080x641` 收敛到 `1080x595`。用户选择“以图片为准”时才保留 PNG 外框尺寸。
    """

    rect_infos = list(key_rects)
    rects = [rect for rect, _center in rect_infos]
    panel_size = _get_ini_size(ini, "PANEL")
    gen_size = _get_ini_size(gen_ini, "PANEL")
    initial_size = panel_size or gen_size or image_size
    source = "PANEL.SIZE" if panel_size else ("gen.ini PANEL.SIZE" if gen_size else ("PNG IHDR" if image_size else "VIEW_RECT"))

    if initial_size:
        width, height = initial_size
    else:
        max_right = 0
        max_bottom = 0
        for rect in rects:
            max_right = max(max_right, rect.right)
            max_bottom = max(max_bottom, rect.bottom)
        width = max(max_right, 1080)
        height = max(max_bottom, 595)

    if size_basis == "image" and image_size:
        width, height = image_size
        return width, height, f"以图片为准: PNG IHDR {width}x{height}"

    full_panel_rect = sorted(
        (
            rect
            for rect, center in rect_infos
            if not center and abs(rect.x) <= 1 and abs(rect.y) <= 1 and rect.w >= width * 0.9 and rect.h > 0
        ),
        key=lambda item: item.area,
        reverse=True,
    )
    if full_panel_rect and initial_size and full_panel_rect[0].h < height:
        old_height = height
        height = full_panel_rect[0].h
        source = f"{source}, 按整面板 KEY 收敛 {old_height}->{height}"

    return width, height, source


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


def _style_refs_for_section(
    archive: SkinArchive,
    css: Dict[str, Dict[str, str]],
    res_path: str,
    values: Dict[str, str],
    include_pressed: bool,
) -> List[StyleImageRef]:
    return _style_refs_for_key(
        archive=archive,
        css=css,
        res_path=res_path,
        back_style=str(values.get("BACK_STYLE", "")),
        include_pressed=include_pressed,
    )


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
    gen_ini: Dict[str, Dict[str, str]],
    include_pressed: bool,
    size_basis: PanelSizeBasis,
) -> Optional[PanelLayout]:
    ini_path = f"{skin_paths['port']}{ini_name}"
    ini_text = archive.read_text(ini_path)
    if not ini_text:
        return None
    ini = parse_ini(ini_text)

    raw_keys: List[tuple[str, Rect, Dict[str, str], List[StyleImageRef]]] = []
    all_refs: List[StyleImageRef] = []
    for section in sorted_numbered_sections(ini, "KEY"):
        values = ini[section]
        rect = parse_rect(values.get("VIEW_RECT"))
        refs = _style_refs_for_section(
            archive=archive,
            css=css,
            res_path=skin_paths["res"],
            values=values,
            include_pressed=include_pressed,
        )
        all_refs.extend(refs)
        if rect:
            raw_keys.append((section, rect, values, refs))

    image_size = _get_primary_atlas_size(archive, all_refs)
    width, height, size_note = _get_panel_size(
        ini=ini,
        key_rects=((item[1], str(item[2].get("CENTER", "")).strip().strip("'\"")) for item in raw_keys),
        gen_ini=gen_ini,
        image_size=image_size,
        size_basis=size_basis,
    )
    keys: List[KeySlot] = []
    for section, rect, values, refs in raw_keys:
        center = str(values.get("CENTER", "")).strip().strip("'\"")
        if _is_full_panel_key(rect, width, height, center):
            continue
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
        size_note=size_note,
    )


def parse_skin_package(
    data: bytes,
    filename: str,
    panel_keys: Optional[Sequence[str]] = None,
    include_pressed: bool = True,
    size_basis: PanelSizeBasis = "default",
) -> SkinPackage:
    """解析目标底包，返回适配所需的面板和图集引用。"""

    archive = SkinArchive(data, filename)
    diagnostics: List[str] = []
    panels: List[PanelLayout] = []
    selected = list(panel_keys or DEFAULT_PANEL_SELECTION)
    themes = detect_themes(archive.paths)

    for theme in themes:
        skin_paths = find_skin_paths(archive.paths, theme)
        css_text = archive.read_text(f"{skin_paths['res']}default.css")
        gen_text = archive.read_text(f"{skin_paths['port']}gen.ini")
        if not css_text:
            diagnostics.append(f"{theme or 'default'}: 未找到 default.css")
            continue
        css = parse_ini(css_text)
        gen_ini = parse_ini(gen_text) if gen_text else {}
        if not gen_text:
            diagnostics.append(f"{theme or 'default'}: 未找到 gen.ini，使用面板自身尺寸/VIEW_RECT 兜底")

        for panel_key in selected:
            ini_name = DEFAULT_PANEL_FILES.get(panel_key, f"{panel_key}.ini")
            panel = parse_panel_layout(
                archive=archive,
                theme=theme,
                panel_key=panel_key,
                ini_name=ini_name,
                skin_paths=skin_paths,
                css=css,
                gen_ini=gen_ini,
                include_pressed=include_pressed,
                size_basis=size_basis,
            )
            if panel:
                panels.append(panel)
            else:
                diagnostics.append(f"{theme or 'default'}: {ini_name} 未找到可替换按键")

    return SkinPackage(archive=archive, themes=themes, panels=panels, diagnostics=diagnostics)
