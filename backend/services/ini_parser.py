from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional


HIDDEN_KEYS = {
    "H_INFO",
    "G_INFO",
    "I_INFO",
    "J_INFO",
    "K_INFO",
    "L_INFO",
    "M_INFO",
    "N_INFO",
    "O_INFO",
    "P_INFO",
}


@dataclass(frozen=True)
class Rect:
    """皮肤配置里最常见的矩形结构：x,y,w,h。"""

    x: int
    y: int
    w: int
    h: int

    @property
    def area(self) -> int:
        return max(0, self.w) * max(0, self.h)

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def is_valid(self) -> bool:
        return self.w > 0 and self.h > 0

    def scaled(self, sx: float, sy: float) -> "Rect":
        """按比例缩放矩形，用于把目标键位映射到 PSD 渲染图坐标。"""

        return Rect(
            x=round(self.x * sx),
            y=round(self.y * sy),
            w=max(1, round(self.w * sx)),
            h=max(1, round(self.h * sy)),
        )

    def clamp(self, width: int, height: int) -> "Rect":
        """把矩形限制在图片范围内，防止 crop 读到负数或越界区域。"""

        left = max(0, min(width, self.x))
        top = max(0, min(height, self.y))
        right = max(left + 1, min(width, self.right))
        bottom = max(top + 1, min(height, self.bottom))
        return Rect(left, top, right - left, bottom - top)

    def to_box(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.right, self.bottom)


def decode_text(data: bytes) -> str:
    """按老皮肤包常见编码读取文本。

    .bds/.bdi 里不少配置文件是 GBK/GB18030；如果只用 UTF-8，会出现路径和中文注释解析失败。
    """

    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb18030", "gb2312", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def parse_ini(text: str) -> Dict[str, Dict[str, str]]:
    """解析百度输入法皮肤里的 INI/TIL/default.css 风格配置。

    这些文件表面像 INI，但经常夹杂中文说明行、空行和不规范片段；解析器要宽松，
    只收集真正的 [SECTION] 与 KEY=VALUE，避免一个注释行让整包失败。
    """

    data: Dict[str, Dict[str, str]] = {"_root": {}}
    section = "_root"

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if re.match(r"^[\u4e00-\u9fa5]", line) and "=" not in line:
            continue

        section_match = re.match(r"^\[(.+?)\]$", line)
        if section_match:
            section = section_match.group(1).strip()
            data.setdefault(section, {})
            continue

        equals_index = line.find("=")
        if equals_index < 0:
            continue

        key = line[:equals_index].strip()
        if key in HIDDEN_KEYS:
            continue
        data.setdefault(section, {})[key] = line[equals_index + 1 :].strip()

    return data


def parse_rect(value: object) -> Optional[Rect]:
    """从 `0,0,1080,595` 这类字符串提取矩形。"""

    match = re.search(r"(-?\d+)\s*,\s*(-?\d+)\s*,\s*(\d+)\s*,\s*(\d+)", str(value or ""))
    if not match:
        return None
    rect = Rect(
        x=int(match.group(1)),
        y=int(match.group(2)),
        w=int(match.group(3)),
        h=int(match.group(4)),
    )
    return rect if rect.is_valid() else None


def extract_style_ids(value: object) -> List[int]:
    """从 BACK_STYLE/FORE_STYLE 等字段提取样式编号。

    皮肤里常见写法是 `93,94,95,941,10`，也可能夹杂空格或历史垃圾字符；
    统一用正则提取数字，后续再去 default.css 找 STYLExx。
    """

    ids: List[int] = []
    for token in re.findall(r"\d+", str(value or "")):
        try:
            style_id = int(token)
        except ValueError:
            continue
        if style_id not in ids:
            ids.append(style_id)
    return ids


def sorted_numbered_sections(ini: Dict[str, Dict[str, str]], prefix: str) -> Iterable[str]:
    pattern = re.compile(rf"^\s*{re.escape(prefix)}(\d+)\s*$", re.IGNORECASE)

    def key_for(section_name: str) -> int:
        match = pattern.match(section_name)
        return int(match.group(1)) if match else 0

    return sorted((name for name in ini if pattern.match(name)), key=key_for)


def find_section_case_insensitive(ini: Dict[str, Dict[str, str]], name: str) -> Optional[Dict[str, str]]:
    target = name.upper()
    for section_name, values in ini.items():
        if section_name.upper() == target:
            return values
    return None

