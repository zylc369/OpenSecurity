# pyright: reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""TTS 锁拆分行为测试（本地域 / 远程域独立性）。

防线对应的真实故障形态:
  • 共锁阻塞: 远程请求"等网络回包"期间占着全局锁——任何本地请求被堵
    （实例: 节点冷启动 34.5s 期间本地试听排队）
  • 对话交错: 本地域容量退化（>1 并发进入 worker 对话 → 应答串台）
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import pytest

from services.remote_link import RemoteLinkService
from services.tts_service import LOCAL_WORKER_POOL_SIZE, TtsService


@dataclass
class _FakeClient:
    """远程 client 桩（tts_synth 由测试闭包控制）。"""

    on_call: "object"  # callable

    def tts_synth(self, text: str, voice: str, speed: float,
                  instruct: str = "", seed: int = -1, mode: str = "") -> bytes:
        return self.on_call(text)  # type: ignore[operator]  (测试桩)


def test_slow_remote_does_not_block_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 核心断言: 慢远程（阻塞）进行中, 本地请求应立即完成（拆锁回归防线）。"""
    svc = TtsService()
    remote_entered = threading.Event()
    release_remote = threading.Event()

    # 上游接管: 整体替换 get_instance 为受控桩对象（should/get_client/
    # note_request_failure 全控——绕开"前序文件留下的类/单例状态"一切疑难）
    def _slow_remote(_text: str) -> bytes:
        remote_entered.set()
        release_remote.wait(timeout=5)
        return b"remote-wav"

    class _Controlled:
        def should_use_remote(self) -> bool:
            return not remote_entered.is_set()

        def get_client(self) -> _FakeClient:
            return _FakeClient(on_call=_slow_remote)

        @staticmethod
        def note_request_failure(_reason: str) -> None:
            pass

    monkeypatch.setattr(RemoteLinkService, "get_instance",
                        classmethod(lambda cls: _Controlled()))
    monkeypatch.setattr(svc, "_qc_check", lambda *a, **k: None)  # 质检放行
    monkeypatch.setattr(svc, "_synth_qc_local",
                        lambda *a, **k: (b"local-wav", 1.0))

    results: "list[object]" = []
    errors: "list[str]" = []

    def _call_a() -> None:
        try:
            results.append(svc.synthesize("远程文本A"))
        except Exception as e:  # noqa: BLE001 —— 线程异常显性化（否则断言只见"未进入")
            errors.append(repr(e))
    ta = threading.Thread(target=_call_a, daemon=True)
    ta.start()
    got = remote_entered.wait(timeout=3)
    if not got:  # 诊断: A 未进入时打全线程栈（跨文件污染排查用）
        import faulthandler as _fh
        import sys as _sys
        _fh.dump_traceback(file=_sys.stderr)
    assert got, f"A 线程未进入远程分支（异常: {errors}）"

    t0 = time.monotonic()
    rb = svc.synthesize("本地文本B")
    dt = time.monotonic() - t0
    assert dt < 1.0, f"本地请求被慢远程阻塞（{dt:.2f}s——共锁回归）"
    assert rb.wav == b"local-wav" and rb.source == "local"

    release_remote.set()
    ta.join(timeout=5)
    assert len(results) == 1 and results[0].wav == b"remote-wav"  # type: ignore[union-attr]
    assert results[0].source == "remote"  # type: ignore[union-attr]


def test_local_semaphore_concurrency_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    """本地域容量=池大小(当前 1=串行): 并发峰值 ≤池大小; 超容请求排队。"""
    svc = TtsService()
    monkeypatch.setattr(RemoteLinkService, "should_use_remote",
                        lambda self: False)
    active = {"n": 0, "max": 0}
    guard = threading.Lock()

    def _fake_local(*_a: object, **_k: object) -> "tuple[bytes, float]":
        with guard:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
        time.sleep(0.15)
        with guard:
            active["n"] -= 1
        return b"wav", 1.0

    monkeypatch.setattr(svc, "_synth_qc_local", _fake_local)
    results: "list[object]" = []
    threads = [threading.Thread(
        target=lambda i=i: results.append(svc.synthesize(f"本地文本{i}")))
        for i in range(4)]
    start = time.monotonic()
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=5)
    elapsed = time.monotonic() - start
    assert active["max"] == LOCAL_WORKER_POOL_SIZE, (
        f"本地域并发峰应=池大小 {LOCAL_WORKER_POOL_SIZE}, 实际 {active['max']}")
    assert len(results) == 4
    # 4 请求 × 0.15s, 容量=LOCAL_WORKER_POOL_SIZE → 轮数=ceil(4/容量)
    rounds = -(-4 // LOCAL_WORKER_POOL_SIZE)
    assert elapsed >= 0.15 * rounds - 0.05, (
        f"超容应排队（{rounds} 轮）——实际 {elapsed:.2f}s")
