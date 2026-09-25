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
import logging
import time

from config import PROXY_RELAY_PORT_CANDIDATES, PROXY_RELAY_PORT_START, PROXY_ROTATE_CONN_THRESHOLD
from services.proxy_pool import JuliangError, get_pool, normalize_domain

_server: asyncio.AbstractServer | None = None
_port: int | None = None
_log = logging.getLogger("proxy_relay")
_rotate_gate: asyncio.Lock | None = None  # 阈值轮换防重入（惰性建，绑定运行循环）

# 活动隧道注册表（优雅关闭用）与 proxy 出口连接计数（阈值轮换用）
_tunnels: set["Tunnel"] = set()
_proxy_conn_count = 0
_drain_grace_sec = 5.0


class Tunnel:
    """一条已建立的转发隧道（客户端连接 + 上游连接 + 双向泵 task）。

    tasks 顺序约定：[0]=client→upstream（请求方向），[1]=upstream→client（响应方向）。
    """

    def __init__(self, client_w: asyncio.StreamWriter, up_w: asyncio.StreamWriter):
        self.client_w = client_w
        self.up_w = up_w
        self.tasks: list[asyncio.Task] = []
        self.draining = False           # 优雅排空中（见 graceful_close_upstream）
        self.drain_deadline: float = 0.0  # 排空宽限截止（monotonic）

    async def graceful_close_upstream(self, grace: float | None = None) -> None:
        """优雅排空（需求 §5.4：在飞响应完整送达）。

        排空模式：上游已 FIN（不再有新请求），此期间客户端可能继续发数据
        （WebSocket/keep-alive 复用/pipelining）——若让 client→up 泵继续跑，
        写已 EOF 的 transport 抛 RuntimeError 令泵异常死亡并连坐取消响应方向泵
        （在飞响应被截断）。因此显式取消请求方向泵（tasks[0]，其数据已无处可去），
        仅保留响应方向泵（tasks[1]）投递剩余字节，至自然 EOF 或 grace 兜底强关。
        """
        if grace is None:
            grace = _drain_grace_sec   # 运行期解析（默认参数会在定义期绑定常量，不可调）
        self.draining = True
        self.drain_deadline = time.monotonic() + grace
        # 上游 FIN（不再有新请求）。请求方向泵不 cancel：排空期间客户端再发数据会令其
        # 因"EOF 后写"结束（RuntimeError 已被泵捕获，finally 半关无害）——泵结束本身
        # 触发 _pipe 的排空等待分支，响应方向泵继续投递。
        try:
            self.up_w.write_eof()
        except (OSError, RuntimeError) as e:
            _log.debug("write_eof 已关闭连接（预期半关收尾）: %s", e)
        # 2. 等待响应方向泵自然结束（剩余字节送达 + 客户端方向收尾），grace 兜底
        deadline = time.monotonic() + grace
        if len(self.tasks) > 1:
            remaining = deadline - time.monotonic()
            if remaining > 0 and not self.tasks[1].done():
                try:
                    await asyncio.wait({self.tasks[1]}, timeout=remaining)
                except Exception as e:
                    _log.debug("等待响应泵结束异常: %r", e)
        # 3. 兜底强关（超长响应场景）
        for w in (self.up_w, self.client_w):
            try:
                w.close()
            except Exception as e:
                _log.debug("graceful_close 兜底关闭异常（多已关闭）: %s", e)


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
    """关闭监听并清空注册态（supervisor 重拉前调用）。

    只 close 不 wait_closed——wait 会等所有存活连接（含 keep-alive）排空，
    可能分钟级；自愈要求秒级，close 后内核继续排空在途数据，新实例即可 bind。
    """
    global _server, _port, _rotate_gate
    _rotate_gate = None            # 关闭时清锁（下次 start 重建）
    if _server is not None:
        try:
            _server.close()
        except Exception as e:
            _log.warning("relay 关闭监听异常: %r", e)
    _server = None
    _port = None


def relay_port() -> int:
    """真实监听端口（未启动时 RuntimeError，调用方回退配置起点值）。"""
    if _port is None:
        raise RuntimeError("relay 未启动")
    return _port


