"""services.log_query 单测（反向读/grep 语义/跨块边界/文件名校验）。"""
# pyright: reportMissingParameterType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportAny=false, reportMissingTypeArgument=false
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import log_query  # noqa: E402
from services.log_query import query_log  # noqa: E402


def _write(tmp_path: Path, name: str, text: str) -> None:
    (tmp_path / name).write_text(text, encoding="utf-8")


# ── 基础语义 ────────────────────────────────────────────────

def test_basic_match_limit_and_order(tmp_path: Path) -> None:
    """小文件：匹配过滤 + limit 截断 + 时间正序输出。"""
    lines = [f"L{i} {'hit' if i % 2 == 0 else 'miss'}" for i in range(1, 21)]
    _write(tmp_path, "a.log", "\n".join(lines) + "\n")
    r = query_log(tmp_path, "a.log", "hit", False, 3)
    assert r.lines == ["L16 hit", "L18 hit", "L20 hit"]
    assert r.more is True  # 更早还有命中未返回
    assert r.file == "a.log"


def test_more_exact_boundary(tmp_path: Path) -> None:
    """more 精确性：恰好耗尽 → False；有剩余 → True。"""
    _write(tmp_path, "b.log", "hit1\nmiss\nhit2\n")
    r2 = query_log(tmp_path, "b.log", "hit", False, 2)
    assert r2.lines == ["hit1", "hit2"]
    assert r2.more is False
    r1 = query_log(tmp_path, "b.log", "hit", False, 1)
    assert r1.lines == ["hit2"]
    assert r1.more is True


def test_empty_pattern_is_tail(tmp_path: Path) -> None:
    """空 pattern = 全部行（纯 tail）；裸空行与尾空段不出现，空白行保留。"""
    _write(tmp_path, "e.log", "a\n\nb\n   \nc\n")
    r = query_log(tmp_path, "e.log", "", True, 10)
    assert r.lines == ["a", "b", "   ", "c"]
    assert r.more is False


def test_regex_vs_literal(tmp_path: Path) -> None:
    """is_regex=True 走正则；False 走字面量（含元字符不炸）；非法正则抛 re.error。"""
    _write(tmp_path, "d.log", "[tts] a\nb\n[tts] c\n")
    assert query_log(tmp_path, "d.log", "[tts]", False, 10).lines == ["[tts] a", "[tts] c"]
    assert query_log(tmp_path, "d.log", r"\[tts\]", True, 10).lines == ["[tts] a", "[tts] c"]
    with pytest.raises(re.error):
        query_log(tmp_path, "d.log", "[tts", True, 10)


# ── 跨块与长行 ──────────────────────────────────────────────

def test_cross_chunk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """chunk 缩小到 64 字节：匹配行必然跨块，结果仍完整正确。"""
    monkeypatch.setattr(log_query, "_READ_CHUNK", 64)
    rows = [f"row-{i:03d} filler filler filler" for i in range(60)]
    rows[30] = "row-030 needle here"
    rows[31] = "row-031 needle again"
    _write(tmp_path, "c.log", "\n".join(rows) + "\n")
    r = query_log(tmp_path, "c.log", "needle", False, 10)
    assert r.lines == ["row-030 needle here", "row-031 needle again"]


def test_single_line_larger_than_chunk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """单行超 chunk（5000+ 字符）跨多块完整还原。"""
    monkeypatch.setattr(log_query, "_READ_CHUNK", 32)
    big = "X" * 5000 + " needle"
    _write(tmp_path, "g.log", "head\n" + big + "\ntail\n")
    r = query_log(tmp_path, "g.log", "needle", False, 5)
    assert r.lines == [big]


def test_first_and_last_lines_hit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """首行/末行命中（残片拼接的边界：文件头与 EOF）。"""
    monkeypatch.setattr(log_query, "_READ_CHUNK", 8)
    _write(tmp_path, "h.log", "needle-top\nmid\nneedle-bottom")
    r = query_log(tmp_path, "h.log", "needle", False, 5)
    assert r.lines == ["needle-top", "needle-bottom"]


# ── 编码与坏字节 ────────────────────────────────────────────

def test_utf8_and_bad_bytes(tmp_path: Path) -> None:
    """中文行正常；坏字节行 errors=replace 不抛且 ASCII 关键词仍可命中。"""
    p = tmp_path / "f.log"
    p.write_bytes(
        "第一行 needle 中文\n".encode("utf-8")
        + b"\xff\xfe bad \x00 needle\n"
        + "第三行\n".encode("utf-8")
    )
    r = query_log(tmp_path, "f.log", "needle", False, 10)
    assert len(r.lines) == 2
    assert "needle" in r.lines[0] and "中文" in r.lines[0]
    assert "needle" in r.lines[1]


# ── 文件名校验与文件状态 ────────────────────────────────────

def test_filename_validation_matrix(tmp_path: Path) -> None:
    """路径形态/字符集外/超长/空串一律 ValueError（防穿越）。"""
    for bad in ["../x.log", "a/b.log", "/abs.log", ".", "..", "", "x" * 129, "a b.log", "日志.log"]:
        with pytest.raises(ValueError):
            query_log(tmp_path, bad, "", True, 10)


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    """指向目录外的 symlink 拒绝（resolve 后父目录校验）。"""
    outside = tmp_path.parent / f"{tmp_path.name}-outside.log"
    outside.write_text("secret\n", encoding="utf-8")
    link = tmp_path / "link.log"
    link.symlink_to(outside)
    with pytest.raises(ValueError):
        query_log(tmp_path, "link.log", "", True, 10)


def test_missing_and_session_states(tmp_path: Path) -> None:
    """不存在 → FileNotFoundError；目录 → FileNotFoundError；空文件 → 空结果。"""
    (tmp_path / "sub").mkdir()
    with pytest.raises(FileNotFoundError):
        query_log(tmp_path, "nope.log", "", True, 10)
    with pytest.raises(FileNotFoundError):
        query_log(tmp_path, "sub", "", True, 10)
    _write(tmp_path, "empty.log", "")
    r = query_log(tmp_path, "empty.log", "", True, 10)
    assert r.lines == [] and r.more is False


def test_limit_and_pattern_guards(tmp_path: Path) -> None:
    """services 层兜底：limit<1 / pattern 超长 → ValueError。"""
    _write(tmp_path, "k.log", "x\n")
    with pytest.raises(ValueError):
        query_log(tmp_path, "k.log", "", True, 0)
    with pytest.raises(ValueError):
        query_log(tmp_path, "k.log", "x" * 1001, False, 10)
