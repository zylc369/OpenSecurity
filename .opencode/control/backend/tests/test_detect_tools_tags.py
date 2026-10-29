"""detect_tools tags 维度测试（ToolTag 圈选 / tool_available 缓存与未知名）。"""
from __future__ import annotations

from services.detect_tools import (
    EXTERNAL_TOOLS,
    ToolTag,
    _TOOL_AVAIL_CACHE,
    tool_available,
)


def test_ffmpeg_entry_tagged() -> None:
    """ffmpeg 条目存在且带 TTS_RUNTIME 标签（agents 保留隐写场景语义）。"""
    ff = [t for t in EXTERNAL_TOOLS if t.name == "ffmpeg"]
    assert len(ff) == 1
    assert ToolTag.TTS_RUNTIME in ff[0].tags
    assert "binary-analysis" in ff[0].agents


def test_tool_available_unknown_name_false() -> None:
    """未知工具名 → False（不抛错——引导链判空安全）。"""
    assert tool_available("definitely_not_a_tool_xyz") is False


def test_tool_available_cached(monkeypatch) -> None:
    """进程内缓存: 首探后不再重复扫描（scan_tool 只调一次）; refresh 强制重探。"""
    calls = {"n": 0}

    class _FakeScanner:
        def scan_tool(self, field):  # noqa: ANN001 —— 测试替身
            calls["n"] += 1
            from dataclasses import dataclass

            @dataclass
            class _St:
                available: bool = True
            return _St()

    from services.detect_tools import ToolField
    probe_field = ToolField(name="cache_probe_tool", agents=[], required=False)
    import services.detect_tools as dt
    # 探针条目注入清单（field 非 None 才会走到 scan_tool）
    monkeypatch.setattr(dt, "EXTERNAL_TOOLS", dt.EXTERNAL_TOOLS + [probe_field])
    monkeypatch.setattr(dt.ToolsScanner, "get_instance",
                        classmethod(lambda cls: _FakeScanner()))
    try:
        assert tool_available("cache_probe_tool") is True
        assert tool_available("cache_probe_tool") is True  # 命中缓存（不重扫）
        assert calls["n"] == 1
        assert tool_available("cache_probe_tool", refresh=True) is True
        assert calls["n"] == 2
    finally:
        _TOOL_AVAIL_CACHE.pop("cache_probe_tool", None)


def test_install_by_tags_selects_only_ffmpeg(monkeypatch) -> None:
    """TTS_RUNTIME 圈选只圈中 ffmpeg（其余工具未打标签; 幂等参数透传）。"""
    from services.detect_tools import ToolsInstaller

    inst = ToolsInstaller.get_instance()
    called: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        inst, "install_tool",
        lambda name, force=False: called.append((name, force)) or
        _mk_result(name), raising=True)
    results = inst.install_by_tags([ToolTag.TTS_RUNTIME], force=False)
    assert called == [("ffmpeg", False)]
    assert len(results) == 1


def _mk_result(name: str):  # noqa: ANN202 —— 测试辅助
    from services.detect_tools import InstallResult
    return InstallResult(name=name, status="installed", detail="test")