async def start_relay() -> None:
    """绑定端口（顺延候选段）并开始服务。幂等（已运行直接返回）。"""
    global _server, _port, _rotate_gate
    if _server is not None:
        return
    _rotate_gate = asyncio.Lock()  # 随监听生命周期重建（绑定当前循环，防跨循环残留）
    global _proxy_conn_count
    _proxy_conn_count = 0
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
        global _rotate_gate
        info = await pool.get()  # 缓存复用；过期/黑名单自动提取（惰性）
        _proxy_conn_count += 1
        if _proxy_conn_count >= PROXY_ROTATE_CONN_THRESHOLD:
            if _rotate_gate is None:
                _rotate_gate = asyncio.Lock()
            async with _rotate_gate:                  # 防重入：并发到达阈值的连接只轮换一次
                if _proxy_conn_count >= PROXY_ROTATE_CONN_THRESHOLD:  # 双重检查
                    _proxy_conn_count = 0
                    await pool.rotate("auto_rotate_35conn")   # 阈值轮换（记 rotate_history）
                    info = await pool.get()                   # 轮换后的新 IP
                    await graceful_close_upstreams()           # 存量隧道优雅收尾
                else:                                        # 已被首个连接轮换过——复用新 IP
                    info = await pool.get()
        proxy_host, _, proxy_port = info.ip.rpartition(":")
        up_r, up_w = await asyncio.open_connection(proxy_host, int(proxy_port))
        # 上游是 HTTP 代理：必须先向接入点完成 CONNECT 握手（建立它到目标站的隧道），
        # 之后的字节才在"客户端↔目标站"端到端流动。缺这一步=TLS 字节灌进裸 TCP(协议垃圾)。
        # 只发请求行+空行（不发 Host 头）——Host 对 CONNECT 是可选的，且部分代理实现
        # 只 readline 一行即进泵，多发的头会泄漏进隧道污染目标请求。
        try:
            up_w.write(f"CONNECT {host}:{port} HTTP/1.1\r\n\r\n".encode())
            await up_w.drain()
            status_line = await asyncio.wait_for(up_r.readline(), timeout=15)
            fields = status_line.split()
            if len(fields) < 2 or fields[1] != b"200":   # 容忍无 reason phrase 的 200
                raise OSError(f"接入点 CONNECT 握手失败: {status_line[:60]!r}")
            while True:  # 读完接入点响应头（到空行）
                line = await asyncio.wait_for(up_r.readline(), timeout=10)
                if line in (b"\r\n", b"\n", b""):
                    break
        except (asyncio.TimeoutError, OSError, RuntimeError) as e:
            _log.warning("上游 CONNECT 握手异常（关闭泄漏连接）: %r", e)
            up_w.close()
            raise
        return up_r, up_w
    # direct 出口：IPv6 字面量去方括号（CONNECT 线格式 [::1]:443 → open_connection 需 ::1）
    return await asyncio.open_connection(host.strip("[]"), port)


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
        except (ConnectionError, asyncio.IncompleteReadError, OSError, RuntimeError) as e:
            _log.debug("隧道泵结束（连接断开/EOF后写属正常流）: %s", e)
        finally:
            # 半关目标（write_eof 传播 EOF）而非 close——close 会立即杀死对端方向
            # 正在投递的在飞响应（优雅关闭场景）。close 留给 _pipe 统一收尾。
            try:
                w.write_eof()
            except (OSError, RuntimeError):
                pass

    _tunnels.add(tunnel)
    t1 = asyncio.create_task(pump(client_r, tunnel.up_w))
    t2 = asyncio.create_task(pump(up_r, tunnel.client_w))
    tunnel.tasks = [t1, t2]
    try:
        await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
        # 排空模式：t1 结束（EOF/被 graceful cancel/异常）而响应泵 t2 仍在投递——
        # 不立即 teardown，等 t2 至排空宽限线（在飞响应完整送达，需求 §5.4）
        if tunnel.draining and not t2.done():
            remaining = tunnel.drain_deadline - time.monotonic()
            if remaining > 0:
                await asyncio.wait({t2}, timeout=remaining)
    finally:
        t1.cancel()
        t2.cancel()
        for w in (tunnel.client_w, tunnel.up_w):
            try:
                w.close()
            except Exception as e:
                _log.debug("隧道收尾关闭异常（多已关闭）: %s", e)
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
            # 明文绝对 URI：解析 host 后转发（请求头仍在 client_r 流中，由管道承载）
            from urllib.parse import urlsplit
            sp = urlsplit(target)
            host, port = sp.hostname or "", sp.port or 80
            try:
                up_r, up_w = await _connect_upstream(host, port)
            except (JuliangError, ValueError, OSError):
                client_w.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                await client_w.drain()
                return
            # 改写为相对 URI（proxy 出口时上游是 CONNECT 隧道后的目标站——隧道内
            # 服务器多接受绝对 URI 但部分拒绝；direct 出口时无影响。统一改写最稳。
            # method 用原始值（明文代理可能承载 POST/HEAD））
            path_part = target[len(f"http://{sp.netloc}"):] or "/"
            if path_part.startswith("?"):          # http://host?a=1（无斜杠）→ /?a=1
                path_part = "/" + path_part
            up_w.write(f"{method} {path_part} HTTP/1.1\r\n".encode())
            await up_w.drain()
            tunnel = Tunnel(client_w, up_w)
            await _pipe(tunnel, client_r, up_r)
        # 其他方法（相对 URI/未知协议）：关闭
    except (asyncio.TimeoutError, ConnectionError, OSError, ValueError) as e:
        _log.debug("客户端连接结束（超时/断开/非法输入）: %r", e)
    finally:
        try:
            client_w.close()
        except Exception as e:
            _log.debug("客户端连接收尾关闭异常: %s", e)
