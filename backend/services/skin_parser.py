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
from .keyboard_templates import infer_layout_type, match_preset_by_position


STYLE_IMAGE_PROPS = ("NM_IMG", "HL_IMG")
PanelSizeBasis = Literal["default", "image"]
PanelLayoutBasis = Literal["ini", "til_scaled"]


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
    template_label: str = ""
    back_style: str = ""
    fore_style: str = ""
    style_refs: List[StyleImageRef] = field(default_factory=list)

    @property
    def debug_name(self) -> str:
        return self.template_label or self.center or self.section


@dataclass(frozen=True)
class ForegroundPathCandidate:
    """小程序前景入口会同时扫描的皮肤目录结构。"""

    theme: str
    structure: str
    port: str
    res: str


@dataclass
class ForegroundLayoutSignal:
    """一次面板命中的前景/贴纸识别信号。"""

    theme: str
    structure: str
    panel: str
    key_count: int
    foreground_images: List[str]
    background_images: List[str]
    valid_til_images: List[str]
    max_til_slice_count: int


@dataclass
class ForegroundDetection:
    """普通前景/贴纸前景的评分结果，规则对齐小程序 foreground-type-detector。"""

    type: str
    confidence: str
    normal_score: int
    sticker_score: int
    normal_layouts: List[ForegroundLayoutSignal]
    sticker_layouts: List[ForegroundLayoutSignal]
    css_file_count: int
    reason: str
    path_candidates: List[ForegroundPathCandidate]


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
    layout_note: str = ""

    @property
    def title(self) -> str:
        return f"{self.theme or 'default'} / {self.panel_key}"


@dataclass
class SkinPackage:
    archive: SkinArchive
    themes: List[str]
    panels: List[PanelLayout]
    diagnostics: List[str] = field(default_factory=list)
    foreground_detection: Optional[ForegroundDetection] = None


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

FOREGROUND_PATH_PATTERNS: tuple[ForegroundPathCandidate, ...] = (
    ForegroundPathCandidate("light", "android-theme", "light/port/", "light/res/"),
    ForegroundPathCandidate("dark", "android-theme", "dark/port/", "dark/res/"),
    ForegroundPathCandidate("light", "ios-theme", "skin/light/skin/port/", "skin/light/skin/res/"),
    ForegroundPathCandidate("dark", "ios-theme", "skin/dark/skin/port/", "skin/dark/skin/res/"),
    ForegroundPathCandidate("light", "ios-theme", "light/skin/port/", "light/skin/res/"),
    ForegroundPathCandidate("dark", "ios-theme", "dark/skin/port/", "dark/skin/res/"),
    ForegroundPathCandidate("default", "root-skin", "skin/port/", "skin/res/"),
    ForegroundPathCandidate("default", "root", "port/", "res/"),
)

SHARED_STICKER_FOREGROUND_NAMES = {"qj", "gnqj"}


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

    if theme:
        # 优先级对齐小程序 findThemeResourcePath：android 主题目录，其次 theme/skin，再其次 iOS skin/theme/skin。
        patterns = [f"{theme}/port/", f"{theme}/skin/port/", f"skin/{theme}/skin/port/", "port/"]
    else:
        patterns = ["skin/port/", "port/"]
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


def _normalize_zip_entry_path(path: str) -> str:
    return str(path or "").replace("\\", "/").strip("/").replace("//", "/").lower()


def _join_zip_path(base_path: str, file_name: str) -> str:
    base = _normalize_zip_entry_path(base_path)
    name = _normalize_zip_entry_path(file_name)
    return f"{base}/{name}".strip("/")


def _path_prefix_exists(path_set: set[str], prefix: str) -> bool:
    normalized = _normalize_zip_entry_path(prefix).rstrip("/") + "/"
    return any(path.startswith(normalized) for path in path_set)


def _exact_path_map(paths: Sequence[str]) -> Dict[str, str]:
    return {_normalize_zip_entry_path(path): path for path in paths}


def _read_text_exact(archive: SkinArchive, path_map: Dict[str, str], target: str) -> Optional[str]:
    """只按精确路径读取，避免 basename 兜底读到另一个主题的同名文件。"""

    matched = path_map.get(_normalize_zip_entry_path(target))
    return archive.read_text(matched) if matched else None


def _has_exact_path(path_map: Dict[str, str], target: str) -> bool:
    return _normalize_zip_entry_path(target) in path_map


def _ini_value(values: Dict[str, str], key: str) -> str:
    target = key.upper()
    for name, value in values.items():
        if name.upper() == target:
            return value
    return ""


