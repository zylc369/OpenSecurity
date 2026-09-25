"""本地代理服务（relay）：固定入口 + 出口选择 + CONNECT 隧道转发。

监听 127.0.0.1:9676 起顺延（冲突 +1，真实端口经 relay_port() 对外）。
设计依据 requirements/evolve/2026-09-25-proxy-ip-manager.md §4.2/§5.3：
  · 零 HTTP 语义理解：HTTPS 只见密文，双向字节管道；
  · 出口选择（每连接）：域名在冷却表 → 代理出口（池惰性提取）；
    否则按全局 mode（direct=本机直连）；
  · 域名归一化与控制接口共用 pool.normalize_domain（收口）；
  · supervisor 自愈：start_relay() 由 server.py 以受监控 task 拉起，
    崩溃自动重拉（2 秒级），不影响控制台主进程。
"""
from __future__ import annotations

import asyncio
import time

from config import PROXY_RELAY_PORT_CANDIDATES, PROXY_RELAY_PORT_START, PROXY_ROTATE_CONN_THRESHOLD
from services.proxy_pool import JuliangError, get_pool, normalize_domain

_server: asyncio.AbstractServer | None = None
_port: int | None = None

# 活动隧道注册表（优雅关闭用）与 proxy 出口连接计数（阈值轮换用）
_tunnels: set["Tunnel"] = set()
_proxy_conn_count = 0
_drain_grace_sec = 5.0


class Tunnel:
    """一条已建立的转发隧道（客户端连接 + 上游连接 + 双向泵 task）。"""

    def __init__(self, client_w: asyncio.StreamWriter, up_w: asyncio.StreamWriter):
        self.client_w = client_w
        self.up_w = up_w
        self.tasks: list[asyncio.Task] = []

    async def graceful_close_upstream(self, grace: float = _drain_grace_sec) -> None:
        """对上游发 FIN（不再发新请求）+ 继续读尽剩余响应字节送达客户端；
        grace 秒后兜底强关（需求 §5.4：在飞响应完整送达，POST 无重复提交风险）。"""
        try:
            self.up_w.write_eof()          # FIN：告诉目标站"我没有新请求了"
        except (OSError, RuntimeError):
            return                          # 已关/半关，无需处理
        deadline = time.monotonic() + grace
        # 等待 up→client 泵自然结束（剩余字节送达 + 客户端方向收尾）
        for t in self.tasks:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                await asyncio.wait({t}, timeout=remaining)
            except Exception:
                pass
        for w in (self.up_w, self.client_w):  # 兜底强关（超长响应场景）
            try:
                w.close()
            except Exception:
                pass


async def graceful_close_upstreams() -> None:
    """换出口时调用：全部存量隧道优雅收尾（在飞响应送达后关闭，§5.4）。"""
    tunnels = list(_tunnels)
    if not tunnels:
        return
    await asyncio.gather(*(t.graceful_close_upstream() for t in tunnels),
                         return_exceptions=True)


def current_server() -> "asyncio.AbstractServer | None":
    """supervisor 探活用：当前 server 对象（可能为 None）。"""
    return _server


async def stop_relay() -> None:
    """关闭当前 server 并清空注册态（supervisor 重拉前调用）。"""
    global _server, _port
    if _server is not None:
        try:
            _server.close()
            await _server.wait_closed()
        except Exception:
            pass
    _server = None
    _port = None


def relay_port() -> int:
    """真实监听端口（未启动时 RuntimeError，调用方回退配置起点值）。"""
    if _port is None:
        raise RuntimeError("relay 未启动")
    return _port


async def start_relay() -> None:
    """绑定端口（顺延候选段）并开始服务。幂等（已运行直接返回）。"""
    global _server, _port
    if _server is not None:
        return
    for port in range(PROXY_RELAY_PORT_START,
                      PROXY_RELAY_PORT_START + PROXY_RELAY_PORT_CANDIDATES):
        try:
            _server = await asyncio.start_server(_handle_client, "127.0.0.1", port)
            _port = port
            return
        except OSError:
            continue
    raise RuntimeError(f"relay 端口候选段耗尽（{PROXY_RELAY_PORT_START} 起）")


