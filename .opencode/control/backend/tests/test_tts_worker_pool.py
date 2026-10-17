"""TtsWorkerPool 单测（真并发/排队/接口兼容/服务级并发实证）。"""
# pyright: reportMissingParameterType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportAny=false, reportMissingTypeArgument=false
from __future__ import annotations

import queue as _queue
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.tts_service import TtsWorkerPool, WorkerResponse  # noqa: E402


class _StubClient:
    """可控桩 worker: 记录并发峰值 + 可注入处理延迟 + 落盘假 wav。"""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self._lock = threading.Lock()
        self._inflight = 0
        self.max_inflight = 0
        self.calls = 0
        self.alive = True
        self.shutdown_called = False

    def request(self, payload: dict) -> WorkerResponse:
        with self._lock:
            self._inflight += 1
            self.calls += 1
            self.max_inflight = max(self.max_inflight, self._inflight)
        try:
            if self.delay:
                time.sleep(self.delay)
            out = Path(str(payload["out"]))
            out.write_bytes(b"RIFF-fake-wav")
            return WorkerResponse(ok=True, path=str(out), duration=1.0)
        finally:
            with self._lock:
                self._inflight -= 1

    def shutdown(self) -> None:
        self.shutdown_called = True


def _pool_with_stubs(size: int, delay: float = 0.0):
    pool = TtsWorkerPool(size=size)
    for c in pool._clients:
        c.shutdown()  # 释放真实 client 占位（未启动，无进程——防御性）
    stubs = [_StubClient(delay) for _ in range(size)]
    pool._clients = stubs  # type: ignore[assignment]  # 测试注入
    free: "_queue.Queue[_StubClient]" = _queue.Queue()
    for s in stubs:
        free.put(s)
    pool._free = free  # type: ignore[assignment]  # 测试注入
    return pool, stubs


