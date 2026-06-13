from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from .ini_parser import Rect


@dataclass(frozen=True)
class KeyPreset:
    """小程序前端用于识别标准键位的坐标模板。"""

    rect: Rect
    text: str


# 小程序 parseKeysFromINI 的自动补全模板。它和 POSITION_PRESETS 的用途不同：
# POSITION_PRESETS 负责给已有键命名；这些模板负责在底包少写 KEY 时补出缺失矩形。
TEMPLATE_17: tuple[Rect, ...] = (
    Rect(170, 0, 247, 149),
    Rect(416, 0, 247, 149),
    Rect(662, 0, 247, 149),
    Rect(170, 148, 247, 149),
    Rect(416, 148, 247, 149),
    Rect(662, 148, 247, 149),
    Rect(170, 296, 247, 149),
    Rect(416, 296, 247, 149),
    Rect(662, 296, 247, 149),
    Rect(340, 444, 399, 149),
    Rect(908, 0, 171, 149),
    Rect(908, 148, 171, 149),
    Rect(908, 296, 171, 297),
    Rect(170, 444, 171, 149),
    Rect(738, 444, 171, 149),
    Rect(0, 444, 171, 149),
    Rect(0, 0, 172, 448),
)

TEMPLATE_SYMBOL_7: tuple[Rect, ...] = (
    Rect(170, 0, 908, 555),
    Rect(0, 554, 170, 148),
    Rect(170, 554, 170, 148),
    Rect(340, 554, 398, 148),
    Rect(738, 554, 170, 148),
    Rect(908, 554, 170, 148),
    Rect(0, 0, 170, 555),
)

TEMPLATE_NUM9_18: tuple[Rect, ...] = (
    Rect(170, 0, 248, 149),
    Rect(416, 0, 248, 149),
    Rect(662, 0, 248, 149),
    Rect(170, 148, 248, 149),
    Rect(416, 148, 248, 149),
    Rect(662, 148, 248, 149),
    Rect(170, 296, 248, 149),
    Rect(416, 296, 248, 149),
    Rect(662, 296, 248, 149),
    Rect(416, 444, 248, 148),
    Rect(908, 0, 171, 149),
    Rect(908, 148, 171, 149),
    Rect(908, 296, 171, 149),
    Rect(908, 444, 171, 148),
    Rect(0, 444, 172, 148),
    Rect(170, 444, 248, 148),
    Rect(662, 444, 248, 148),
    Rect(0, 0, 171, 444),
)

TEMPLATE_HWGRID_9: tuple[Rect, ...] = (
    Rect(170, 0, 739, 445),
    Rect(908, 0, 171, 149),
    Rect(908, 148, 171, 149),
    Rect(908, 296, 171, 297),
    Rect(0, 444, 171, 148),
    Rect(170, 444, 171, 148),
    Rect(340, 444, 399, 148),
    Rect(738, 444, 171, 148),
    Rect(0, 0, 171, 445),
)