def _split_host_port(host_port: str) -> tuple[str, int]:
    host, _, port = host_port.rpartition(":")
    if not host or not port.isdigit():
        raise ValueError(f"非法目标地址: {host_port!r}")
    return host, int(port)


async def _connect_upstream(host: str, port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """按出口选择建上游连接：冷却域/全局 proxy → 代理出口；否则本机直连。
    proxy 出口新建连接满阈值自动轮换并优雅关闭存量（记 history，铁律一）。"""
    global _proxy_conn_count
    pool = get_pool()
    domain = normalize_domain(host)  # 与控制接口同一归一化（收口）
    use_proxy = pool.domain_cooled(domain) or pool.status()["mode"] == "proxy"
    if use_proxy:
        info = await pool.get()  # 缓存复用；过期/黑名单自动提取（惰性）
        _proxy_conn_count += 1
        if _proxy_conn_count >= PROXY_ROTATE_CONN_THRESHOLD:
            _proxy_conn_count = 0
            await pool.rotate("auto_rotate_35conn")   # 阈值轮换（记 rotate_history）
            info = await pool.get()                   # 拿轮换后的新 IP（否则本次连接仍走旧出口）
            await graceful_close_upstreams()           # 存量隧道优雅收尾→新连接走新出口
        proxy_host, _, proxy_port = info.ip.rpartition(":")
        return await asyncio.open_connection(proxy_host, int(proxy_port))
    return await asyncio.open_connection(host, port)


async def _pipe(tunnel: Tunnel, client_r: asyncio.StreamReader,
                up_r: asyncio.StreamReader) -> None:
    """双向字节泵（零理解转发）。任一方向结束即整体收尾；隧道注销。"""

    async def pump(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        try:
            while True:
                data = await r.read(65536)
                if not data:
                    break
                w.write(data)
                await w.drain()
        except (ConnectionError, asyncio.IncompleteReadError, OSError):
            pass
        finally:
            try:
                w.close()
            except Exception:
                pass

    _tunnels.add(tunnel)
    t1 = asyncio.create_task(pump(client_r, tunnel.up_w))
    t2 = asyncio.create_task(pump(up_r, tunnel.client_w))
    tunnel.tasks = [t1, t2]
    try:
        await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        t1.cancel()
        t2.cancel()
        for w in (tunnel.client_w, tunnel.up_w):
            try:
                w.close()
            except Exception:
                pass
        _tunnels.discard(tunnel)


async def _handle_client(client_r: asyncio.StreamReader,
                         client_w: asyncio.StreamWriter) -> None:
    """客户端协议入口：CONNECT 隧道（HTTPS）与明文绝对 URI 转发。"""
    try:
        first = await asyncio.wait_for(client_r.readline(), timeout=30)
        parts = first.split()
        if len(parts) < 2:
            return
        method, target = parts[0].decode("latin-1"), parts[1].decode("latin-1")

        if method == "CONNECT":
            host, port = _split_host_port(target)
            # 读完请求头（到空行）
            while True:
                line = await asyncio.wait_for(client_r.readline(), timeout=10)
                if line in (b"\r\n", b"\n", b""):
                    break
            try:
                up_r, up_w = await _connect_upstream(host, port)
            except (JuliangError, ValueError, OSError):
                client_w.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                await client_w.drain()
                return
            client_w.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await client_w.drain()
            tunnel = Tunnel(client_w, up_w)
            await _pipe(tunnel, client_r, up_r)

        elif target.startswith("http://"):
            # 明文绝对 URI：解析 host 后原样转发（请求头仍在 client_r 流中，由管道承载）
            from urllib.parse import urlsplit
            sp = urlsplit(target)
            host, port = sp.hostname or "", sp.port or 80
            try:
                up_r, up_w = await _connect_upstream(host, port)
            except (JuliangError, ValueError, OSError):
                client_w.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                await client_w.drain()
                return
            up_w.write(first)  # 原样转发请求行
            await up_w.drain()
            tunnel = Tunnel(client_w, up_w)
            await _pipe(tunnel, client_r, up_r)
        # 其他方法（相对 URI/未知协议）：关闭
    except (asyncio.TimeoutError, ConnectionError, OSError, ValueError):
        pass
    finally:
        try:
            client_w.close()
        except Exception:
            pass