def _normalize_style_image_name(value: str) -> str:
    normalized = _normalize_zip_entry_path(value)
    return re.sub(r"\.(png|til)$", "", normalized, flags=re.IGNORECASE)


def _resource_leaf_name(value: str) -> str:
    return os.path.basename(_normalize_style_image_name(value))


def _collect_foreground_path_candidates(paths: Sequence[str]) -> List[ForegroundPathCandidate]:
    path_set = {_normalize_zip_entry_path(path) for path in paths}
    return [
        candidate
        for candidate in FOREGROUND_PATH_PATTERNS
        if _path_prefix_exists(path_set, candidate.port) or _path_prefix_exists(path_set, candidate.res)
    ]


def _key_sections(ini: Dict[str, Dict[str, str]]) -> List[str]:
    return list(sorted_numbered_sections(ini, "KEY"))


def _count_keys_like_frontend(panel_ini: Dict[str, Dict[str, str]], filename: str) -> int:
    """复刻 parseKeysFromINI 的核心过滤，用于前景类型评分。

    这里只需要得到稳定的 keyCount，不创建可写回的 KeySlot，所以不依赖 CSS/TIL。
    """

    raw: List[tuple[Rect, str]] = []
    width = 0
    height = 0
    lower = filename.lower()
    is_py26 = "py_26" in lower or "en_26" in lower

    for section in _key_sections(panel_ini):
        rect = parse_rect(_ini_value(panel_ini[section], "VIEW_RECT"))
        if not rect:
            continue
        width = max(width, rect.right)
        height = max(height, rect.bottom)
        raw.append((rect, _ini_value(panel_ini[section], "CENTER").strip().strip("'\"")))

    width = width or 1080
    height = height or 595
    seen: set[str] = set()
    count = 0
    for rect, center in raw:
        same_size = abs(rect.x) <= 1 and abs(rect.y) <= 1 and abs(rect.w - width) <= 1 and abs(rect.h - height) <= 1
        same_area = rect.area == width * height
        mostly_covers = not center and abs(rect.x) <= 1 and abs(rect.y) <= 1 and rect.w >= width * 0.9 and rect.h >= height * 0.85
        if same_size or same_area or mostly_covers:
            continue
        if is_py26 and not center:
            continue
        signature = f"{rect.x},{rect.y},{rect.w},{rect.h}"
        if signature in seen:
            continue
        seen.add(signature)
        count += 1
    return count


def _collect_style_image_usage(
    panel_ini: Dict[str, Dict[str, str]],
    css: Dict[str, Dict[str, str]],
    style_prop: str,
) -> Dict[str, int]:
    """按小程序 skin-style-resource-resolver 统计 KEY -> STYLE -> PNG/TIL 引用次数。"""

    usage: Dict[str, int] = {}
    for section in _key_sections(panel_ini):
        values = panel_ini[section]
        for style_id in extract_style_ids(_ini_value(values, style_prop)):
            style = _style_section(css, style_id) or {}
            for image_prop in STYLE_IMAGE_PROPS:
                parsed = _parse_style_image_value(_ini_value(style, image_prop))
                if not parsed:
                    continue
                basename, _tile_index = parsed
                normalized = _normalize_style_image_name(basename)
                usage[normalized] = usage.get(normalized, 0) + 1
    return usage


def _repeated_style_image_names(usage: Dict[str, int], key_count: int, ratio: float = 0.35, min_count: int = 3) -> List[str]:
    threshold = max(min_count, int(key_count * ratio))
    return [name for name, count in usage.items() if count >= threshold]


def _count_til_slices(
    archive: SkinArchive,
    path_map: Dict[str, str],
    res_path: str,
    image_name: str,
    cache: Dict[str, int],
) -> int:
    til_path = _find_resource_path(path_map, res_path, image_name, ".til")
    cache_key = _normalize_zip_entry_path(til_path or _join_zip_path(res_path, f"{_normalize_style_image_name(image_name)}.til"))
    if cache_key in cache:
        return cache[cache_key]
    til_text = _read_text_exact(archive, path_map, til_path) if til_path else None
    count = len(parse_til_slices(til_text or "")) if til_text else 0
    cache[cache_key] = count
    return count