# 这些模板直接对齐小程序 packageSkin/shared/keyboard-layout-helper.ts。
# 设计稿里的 CENTER 经常是 F36、F38 这类内部占位符，所以贴纸前景页会优先按坐标识别真实键名。
POSITION_PRESETS: dict[str, list[KeyPreset]] = {
    "py_26_chinese": [
        KeyPreset(Rect(0, 0, 115, 165), "Q"),
        KeyPreset(Rect(114, 0, 115, 165), "W"),
        KeyPreset(Rect(228, 0, 115, 165), "E"),
        KeyPreset(Rect(342, 0, 115, 165), "R"),
        KeyPreset(Rect(456, 0, 115, 165), "T"),
        KeyPreset(Rect(570, 0, 115, 165), "Y"),
        KeyPreset(Rect(684, 0, 115, 165), "U"),
        KeyPreset(Rect(798, 0, 115, 165), "I"),
        KeyPreset(Rect(912, 0, 115, 165), "O"),
        KeyPreset(Rect(1026, 0, 115, 165), "P"),
        KeyPreset(Rect(58, 164, 113, 165), "A"),
        KeyPreset(Rect(170, 164, 113, 165), "S"),
        KeyPreset(Rect(282, 164, 113, 165), "D"),
        KeyPreset(Rect(394, 164, 113, 165), "F"),
        KeyPreset(Rect(506, 164, 113, 165), "G"),
        KeyPreset(Rect(618, 164, 113, 165), "H"),
        KeyPreset(Rect(730, 164, 113, 165), "J"),
        KeyPreset(Rect(842, 164, 113, 165), "K"),
        KeyPreset(Rect(954, 164, 113, 165), "L"),
        KeyPreset(Rect(0, 328, 171, 165), "大写"),
        KeyPreset(Rect(170, 328, 113, 165), "Z"),
        KeyPreset(Rect(282, 328, 113, 165), "X"),
        KeyPreset(Rect(394, 328, 113, 165), "C"),
        KeyPreset(Rect(506, 328, 113, 165), "V"),
        KeyPreset(Rect(618, 328, 113, 165), "B"),
        KeyPreset(Rect(730, 328, 113, 165), "N"),
        KeyPreset(Rect(842, 328, 113, 165), "M"),
        KeyPreset(Rect(954, 328, 227, 165), "删除"),
        KeyPreset(Rect(0, 492, 113, 165), "符号"),
        KeyPreset(Rect(112, 492, 113, 165), "123"),
        KeyPreset(Rect(224, 492, 113, 165), ","),
        KeyPreset(Rect(336, 492, 397, 165), "空格"),
        KeyPreset(Rect(732, 492, 113, 165), "."),
        KeyPreset(Rect(844, 492, 113, 165), "中/英"),
        KeyPreset(Rect(956, 492, 171, 165), "发送"),
    ],
    "py_26_english": [
        KeyPreset(Rect(0, 0, 115, 165), "q"),
        KeyPreset(Rect(114, 0, 115, 165), "w"),
        KeyPreset(Rect(228, 0, 115, 165), "e"),
        KeyPreset(Rect(342, 0, 115, 165), "r"),
        KeyPreset(Rect(456, 0, 115, 165), "t"),
        KeyPreset(Rect(570, 0, 115, 165), "y"),
        KeyPreset(Rect(684, 0, 115, 165), "u"),
        KeyPreset(Rect(798, 0, 115, 165), "i"),
        KeyPreset(Rect(912, 0, 115, 165), "o"),
        KeyPreset(Rect(1026, 0, 115, 165), "p"),
        KeyPreset(Rect(58, 164, 113, 165), "a"),
        KeyPreset(Rect(170, 164, 113, 165), "s"),
        KeyPreset(Rect(282, 164, 113, 165), "d"),
        KeyPreset(Rect(394, 164, 113, 165), "f"),
        KeyPreset(Rect(506, 164, 113, 165), "g"),
        KeyPreset(Rect(618, 164, 113, 165), "h"),
        KeyPreset(Rect(730, 164, 113, 165), "j"),
        KeyPreset(Rect(842, 164, 113, 165), "k"),
        KeyPreset(Rect(954, 164, 113, 165), "l"),
        KeyPreset(Rect(0, 328, 171, 165), "大写"),
        KeyPreset(Rect(170, 328, 113, 165), "z"),
        KeyPreset(Rect(282, 328, 113, 165), "x"),
        KeyPreset(Rect(394, 328, 113, 165), "c"),
        KeyPreset(Rect(506, 328, 113, 165), "v"),
        KeyPreset(Rect(618, 328, 113, 165), "b"),
        KeyPreset(Rect(730, 328, 113, 165), "n"),
        KeyPreset(Rect(842, 328, 113, 165), "m"),
        KeyPreset(Rect(954, 328, 227, 165), "删除"),
        KeyPreset(Rect(0, 492, 113, 165), "符号"),
        KeyPreset(Rect(112, 492, 113, 165), "123"),
        KeyPreset(Rect(224, 492, 113, 165), ","),
        KeyPreset(Rect(336, 492, 397, 165), "空格"),
        KeyPreset(Rect(732, 492, 113, 165), "."),
        KeyPreset(Rect(844, 492, 113, 165), "中/英"),
        KeyPreset(Rect(956, 492, 171, 165), "发送"),
    ],
    "py_9_upper": [
        KeyPreset(Rect(0, 0, 172, 160), ""),
        KeyPreset(Rect(170, 0, 247, 160), "分词"),
        KeyPreset(Rect(416, 0, 247, 160), "ABC"),
        KeyPreset(Rect(662, 0, 247, 160), "DEF"),
        KeyPreset(Rect(908, 0, 171, 160), "删除"),
        KeyPreset(Rect(170, 160, 247, 160), "GHI"),
        KeyPreset(Rect(416, 160, 247, 160), "JKL"),
        KeyPreset(Rect(662, 160, 247, 160), "MNO"),
        KeyPreset(Rect(908, 160, 171, 160), "清空"),
        KeyPreset(Rect(170, 320, 247, 160), "PQRS"),
        KeyPreset(Rect(416, 320, 247, 160), "TUV"),
        KeyPreset(Rect(662, 320, 247, 160), "WXYZ"),
        KeyPreset(Rect(908, 320, 171, 275), "发送"),
        KeyPreset(Rect(0, 480, 171, 115), "符号"),
        KeyPreset(Rect(170, 480, 171, 115), "123"),
        KeyPreset(Rect(340, 480, 399, 115), "空格"),
        KeyPreset(Rect(738, 480, 171, 115), "中/英"),
    ],
    "py_9_lower": [
        KeyPreset(Rect(0, 0, 172, 160), ""),
        KeyPreset(Rect(170, 0, 247, 160), "分词"),
        KeyPreset(Rect(416, 0, 247, 160), "abc"),
        KeyPreset(Rect(662, 0, 247, 160), "def"),
        KeyPreset(Rect(908, 0, 171, 160), "删除"),
        KeyPreset(Rect(170, 160, 247, 160), "ghi"),
        KeyPreset(Rect(416, 160, 247, 160), "jkl"),
        KeyPreset(Rect(662, 160, 247, 160), "mno"),
        KeyPreset(Rect(908, 160, 171, 160), "清空"),
        KeyPreset(Rect(170, 320, 247, 160), "pqrs"),
        KeyPreset(Rect(416, 320, 247, 160), "tuv"),
        KeyPreset(Rect(662, 320, 247, 160), "wxyz"),
        KeyPreset(Rect(908, 320, 171, 275), "发送"),
        KeyPreset(Rect(0, 480, 171, 115), "符号"),
        KeyPreset(Rect(170, 480, 171, 115), "123"),
        KeyPreset(Rect(340, 480, 399, 115), "空格"),
        KeyPreset(Rect(738, 480, 171, 115), "中/英"),
    ],
    "bh": [
        KeyPreset(Rect(0, 0, 172, 149), ""),
        KeyPreset(Rect(170, 0, 247, 149), "一"),
        KeyPreset(Rect(416, 0, 247, 149), "丨"),
        KeyPreset(Rect(662, 0, 247, 149), "丿"),
        KeyPreset(Rect(908, 0, 171, 149), "删除"),
        KeyPreset(Rect(170, 148, 247, 149), "丶"),
        KeyPreset(Rect(416, 148, 247, 149), "ㄥ"),
        KeyPreset(Rect(662, 148, 247, 149), "·"),
        KeyPreset(Rect(908, 148, 171, 149), "清空"),
        KeyPreset(Rect(170, 296, 247, 149), ","),
        KeyPreset(Rect(416, 296, 247, 149), ":"),
        KeyPreset(Rect(662, 296, 247, 149), ";"),
        KeyPreset(Rect(908, 296, 171, 297), "发送"),
        KeyPreset(Rect(0, 444, 171, 149), "符号"),
        KeyPreset(Rect(170, 444, 171, 149), "123"),
        KeyPreset(Rect(340, 444, 399, 149), "空格"),
        KeyPreset(Rect(738, 444, 171, 149), "中/英"),
    ],
    "symbol": [
        KeyPreset(Rect(0, 554, 170, 148), ""),
        KeyPreset(Rect(170, 554, 170, 148), "返回"),
        KeyPreset(Rect(340, 554, 398, 148), "下"),
        KeyPreset(Rect(738, 554, 170, 148), "上"),
        KeyPreset(Rect(908, 554, 170, 148), "删除"),
    ],
    "num_9": [
        KeyPreset(Rect(170, 0, 248, 149), "1"),
        KeyPreset(Rect(416, 0, 248, 149), "2"),
        KeyPreset(Rect(662, 0, 248, 149), "3"),
        KeyPreset(Rect(170, 148, 248, 149), "4"),
        KeyPreset(Rect(416, 148, 248, 149), "5"),
        KeyPreset(Rect(662, 148, 248, 149), "6"),
        KeyPreset(Rect(170, 296, 248, 149), "7"),
        KeyPreset(Rect(416, 296, 248, 149), "8"),
        KeyPreset(Rect(662, 296, 248, 149), "9"),
        KeyPreset(Rect(416, 444, 248, 148), "0"),
        KeyPreset(Rect(908, 0, 171, 149), "删除"),
        KeyPreset(Rect(908, 148, 171, 149), "@"),
        KeyPreset(Rect(908, 296, 171, 149), "."),
        KeyPreset(Rect(908, 444, 171, 148), "发送"),
        KeyPreset(Rect(0, 444, 172, 148), "符号"),
        KeyPreset(Rect(170, 444, 248, 148), "返回"),
        KeyPreset(Rect(662, 444, 248, 148), "空格"),
    ],
    "hw_grid": [
        KeyPreset(Rect(170, 0, 739, 445), ""),
        KeyPreset(Rect(908, 0, 171, 149), "删除"),
        KeyPreset(Rect(908, 148, 171, 149), "清空"),
        KeyPreset(Rect(908, 296, 171, 297), "发送"),
        KeyPreset(Rect(0, 444, 171, 148), "符号"),
        KeyPreset(Rect(170, 444, 171, 148), "123"),
        KeyPreset(Rect(340, 444, 399, 148), "空格"),
        KeyPreset(Rect(738, 444, 171, 148), "中/英"),
        KeyPreset(Rect(0, 0, 171, 445), ""),
    ],
}


