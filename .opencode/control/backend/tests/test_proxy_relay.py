"""proxy_relay 集成测试：按真实代理语义 mock 上游（收 CONNECT → 回 200 → 隧道回环）。

结构约定：每个用例单次 asyncio.run() —— mock 目标站/mock 上游代理/relay/客户端
全部运行在**同一个事件循环**内（跨 run 的 server 对象会随旧循环失活，连接挂死）。
全部 127.0.0.1 回环，零外网、零真实配额消耗。
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from services import proxy_relay as pr
from services import proxy_pool as pp

ORIGIN_BODY = b"ORIGIN-RESPONSE-" + b"X" * 500


class FakePool:
    """替身 pool：返回指定代理地址；计数提取/轮换。"""

    def __init__(self, proxy_addr: str, force_proxy: bool = True):
        self.proxy_addr = proxy_addr
        self.get_calls = 0
        self.rotate_calls = 0
        self._force_proxy = force_proxy

    async def get(self, force_new: bool = False) -> "pp.ProxyInfo":
        self.get_calls += 1
        return pp.ProxyInfo(ip=self.proxy_addr, fetched_at=time.time(),
                            expire_at=time.time() + 270)

    async def rotate(self, reason: str) -> "pp.ProxyInfo":
        self.rotate_calls += 1
        return await self.get(force_new=True)

    def domain_cooled(self, domain_raw: str) -> bool:
        return self._force_proxy

    def status(self) -> dict:
        return {"mode": "proxy" if self._force_proxy else "direct"}


async def start_mock_origin(slow: bool = False) -> int:
    """mock 目标站：回 ORIGIN_BODY（slow 分块 0.1s×5）。"""
    async def handler(reader, writer):
        await reader.read(65536)
        if slow:
            sz = len(ORIGIN_BODY) // 5
            for i in range(5):
                writer.write(ORIGIN_BODY[i*sz:(i+1)*sz]); await writer.drain()
                await asyncio.sleep(0.1)
        else:
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n" % len(ORIGIN_BODY) + ORIGIN_BODY)
            await writer.drain()
        writer.close()
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    return server.sockets[0].getsockname()[1]


async def start_mock_proxy(connect_ok: bool = True) -> tuple[int, list]:
    """mock 上游代理（真实语义）：CONNECT → 200/407 → 隧道回环；明文绝对 URI 回环。
    返回 (port, seen)：seen 记录代理收到的请求行。"""
    seen: list[str] = []

    async def handler(reader, writer):
        first = await reader.readline()
        parts = first.split()
        if not parts:
            writer.close(); return
        if parts[0] == b"CONNECT":
            seen.append(first.decode().strip())
            while True:  # 标准代理语义：读完 CONNECT 请求全部头（到空行）再回 200
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
            if not connect_ok:
                writer.write(b"HTTP/1.1 407 Proxy Auth Required\r\n\r\n")
                await writer.drain(); writer.close(); return
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            host, _, port = parts[1].decode().rpartition(":")
            u_r, u_w = await asyncio.open_connection(host, int(port))
        else:
            seen.append(first.decode().strip())
            from urllib.parse import urlsplit
            sp = urlsplit(parts[1].decode())
            u_r, u_w = await asyncio.open_connection(sp.hostname, sp.port or 80)
            u_w.write(first); await u_w.drain()

        async def pump(r, w, *, half_close_peer_w=None):
            """half_close_peer_w: 本方向 EOF 时只对其 write_eof(半关), 不整体退出——
            模拟真实代理的 half-close 语义(FIN=不再发新请求, 继续转发剩余响应)。"""
            try:
                while True:
                    d = await r.read(65536)
                    if not d:
                        break
                    w.write(d); await w.drain()
            except Exception:
                pass
            finally:
                try:
                    if half_close_peer_w is not None:
                        half_close_peer_w.write_eof()
                    else:
                        w.close()
                except Exception:
                    pass
        # reader(client)→u_w: EOF 时半关 u_w(write_eof), 让 u_r 方向继续转发
        await asyncio.gather(
            pump(reader, u_w, half_close_peer_w=u_w),
            pump(u_r, writer))

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    return server.sockets[0].getsockname()[1], seen


async def read_all(r, timeout=5):
    """循环读直到 EOF 或超时（read(n) 只取当前缓冲，不等待数据到齐）。"""
    got = b""
    try:
        while True:
            d = await asyncio.wait_for(r.read(65536), timeout=timeout)
            if not d:
                break
            got += d
    except asyncio.TimeoutError:
        pass
    return got


async def client(port: int):
    return await asyncio.open_connection("127.0.0.1", port)


def run_relay_test(scenario):
    """统一入口：单循环内起 relay → 跑 scenario(relay_port) → 收尾 stop。
    注入 FakePool 的方式 = 直接替换 pr.get_pool（同循环内生效）。"""
    async def main():
        await pr.start_relay()
        try:
            return await scenario(pr.relay_port())
        finally:
            await pr.stop_relay()
    return asyncio.run(main())


# ─── 用例（每个 scenario 内自行起 mock）───────────────────


def test_connect_tunnel_end_to_end():
    """R1/R2: CONNECT 经 relay → mock代理(握手200) → 目标站，字节端到端。"""
    async def scenario(relay_port):
        origin = await start_mock_origin()
        proxy_port, seen = await start_mock_proxy()
        pr.get_pool = lambda: FakePool(f"127.0.0.1:{proxy_port}")
        r, w = await client(relay_port)
        w.write(f"CONNECT 127.0.0.1:{origin} HTTP/1.1\r\n\r\n".encode()); await w.drain()
        resp = await r.readline()
        assert b"200 Connection Established" in resp, resp
        await r.readline()  # 吃掉应答尾部空行
        w.write(b"HELLO"); await w.drain()
        echoed = await read_all(r)
        assert b"ORIGIN-RESPONSE" in echoed
        assert seen[0].startswith(f"CONNECT 127.0.0.1:{origin}")  # 代理收到 CONNECT 握手
    run_relay_test(scenario)


def test_connect_upstream_rejected_502():
    """R3: 上游代理拒 CONNECT(407) → relay 给客户端 502。"""
    async def scenario(relay_port):
        origin = await start_mock_origin()
        rej_port, _ = await start_mock_proxy(connect_ok=False)
        pr.get_pool = lambda: FakePool(f"127.0.0.1:{rej_port}")
        r, w = await client(relay_port)
        w.write(f"CONNECT 127.0.0.1:{origin} HTTP/1.1\r\n\r\n".encode()); await w.drain()
        line = await r.readline()
        assert b"502" in line, line
    run_relay_test(scenario)


def test_threshold_rotate_uses_new_ip():
    """R4: 阈值轮换后新连接必须走新代理地址（回归：曾沿用旧 info.ip）。"""
    async def scenario(relay_port):
        origin = await start_mock_origin()
        proxy_port, _ = await start_mock_proxy()
        fake = FakePool(f"127.0.0.1:{proxy_port}")
        pr.get_pool = lambda: fake
        pr.PROXY_ROTATE_CONN_THRESHOLD = 2
        async def one():
            r, w = await client(relay_port)
            w.write(f"CONNECT 127.0.0.1:{origin} HTTP/1.1\r\n\r\n".encode()); await w.drain()
            await r.readline(); w.close()
        await one(); await one()          # 第2连接触发阈值轮换
        new_port, new_seen = await start_mock_proxy()
        fake.proxy_addr = f"127.0.0.1:{new_port}"
        await one()                        # 轮换后的连接
        assert fake.rotate_calls >= 1, "阈值轮换未触发"
        assert len(new_seen) >= 1, "轮换后新连接未打到新代理（回归 bug）"
        assert new_seen[0].startswith(f"CONNECT 127.0.0.1:{origin}")
        pr.PROXY_ROTATE_CONN_THRESHOLD = 35
    run_relay_test(scenario)


def test_plaintext_rewrite_and_method_preserved():
    """R5: 明文绝对 URI 经 proxy 出口 → 改写为相对 URI、method 保留（目标站可解析）。"""
    async def scenario(relay_port):
        # 用"记录请求行的目标站"验证改写
        got_line: list[bytes] = []
        async def echo_origin(reader, writer):
            got_line.append(await reader.readline())
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK"); await writer.drain()
            writer.close()
        srv = await asyncio.start_server(echo_origin, "127.0.0.1", 0)
        origin = srv.sockets[0].getsockname()[1]
        proxy_port, _ = await start_mock_proxy()
        pr.get_pool = lambda: FakePool(f"127.0.0.1:{proxy_port}")
        r, w = await client(relay_port)
        w.write(f"POST http://127.0.0.1:{origin}/submit?a=1 HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\n\r\n".encode())
        await w.drain()
        body = await read_all(r)
        assert body.endswith(b"OK")
        assert got_line and got_line[0].startswith(b"POST /submit?a=1 "), got_line  # 相对 URI + POST 保留
    run_relay_test(scenario)


def test_garbage_input_relay_survives():
    """R6: 垃圾输入 → 连接关闭，relay 存活可继续服务。"""
    async def scenario(relay_port):
        origin = await start_mock_origin()
        proxy_port, _ = await start_mock_proxy()
        pr.get_pool = lambda: FakePool(f"127.0.0.1:{proxy_port}")
        r, w = await client(relay_port)
        w.write(b"\x00\x01garbage no protocol\r\n\r\n"); await w.drain()
        try:
            await asyncio.wait_for(r.read(), timeout=3)
        except asyncio.TimeoutError:
            pass
        w.close()
        r2, w2 = await client(relay_port)
        w2.write(f"CONNECT 127.0.0.1:{origin} HTTP/1.1\r\n\r\n".encode()); await w2.drain()
        line = await r2.readline()
        assert b"200" in line, "relay 被垃圾输入搞挂"
    run_relay_test(scenario)


def test_graceful_close_inflight_delivered():
    """R7: 慢响应传输途中切换出口 → 客户端收满全部字节。"""
    async def scenario(relay_port):
        slow_port = await start_mock_origin(slow=True)
        proxy_port, _ = await start_mock_proxy()
        pr.get_pool = lambda: FakePool(f"127.0.0.1:{proxy_port}")
        r, w = await client(relay_port)
        w.write(f"CONNECT 127.0.0.1:{slow_port} HTTP/1.1\r\n\r\n".encode()); await w.drain()
        await r.readline(); await r.readline()  # 状态行 + 空行
        await asyncio.sleep(0.25)  # 传到一半
        await pr.graceful_close_upstreams()
        got = b""
        try:
            while True:
                d = await asyncio.wait_for(r.read(65536), timeout=6)
                if not d:
                    break
                got += d
        except asyncio.TimeoutError:
            pass
        assert got.endswith(b"X" * 100), f"在飞响应未完整送达({len(got)}/{len(ORIGIN_BODY)})"
    run_relay_test(scenario)


def test_concurrent_tunnels():
    """R8: 5 条并发隧道同时工作。"""
    async def scenario(relay_port):
        origin = await start_mock_origin()
        proxy_port, _ = await start_mock_proxy()
        pr.get_pool = lambda: FakePool(f"127.0.0.1:{proxy_port}")
        async def one():
            r, w = await client(relay_port)
            w.write(f"CONNECT 127.0.0.1:{origin} HTTP/1.1\r\n\r\n".encode()); await w.drain()
            line = await r.readline()
            await r.readline()  # 空行
            w.write(b"REQ"); await w.drain()
            data = await read_all(r)
            w.close()
            return b"200" in line and b"ORIGIN-RESPONSE" in data
        assert all(await asyncio.gather(*[one() for _ in range(5)]))
    run_relay_test(scenario)


def test_concurrent_threshold_single_rotate():
    """并发到达阈值：多个连接同时触发轮换分支 → 恰好 1 次 rotate（防重入锁）。"""
    async def scenario(relay_port):
        origin = await start_mock_origin()
        proxy_port, _ = await start_mock_proxy()
        fake = FakePool(f"127.0.0.1:{proxy_port}")
        pr.get_pool = lambda: fake
        pr.PROXY_ROTATE_CONN_THRESHOLD = 3
        async def one():
            r, w = await client(relay_port)
            w.write(f"CONNECT 127.0.0.1:{origin} HTTP/1.1\r\n\r\n".encode()); await w.drain()
            await r.readline(); await r.readline()
            w.write(b"ping"); await w.drain()
            await read_all(r, timeout=3)
        # 先串行 2 连接（count=2，未达阈值），再并发 3 连接——三者同时见 count>=3，
        # 防重入锁保证这批并发只轮换 1 次（若无锁会轮换 3 次）
        await one(); await one()
        await asyncio.gather(*[one() for _ in range(3)])
        assert fake.rotate_calls == 1, f"并发到达阈值应只轮换 1 次，实际 {fake.rotate_calls}"
        assert fake.get_calls >= 5
        pr.PROXY_ROTATE_CONN_THRESHOLD = 35
    run_relay_test(scenario)


def test_graceful_close_survives_client_sends_during_drain():
    """回归（外部 review 复现）：优雅排空期间客户端继续发数据（WebSocket/keep-alive
    复用形态）——排空模式应丢弃该数据而非令泵异常死亡截断在飞响应。"""
    async def scenario(relay_port):
        slow_port = await start_mock_origin(slow=True)
        proxy_port, _ = await start_mock_proxy()
        pr.get_pool = lambda: FakePool(f"127.0.0.1:{proxy_port}")
        r, w = await client(relay_port)
        w.write(f"CONNECT 127.0.0.1:{slow_port} HTTP/1.1\r\n\r\n".encode()); await w.drain()
        await r.readline(); await r.readline()
        await asyncio.sleep(0.2)                       # 慢响应传输中
        drain_task = asyncio.create_task(pr.graceful_close_upstreams())
        await asyncio.sleep(0.05)
        # 排空期间客户端持续发数据（打过的泵若写已 EOF transport 会 RuntimeError 死亡）
        for _ in range(4):
            try:
                w.write(b"CLIENT-DATA-DURING-DRAIN"); await w.drain()
            except (ConnectionError, RuntimeError):
                pass                                    # 连接后期被关属预期
            await asyncio.sleep(0.08)
        await drain_task
        got = b""
        try:
            while True:
                d = await asyncio.wait_for(r.read(65536), timeout=6)
                if not d:
                    break
                got += d
        except asyncio.TimeoutError:
            pass
        assert got.endswith(b"X" * 100), f"排空期客户端发数据截断了在飞响应({len(got)}/{len(ORIGIN_BODY)})"
    run_relay_test(scenario)


def test_direct_mode_ipv6_literal_target():
    """回归（外部 review #2）：direct 出口 CONNECT [::1]:port —— 方括号剥离后可达。"""
    async def scenario(relay_port):
        async def v6_origin(reader, writer):
            await reader.read(65536)
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nV6OK"); await writer.drain()
            writer.close()
        srv = await asyncio.start_server(v6_origin, "::1", 0)
        v6port = srv.sockets[0].getsockname()[1]
        pr.get_pool = lambda: FakePool("127.0.0.1:1", force_proxy=False)  # direct
        r, w = await client(relay_port)
        w.write(f"CONNECT [::1]:{v6port} HTTP/1.1\r\n\r\n".encode()); await w.drain()
        line = await r.readline()
        assert b"200" in line, f"IPv6 direct 应剥方括号直连: {line!r}"
        w.write(b"ping"); await w.drain()
        data = await read_all(r)
        assert b"V6OK" in data
    run_relay_test(scenario)


