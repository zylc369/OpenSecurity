"""P2P 直连修复批 单测：remote_netutil / 地址上报 / LAN 候选 / 后台升级 / 状态贯通。"""
from __future__ import annotations

from typing import cast

import pytest

from services import remote_netutil
from services import remote_transport


def test_probe_lan_ip_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认出站接口探测成功返回真实 IPv4。"""

    class _FakeSocket:
        def __init__(self, *a: object, **k: object) -> None:
            pass

        def connect(self, addr: "tuple[str, int]") -> None:
            assert addr == ("8.8.8.8", 53)

        def getsockname(self) -> "tuple[str, int]":
            return ("192.168.3.194", 40000)

        def close(self) -> None:
            pass

    monkeypatch.setattr(remote_netutil.socket, "socket", _FakeSocket)
    assert remote_netutil.probe_lan_ip() == "192.168.3.194"


def test_probe_lan_ip_no_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """无默认路由（OSError）→ None，不抛。"""

    class _FailSocket:
        def __init__(self, *a: object, **k: object) -> None:
            pass

        def connect(self, addr: "tuple[str, int]") -> None:
            raise OSError("network down")

        def close(self) -> None:
            pass

    monkeypatch.setattr(remote_netutil.socket, "socket", _FailSocket)
    assert remote_netutil.probe_lan_ip() is None


def test_probe_lan_ip_wildcard_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """sockname 仍为通配/回环 → None（绝不返回 0.0.0.0）。"""

    class _WildSocket:
        def __init__(self, *a: object, **k: object) -> None:
            pass

        def connect(self, addr: "tuple[str, int]") -> None:
            pass

        def getsockname(self) -> "tuple[str, int]":
            return ("0.0.0.0", 40000)

        def close(self) -> None:
            pass

    monkeypatch.setattr(remote_netutil.socket, "socket", _WildSocket)
    assert remote_netutil.probe_lan_ip() is None


def test_resolve_udp_ep_replaces_wildcard(monkeypatch: pytest.MonkeyPatch) -> None:
    """sockname=0.0.0.0 → 探测值替换（端口保持）。"""
    monkeypatch.setattr(remote_transport.remote_netutil, "probe_lan_ip",
                        lambda: "192.168.3.194")
    assert remote_transport.resolve_udp_ep(("0.0.0.0", 5000)) == ("192.168.3.194", 5000)


def test_resolve_udp_ep_keeps_valid_address() -> None:
    """真实地址原样返回（不触发探测）。"""
    assert remote_transport.resolve_udp_ep(("10.0.0.5", 5000)) == ("10.0.0.5", 5000)


def test_resolve_udp_ep_probe_failure_keeps_wildcard(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """探测失败 → 保持原值（relayd TCP 兜底路径，不劣化）。"""
    monkeypatch.setattr(remote_transport.remote_netutil, "probe_lan_ip",
                        lambda: None)
    assert remote_transport.resolve_udp_ep(("0.0.0.0", 5000)) == ("0.0.0.0", 5000)


def test_registry_lan_ep_roundtrip() -> None:
    """registry: lan_ep 注册/刷新语义（None 不覆盖旧值）。"""
    from services.remote_relayd.registry import Registry

    class _W:  # 桩 writer（registry 仅存引用）
        pass

    class _S:  # 桩 session
        pass

    reg = Registry()
    reg.register("n1", _W(), _S(),  # type: ignore[arg-type]
                 lan_ep=("192.168.3.3", 41000))
    e = reg.get("n1")
    assert e is not None and e.lan_ep == ("192.168.3.3", 41000)
    # 不带 lan 的刷新不覆盖
    assert reg.update_ep("n1", ("1.2.3.4", 5))
    e = reg.get("n1")
    assert e is not None and e.lan_ep == ("192.168.3.3", 41000)
    # 带 lan 的刷新覆盖
    assert reg.update_ep("n1", ("1.2.3.4", 5), lan_ep=("192.168.3.9", 6))
    e = reg.get("n1")
    assert e is not None and e.lan_ep == ("192.168.3.9", 6)


def test_wire_register_encode_lan_ep() -> None:
    """wire: register/update_ep 编码随 lan_ep 携带（None 时省略字段）。"""
    from services.remote_crypto import decode_msg
    from services import remote_wire as w

    raw = decode_msg(w.encode(w.SignalRegister(msg_id=0, node="n1", ver=1,
                                               lan_ep=("192.168.3.3", 41000))))
    assert raw.get("lan_ep") == ["192.168.3.3", 41000]
    raw2 = decode_msg(w.encode(w.SignalRegister(msg_id=0, node="n1", ver=1)))
    assert "lan_ep" not in raw2
    raw3 = decode_msg(w.encode(w.SignalUpdateEp(msg_id=0, ep=("1.2.3.4", 5),
                                                lan_ep=("192.168.3.3", 41000))))
    assert raw3.get("lan_ep") == ["192.168.3.3", 41000]


def test_wire_lookup_resp_gw_lan() -> None:
    """wire: endpoints 应答含/缺 gw_lan 两种解码（含旧 relayd 兼容）。"""
    from services.remote_crypto import encode_msg
    from services import remote_wire as w

    raw = encode_msg({"t": "endpoints", "id": 1, "ok": True,
                      "gw": ["1.2.3.4", 5], "sid": "s",
                      "gw_lan": ["192.168.3.3", 41000]})
    resp = w.decode(raw)
    assert isinstance(resp, w.LookupResp)
    assert resp.gw_lan == ("192.168.3.3", 41000)
    raw2 = encode_msg({"t": "endpoints", "id": 1, "ok": True,
                       "gw": ["1.2.3.4", 5], "sid": "s"})
    resp2 = w.decode(raw2)
    assert isinstance(resp2, w.LookupResp)
    assert resp2.gw_lan == ("", 0)


def test_relayd_lookup_returns_gw_lan() -> None:
    """relayd: 注册带 lan_ep 后 lookup 应答含 gw_lan（_lookup 全路径）。"""
    import asyncio

    from services.remote_relayd.server import RelayServer
    from tests.remote_testkit import make_psk

    class _W:  # 桩 writer: _lookup 会 write+drain+get_extra_info（hint 下发）
        def write(self, b: bytes) -> None:
            pass

        async def drain(self) -> None:
            pass

        def get_extra_info(self, name: str) -> object:
            return ("192.168.3.194", 12345)

    class _S:  # 桩 session: encrypt_seq 原样返回
        def encrypt_seq(self, data: bytes) -> bytes:
            return data

    async def run() -> None:
        server = RelayServer(make_psk())
        w = _W()
        server.registry.register("n1", w, _S(),  # type: ignore[arg-type]
                                 lan_ep=("192.168.3.3", 41000))
        entry = server.registry.get("n1")
        assert entry is not None
        entry.ep = ("1.2.3.4", 5)  # 模拟 STUN 刷新后的公网映射
        resp = await server._lookup("n1", w, _S(), None)  # type: ignore[arg-type]
        assert resp["ok"] is True
        assert resp["gw_lan"] == ["192.168.3.3", 41000]
        assert resp["gw"] == ["1.2.3.4", 5]

    asyncio.run(run())


def test_gateway_lan_ep(monkeypatch: pytest.MonkeyPatch) -> None:
    """gateway: _lan_ep = 探测 IP + 固定 socket 端口（无 udp/无探测 → None）。"""
    from services import remote_gateway

    monkeypatch.setattr(remote_gateway.remote_netutil, "probe_lan_ip",
                        lambda: "192.168.3.3")

    class _FakeTransport:
        def get_extra_info(self, name: str) -> object:
            return ("0.0.0.0", 45000)

    class _FakeUdp:
        transport = _FakeTransport()

    gw = remote_gateway.RemoteGateway(b"\x01" * 32, "relay.example", 41000, "node1")
    assert gw._lan_ep() is None  # 未建 UDP socket
    gw._udp = _FakeUdp()  # type: ignore[assignment]  # 测试注入
    assert gw._lan_ep() == ("192.168.3.3", 45000)
    monkeypatch.setattr(remote_gateway.remote_netutil, "probe_lan_ip",
                        lambda: None)
    assert gw._lan_ep() is None  # 探测失败 → 不劣化（回退公网候选）


def test_build_punch_candidates() -> None:
    """打洞候选: 顺序保持（LAN 优先）、无效过滤、重复去重。"""
    f = remote_transport.build_punch_candidates
    # 无 LAN（空端点被过滤）→ 只剩公网
    assert f(("", 0), ("1.2.3.4", 5)) == [("1.2.3.4", 5)]
    # LAN 优先且全保留
    assert f(("192.168.3.3", 9), ("1.2.3.4", 5)) == [("192.168.3.3", 9), ("1.2.3.4", 5)]
    # 重复去重
    assert f(("1.2.3.4", 5), ("1.2.3.4", 5)) == [("1.2.3.4", 5)]
    # 全无效 → 空（调用方判"endpoints 响应畸形"）
    assert f(("", 0), ("", 0)) == []


def test_upgrade_loop_relay_to_direct() -> None:
    """中继态后台升级: 失败记录原因 → 候选恢复后自动升级直连（间隔参数化）。"""
    import asyncio

    from services.remote_gateway import RemoteGateway
    from services.remote_transport import RemoteTransport, TransportConfig
    from services.remote_relayd.server import RelayServer
    from tests.remote_testkit import make_psk
    from tests.test_remote_relayd import _start_http_stub

    async def run() -> None:
        psk = make_psk(seed=72)
        stub = _start_http_stub()
        stub_port = int(await stub.start())  # type: ignore[attr-defined]
        server = RelayServer(psk)
        port = await server.serve("127.0.0.1", 0)
        gw = RemoteGateway(psk=psk, relay_host="127.0.0.1", relay_port=port,
                           node_id="macmini", backend_port=stub_port)
        cfg = TransportConfig(relay_host="127.0.0.1", relay_port=port,
                              psk=psk, node_id="macmini",
                              punch_timeout_sec=0.5,
                              direct_upgrade_interval_sec=0.3)
        transport = RemoteTransport(cfg)
        loop = asyncio.get_running_loop()
        try:
            gw.start()
            for _ in range(50):
                await asyncio.sleep(0.1)
                if server.registry.get("macmini") is not None:
                    break
            entry = server.registry.get("macmini")
            assert entry is not None
            orig_ep, orig_lan = entry.ep, entry.lan_ep

            transport.start()
            # ① 强制中继（双候选不可达）→ 会话建立即中继
            entry.ep = ("203.0.113.1", 9)
            entry.lan_ep = ("203.0.113.9", 9)
            r = await loop.run_in_executor(
                None, lambda: transport.request("GET", "/api/remote/health"))
            assert r.status == 200
            assert transport.current_path == "relay"

            # ② 后台升级失败 → 记录原因，保持中继
            await asyncio.sleep(1.2)
            assert transport.current_path == "relay"
            assert transport.direct_last_error != ""

            # ③ 候选恢复 → 自动升级直连
            entry.lan_ep = orig_lan
            entry.ep = orig_ep
            ok = False
            for _ in range(30):
                await asyncio.sleep(0.1)
                if transport.current_path == "direct":
                    ok = True
                    break
            assert ok, (f"未自动升级（path={transport.current_path}, "
                        f"err={transport.direct_last_error}）")
            assert transport.direct_last_error == ""

            # ④ 升级后服务仍可用（新会话路由正确）
            r2 = await loop.run_in_executor(
                None, lambda: transport.request("GET", "/api/remote/health"))
            assert r2.status == 200
        finally:
            transport.stop()
            await gw.stop()
            await server.close()
            await stub.close()  # type: ignore[attr-defined]

    asyncio.run(run())


def test_status_response_contains_path_fields() -> None:
    """可见性贯通: /api/remote/status 响应含 path / direct_last_error。"""
    from fastapi.testclient import TestClient

    from server import create_app

    app = create_app()
    with TestClient(app) as c:
        r = c.get("/api/remote/status")
        assert r.status_code == 200
        d = cast("dict[str, object]", r.json())
        assert "path" in d, f"缺少 path 字段: {sorted(d)}"
        assert "direct_last_error" in d, f"缺少 direct_last_error 字段: {sorted(d)}"