def _resource_path_candidates(res_path: str, image_name: str, ext: str) -> List[str]:
    """生成 CSS 图片引用可能对应的包内路径。

    CSS 有时写 `26`，有时写 `26.png`，也可能写完整相对路径；这里不只拼 res 目录，
    否则会把 `skin/dark/skin/res/26` 误拼成 `skin/dark/skin/res/skin/dark/skin/res/26`。
    """

    normalized = _normalize_style_image_name(image_name)
    leaf = os.path.basename(normalized)
    return [
        f"{normalized}{ext}",
        _join_zip_path(res_path, f"{normalized}{ext}"),
        _join_zip_path(res_path, f"{leaf}{ext}"),
    ]


def _find_resource_path(path_map: Dict[str, str], res_path: str, image_name: str, ext: str) -> str:
    for candidate in _resource_path_candidates(res_path, image_name, ext):
        matched = path_map.get(_normalize_zip_entry_path(candidate))
        if matched:
            return matched
    return ""


def _sticker_target_candidate(candidate: ForegroundPathCandidate) -> bool:
    # 小程序贴纸页只消费 light/dark 主题，root/root-skin 单结构主要是普通前景入口。
    return candidate.theme in {"light", "dark"}


def _has_light_dark_pair(candidates: Sequence[ForegroundPathCandidate]) -> bool:
    structures = {item.structure for item in candidates if item.theme in {"light", "dark"}}
    for structure in structures:
        has_light = any(item.structure == structure and item.theme == "light" for item in candidates)
        has_dark = any(item.structure == structure and item.theme == "dark" for item in candidates)
        if has_light and has_dark:
            return True
    return False


def _foreground_reason(foreground_type: str, normal_score: int, sticker_score: int) -> str:
    if foreground_type == "normal":
        return f"已识别为普通前景结构（普通 {normal_score} / 贴纸 {sticker_score}）"
    if foreground_type == "sticker":
        return f"已识别为贴纸前景结构（贴纸 {sticker_score} / 普通 {normal_score}）"
    if foreground_type == "both":
        return "普通前景和贴纸前景都可处理，请选择要使用的方式"
    return "未找到可修改的前景结构"


def _foreground_confidence(foreground_type: str, normal_score: int, sticker_score: int) -> str:
    if foreground_type in {"unknown", "both"}:
        return "low"
    diff = abs(normal_score - sticker_score)
    if diff >= 8:
        return "high"
    if diff >= 4:
        return "medium"
    return "low"