def test_plaintext_path_without_slash():
    """回归（外部 review 信息级）：GET http://host?a=1（无斜杠）→ 改写为 /?a=1。"""
    async def scenario(relay_port):
        got_line: list[bytes] = []
        async def echo_origin(reader, writer):
            got_line.append(await reader.readline())
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK"); await writer.drain()
            writer.close()
        srv = await asyncio.start_server(echo_origin, "127.0.0.1", 0)
        origin = srv.sockets[0].getsockname()[1]
        proxy_port, _ = await start_mock_proxy()
        pr.get_pool = lambda: FakePool(f"127.0.0.1:{proxy_port}")
        r, w = await client(relay_port)
        w.write(f"GET http://127.0.0.1:{origin}?a=1 HTTP/1.1\r\nHost: x\r\n\r\n".encode()); await w.drain()
        body = await read_all(r)
        assert body.endswith(b"OK")
        assert got_line[0].startswith(b"GET /?a=1 "), got_line
    run_relay_test(scenario)


def test_connect_status_line_without_reason_phrase():
    """回归（外部 review 信息级）：接入点回无 reason phrase 的 `HTTP/1.1 200` 不误判失败。"""
    async def scenario(relay_port):
        origin = await start_mock_origin()
        async def terse_proxy(reader, writer):
            await reader.readline()
            while True:
                if (await reader.readline()) in (b"\r\n", b"\n", b""):
                    break
            writer.write(b"HTTP/1.1 200\r\n\r\n"); await writer.drain()   # 无 reason phrase
            u_r, u_w = await asyncio.open_connection("127.0.0.1", origin)
            async def pump(rr, ww):
                try:
                    while True:
                        d = await rr.read(65536)
                        if not d: break
                        ww.write(d); await ww.drain()
                except Exception: pass
            await asyncio.gather(pump(reader, u_w), pump(u_r, writer))
        srv = await asyncio.start_server(terse_proxy, "127.0.0.1", 0)
        pp = srv.sockets[0].getsockname()[1]
        pr.get_pool = lambda: FakePool(f"127.0.0.1:{pp}")
        r, w = await client(relay_port)
        w.write(f"CONNECT 127.0.0.1:{origin} HTTP/1.1\r\n\r\n".encode()); await w.drain()
        line = await r.readline()
        assert b"200" in line, f"无 reason phrase 的 200 被误判: {line!r}"
    run_relay_test(scenario)


