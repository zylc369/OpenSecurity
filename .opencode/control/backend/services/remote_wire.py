"""remote-p2p 线协议消息对象（业务消息 dataclass + 编解码单点）。

收口边界:
  - 业务消息（api.req/api.resp/ping/pong/register/heartbeat/update_ep）→ 本模块
    dataclass，构造/消费一律经类型化对象（裸 dict 禁令）。
  - 分片信封（_frag/_frag_nack）→ crypto 层机制信封（Fragmenter/Reassembler
    内部协议，字段无业务语义演变），保持 crypto 模块内部 dict——不属于本层。
  - wire 字节流兼容: encode/decode 是唯二的 dict↔bytes 转换点，消息字段与
    protocol.md 一致（relayd 侧独立实现同一字节流，零影响）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from services.remote_crypto import decode_msg, encode_msg


@dataclass(frozen=True)
class WireMsg:
    """线协议消息基类（t 值 = 类名对应的 wire tag）。"""
    msg_id: int


@dataclass(frozen=True)
class ApiReq(WireMsg):
    """客户端 → 节点: 推理/管理 API 调用（protocol.md §4.3）。"""
    method: str
    path: str
    body: "dict[str, object] | None"
    token: str | None


@dataclass(frozen=True)
class ApiResp(WireMsg):
    """节点 → 客户端: API 响应。"""
    status: int
    mime: str
    body: object  # JSON 值（响应体任意形状——消费方窄化）


@dataclass(frozen=True)
class PingMsg(WireMsg):
    """心跳探测。"""


@dataclass(frozen=True)
class PongMsg(WireMsg):
    """心跳应答（ts 回显——gateway 服务端填充）。"""
    ts: "float | None" = None


@dataclass(frozen=True)
class SignalRegister(WireMsg):
    """gateway → relayd: 节点注册。"""
    node: str
    ver: int


@dataclass(frozen=True)
class SignalHeartbeat(WireMsg):
    """gateway → relayd: 保活。"""


@dataclass(frozen=True)
class SignalUpdateEp(WireMsg):
    """gateway → relayd: 端点刷新（NAT 前缀变化）。"""
    ep: "tuple[str, int]"


@dataclass(frozen=True)
class Registered(WireMsg):
    """relayd → gateway: 注册确认。"""


@dataclass(frozen=True)
class HeartbeatAck(WireMsg):
    """relayd → gateway: 保活确认。"""


@dataclass(frozen=True)
class PunchHint(WireMsg):
    """relayd → gateway: 打洞提示（client 公网端点）。"""
    sid: str
    client: "tuple[str, int]"


@dataclass(frozen=True)
class RelayPeer(WireMsg):
    """relayd → gateway: 客户端接入（触发中继连接建立）。"""
    sid: str


@dataclass(frozen=True)
class LookupMsg(WireMsg):
    """client → relayd: 节点查询（udp_ep=None 省略——relayd 回退 TCP 对端地址）。"""
    node: str
    udp_ep: "tuple[str, int] | None" = None


@dataclass(frozen=True)
class LookupResp(WireMsg):
    """relayd → client: 查询结果（gw 端点 + 会话 id）。"""
    ok: bool
    error: str
    gw: "tuple[str, int]"
    sid: str


@dataclass(frozen=True)
class RelayJoin(WireMsg):
    """gateway → relayd: 加入中继会话。"""
    sid: str


@dataclass(frozen=True)
class RelayOpen(WireMsg):
    """client → relayd: 请求中继（指定节点+会话）。"""
    node: str
    sid: str


@dataclass(frozen=True)
class RelayAttach(WireMsg):
    """client/gateway → relayd: 数据面接入会话。"""
    sid: str


@dataclass(frozen=True)
class RelayReady(WireMsg):
    """relayd → client: 中继双方就绪（数据面可 attach）。"""


@dataclass(frozen=True)
class WireError(WireMsg):
    """relayd → 对端: 协议错误（code 定位类别）。"""
    code: str
    error: str


@dataclass(frozen=True)
class RelayStart(WireMsg):
    """relayd → gateway: 中继管道就绪。"""


@dataclass(frozen=True)
class UnknownMsg(WireMsg):
    """未知 t（前向兼容——保留原始载荷，消费方忽略）。"""
    raw: "dict[str, object]"


def _as_int(raw: object, key: str) -> int:
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    raise ValueError(f"消息 {key} 非整数: {raw!r}")


def encode(m: WireMsg) -> bytes:
    """消息对象 → wire 字节（唯一出站编码点; UnknownMsg 只入站不编码）。"""
    d: dict[str, object] = {"id": m.msg_id}
    if isinstance(m, ApiReq):
        d.update({"t": "api.req", "method": m.method, "path": m.path,
                  "body": m.body, "token": m.token})
    elif isinstance(m, PingMsg):
        d["t"] = "ping"
    elif isinstance(m, PongMsg):
        d["t"] = "pong"
        if m.ts is not None:
            d["ts"] = m.ts
    elif isinstance(m, ApiResp):
        d.update({"t": "api.resp", "status": m.status, "mime": m.mime,
                  "body": m.body})
    elif isinstance(m, SignalRegister):
        d.update({"t": "register", "node": m.node, "ver": m.ver})
    elif isinstance(m, SignalHeartbeat):
        d["t"] = "heartbeat"
    elif isinstance(m, SignalUpdateEp):
        d.update({"t": "update_ep", "ep": [m.ep[0], m.ep[1]]})
    elif isinstance(m, RelayJoin):
        d.update({"t": "relay_join", "sid": m.sid})
    elif isinstance(m, LookupMsg):
        d.update({"t": "lookup", "node": m.node})
        if m.udp_ep is not None:
            d["udp_ep"] = [m.udp_ep[0], m.udp_ep[1]]
    elif isinstance(m, RelayOpen):
        d.update({"t": "relay_open", "node": m.node, "sid": m.sid})
    elif isinstance(m, RelayAttach):
        d.update({"t": "relay_attach", "sid": m.sid})
    else:
        raise TypeError(f"不支持的出站消息类型: {type(m).__name__}")
    return encode_msg(d)


def decode(data: bytes) -> WireMsg:
    """wire 字节 → 消息对象（唯一入站解码点; 未知 t → UnknownMsg）。"""
    d = decode_msg(data)
    tag = str(d.get("t", ""))
    msg_id = _as_int(d.get("id", -1), "id")
    if tag == "api.resp":
        return ApiResp(msg_id=msg_id, status=_as_int(d.get("status", 0), "status"),
                       mime=cast(str, d.get("mime", "")), body=d.get("body"))
    if tag == "pong":
        ts = d.get("ts")
        return PongMsg(msg_id=msg_id,
                       ts=ts if isinstance(ts, (int, float)) and not isinstance(ts, bool) else None)
    if tag == "ping":
        return PingMsg(msg_id=msg_id)
    if tag == "api.req":
        body = d.get("body")
        return ApiReq(msg_id=msg_id, method=str(d.get("method", "")),
                      path=str(d.get("path", "")),
                      body=cast("dict[str, object] | None", body),
                      token=cast("str | None", d.get("token")))
    if tag == "relay_ready":
        return RelayReady(msg_id=msg_id)
    if tag == "error":
        code = d.get("code")
        err = d.get("msg") or d.get("error")  # relayd 字段为 msg; error 前向兼容
        return WireError(msg_id=msg_id, code=code if isinstance(code, str) else "",
                         error=err if isinstance(err, str) else "")
    if tag == "endpoints":  # lookup 应答（协议 tag——见 relayd 协议测试）
        ok_raw = d.get("ok")
        gw = d.get("gw")
        gw_items = cast("list[object]", gw) if isinstance(gw, list) else []
        gw_host = gw_items[0] if gw_items and isinstance(gw_items[0], str) else ""
        gw_port = gw_items[1] if len(gw_items) > 1 and isinstance(gw_items[1], int) else 0
        err = d.get("error")
        return LookupResp(
            msg_id=msg_id, ok=bool(ok_raw),
            error=err if isinstance(err, str) else "",
            gw=(gw_host, gw_port), sid=str(d.get("sid", "")))
    if tag == "registered":
        return Registered(msg_id=msg_id)
    if tag == "heartbeat_ack":
        return HeartbeatAck(msg_id=msg_id)
    if tag == "relay_start":
        return RelayStart(msg_id=msg_id)
    if tag == "relay_peer":
        sid = str(d.get("sid", ""))
        return RelayPeer(msg_id=msg_id, sid=sid)
    if tag == "punch_hint":
        client = d.get("client")
        items = cast("list[object]", client) if isinstance(client, list) else []
        host = items[0] if items and isinstance(items[0], str) else ""
        port = items[1] if len(items) > 1 and isinstance(items[1], int) else 0
        return PunchHint(msg_id=msg_id, sid=str(d.get("sid", "")),
                         client=(host, port))
    if tag == "_frag":
        # 分片信封（crypto 层机制——不经业务对象，由 Reassembler 直接消费）
        return UnknownMsg(msg_id=msg_id, raw=d)
    return UnknownMsg(msg_id=msg_id, raw=d)