def detect_foreground_type(archive: SkinArchive) -> ForegroundDetection:
    """按小程序贴纸/普通前景入口的评分方式识别包类型。"""

    path_map = _exact_path_map(archive.paths)
    candidates = _collect_foreground_path_candidates(archive.paths)
    til_cache: Dict[str, int] = {}
    normal_layouts: List[ForegroundLayoutSignal] = []
    sticker_layouts: List[ForegroundLayoutSignal] = []
    all_foreground_images: List[str] = []
    css_paths: set[str] = set()
    repeated_background_atlas_panel_count = 0
    normal_score = 0
    sticker_score = 0

    if _has_light_dark_pair(candidates):
        sticker_score += 4
    for candidate in candidates:
        if candidate.structure in {"root-skin", "root"}:
            normal_score += 3

    for candidate in candidates:
        css_text = _read_text_exact(archive, path_map, _join_zip_path(candidate.res, "default.css"))
        if not css_text:
            continue
        css_paths.add(_normalize_zip_entry_path(_join_zip_path(candidate.res, "default.css")))
        css = parse_ini(css_text)

        for panel_file in DEFAULT_PANEL_FILES.values():
            panel_text = _read_text_exact(archive, path_map, _join_zip_path(candidate.port, panel_file))
            if not panel_text:
                continue
            panel_ini = parse_ini(panel_text)
            key_count = _count_keys_like_frontend(panel_ini, panel_file)
            if key_count <= 0:
                continue

            foreground_usage = _collect_style_image_usage(panel_ini, css, "FORE_STYLE")
            background_usage = _collect_style_image_usage(panel_ini, css, "BACK_STYLE")
            foreground_images = sorted(foreground_usage)
            background_images = sorted(background_usage)
            valid_til_images: List[str] = []
            max_til_slice_count = 0

            for image_name in foreground_images:
                slice_count = _count_til_slices(archive, path_map, candidate.res, image_name, til_cache)
                has_png = bool(_find_resource_path(path_map, candidate.res, image_name, ".png"))
                if slice_count > 0 and has_png:
                    valid_til_images.append(image_name)
                    max_til_slice_count = max(max_til_slice_count, slice_count)

            all_foreground_images.extend(_resource_leaf_name(name) for name in foreground_images)
            sticker_candidate = _sticker_target_candidate(candidate)
            has_repeated_background_atlas = False
            for image_name in _repeated_style_image_names(background_usage, key_count):
                slice_count = _count_til_slices(archive, path_map, candidate.res, image_name, til_cache)
                has_png = bool(_find_resource_path(path_map, candidate.res, image_name, ".png"))
                if slice_count > 0 and has_png:
                    has_repeated_background_atlas = True
                    break

            if sticker_candidate and has_repeated_background_atlas:
                repeated_background_atlas_panel_count += 1

            if sticker_candidate:
                sticker_score += 1
                sticker_layouts.append(
                    ForegroundLayoutSignal(
                        theme=candidate.theme,
                        structure=candidate.structure,
                        panel=panel_file,
                        key_count=key_count,
                        foreground_images=foreground_images,
                        background_images=background_images,
                        valid_til_images=valid_til_images,
                        max_til_slice_count=max_til_slice_count,
                    )
                )

            if valid_til_images:
                normal_score += 2
                if max_til_slice_count >= max(3, key_count // 2):
                    normal_score += 1
                normal_layouts.append(
                    ForegroundLayoutSignal(
                        theme=candidate.theme,
                        structure=candidate.structure,
                        panel=panel_file,
                        key_count=key_count,
                        foreground_images=foreground_images,
                        background_images=background_images,
                        valid_til_images=valid_til_images,
                        max_til_slice_count=max_til_slice_count,
                    )
                )

    unique_foreground_leaves = sorted({name.lower() for name in all_foreground_images if name})
    shared_sticker_count = len([name for name in unique_foreground_leaves if name in SHARED_STICKER_FOREGROUND_NAMES])
    if len(normal_layouts) >= 3 and 0 < len(unique_foreground_leaves) <= 4:
        sticker_score += 6
        if shared_sticker_count:
            sticker_score += 2
    if len(normal_layouts) >= 3 and len(unique_foreground_leaves) >= 3:
        normal_score += 3
    if repeated_background_atlas_panel_count >= 3:
        sticker_score += min(8, repeated_background_atlas_panel_count * 2)

    has_normal = bool(normal_layouts)
    has_sticker = bool(sticker_layouts)
    if not has_normal and not has_sticker:
        foreground_type = "unknown"
    elif has_normal and not has_sticker:
        foreground_type = "normal"
    elif has_sticker and not has_normal:
        foreground_type = "sticker"
    else:
        diff = abs(normal_score - sticker_score)
        if diff <= 3:
            foreground_type = "both"
        elif normal_score > sticker_score:
            foreground_type = "normal"
        else:
            foreground_type = "sticker"

    return ForegroundDetection(
        type=foreground_type,
        confidence=_foreground_confidence(foreground_type, normal_score, sticker_score),
        normal_score=normal_score,
        sticker_score=sticker_score,
        normal_layouts=normal_layouts,
        sticker_layouts=sticker_layouts,
        css_file_count=len(css_paths),
        reason=_foreground_reason(foreground_type, normal_score, sticker_score),
        path_candidates=candidates,
    )


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


def _select_layout_ref(refs: Sequence[StyleImageRef]) -> Optional[StyleImageRef]:
    """选择一个最适合反推按键位置的 TIL 引用。

    常态图 `NM_IMG` 比按压态 `HL_IMG` 更适合作为布局来源；如果没有常态图，再退回第一个引用。
    """

    for ref in refs:
        if ref.prop == "NM_IMG":
            return ref
    return refs[0] if refs else None


def _read_til_slices_cached(
    archive: SkinArchive,
    cache: Dict[str, Dict[int, Rect]],
    til_path: str,
) -> Dict[int, Rect]:
    if til_path in cache:
        return cache[til_path]
    til_text = archive.read_text(til_path)
    slices = parse_til_slices(til_text or "")
    cache[til_path] = slices
    return slices


def _resolve_til_layout_rects(
    archive: SkinArchive,
    raw_keys: Sequence[tuple[str, Rect, Dict[str, str], List[StyleImageRef]]],
    width: int,
    height: int,
) -> tuple[Dict[str, Rect], str]:
    """用 TIL 的 SOURCE_RECT 反推面板按键位置。

    TIL 坐标本质上是图集坐标，不一定等于屏幕坐标；贴纸包里常见 640/641 高度的外框。
    因此这里先取当前面板所有 TIL 切片的最大边界，再只对明显不一致的轴做缩放。
    """

    til_cache: Dict[str, Dict[int, Rect]] = {}
    candidates: List[tuple[str, Rect]] = []
    fallback_count = 0
    max_right = 0
    max_bottom = 0

    for section, view_rect, values, refs in raw_keys:
        center = str(values.get("CENTER", "")).strip().strip("'\"")
        if _is_full_panel_key(view_rect, width, height, center):
            continue

        ref = _select_layout_ref(refs)
        if not ref:
            fallback_count += 1
            continue

        slices = _read_til_slices_cached(archive, til_cache, ref.til_path)
        til_rect = slices.get(ref.tile_index)
        if not til_rect:
            fallback_count += 1
            continue

        candidates.append((section, til_rect))
        max_right = max(max_right, til_rect.right)
        max_bottom = max(max_bottom, til_rect.bottom)

    if not candidates or max_right <= 0 or max_bottom <= 0:
        return {}, "INI VIEW_RECT"

    scale_x = width / max_right if abs(max_right - width) > 8 else 1.0
    scale_y = height / max_bottom if abs(max_bottom - height) > 8 else 1.0
    rects: Dict[str, Rect] = {}
    for section, til_rect in candidates:
        rects[section] = Rect(
            x=round(til_rect.x * scale_x),
            y=round(til_rect.y * scale_y),
            w=max(1, round(til_rect.w * scale_x)),
            h=max(1, round(til_rect.h * scale_y)),
        )

    note = f"TIL SOURCE_RECT 缩放定位 bounds={max_right}x{max_bottom}, scale={scale_x:.4f},{scale_y:.4f}"
    if fallback_count:
        note += f", {fallback_count} 个键回退 VIEW_RECT"
    return rects, note


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
    layout_basis: PanelLayoutBasis,
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
    layout_rects: Dict[str, Rect] = {}
    layout_note = "INI VIEW_RECT"
    if layout_basis == "til_scaled":
        layout_rects, layout_note = _resolve_til_layout_rects(
            archive=archive,
            raw_keys=raw_keys,
            width=width,
            height=height,
        )

    is_py26_layout = "py_26" in ini_name.lower() or "en_26" in ini_name.lower()
    for section, rect, values, refs in raw_keys:
        center = str(values.get("CENTER", "")).strip().strip("'\"")
        if _is_full_panel_key(rect, width, height, center):
            continue
        # 小程序前端会丢弃 26 键面板里 CENTER 为空的装饰/占位 KEY，避免把边角占位误当按键拉伸。
        if is_py26_layout and not center:
            continue
        # 没有图集引用的装饰配置先跳过；后续如果要处理纯背景或候选栏，可在这里扩展。
        if not refs:
            continue
        keys.append(
            KeySlot(
                section=section,
                rect=layout_rects.get(section, rect),
                center=center,
                back_style=str(values.get("BACK_STYLE", "")),
                fore_style=str(values.get("FORE_STYLE", "")),
                style_refs=refs,
            )
        )

    if not keys:
        return None
    labels = match_preset_by_position(
        rects=[key.rect for key in keys],
        filename=ini_name,
        canvas_width=width,
        canvas_height=height,
        layout_type=infer_layout_type(panel_key, ini_name),
        fallbacks=[key.center or key.section for key in keys],
    )
    for key, label in zip(keys, labels):
        # 只作为展示/PSD 图层名使用，写回仍依赖原始 BACK_STYLE -> TIL 切片引用。
        key.template_label = label.strip() if label else ""
    return PanelLayout(
        theme=theme,
        panel_key=panel_key,
        ini_path=archive.find_path(ini_path) or ini_path,
        res_path=skin_paths["res"],
        width=width,
        height=height,
        keys=keys,
        size_note=size_note,
        layout_note=layout_note,
    )


def parse_skin_package(
    data: bytes,
    filename: str,
    panel_keys: Optional[Sequence[str]] = None,
    include_pressed: bool = True,
    size_basis: PanelSizeBasis = "default",
    layout_basis: PanelLayoutBasis = "ini",
) -> SkinPackage:
    """解析目标底包，返回适配所需的面板和图集引用。"""

    archive = SkinArchive(data, filename)
    diagnostics: List[str] = []
    panels: List[PanelLayout] = []
    selected = list(panel_keys or DEFAULT_PANEL_SELECTION)
    themes = detect_themes(archive.paths)
    foreground_detection = detect_foreground_type(archive)

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
                layout_basis=layout_basis,
            )
            if panel:
                panels.append(panel)
            else:
                diagnostics.append(f"{theme or 'default'}: {ini_name} 未找到可替换按键")

    return SkinPackage(
        archive=archive,
        themes=themes,
        panels=panels,
        diagnostics=diagnostics,
        foreground_detection=foreground_detection,
    )