def test_graceful_close_grace_timeout_force_close():
    """排空宽限超时分支：响应慢于 grace → 宽限后强关（不挂死，收到部分即闭环）。"""
    async def scenario(relay_port):
        async def very_slow_origin(reader, writer):
            await reader.read(65536)
            for i in range(10):
                writer.write(b"S" * 50); await writer.drain()
                await asyncio.sleep(0.15)          # 总 1.5s > 缩短的 grace
        srv = await asyncio.start_server(very_slow_origin, "127.0.0.1", 0)
        slow = srv.sockets[0].getsockname()[1]
        proxy_port, _ = await start_mock_proxy()
        pr.get_pool = lambda: FakePool(f"127.0.0.1:{proxy_port}")
        old_grace = pr._drain_grace_sec
        pr._drain_grace_sec = 0.3                  # 缩短宽限加速测试
        try:
            r, w = await client(relay_port)
            w.write(f"CONNECT 127.0.0.1:{slow} HTTP/1.1\r\n\r\n".encode()); await w.drain()
            await r.readline(); await r.readline()
            await asyncio.sleep(0.2)
            t0 = time.monotonic()
            await pr.graceful_close_upstreams()
            elapsed = time.monotonic() - t0
            assert elapsed < 1.0, f"grace 超时应及时强关(实际{elapsed:.1f}s)——挂死"
        finally:
            pr._drain_grace_sec = old_grace
    run_relay_test(scenario)
