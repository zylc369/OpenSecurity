"""TtsService 单测（worker 协议 mock——不起真模型; 远程路由强制本地）。"""
# pyright: reportMissingParameterType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportAny=false, reportMissingTypeArgument=false
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.tts_service import (  # noqa: E402
    TtsService, TtsUnavailable, WorkerResponse)


def _reset_for_tests() -> None:
    TtsService._reset_for_tests()


@pytest.fixture(autouse=True)
def _fresh_service(monkeypatch, tmp_path):
    """每用例独立实例 + 远程路由关闭 + 假 worker。"""
    _reset_for_tests()
    svc = TtsService.get_instance()
    # 远程链路不可用 → use_remote=False（本地路径）
    import services.remote_link as rl
    monkeypatch.setattr(rl.RemoteLinkService, "should_use_remote",
                        lambda self: False)
    calls: list[dict] = []

    class _FakeWorker:
        alive = True

        def request(self, payload: dict) -> WorkerResponse:
            calls.append(payload)
            out = Path(str(payload["out"]))
            out.write_bytes(b"RIFF-fake-wav-bytes")
            return WorkerResponse(ok=True, path=str(out), duration=1.0)

    monkeypatch.setattr(svc._worker, "request", _FakeWorker().request)
    monkeypatch.setattr(svc._worker, "_ensure", lambda: None)
    # 质检纯化: 协议单测不起真 ASR——否则"其它测试文件先加载了 funasr"
    # 时本文件行为漂移（假 wav 走真质检→判败→4 版重试, calls 断言翻车）
    monkeypatch.setattr(svc, "_qc_check", lambda *a, **k: None)
    yield svc, calls
    _reset_for_tests()


def test_synth_default_voice(_fresh_service):
    svc, calls = _fresh_service
    r = svc.synthesize("你好世界")
    assert r.wav.startswith(b"RIFF")
    assert r.cached is False
    assert r.voice == "official_female"  # 音色库默认（plus 定稿音色）
    assert len(calls) == 1
    assert calls[0]["ref_text"]  # 音色逐字稿透传 worker


def test_cache_hit(_fresh_service):
    svc, calls = _fresh_service
    svc.synthesize("同一段文本", speed=0.9)
    r2 = svc.synthesize("同一段文本", speed=0.9)
    assert r2.cached is True and r2.gen_ms == 0.0
    assert len(calls) == 1  # 只发一次 worker 请求
    # 不同 speed 不共享缓存
    svc.synthesize("同一段文本", speed=1.0)
    assert len(calls) == 2


def test_unknown_voice(_fresh_service):
    svc, _ = _fresh_service
    with pytest.raises(ValueError, match="未知音色"):
        svc.synthesize("文本", voice="不存在的音色")


def test_worker_error_surface(_fresh_service, monkeypatch):
    svc, _ = _fresh_service

    def _fail(payload: dict) -> WorkerResponse:
        return WorkerResponse(ok=False, error="RuntimeError: 模型崩")

    monkeypatch.setattr(svc._worker, "request", _fail)
    with pytest.raises(TtsUnavailable, match="worker 合成失败"):
        svc.synthesize("文本")


def test_speed_clamp(_fresh_service):
    svc, calls = _fresh_service
    svc.synthesize("文本", speed=99.0)   # 越界钳制到 3.0
    svc.synthesize("文本2", speed=0.1)   # 越界钳制到 0.5
    assert calls[0]["speed"] == 3.0 and calls[1]["speed"] == 0.5


def test_tail_silence_detection(tmp_path):
    """worker 尾部静音判定（纯函数——合成半截事故的检测器）。"""
    import importlib.util
    import numpy as np
    import soundfile as sf
    # worker 在 scripts/（非包内）——按路径加载
    spec = importlib.util.spec_from_file_location(
        "tts_worker", str(Path(__file__).parent.parent / "scripts" / "tts_worker.py"))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportAny] —— 动态加载边界
    spec.loader.exec_module(mod)  # pyright: ignore[reportUnknownMemberType] —— 动态加载边界

    sr = 24000
    # 正常音频（尾部有声）
    loud = tmp_path / "loud.wav"
    tone = np.full(sr * 12, 0.3, dtype=np.float32)
    sf.write(str(loud), tone, sr, subtype="PCM_16")
    checker = mod._tail_is_silent  # pyright: ignore[reportUnknownMemberType, reportAny] —— 动态加载
    assert checker(loud) is False
    # 尾部 10s 全静音（半截合成）
    silent = tmp_path / "silent.wav"
    tone2 = np.concatenate([np.full(sr * 2, 0.3, dtype=np.float32),
                            np.zeros(sr * 10, dtype=np.float32)])
    sf.write(str(silent), tone2, sr, subtype="PCM_16")
    assert checker(silent) is True
    # 短于检测窗（全有声）
    short = tmp_path / "short.wav"
    sf.write(str(short), np.full(sr * 3, 0.3, dtype=np.float32), sr, subtype="PCM_16")
    assert checker(short) is False