def get_preset_key_for_layout(filename: str, layout_type: str = "chinese") -> str:
    """按小程序规则由 ini 文件名和中英文布局类型选择模板。"""

    lower = filename.lower()
    if "py_26" in lower or "en_26" in lower:
        return f"py_26_{layout_type}"
    if "py_9" in lower or "en_9" in lower:
        return "py_9_upper" if layout_type == "chinese" else "py_9_lower"
    if "bh" in lower:
        return "bh"
    if "num_9" in lower:
        return "num_9"
    if "symbol" in lower:
        return "symbol"
    if "hw_grid" in lower:
        return "hw_grid"
    return ""


def infer_layout_type(panel_key: str, ini_name: str) -> str:
    """独立工具没有小程序那套 layout id，这里用面板名判断中英文模板。"""

    lower = f"{panel_key}/{ini_name}".lower()
    return "english" if "en_26" in lower or "en_9" in lower else "chinese"


def _rect_iou(a: Rect, b: Rect) -> float:
    left = max(a.x, b.x)
    top = max(a.y, b.y)
    right = min(a.right, b.right)
    bottom = min(a.bottom, b.bottom)
    inter = max(0, right - left) * max(0, bottom - top)
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def _coverage(a: Rect, b: Rect) -> float:
    left = max(a.x, b.x)
    top = max(a.y, b.y)
    right = min(a.right, b.right)
    bottom = min(a.bottom, b.bottom)
    inter = max(0, right - left) * max(0, bottom - top)
    # 对齐小程序 calcCoverage(key, preset)：按键覆盖“预设槽位”的比例。
    return inter / max(1, b.area)


