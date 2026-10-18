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
                 ping_pong: bool = True, api_reply: float | None = None) -> None:
        self._t = transport
        self.ping_pong = ping_pong
        self.api_reply = api_reply
        self.sent: "list[object]" = []
        self.broken = False
        self._tasks: "list[asyncio.Task[None]]" = []

    async def send_msg(self, msg: "object") -> None:
        self.sent.append(msg)
        loop = asyncio.get_running_loop()
        if isinstance(msg, remote_wire.PingMsg):
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
    cfg = TransportConfig(
        relay_host="127.0.0.1", relay_port=1, psk=b"\x00" * 32,
        node_id="dummy", watchdog_sec=1.0, probe_wait_sec=0.5, **overrides)
    t = RemoteTransport(cfg)
    t.start()
    return t


@pytest.mark.slow
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


@pytest.mark.slow
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


@pytest.mark.slow
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


def test_tts_timeout_converged() -> None:
    """TTS 远程调用超时收敛为 90s（灾难上限 600s→90s）。"""
    from services.remote_client import RemoteConsoleClient
    assert RemoteConsoleClient.TTS_TIMEOUT_SEC == 90.0
