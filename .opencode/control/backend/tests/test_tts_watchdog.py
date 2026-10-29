"""TTS 空闲看门狗行为测试（TtsWorkerClient 层——阈值释放 / 链式重排 / 常驻不建）。

防线的真实故障形态:
  • one-shot Timer 不重排: 检查只在"请求后整点"发生一次, 稳定静置下
    1800s 阈值永远到不了（空闲内存永不释放, 只能手动卸载）
  • 常驻策略（=0）仍建看门狗: 白耗 Timer
"""
from __future__ import annotations

import time

import pytest

from services import model_policy
from services.tts_service import TtsWorkerClient


class _FakeProc:
    """伪造 worker 子进程（记录 kill; watchdog 判定不查 poll）。"""

    def __init__(self) -> None:
        self.killed = False

    def poll(self) -> None:
        return None

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float = 0) -> int:
        return 0


@pytest.fixture(autouse=True)
def _clean_policy():
    model_policy.reset_overrides_for_tests()
    yield
    model_policy.reset_overrides_for_tests()


def _mk(interval: float = 0.05) -> "tuple[TtsWorkerClient, _FakeProc]":
    svc = TtsWorkerClient()  # 构造轻量, 不发子进程
    proc = _FakeProc()
    svc._proc = proc  # pyright: ignore[reportAttributeAccessIssue]  (测试伪造存活 worker)
    svc._last_active = time.monotonic()
    svc._idle_check_interval_sec = interval
    return svc, proc


def _cancel(svc: TtsWorkerClient) -> None:
    if svc._idle_watchdog is not None:
        svc._idle_watchdog.cancel()
        svc._idle_watchdog = None


def test_release_after_threshold() -> None:
    """达阈值 → 释放（kill 被调）。"""
    model_policy.apply_idle_override("cosyvoice3-8bit", 0.15)
    svc, proc = _mk()
    try:
        svc._ensure_idle_watchdog()
        time.sleep(0.5)  # 0.15 阈值 + 0.05 周期 + 余量
        assert proc.killed, "达阈值后应释放 worker"
    finally:
        _cancel(svc)


def test_watchdog_chains_when_not_due() -> None:
    """★ 精确防回归: 未达阈值时检查必须链式重排（one-shot 不重排 → 永不释放）。"""
    model_policy.apply_idle_override("cosyvoice3-8bit", 0.4)
    svc, proc = _mk()
    try:
        svc._ensure_idle_watchdog()
        time.sleep(0.20)  # 已过多个检查周期, 未达 0.4 阈值
        assert svc._idle_watchdog is not None, (
            "未达阈值必须重排下一次检查（one-shot 不重排 = 空闲永不释放）")
        assert not proc.killed
        time.sleep(0.5)  # 阈值到达
        assert proc.killed, "重排链路必须最终到达阈值并释放"
    finally:
        _cancel(svc)


def test_permanent_never_arms() -> None:
    """常驻（=0）→ 不建看门狗。"""
    model_policy.apply_idle_override("cosyvoice3-8bit", 0)
    svc, _proc = _mk()
    svc._ensure_idle_watchdog()
    assert svc._idle_watchdog is None


def test_no_proc_no_rearm() -> None:
    """worker 不在（未启动/已释放）→ 检查后不再重排（无内存可收）。"""
    model_policy.apply_idle_override("cosyvoice3-8bit", 0.1)
    svc, _proc = _mk()
    svc._proc = None
    svc._ensure_idle_watchdog()
    time.sleep(0.25)
    assert svc._idle_watchdog is None, "无 worker 时检查不应重排"
