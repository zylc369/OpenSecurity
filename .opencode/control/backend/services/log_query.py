"""日志查询（反向 chunk 读取，grep + limit 语义）。

- 从文件尾部向前读块，返回"最近 limit 条匹配行"（时间正序）——等价于
  `grep -E "pattern" file | tail -n limit` 的高效实现（不扫描完整大文件即可
  命中大多数查询；命满即停）。
- 只读、无状态；`file` 限定调用方给定的日志目录内（单点校验，防路径穿越）。
- services 层不依赖 web 框架：异常用标准类型（`ValueError` / `re.error` /
  `FileNotFoundError`），由路由层映射为 HTTP 状态码。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_READ_CHUNK = 256 * 1024  # 反向读取块大小（函数体内读取；测试可 monkeypatch 缩小驱动跨块路径）
_FILE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_PATTERN_MAX_LEN = 1000


@dataclass(frozen=True)
class LogQueryResult:
    """日志查询结果（`lines` 为时间正序的最近匹配行）。"""

    file: str
    lines: list[str]
    more: bool


def _validate_file(log_dir: Path, file: str) -> Path:
    """校验并返回日志文件路径（非法 ValueError / 不存在 FileNotFoundError）。"""
    if not _FILE_NAME_RE.fullmatch(file) or file in (".", "..") or Path(file).name != file:
        raise ValueError(f"非法文件名: {file!r}（只接受日志目录内的文件名）")
    path = log_dir / file
    if not path.is_file():
        raise FileNotFoundError(f"日志文件不存在: {file}")
    if path.resolve().parent != log_dir.resolve():
        raise ValueError(f"非法文件名: {file!r}（越出日志目录）")
    return path


def _hit(line: str, pattern: str, matcher: "re.Pattern[str] | None") -> bool:
    """行是否命中（空 pattern 恒真；matcher 非 None 即正则模式）。"""
    if not pattern:
        return True
    if matcher is not None:
        return matcher.search(line) is not None
    return pattern in line


def query_log(log_dir: Path, file: str, pattern: str, is_regex: bool, limit: int) -> LogQueryResult:
    """返回 `log_dir/file` 中最近 `limit` 条匹配 `pattern` 的行（时间正序）。

    - `pattern` 空串 = 全部行（纯 tail 语义）；`is_regex=False` 为字面量包含。
    - `more=True` 表示还有更早的匹配未返回（精确 limit+1 探测）。
    - 异常契约：文件名非法 → ValueError；正则非法 → re.error；
      文件不存在 → FileNotFoundError。
    """
    if limit < 1:
        raise ValueError(f"limit 必须 >= 1（收到 {limit}）")
    if len(pattern) > _PATTERN_MAX_LEN:
        raise ValueError(f"pattern 超长（>{_PATTERN_MAX_LEN}）")
    path = _validate_file(log_dir, file)
    matcher = re.compile(pattern) if (is_regex and pattern) else None

    matched: list[str] = []  # 收集顺序为"从新到旧"，输出前反转
    with open(path, "rb") as f:
        f.seek(0, 2)
        pos = f.tell()
        remainder = b""  # 上一轮（更晚字节）的未完行片段
        while pos > 0:
            read_size = min(_READ_CHUNK, pos)
            pos -= read_size
            f.seek(pos)
            parts = (f.read(read_size) + remainder).split(b"\n")
            if pos == 0:
                candidates = parts  # 首块：parts[0] 即完整首行
            else:
                remainder = parts[0]  # 可能与更早块相连的残片——本轮不参与匹配
                candidates = parts[1:]
            for raw in reversed(candidates):
                if not raw:
                    continue  # 丢弃空串段（尾空段/裸空行）
                line = raw.decode("utf-8", errors="replace").rstrip("\r")
                if _hit(line, pattern, matcher):
                    matched.append(line)
                    if len(matched) > limit:
                        return LogQueryResult(file=file, lines=list(reversed(matched[:limit])), more=True)
    return LogQueryResult(file=file, lines=list(reversed(matched)), more=False)
