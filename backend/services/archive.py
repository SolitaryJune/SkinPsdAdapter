from __future__ import annotations

import io
import os
import re
import struct
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Optional, Union

from .ini_parser import decode_text


ZIP_UTF8_FLAG = 0x800


def _normalize_archive_path(path: str) -> Optional[str]:
    """把 ZIP 内路径规整成安全的 POSIX 相对路径。

    Windows 发包时尤其要注意：压缩包里可能出现反斜杠、绝对盘符、`..` 或 macOS 元数据。
    后端永远只使用规整后的“可见路径”，避免写回时被恶意路径穿透。
    """

    raw = str(path or "").replace("\\", "/")
    if not raw or "\0" in raw or raw.startswith("/"):
        return None
    first = raw.split("/", 1)[0]
    if re.match(r"^[A-Za-z]:", first):
        return None

    parts: List[str] = []
    for part in PurePosixPath(raw).parts:
        if part in ("", "."):
            continue
        if part == "..":
            return None
        lower = part.lower()
        if lower == "__macosx" or (lower.startswith(".") and lower not in (".", "..")):
            return None
        parts.append(part)
    return "/".join(parts) if parts else None


def _decode_zip_name(raw_name: bytes, uses_utf8: bool) -> str:
    """按 ZIP 标志位和老皮肤包习惯解码文件名。"""

    if uses_utf8:
        return raw_name.decode("utf-8", errors="replace")
    for encoding in ("utf-8", "gbk", "gb18030", "cp437"):
        try:
            return raw_name.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_name.decode("cp437", errors="replace")


def _read_central_directory_names(data: bytes) -> List[str]:
    """从中央目录读取原始文件名字节。

    Python 的 `zipfile` 会先按 CP437/UTF-8 解码文件名；老 .bds/.bdi 如果是 GBK 名，
    `ZipInfo.filename` 可能已经变成乱码。这里按中央目录顺序再解一次，用于和 infolist 对齐。
    """

    max_comment = 65535
    search_from = max(0, len(data) - (22 + max_comment))
    eocd = data.rfind(b"PK\x05\x06", search_from)
    if eocd < 0 or eocd + 22 > len(data):
        return []

    total_entries = struct.unpack_from("<H", data, eocd + 10)[0]
    central_size = struct.unpack_from("<I", data, eocd + 12)[0]
    central_offset = struct.unpack_from("<I", data, eocd + 16)[0]
    central_end = central_offset + central_size
    if central_offset < 0 or central_end > eocd:
        return []

    names: List[str] = []
    offset = central_offset
    for _ in range(total_entries):
        if offset + 46 > central_end or data[offset : offset + 4] != b"PK\x01\x02":
            return []
        flags = struct.unpack_from("<H", data, offset + 8)[0]
        name_length = struct.unpack_from("<H", data, offset + 28)[0]
        extra_length = struct.unpack_from("<H", data, offset + 30)[0]
        comment_length = struct.unpack_from("<H", data, offset + 32)[0]
        name_start = offset + 46
        name_end = name_start + name_length
        if name_end > central_end:
            return []
        names.append(_decode_zip_name(data[name_start:name_end], bool(flags & ZIP_UTF8_FLAG)))
        offset = name_end + extra_length + comment_length
    return names


@dataclass(frozen=True)
class ArchiveEntry:
    visible_path: str
    zip_info: zipfile.ZipInfo


