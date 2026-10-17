"""no_cache 贯通单测（P3 预热可信化: 跳过缓存读写的强制真合成）。"""
# pyright: reportMissingParameterType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportAny=false, reportMissingTypeArgument=false
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.tts_service import TtsService, WorkerResponse  # noqa: E402


def _reset_for_tests() -> None:
    TtsService._reset_for_tests()


@pytest.fixture(autouse=True)
def _fresh_service(monkeypatch, tmp_path):
    """独立实例 + 远程路由关闭 + 假 worker（复用 test_tts_service 模式）。"""
    _reset_for_tests()
    svc = TtsService.get_instance()
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
    monkeypatch.setattr(svc, "_qc_check", lambda *a, **k: None)
    yield svc, calls
    _reset_for_tests()


def test_no_cache_skips_read_and_write(_fresh_service):
    """no_cache=True: 真合成（worker 被调）+ 不留缓存条目。"""
    svc, calls = _fresh_service
    r1 = svc.synthesize("预热水。", no_cache=True)
    assert r1.cached is False and len(calls) == 1
    # 第一次没写缓存 → 第二次同文本仍真合成
    r2 = svc.synthesize("预热水。")
    assert r2.cached is False and len(calls) == 2
    # 第二次（普通路径）写了缓存 → 第三次命中
    r3 = svc.synthesize("预热水。")
    assert r3.cached is True and len(calls) == 2


def test_no_cache_true_bypasses_existing_cache(_fresh_service):
    """已缓存文本 + no_cache=True → 仍真合成（预热不被缓存吸收）。"""
    svc, calls = _fresh_service
    svc.synthesize("已缓存的。")                      # 正常写缓存
    assert svc.synthesize("已缓存的。").cached is True
    r = svc.synthesize("已缓存的。", no_cache=True)   # 预热穿透
    assert r.cached is False and len(calls) == 2


def test_tts_synth_payload_contains_no_cache() -> None:
    """remote_client: no_cache 进入 /api/tts payload（P2P 与 HTTP 共用一处）。"""
    from typing import cast

    from services.remote_client import RemoteConsoleClient
    from services.remote_transport import TransportConfig
    from services.remote_wire import ApiResp

    cfg = TransportConfig(relay_host="127.0.0.1", relay_port=1,
                          psk=b"\x00" * 32, node_id="n")
    c = RemoteConsoleClient("http://unit-test", p2p=cfg)
    captured: dict[str, object] = {}

    class _FakeTransport:
        def request(self, method, path, body, token="", timeout=None):
            captured["payload"] = body
            return ApiResp(msg_id=0, status=200, mime="audio/wav",
                           body=b"RIFF-fake")

    c._transport = cast("object", _FakeTransport())  # type: ignore[assignment]
    wav = c.tts_synth("好。", "", 1.0, no_cache=True)
    assert wav == b"RIFF-fake"
    payload = cast("dict[str, object]", captured["payload"])
    assert payload["no_cache"] is True
    assert payload["text"] == "好。"
    # 默认不带（向后兼容——False 也显式在 payload，语义一致）
    c.tts_synth("好。", "", 1.0)
    payload2 = cast("dict[str, object]", captured["payload"])
    assert payload2["no_cache"] is False


def test_remote_branch_forwards_no_cache(monkeypatch):
    """主控远程分支: no_cache 透传到 client.tts_synth（节点侧才可真穿透）。"""
    _reset_for_tests()
    svc = TtsService.get_instance()
    import services.remote_link as rl
    # 防御跨文件单例泄漏（历史: 有测试向单例注入 get_client 实例属性，
    # 实例字典优先于类属性——类级 monkeypatch 会被遮蔽）: 先复位单例
    rl.RemoteLinkService._reset_for_tests()
    monkeypatch.setattr(rl.RemoteLinkService, "should_use_remote",
                        lambda self: True)
    captured: dict = {}

    class _FakeClient:
        def tts_synth(self, text, voice, speed, instruct="", seed=-1, mode="",
                      no_cache=False):
            captured["no_cache"] = no_cache
            return b"RIFF-fake"

    monkeypatch.setattr(rl.RemoteLinkService, "get_client",
                        lambda self: _FakeClient())
    try:
        r = svc.synthesize("预热水。", no_cache=True)
        assert r.source == "remote"
        assert captured["no_cache"] is True
        r2 = svc.synthesize("普通水。")
        assert captured["no_cache"] is False
    finally:
        _reset_for_tests()