def test_pool_concurrent_requests_use_two_clients() -> None:
    """两并发请求进入两个不同 client（真并发——总耗时≈单请求, 非串行和）。"""
    pool, stubs = _pool_with_stubs(2, delay=0.15)
    results: list[WorkerResponse] = []

    def call() -> None:
        results.append(pool.request({"op": "synth", "out": "/tmp/x"}))

    threads = [threading.Thread(target=call) for _ in range(2)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - t0
    assert len(results) == 2
    assert all(c.calls == 1 for c in stubs)   # 双桩各一——真分发（非重试/单桩）
    assert elapsed < 0.28                     # 并行（串行 0.30+——宽裕断言）


def test_pool_third_request_queues() -> None:
    """无空闲时第三个请求排队（阻塞——背压语义）。"""
    pool, _stubs = _pool_with_stubs(2, delay=0.25)
    done: list[float] = []
    lock = threading.Lock()

    def call() -> None:
        pool.request({"op": "synth", "out": "/tmp/x"})
        with lock:
            done.append(time.monotonic())

    threads = [threading.Thread(target=call) for _ in range(3)]
    for t in threads:
        t.start()
    time.sleep(0.05)  # 让前两个先占满两个槽
    for t in threads:
        t.join()
    assert len(done) == 3
    done.sort()
    assert done[2] - done[1] >= 0.15   # 第三个等了前一轮才拿到槽


def test_pool_alive_and_shutdown() -> None:
    pool, stubs = _pool_with_stubs(2)
    assert pool.alive
    pool.shutdown()
    assert all(c.shutdown_called for c in stubs)


def test_pool_interface_mock_compatible(monkeypatch) -> None:
    """接口兼容: 实例级 patch request 生效（现有测试的 mock 模式）。"""
    pool, _stubs = _pool_with_stubs(2)
    monkeypatch.setattr(pool, "request",
                        lambda payload: WorkerResponse(ok=True, path="x", duration=0.0))
    r = pool.request({"op": "synth"})
    assert r.ok and r.path == "x"


def test_service_level_concurrent_synthesize(monkeypatch) -> None:
    """服务级: 两并发 synthesize 真并行（总耗时 < 串行和）; 单请求路径不变。"""
    import services.remote_link as rl
    from services.tts_service import TtsService

    TtsService._reset_for_tests()
    svc = TtsService.get_instance()
    monkeypatch.setattr(rl.RemoteLinkService, "should_use_remote",
                        lambda self: False)
    pool, stubs = _pool_with_stubs(2, delay=0.15)
    svc._worker = pool  # type: ignore[assignment]  # 测试注入
    monkeypatch.setattr(svc, "_qc_check", lambda *a, **k: None)

    results = []

    def run(text: str) -> None:
        results.append(svc.synthesize(text))

    t0 = time.monotonic()
    ts = [threading.Thread(target=run, args=(t,)) for t in ("并发甲文本", "并发乙文本")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    elapsed = time.monotonic() - t0
    try:
        assert len(results) == 2
        assert all(len(r.wav) > 0 for r in results)
        assert all(c.calls == 1 for c in stubs)   # 真并行分发
        assert elapsed < 0.28                      # 串行需 0.30+
    finally:
        TtsService._reset_for_tests()


def test_pool_warm_all_targets_each_worker() -> None:
    """warm_all: 池内每个 worker 各被烧一次（覆盖范围=池容量——与池大小不脱节）。"""
    pool, stubs = _pool_with_stubs(2)
    n = pool.warm_all(lambda i: {"op": "synth", "out": f"/tmp/warm{i}"})
    assert n == 2
    assert all(c.calls == 1 for c in stubs)   # 两桩各一次（真覆盖, 非重试单桩）


def test_service_warm_local_workers() -> None:
    """服务级: warm_local_workers 全池预热（唯一入口——节点预载/远程促热共用）。"""
    from services.tts_service import TtsService

    TtsService._reset_for_tests()
    svc = TtsService.get_instance()
    pool, stubs = _pool_with_stubs(2)
    svc._worker = pool  # type: ignore[assignment]  # 测试注入
    try:
        n = svc.warm_local_workers()
        assert n == 2
        assert all(c.calls == 1 for c in stubs)
    finally:
        TtsService._reset_for_tests()


def test_release_waits_inflight_and_clears_cache(monkeypatch) -> None:
    """release: 取满域许可——等全部在途完成（不杀请求）后关 worker + 缓存零残留。

    容量 1→2 后取单票只能挡住一路在途（本用例为池化配套回归防线）。
    """
    import services.remote_link as rl
    from services.tts_service import TtsService

    TtsService._reset_for_tests()
    svc = TtsService.get_instance()
    monkeypatch.setattr(rl.RemoteLinkService, "should_use_remote",
                        lambda self: False)
    started = threading.Event()
    finish = threading.Event()

    def _slow_local(*_a: object, **_k: object) -> "tuple[bytes, float]":
        started.set()
        finish.wait(timeout=5)  # 挂住"在途"
        return b"wav-slow", 1.0

    monkeypatch.setattr(svc, "_synth_qc_local", _slow_local)
    results = []
    t = threading.Thread(target=lambda: results.append(svc.synthesize("在途文本")))
    t.start()
    assert started.wait(timeout=2)
    done = threading.Event()

    def _rel() -> None:
        svc.release()
        done.set()

    tr = threading.Thread(target=_rel)
    tr.start()
    try:
        assert not done.wait(timeout=0.3), "release 不应在在途完成前返回（取满语义）"
        finish.set()
        tr.join(timeout=5)
        t.join(timeout=5)
        assert done.is_set()
        assert len(results) == 1                     # 在途请求未被杀（正常返回）
        with svc._cache_lock:                        # type: ignore[attr-defined]
            assert len(svc._cache) == 0              # 卸载后缓存零残留
    finally:
        finish.set()
        TtsService._reset_for_tests()