class SkinArchive:
    """面向 .bds/.bdi/.zip 的只读 + 替换写回工具。

    设计原则是：解析时用“可见路径”，写回时保留原包其它文件，只替换生成的新 PNG/TIL。
    第一版不会改 ZIP 伪加密标志；如果后续要兼容更怪的包，可以在这个类里集中增强。
    """

    def __init__(self, data: bytes, filename: str = "skin.bds") -> None:
        self.data = data
        self.filename = filename
        self._zip = zipfile.ZipFile(io.BytesIO(data), "r")
        self._entries: List[ArchiveEntry] = []
        self._entry_by_lower: Dict[str, ArchiveEntry] = {}
        self._build_entries()

    def close(self) -> None:
        self._zip.close()

    def _build_entries(self) -> None:
        decoded_names = _read_central_directory_names(self.data)
        infos = self._zip.infolist()
        for index, info in enumerate(infos):
            decoded = decoded_names[index] if index < len(decoded_names) else info.filename
            visible_path = _normalize_archive_path(decoded or info.filename)
            if not visible_path or info.is_dir():
                continue
            entry = ArchiveEntry(visible_path=visible_path, zip_info=info)
            self._entries.append(entry)
            self._entry_by_lower[visible_path.lower()] = entry

    @property
    def paths(self) -> List[str]:
        return [entry.visible_path for entry in self._entries]

    def find_path(self, target: str) -> Optional[str]:
        """宽松查找路径：先精确，再大小写，再按 basename 兜底。"""

        normalized = _normalize_archive_path(target)
        if not normalized:
            return None
        lower = normalized.lower()
        if lower in self._entry_by_lower:
            return self._entry_by_lower[lower].visible_path

        basename = os.path.basename(lower)
        candidates = [
            entry.visible_path
            for entry in self._entries
            if entry.visible_path.lower().endswith("/" + basename)
            or entry.visible_path.lower() == basename
        ]
        if not candidates:
            return None

        # 路径里包含目标目录片段的优先，例如 dark/res/26.png 优先于其它同名文件。
        target_parts = [part for part in lower.split("/") if part]
        for candidate in candidates:
            candidate_lower = candidate.lower()
            if all(part in candidate_lower for part in target_parts[:-1]):
                return candidate
        return candidates[0]

    def read_binary(self, target: str) -> Optional[bytes]:
        matched = self.find_path(target)
        if not matched:
            return None
        entry = self._entry_by_lower[matched.lower()]
        return self._zip.read(entry.zip_info)

    def read_text(self, target: str) -> Optional[str]:
        data = self.read_binary(target)
        return decode_text(data) if data is not None else None

    def write_replaced(self, replacements: Dict[str, Union[bytes, str]]) -> bytes:
        """复制原包并替换指定文件。

        replacements 的 key 使用可见路径；如果 key 在原包中存在，就保持原条目的文件名和压缩参数。
        新增文件则使用 UTF-8 路径写入。这个方法只做“替换/新增”，不删除原包其它内容。
        """

        normalized_replacements: Dict[str, bytes] = {}
        for path, payload in replacements.items():
            normalized = _normalize_archive_path(path)
            if not normalized:
                continue
            normalized_replacements[normalized.lower()] = (
                payload.encode("utf-8") if isinstance(payload, str) else payload
            )

        output = io.BytesIO()
        written: set[str] = set()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for entry in self._entries:
                key = entry.visible_path.lower()
                payload = normalized_replacements.get(key)
                if payload is None:
                    payload = self._zip.read(entry.zip_info)

                info = zipfile.ZipInfo(filename=entry.zip_info.filename)
                info.date_time = entry.zip_info.date_time
                info.external_attr = entry.zip_info.external_attr
                info.compress_type = zipfile.ZIP_DEFLATED
                zout.writestr(info, payload)
                written.add(key)

            for key, payload in normalized_replacements.items():
                if key in written:
                    continue
                # 新增路径已经是 lower key，这里保留小写即可；皮肤资源通常对大小写不敏感。
                zout.writestr(key, payload)

        return output.getvalue()


def is_zip_like(filename: str, data: bytes) -> bool:
    lower = filename.lower()
    return lower.endswith((".zip", ".bds", ".bdi", ".it", ".skinb")) or data.startswith(b"PK")


def iter_zip_files(data: bytes) -> Iterable[tuple[str, bytes]]:
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        decoded_names = _read_central_directory_names(data)
        for index, info in enumerate(zf.infolist()):
            if info.is_dir():
                continue
            name = decoded_names[index] if index < len(decoded_names) else info.filename
            visible = _normalize_archive_path(name or info.filename)
            if not visible:
                continue
            yield visible, zf.read(info)