def _scale_template(template: Sequence[Rect], width: int, height: int, base_width: int, base_height: int) -> list[Rect]:
    scale_x = width / max(1, base_width)
    scale_y = height / max(1, base_height)
    return [slot.scaled(scale_x, scale_y) for slot in template]


def _group_by_near(values: Sequence[int], eps: int = 6) -> list[int]:
    groups: list[list[int]] = []
    for value in sorted(values):
        for group in groups:
            if abs(group[0] - value) <= eps:
                group.append(value)
                break
        else:
            groups.append([value])
    return [round(sum(group) / len(group)) for group in groups]


def _average(values: Sequence[int]) -> int:
    return round(sum(values) / len(values)) if values else 0


def _nearest(value: int, candidates: Sequence[int]) -> int | None:
    if not candidates:
        return None
    return min(candidates, key=lambda item: abs(item - value))


def _mark_template_matches(
    visible: Sequence[Rect],
    expected: Sequence[Rect],
    *,
    iou_threshold: float,
    coverage_first: bool = False,
) -> list[bool]:
    """按小程序规则判断哪些模板槽位已被真实 KEY 占用。"""

    matched = [False] * len(expected)
    if coverage_first:
        for index, slot in enumerate(expected):
            matched[index] = any(_coverage(rect, slot) >= 0.8 for rect in visible)

    for rect in visible:
        best_index = -1
        best_iou = 0.0
        for index, slot in enumerate(expected):
            if coverage_first and matched[index]:
                continue
            iou = _rect_iou(rect, slot)
            if iou > best_iou:
                best_index = index
                best_iou = iou
        if best_index >= 0 and best_iou >= iou_threshold and not matched[best_index]:
            matched[best_index] = True
    return matched


