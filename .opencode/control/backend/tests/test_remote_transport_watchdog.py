"""transport 在途请求看门狗 + 消息级跟踪日志测试。

场景:
 1. 消息级跟踪: 正常请求应出现"api.req 已发送 / api.resp 已收到"成对 INFO 日志
 2. 看门狗·假活: 消息发出后无人响应且连接探测（ping）也失败
    → 请求在 watchdog_sec + probe_wait_sec 量级内快速失败（远小于总超时）
    → 异常消息非空（防"请求失败: "空消息回归）
 3. 看门狗·不误杀: 响应慢于 watchdog_sec 但连接健康（ping 有 pong）
    → 请求继续等待并最终成功
 4. TTS 超时常量收敛: TTS_TIMEOUT_SEC == 90.0

单元级构造: 可编程哑连接（_DummyConn）直接注入 transport._conn——
不走真网络，精确控制"是否响应 / 响应延迟"。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import cast

import pytest

from services import remote_wire
from services.remote_transport import (
    ApiJob, RelayConnection, RemoteTransport, TransportConfig, TransportError,
)


class _DummyConn:
    """可编程哑连接: 记录发出消息; ping/api 响应策略由测试配置。

    - ping_pong: True=立刻回 PongMsg; False=不回（模拟探测失败）
    - api_reply: None=不回（模拟假活）; float=延迟该秒数后回 ApiResp
    """

    def __init__(self, transport: RemoteTransport, *,
                 ping_pong: bool = True, api_reply: float | None = None,
                 ping_error: bool = False) -> None:
        self._t = transport
        self.ping_pong = ping_pong
        self.api_reply = api_reply
        self.ping_error = ping_error
        self.sent: "list[object]" = []
        self.broken = False
        self._tasks: "list[asyncio.Task[None]]" = []

    async def send_msg(self, msg: "object") -> None:
        self.sent.append(msg)
        loop = asyncio.get_running_loop()
        if isinstance(msg, remote_wire.PingMsg):
            if self.ping_error:
                raise OSError("探针发送失败（测试注入）")
            if self.ping_pong:
                async def _pong() -> None:
                    await asyncio.sleep(0.01)
                    await self._t._on_msg(  # noqa: SLF001 —— 测试注入
                        remote_wire.PongMsg(msg_id=msg.msg_id))
                self._tasks.append(loop.create_task(_pong()))
        elif isinstance(msg, remote_wire.ApiReq):
            if self.api_reply is not None:
                async def _resp() -> None:
                    await asyncio.sleep(self.api_reply)  # type: ignore[arg-type]
                    await self._t._on_msg(  # noqa: SLF001 —— 测试注入
                        remote_wire.ApiResp(msg_id=msg.msg_id, status=200,
                                            mime="application/json",
                                            body={"ok": True}))
                self._tasks.append(loop.create_task(_resp()))
        # 其余（ApiResp 等）忽略

    async def aclose(self) -> None:
        self.broken = True


def _mk_transport(**overrides: float) -> RemoteTransport:
    base: "dict[str, float]" = {"watchdog_sec": 1.0, "probe_wait_sec": 0.5}
    base.update(overrides)
    cfg = TransportConfig(
        relay_host="127.0.0.1", relay_port=1, psk=b"\x00" * 32,
        node_id="dummy", **base)
    t = RemoteTransport(cfg)
    t.start()
    return t


def test_watchdog_fakes_alive_fails_fast(caplog: pytest.LogCaptureFixture) -> None:
    """假活（api 无响应 + ping 无 pong）: 请求快速失败且异常消息非空。"""
    t = _mk_transport()
    try:
        dummy = _DummyConn(t, ping_pong=False, api_reply=None)

        async def _run() -> None:
            t._conn = cast("RelayConnection", dummy)  # noqa: SLF001 —— 注入
            loop = asyncio.get_running_loop()
            t0 = time.monotonic()
            with caplog.at_level(logging.INFO, logger="services.remote_transport"):
                with pytest.raises(TransportError) as ei:
                    await loop.run_in_executor(
                        None, lambda: t.request("POST", "/api/tts",
                                                {"text": "x"}, timeout=600.0))
            elapsed = time.monotonic() - t0
            # 快速失败: 远小于 600s（watchdog 1s + probe 0.5s + 余量）
            assert elapsed < 10.0, f"应快速失败，实际 {elapsed:.1f}s"
            msg = str(ei.value)
            # 异常消息非空（防"请求失败: "空消息回归）
            assert msg.strip() and msg != "请求失败: ", f"异常消息为空: {msg!r}"
            assert ("看门狗" in msg) or ("无响应" in msg), f"缺少原因: {msg!r}"
        asyncio.run(_run())
    finally:
        t.stop()


def test_watchdog_does_not_kill_slow_but_healthy(caplog: pytest.LogCaptureFixture) -> None:
    """慢但健康的连接: 响应慢于 watchdog_sec（ping 有 pong）→ 最终成功。"""
    t = _mk_transport()
    try:
        dummy = _DummyConn(t, ping_pong=True, api_reply=2.5)

        async def _run() -> None:
            t._conn = cast("RelayConnection", dummy)  # noqa: SLF001 —— 注入
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(
                None, lambda: t.request("POST", "/api/tts",
                                        {"text": "slow"}, timeout=600.0))
            assert isinstance(resp, remote_wire.ApiResp)
            assert resp.status == 200
        asyncio.run(_run())
    finally:
        t.stop()


def test_message_tracking_logs(caplog: pytest.LogCaptureFixture) -> None:
    """正常请求: "已发送 / 已收到"成对 INFO 日志各出现一次。"""
    t = _mk_transport()
    try:
        dummy = _DummyConn(t, ping_pong=True, api_reply=0.05)

        async def _run() -> None:
            t._conn = cast("RelayConnection", dummy)  # noqa: SLF001 —— 注入
            loop = asyncio.get_running_loop()
            with caplog.at_level(logging.INFO, logger="services.remote_transport"):
                await loop.run_in_executor(
                    None, lambda: t.request("POST", "/api/tts",
                                            {"text": "hi"}, timeout=600.0))
            text = "\n".join(r.message for r in caplog.records)
            assert "api.req 已发送" in text, text
            assert "api.resp 已收到" in text, text
        asyncio.run(_run())
    finally:
        t.stop()


def test_watchdog_probes_request_conn_not_current() -> None:
    """探测针对"承载请求的连接": 请求挂在死连接、self._conn 已被切成健康新连接
    → 仍应快速失败（探测请求连接），而不是探到健康新连接后继续等满总超时。"""
    t = _mk_transport()
    try:
        dead = _DummyConn(t, ping_pong=False, api_reply=None)
        healthy = _DummyConn(t, ping_pong=True, api_reply=None)
        t._conn = cast("RelayConnection", dead)  # noqa: SLF001 —— 注入

        async def _run() -> None:
            async def _swap() -> None:
                await asyncio.sleep(0.3)  # 请求进行中切换 self._conn（模拟升级/重建）
                t._conn = cast("RelayConnection", healthy)  # noqa: SLF001
            asyncio.get_running_loop().create_task(_swap())
            loop = asyncio.get_running_loop()
            t0 = time.monotonic()
            with pytest.raises(TransportError) as ei:
                await loop.run_in_executor(
                    None, lambda: t.request("POST", "/api/tts",
                                            {"t": "x"}, timeout=10.0))
            assert "看门狗" in str(ei.value), str(ei.value)  # 快速失败（探测 dead）
            assert time.monotonic() - t0 < 5.0
        asyncio.run(_run())
    finally:
        t.stop()


def test_watchdog_delivers_response_arriving_in_probe_window() -> None:
    """探测判定失败期间，响应恰好到达 → 优先交付（不丢弃已送达的合成结果）。"""
    t = _mk_transport()
    try:
        # ping 不回（探测将失败）; api 响应 1.3s 到达（watchdog 1.0s + probe 0.5s 窗口内）
        dummy = _DummyConn(t, ping_pong=False, api_reply=1.3)
        t._conn = cast("RelayConnection", dummy)  # noqa: SLF001 —— 注入

        async def _run() -> None:
            loop = asyncio.get_running_loop()
            t0 = time.monotonic()
            resp = await loop.run_in_executor(
                None, lambda: t.request("POST", "/api/tts",
                                        {"s": "y"}, timeout=10.0))
            assert isinstance(resp, remote_wire.ApiResp)
            assert resp.status == 200
            assert time.monotonic() - t0 < 10.0
        asyncio.run(_run())
    finally:
        t.stop()


def test_watchdog_broken_conn_fails_without_probe() -> None:
    """连接已标记 broken → 探测立即返回失败（不再发探针、不耗探测窗口）。"""
    t = _mk_transport()
    try:
        dummy = _DummyConn(t, ping_pong=True, api_reply=None)
        t._conn = cast("RelayConnection", dummy)  # noqa: SLF001 —— 注入

        async def _run() -> None:
            async def _mark_broken() -> None:
                await asyncio.sleep(0.3)  # 请求拿到 conn 后置 broken
                dummy.broken = True
            asyncio.get_running_loop().create_task(_mark_broken())
            loop = asyncio.get_running_loop()
            t0 = time.monotonic()
            with pytest.raises(TransportError) as ei:
                await loop.run_in_executor(
                    None, lambda: t.request("POST", "/api/tts",
                                            {"b": "x"}, timeout=10.0))
            assert "看门狗" in str(ei.value), str(ei.value)
            # 只有 api.req（1 条）——broken 后探测未发探针（ping 数为 0）
            pings = [m for m in dummy.sent if isinstance(m, remote_wire.PingMsg)]
            assert pings == [], pings
            # 快速失败：watchdog 1s（探测立即返回，无 0.5s 探测等待）
            assert time.monotonic() - t0 < 3.0
        asyncio.run(_run())
    finally:
        t.stop()


def test_watchdog_probe_send_error_fails() -> None:
    """探测探针发送本身抛错（连接断）→ 判定失败并中止请求。"""
    t = _mk_transport()
    try:
        dummy = _DummyConn(t, ping_pong=False, api_reply=None, ping_error=True)
        t._conn = cast("RelayConnection", dummy)  # noqa: SLF001 —— 注入

        async def _run() -> None:
            loop = asyncio.get_running_loop()
            t0 = time.monotonic()
            with pytest.raises(TransportError) as ei:
                await loop.run_in_executor(
                    None, lambda: t.request("POST", "/api/tts",
                                            {"p": "x"}, timeout=10.0))
            assert "看门狗" in str(ei.value), str(ei.value)
            assert time.monotonic() - t0 < 3.0
        asyncio.run(_run())
    finally:
        t.stop()


def test_watchdog_healthy_but_never_responds_hits_total_timeout() -> None:
    """连接健康（探针有 pong）但请求永不响应 → 总预算耗尽 → "请求超时"（带消息）。"""
    t = _mk_transport()
    try:
        dummy = _DummyConn(t, ping_pong=True, api_reply=None)
        t._conn = cast("RelayConnection", dummy)  # noqa: SLF001 —— 注入

        async def _run() -> None:
            loop = asyncio.get_running_loop()
            t0 = time.monotonic()
            with pytest.raises(TransportError) as ei:
                await loop.run_in_executor(
                    None, lambda: t.request("POST", "/api/tts",
                                            {"n": "x"}, timeout=3.0))
            msg = str(ei.value)
            assert "请求超时" in msg and "无响应" in msg, msg
            elapsed = time.monotonic() - t0
            assert 2.5 <= elapsed < 8.0, elapsed  # 应约 3s（不被看门狗提前中止）
            # 健康路径: 看门狗探测发生过（至少 1 个探针），但未中止
            pings = [m for m in dummy.sent if isinstance(m, remote_wire.PingMsg)]
            assert len(pings) >= 1
        asyncio.run(_run())
    finally:
        t.stop()


def test_ping_job_skips_watchdog_probe() -> None:
    """PingJob（probe() 内部路径）不走看门狗探测（is_api 守卫——防递归），
    只受自身超时约束；即使 ping 无响应也不会触发额外探针。"""
    t = _mk_transport(api_timeout_sec=2.0)
    try:
        dummy = _DummyConn(t, ping_pong=False, api_reply=None)
        t._conn = cast("RelayConnection", dummy)  # noqa: SLF001 —— 注入

        async def _run() -> None:
            loop = asyncio.get_running_loop()
            t0 = time.monotonic()
            ok = await loop.run_in_executor(None, lambda: t.probe())
            assert ok is False  # probe() 吞错返回 False（不向上抛）
            elapsed = time.monotonic() - t0
            assert 1.5 <= elapsed < 6.0, elapsed  # 约 2s（api_timeout），非看门狗节奏
            # 只有 probe() 自己那 1 个 ping——看门狗没有追加探针
            pings = [m for m in dummy.sent if isinstance(m, remote_wire.PingMsg)]
            assert len(pings) == 1, pings
        asyncio.run(_run())
    finally:
        t.stop()


def test_tts_timeout_converged() -> None:
    """TTS 远程调用超时收敛为 90s（灾难上限 600s→90s）。"""
    from services.remote_client import RemoteConsoleClient
    assert RemoteConsoleClient.TTS_TIMEOUT_SEC == 90.0
