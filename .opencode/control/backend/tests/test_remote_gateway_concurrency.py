"""gateway 中继会话多路复用并发测试（修复前红 / 修复后绿）。

场景（本机三组件: RelayServer + RemoteGateway + SlowStubServer，不依赖真机）:
  1. relay 路径两笔并发: stub 并发峰值=2 且 wall<2.5s
     （修复前形态: 峰值=1、wall≈3s+ —— 中继循环串行）
  2. 慢请求进行中: transport.probe（协议 Ping）与 probe_health（生产心跳）均 <1s
  3. 异常隔离: 一笔 500 不杀会话（随后一笔成功）
  4. 断连清理: 客户端断开后新连接立即可用
"""
# pyright: reportMissingParameterType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportAny=false, reportMissingTypeArgument=false
from __future__ import annotations

import asyncio
import time

import pytest

from services.remote_client import RemoteConsoleClient, RemoteUnavailable
from services.remote_gateway import RemoteGateway
from services.remote_relayd.server import RelayServer
from tests.remote_testkit import SlowStubServer, make_psk

pytestmark = pytest.mark.slow  # 每用例含打洞超时 ~5s（强制落中继）

_EMBED_BODY = b"[[0.1, 0.2]]"
_HEALTH_BODY = b'{"service":"stub","version":"t","models":[]}'
_NODE = "macmini"


def _client(psk: bytes, port: int) -> RemoteConsoleClient:
    from services.remote_transport import TransportConfig
    return RemoteConsoleClient("http://p2p-unused", p2p=TransportConfig(
        relay_host="127.0.0.1", relay_port=port, psk=psk, node_id=_NODE))


async def _wait_registered(server: RelayServer) -> None:
    for _ in range(50):
        await asyncio.sleep(0.1)
        if server.registry.get(_NODE) is not None:
            return
    raise AssertionError("gateway 未注册")


async def _force_relay(server: RelayServer, client: RemoteConsoleClient) -> None:
    """强制落中继（模式同 test_remote_e2e 场景 2）。

    先经一笔请求建立传输与直连会话（transport 懒启动）→ ep 置不可达 + drop
    会话 → 热身笔完成中继建立（打洞超时在计时外）。
    """
    run_loop = asyncio.get_running_loop()
    await run_loop.run_in_executor(None, lambda: client.embed(["pre"]))
    entry = server.registry.get(_NODE)
    assert entry is not None
    entry.ep = ("203.0.113.1", 9)
    entry.lan_ep = ("203.0.113.1", 9)  # 两段式打洞的 LAN 候选同置不可达
    tr = client._transport  # noqa: SLF001 —— 测试桩
    assert tr is not None
    loop = tr._loop  # noqa: SLF001
    assert loop is not None
    lf = asyncio.run_coroutine_threadsafe(tr._drop_session(), loop)  # noqa: SLF001
    lf.result(timeout=5.0)
    await run_loop.run_in_executor(None, lambda: client.embed(["warm"]))
    assert tr.current_path == "relay", f"未落中继（path={tr.current_path}）"


class _Stack:
    """三组件测试栈（慢 stub + relayd + gateway + client）。"""

    def __init__(self, psk: bytes, port: int, server: RelayServer,
                 gw: RemoteGateway, stub: SlowStubServer,
                 client: RemoteConsoleClient) -> None:
        self.psk = psk
        self.port = port
        self.server = server
        self.gw = gw
        self.stub = stub
        self.client = client

    async def close(self) -> None:
        self.client.close()
        await self.gw.stop()
        await self.stub.close()
        await self.server.close()


async def _stack(embed_delay: float = 0.0, embed_status: int = 200) -> _Stack:
    psk = make_psk(seed=97)
    stub = SlowStubServer(responses={
        "embed": (embed_delay, embed_status, _EMBED_BODY),  # client.embed 实际路径 /embed
        "/api/remote/health": (0.0, 200, _HEALTH_BODY),
    })
    stub_port = await stub.start()
    server = RelayServer(psk)
    port = await server.serve("127.0.0.1", 0)
    gw = RemoteGateway(psk=psk, relay_host="127.0.0.1", relay_port=port,
                       node_id=_NODE, backend_port=stub_port)
    gw.start()
    await _wait_registered(server)
    client = _client(psk, port)
    return _Stack(psk, port, server, gw, stub, client)


