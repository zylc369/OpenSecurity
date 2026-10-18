"""gateway 换网自愈测试（信令活性检测 + UDP 重绑）。

场景（对应 2026-10-18-node-network-heal 需求 §3.1 步骤 2）:
  1. 信令静默（换网后死连接: send 不报错、recv 永远超时）→ 判死抛错进入重建
  2. 正常收包（含 heartbeat_ack）→ 阈值内不误杀
  3. _close_udp 幂等; 重绑后为新 socket 对象（重建路径绑定新网络）
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import remote_gateway  # noqa: E402
from services.remote_gateway import RemoteGateway  # noqa: E402
from tests.remote_testkit import make_psk  # noqa: E402


class _SilentClient:
    """recv 永远超时（模拟换网死连接）；send 只计数（不抛——与真实"黑洞"一致）。"""

    def __init__(self) -> None:
        self.sent = 0

    async def send(self, msg: object) -> None:
        self.sent += 1

    async def recv(self, timeout: float = 1.0) -> object:
        raise asyncio.TimeoutError()


class _EchoClient:
    """recv 返回一条合法 wire 消息（模拟正常心跳 ack 流）；send 计数。

    注意: 每次 recv 含真实 yield（sleep）——否则紧循环不让出事件循环，
    asyncio.wait_for 的超时定时器永不触发（测试自身挂起）。
    """

    def __init__(self) -> None:
        self.sent = 0

    async def send(self, msg: object) -> None:
        self.sent += 1

    async def recv(self, timeout: float = 1.0) -> object:
        await asyncio.sleep(0.01)
        from services import remote_wire
        return remote_wire.SignalHeartbeat(msg_id=0)


def _gw() -> RemoteGateway:
    return RemoteGateway(psk=make_psk(seed=77), relay_host="127.0.0.1",
                         relay_port=1, node_id="heal-test", backend_port=0)


def test_signal_dead_triggers_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    """静默 > 阈值 → 判死抛 ConnectionError（进入 _register_loop 重建路径）。"""

    async def run() -> None:
        monkeypatch.setattr(remote_gateway, "SIGNAL_DEAD_SEC", 0.3)
        gw = _gw()
        gw._running = True

        async def _no_stun() -> None:  # 隔离 STUN（本测试只聚焦活性检测）
            return None
        monkeypatch.setattr(gw, "_stun_probe", _no_stun)

        client = _SilentClient()
        with pytest.raises(ConnectionError, match="静默超时"):
            await gw._signal_steady(client)  # type: ignore[arg-type]
        assert client.sent >= 1  # 期间仍在尝试发心跳（死连接不可见性=本缺口本体）

    asyncio.run(run())


def test_signal_alive_no_false_kill(monkeypatch: pytest.MonkeyPatch) -> None:
    """正常收包流（含 heartbeat_ack 语义）→ 阈值内不判死（不误杀）。"""

    async def run() -> None:
        monkeypatch.setattr(remote_gateway, "SIGNAL_DEAD_SEC", 0.5)
        gw = _gw()
        gw._running = True

        async def _no_stun() -> None:
            return None
        monkeypatch.setattr(gw, "_stun_probe", _no_stun)

        client = _EchoClient()
        # 运行 0.9s（> 判死阈值 0.5s）——持续收包应刷新活性、不抛错
        try:
            await asyncio.wait_for(gw._signal_steady(client), timeout=0.9)  # type: ignore[arg-type]
            raise AssertionError("_signal_steady 意外返回")
        except asyncio.TimeoutError:
            pass  # 预期: 被 wait_for 取消（而非判死抛错）

    asyncio.run(run())


def test_close_udp_idempotent_and_rebinds() -> None:
    """_close_udp 幂等；重绑后 _udp 为新对象（换网重建=绑新网络）。"""

    async def run() -> None:
        gw = _gw()
        await gw._ensure_udp()
        udp1 = gw._udp
        assert udp1 is not None
        gw._close_udp()
        assert gw._udp is None
        gw._close_udp()  # 幂等（再次调用无异常、仍为 None）
        assert gw._udp is None
        await gw._ensure_udp()
        assert gw._udp is not None
        assert gw._udp is not udp1  # 新 socket 对象（换网后绑定新网络）
        gw._close_udp()

    asyncio.run(run())