def _cluster_metrics(visible: Sequence[Rect]) -> tuple[list[int], list[int], dict[int, int], dict[int, int]]:
    """提取已有键的行列聚类，用来把补全键吸附到真实底包坐标。"""

    eps = 6
    col_xs = _group_by_near([rect.x for rect in visible], eps)
    row_ys = sorted(_group_by_near([rect.y for rect in visible], eps))
    col_widths = {
        x: _average([rect.w for rect in visible if abs(rect.x - x) <= eps])
        for x in col_xs
    }
    row_heights = {
        y: _average([rect.h for rect in visible if abs(rect.y - y) <= eps])
        for y in row_ys
    }
    return col_xs, row_ys, col_widths, row_heights


def _first_rows_height(visible: Sequence[Rect], row_ys: Sequence[int], row_heights: dict[int, int], left_main_col_x: int | None) -> int:
    if left_main_col_x is not None:
        col_keys = sorted((rect for rect in visible if abs(rect.x - left_main_col_x) <= 6), key=lambda item: item.y)
        total = sum(rect.h for rect in col_keys[:3])
        if total > 0:
            return total

    heights = [row_heights.get(y, 0) for y in list(row_ys)[:3]]
    if not heights:
        return 0
    sorted_heights = sorted(heights)
    median = sorted_heights[len(sorted_heights) // 2] if sorted_heights else 0
    clipped = [median if median and height > median * 1.7 else height for height in heights]
    return sum(clipped)


def _append_missing_template_rects(
    visible: Sequence[Rect],
    expected: Sequence[Rect],
    matched: Sequence[bool],
    width: int,
    height: int,
    *,
    left_bar_index: int | None = None,
    main_index: int | None = None,
    num9_left_bar: bool = False,
) -> list[Rect]:
    """把未命中的模板槽位补进来，并按真实行列尺寸做轻量吸附。"""

    if not visible:
        return list(visible)

    col_xs, row_ys, col_widths, row_heights = _cluster_metrics(visible)
    left_col_x = next((x for x in col_xs if abs(x) <= 6), 0)
    left_col_widths = [rect.w for rect in visible if abs(rect.x - left_col_x) <= 6]
    positive_cols = sorted(x for x in col_xs if x > 0)
    left_main_col_x = positive_cols[0] if positive_cols else None
    left_col_typical_w = _average(left_col_widths)
    if left_col_typical_w <= 0 and left_main_col_x is not None:
        left_col_typical_w = col_widths.get(left_main_col_x, 0)

    main_area_h = 0
    if main_index is not None and 0 <= main_index < len(expected):
        main_slot = expected[main_index]
        main_area_h = main_slot.h
        best_iou = 0.0
        for rect in visible:
            iou = _rect_iou(rect, main_slot)
            if iou > best_iou:
                best_iou = iou
                main_area_h = rect.h

    max_row_height = max(row_heights.values(), default=0)
    augmented = list(visible)
    for index, slot in enumerate(expected):
        if matched[index]:
            continue

        auto = slot
        near_left = slot.x <= max(5, round(width * 0.01))
        near_top = slot.y <= max(5, round(height * 0.01))
        is_left_bar = index == left_bar_index or (near_left and near_top)
        if num9_left_bar:
            is_left_bar = near_left and near_top and slot.h >= max_row_height * 2

        if is_left_bar:
            auto = Rect(
                x=0,
                y=0,
                w=left_col_typical_w or auto.w,
                h=(main_area_h if main_area_h > 0 else _first_rows_height(visible, row_ys, row_heights, left_main_col_x)) or auto.h,
            )
        elif main_index is not None and index == main_index and main_area_h > 0:
            auto = Rect(auto.x, auto.y, auto.w, main_area_h)
        else:
            snap_col = _nearest(slot.x, col_xs)
            snap_row = _nearest(slot.y, row_ys)
            if snap_col is not None and col_widths.get(snap_col):
                auto = Rect(snap_col, auto.y, col_widths[snap_col], auto.h)
            if snap_row is not None and row_heights.get(snap_row):
                auto = Rect(auto.x, snap_row, auto.w, row_heights[snap_row])

        augmented.append(auto.clamp(width, height))
    return augmented


def auto_fill_rects(rects: Sequence[Rect], width: int, height: int, filename: str) -> tuple[list[Rect], int]:
    """复刻小程序 autoFillKeys：底包少写常见键位时，按标准模板补出矩形。

    返回值是 `(补全后的矩形列表, 新增数量)`。新增矩形没有原始 TIL 引用，只用于预览/PSD 图层；
    如果要写回底包，仍只能写已有 KEY 的 BACK_STYLE/HL_IMG/NM_IMG 切片。
    """

    lower = filename.lower()
    visible = list(rects)
    if not visible:
        return visible, 0

    if ("bh.ini" in lower or "py_9.ini" in lower or "en_9.ini" in lower or "bh" in lower or "py_9" in lower or "en_9" in lower) and len(visible) < 17:
        expected = _scale_template(TEMPLATE_17, width, height, 1080, 595)
        matched = _mark_template_matches(visible, expected, iou_threshold=0.2)
        filled = _append_missing_template_rects(visible, expected, matched, width, height)
        return filled, len(filled) - len(visible)

    if ("num_9.ini" in lower or "num_9" in lower) and len(visible) < 18:
        expected = _scale_template(TEMPLATE_NUM9_18, width, height, 1080, 595)
        matched = _mark_template_matches(visible, expected, iou_threshold=0.2)
        filled = _append_missing_template_rects(visible, expected, matched, width, height, num9_left_bar=True)
        return filled, len(filled) - len(visible)

    if ("symbol.ini" in lower or "symbol" in lower) and len(visible) < 7:
        expected = _scale_template(TEMPLATE_SYMBOL_7, width, height, 1080, 704)
        matched = _mark_template_matches(visible, expected, iou_threshold=0.25, coverage_first=True)
        filled = _append_missing_template_rects(visible, expected, matched, width, height, left_bar_index=6, main_index=0)
        return filled, len(filled) - len(visible)

    if ("hw_grid.ini" in lower or "hw_grid" in lower) and len(visible) < 9:
        expected = _scale_template(TEMPLATE_HWGRID_9, width, height, 1080, 595)
        matched = _mark_template_matches(visible, expected, iou_threshold=0.25, coverage_first=True)
        filled = _append_missing_template_rects(visible, expected, matched, width, height, left_bar_index=8, main_index=0)
        return filled, len(filled) - len(visible)

    return visible, 0


def _symbol_bottom_labels(rects: Sequence[Rect], fallbacks: Sequence[str]) -> list[str]:
    """复刻小程序 symbol.ini 的特殊逻辑：底部键按 X 从左到右直接命名。"""

    if not rects:
        return []
    max_y = max(rect.y for rect in rects)
    bottom_threshold = max_y * 0.7
    bottom = [(rect, index) for index, rect in enumerate(rects) if rect.y > bottom_threshold]
    sorted_bottom = sorted(bottom, key=lambda item: item[0].x)
    bottom_texts = ["返回", "下", "上", "删除"]
    bottom_label_by_index = {
        index: bottom_texts[position]
        for position, (_rect, index) in enumerate(sorted_bottom)
        if position < len(bottom_texts)
    }
    return [
        bottom_label_by_index.get(index) or (fallbacks[index] if index < len(fallbacks) else "")
        for index in range(len(rects))
    ]


def match_preset_by_position(
    rects: Sequence[Rect],
    filename: str,
    canvas_width: int,
    canvas_height: int,
    layout_type: str = "chinese",
    fallbacks: Sequence[str] | None = None,
) -> list[str]:
    """按坐标识别标准键名。

    这段算法和小程序一致：先把模板按当前画布缩放，再综合 IoU、覆盖度和中心点距离打分。
    识别出的名字只用于展示/图层命名，不会改原始 INI、CSS 或 TIL。
    """

    fallback_values = list(fallbacks or [])
    preset_key = get_preset_key_for_layout(filename, layout_type)
    presets = POSITION_PRESETS.get(preset_key)
    if not presets:
        return [fallback_values[index] if index < len(fallback_values) else "" for index in range(len(rects))]
    if preset_key == "symbol":
        return _symbol_bottom_labels(rects, fallback_values)

    base_width = max((preset.rect.right for preset in presets), default=1)
    base_height = max((preset.rect.bottom for preset in presets), default=1)
    scale_x = canvas_width / max(1, base_width)
    scale_y = canvas_height / max(1, base_height)
    used_presets: set[int] = set()
    result: list[str] = []

    for index, rect in enumerate(rects):
        best_text = ""
        best_score = 0.0
        best_index = -1

        for preset_index, preset in enumerate(presets):
            if preset_index in used_presets:
                continue
            scaled = Rect(
                x=round(preset.rect.x * scale_x),
                y=round(preset.rect.y * scale_y),
                w=max(1, round(preset.rect.w * scale_x)),
                h=max(1, round(preset.rect.h * scale_y)),
            )

            key_center_x = (rect.x + rect.w / 2) / max(1, canvas_width)
            key_center_y = (rect.y + rect.h / 2) / max(1, canvas_height)
            preset_center_x = (preset.rect.x + preset.rect.w / 2) / max(1, base_width)
            preset_center_y = (preset.rect.y + preset.rect.h / 2) / max(1, base_height)
            # 小程序对 X 轴权重更高，因为横向错位最容易把相邻字母识别串位。
            distance = math.sqrt((key_center_x - preset_center_x) ** 2 * 9 + (key_center_y - preset_center_y) ** 2)
            normalized_distance = 1 - min(1.0, distance * 1.5)
            score = _rect_iou(rect, scaled) * 0.2 + _coverage(rect, scaled) * 0.2 + normalized_distance * 0.6

            if score > best_score:
                best_score = score
                best_text = preset.text
                best_index = preset_index

        if best_text and best_index >= 0:
            result.append(best_text)
            used_presets.add(best_index)
        else:
            result.append(fallback_values[index] if index < len(fallback_values) else "")

    return result