def test_relay_two_concurrent_no_queue() -> None:
    """relay 路径两笔并发: 峰值=2 且 wall<2.5s（修复前: 峰值1、wall≈3s+）。"""

    async def run() -> None:
        s = await _stack(embed_delay=1.5)
        loop = asyncio.get_running_loop()
        try:
            await _force_relay(s.server, s.client)
            t0 = time.monotonic()
            r1, r2 = await asyncio.gather(
                loop.run_in_executor(None, lambda: s.client.embed(["a"])),
                loop.run_in_executor(None, lambda: s.client.embed(["b"])))
            wall = time.monotonic() - t0
            assert r1 == [[0.1, 0.2]] and r2 == [[0.1, 0.2]]
            assert s.stub.max_inflight == 2, (
                f"stub 并发峰值={s.stub.max_inflight}（期望 2——串行时=1）")
            assert wall < 2.5, f"wall={wall:.2f}s（期望 <2.5——串行形态 ≈3.0s+）"
        finally:
            await s.close()

    asyncio.run(run())


def test_ping_not_blocked_by_slow_request() -> None:
    """慢请求进行中: 协议 Ping 与生产心跳均 <1s（修复前等待慢请求完成）。"""

    async def run() -> None:
        s = await _stack(embed_delay=1.5)
        loop = asyncio.get_running_loop()
        try:
            await _force_relay(s.server, s.client)
            slow = loop.run_in_executor(None, lambda: s.client.embed(["slow"]))
            await asyncio.sleep(0.3)  # 确认慢请求已在 stub 处理中
            assert s.stub.inflight == 1, "慢请求未在进行中（测试时序问题）"
            tr = s.client._transport  # noqa: SLF001
            assert tr is not None
            t0 = time.monotonic()
            ok = await loop.run_in_executor(None, tr.probe)
            ping_ms = (time.monotonic() - t0) * 1000
            assert ok, "transport.probe 失败"
            assert ping_ms < 1000, f"协议 Ping 被阻塞 {ping_ms:.0f}ms（期望 <1000）"
            t0 = time.monotonic()
            info = await loop.run_in_executor(None, s.client.probe_health)
            health_ms = (time.monotonic() - t0) * 1000
            assert info.service == "stub"
            assert health_ms < 1000, f"probe_health 被阻塞 {health_ms:.0f}ms（期望 <1000）"
            await slow
        finally:
            await s.close()

    asyncio.run(run())


def test_error_isolation() -> None:
    """异常隔离: 一笔 500 不杀会话（随后一笔成功）。"""

    async def run() -> None:
        s = await _stack(embed_delay=0.0)
        loop = asyncio.get_running_loop()
        try:
            await _force_relay(s.server, s.client)
            s.stub.responses["/api/boom"] = (0.0, 500, b'{"error":"boom"}')
            try:
                await loop.run_in_executor(
                    None, lambda: s.client._post_json("/api/boom", {}))  # noqa: SLF001
                raise AssertionError("应抛 RemoteUnavailable")
            except RemoteUnavailable:
                pass
            r = await loop.run_in_executor(None, lambda: s.client.embed(["after"]))
            assert r == [[0.1, 0.2]]
        finally:
            await s.close()

    asyncio.run(run())


def test_client_reconnect_after_close() -> None:
    """断连清理: 客户端断开后新连接立即可用。"""

    async def run() -> None:
        s = await _stack(embed_delay=0.0)
        loop = asyncio.get_running_loop()
        try:
            await _force_relay(s.server, s.client)
            s.client.close()
            await asyncio.sleep(0.3)  # 等 gateway 侧会话收尾
            c2 = _client(s.psk, s.port)
            try:
                r = await loop.run_in_executor(None, lambda: c2.embed(["again"]))
                assert r == [[0.1, 0.2]]
            finally:
                c2.close()
        finally:
            await s.close()

    asyncio.run(run())
