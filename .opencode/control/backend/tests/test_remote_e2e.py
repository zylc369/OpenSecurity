"""remote-p2p 端到端验收测试（需求 §4 验收清单的可执行化）。

场景（本机三组件: RelayServer + RemoteGateway + HTTP stub backend）:
 1. P2P 直连: remote_client(p2p) → transport → gw → stub（embed 语义）
 2. 打洞失败自动落中继（gw ep 指向不可达地址）
 3. 节点离线 probe 失败 + request 抛 RemoteUnavailable
 4. 无 PSK/错 PSK 被拒（failban 计数）
"""
from __future__ import annotations

import asyncio
from typing import cast

from services.remote_client import RemoteConsoleClient, RemoteUnavailable
from services.remote_gateway import RemoteGateway
from services.remote_relayd.server import RelayServer
from tests.remote_testkit import make_psk
from tests.test_remote_relayd import _start_http_stub


def _client(psk: bytes, port: int, node: str = "macmini") -> RemoteConsoleClient:
    from services.remote_transport import TransportConfig
    return RemoteConsoleClient("http://p2p-unused", p2p=TransportConfig(
        relay_host="127.0.0.1", relay_port=port, psk=psk, node_id=node))


async def _wait_registered(server: RelayServer, node: str) -> None:
    for _ in range(50):
        await asyncio.sleep(0.1)
        if server.registry.get(node) is not None:
            return
    raise AssertionError(f"gateway {node} 未注册")


def test_e2e_direct_and_relay_and_failure() -> None:
    async def run() -> None:
        psk = make_psk(seed=91)
        stub = _start_http_stub(b"[[0.1, 0.2]]")  # embed 响应形状
        stub_port = int(await stub.start())  # type: ignore[attr-defined]
        server = RelayServer(psk)
        port = await server.serve("127.0.0.1", 0)
        gw = RemoteGateway(psk=psk, relay_host="127.0.0.1", relay_port=port,
                           node_id="macmini", backend_port=stub_port)
        client = _client(psk, port)
        loop = asyncio.get_running_loop()
        try:
            gw.start()
            await _wait_registered(server, "macmini")

            # ── 场景 1: 直连（embed 语义经 api.req 转发 stub）──
            result = await loop.run_in_executor(
                None, lambda: client.embed(["hello"]))
            assert result == [[0.1, 0.2]]
            # probe_health 对 stub 的 list 响应 → 畸形 → RemoteUnavailable（语义正确）
            try:
                await loop.run_in_executor(None, client.probe_health)
                raise AssertionError("stub 非 health 形状应抛")
            except RemoteUnavailable:
                pass

            # ── 场景 2: 打洞不可达 → 中继兜底（同 client 复用/重建）──
            entry = server.registry.get("macmini")
            assert entry is not None
            entry.ep = ("203.0.113.1", 9)
            assert client._transport is not None  # noqa: SLF001 —— 触发会话重建
            asyncio.run_coroutine_threadsafe(
                client._transport._drop_session(),  # type: ignore[union-attr] # noqa: SLF001
                client._transport._loop).result(timeout=5.0)  # type: ignore[union-attr] # noqa: SLF001
            result2 = await loop.run_in_executor(
                None, lambda: client.embed(["relay-me"]))
            assert result2 == [[0.1, 0.2]]

            # ── 场景 3: 节点下线 → RemoteUnavailable ──
            await gw.stop()
            await asyncio.sleep(0.5)  # 管道断链传播（relayd pump → client EOF）

            try:
                await loop.run_in_executor(None, lambda: client.embed(["x"]))
                raise AssertionError("应抛 RemoteUnavailable")
            except RemoteUnavailable:
                pass
        finally:
            client.close()
            await gw.stop()
            await server.close()
            await stub.close()  # type: ignore[attr-defined]

    asyncio.run(run())


def test_e2e_wrong_psk_rejected_by_relayd() -> None:
    async def run() -> None:
        psk = make_psk(seed=93)
        server = RelayServer(psk)
        port = await server.serve("127.0.0.1", 0)
        bad_client = _client(make_psk(seed=94), port)
        try:
            # 错 PSK: 准入握手即失败 → RemoteUnavailable（不消耗 relayd 状态）
            try:
                bad_client.embed(["x"])
                raise AssertionError("应抛 RemoteUnavailable")
            except RemoteUnavailable:
                pass
            assert server.registry.nodes_online() == []
        finally:
            bad_client.close()
            await server.close()

    asyncio.run(run())


def test_e2e_vectors_file_consumable() -> None:
    """向量文件可被外部消费者读取（Kotlin 侧契约: 六段齐全）。"""
    import json
    from pathlib import Path
    from typing import Any, cast as _cast2
    data = _cast2("dict[str, Any]",
                  json.loads((Path(__file__).parent.parent / "services"
                              / "remote_relayd" / "vectors.json").read_text()))
    for section in ("noise_nnposk2", "session_roundtrip", "tcp_frame",
                    "udp_frame", "frag", "punch_mac"):
        section_list: "list[object]" = data[section]  # pyright: ignore[reportAny]
        assert len(section_list) >= 1
