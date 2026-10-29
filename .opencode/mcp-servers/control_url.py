"""控制台 IPC 地址读取与 HTTP 客户端工厂（Python 侧唯一入口）。

所有需要访问控制台的 MCP 薄壳（knowledge/events/ocr/proxy）通过本模块获取
地址与 httpx 客户端。本模块**不依赖控制台代码**：IPC 地址由启动方
（插件 mcp-manager）以环境变量 `OPENSECURITY_CONTROL_IPC` 注入——
  • macOS/Linux：Unix Domain Socket 绝对路径（httpx 原生支持 uds=...）
  • Windows：命名管道名（httpx 不支持管道 → ControlIpc 内置进程内本地代理
    线程：127.0.0.1 随机端口 → 管道，双泵；随机端口是进程内部实现细节）。

控制台重启后：调用方在请求失败时重新调用 resolve_control() 即可
（Unix 地址不变，重连即自愈；Windows 代理线程常驻，同样重连）。
"""
from __future__ import annotations

import os
import socket
import sys
import threading
from dataclasses import dataclass
from typing import cast

import httpx

IS_WINDOWS = sys.platform == "win32"  # 与后端 services/config_manager.py 的平台判定写法一致
IPC_ENV_NAME = "OPENSECURITY_CONTROL_IPC"  # 启动方（插件 mcp-manager）注入的平台最终地址

_BUF = 65536


def _ipc_address() -> str:
    """控制台 IPC 会合地址（Unix socket 绝对路径 / Windows 管道名）。"""
    addr = os.environ.get(IPC_ENV_NAME)
    if not addr:
        raise RuntimeError(f"{IPC_ENV_NAME} 未注入——MCP 薄壳须由插件 mcp-manager 启动")
    return addr


@dataclass(frozen=True)
class ControlAddr:
    """控制台 IPC 地址。

    url：httpx 请求用的 base（uds 模式 host 为占位）。
    via：实际通道（"uds" / "pipe-proxy"）。
    """
    url: str
    via: str


class ControlIpc:
    """IPC 地址解析 + Windows 管道代理 + httpx 客户端工厂。

    线程模型：_proxy_lock 保护代理线程的单次启动（多 MCP lifespan 并发时）；
    代理 accept/泵为连接局部状态，不持锁。
    """

    def __init__(self) -> None:
        self._proxy_lock = threading.Lock()
        self._proxy_port: int | None = None

    # ── 地址解析 ──────────────────────────────────────────

    def resolve(self) -> ControlAddr | None:
        """解析当前控制台 IPC 地址（无发现文件——地址是编译期常量）。

        Unix：socket 路径存在即认为控制台可达（连接失败由调用方自愈重试）；
        Windows：管道常量永远"存在"（服务端未起时连接失败同样由调用方处理）。
        """
        if IS_WINDOWS:
            port = self._ensure_pipe_proxy()
            return ControlAddr(url=f"http://127.0.0.1:{port}", via="pipe-proxy")
        if os.path.exists(_ipc_address()):
            return ControlAddr(url="http://localhost", via="uds")
        return None

    # ── httpx 客户端工厂 ──────────────────────────────────

    def make_client(self, timeout: "httpx.Timeout | float" = 30.0) -> httpx.AsyncClient:
        """构造连控制台 IPC 的 httpx AsyncClient（薄壳 lifespan 用）。

        显式子集签名: 全部薄壳只传 timeout; base_url 不可传（防覆盖 IPC 地址）。
        """
        self.resolve()  # 确保 Windows 代理线程已启动
        if IS_WINDOWS:
            return httpx.AsyncClient(timeout=timeout)
        return httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=_ipc_address()),
            timeout=timeout,
        )

    # ── Windows 管道代理（127.0.0.1 随机端口 → 管道）──────

    def _ensure_pipe_proxy(self) -> int:
        """启动（一次性）本地代理线程，返回其监听端口。"""
        with self._proxy_lock:
            port = self._proxy_port
            if port:
                return port
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.bind(("127.0.0.1", 0))          # 随机端口：进程内实现细节
            srv.listen(8)
            port = cast(int, srv.getsockname()[1])  # typeshed 的 getsockname 返回宽元组——cast 收口
            self._proxy_port = port
            threading.Thread(target=self._proxy_accept_loop, args=(srv,), daemon=True).start()
            return port

    def _proxy_accept_loop(self, srv: socket.socket) -> None:
        while True:
            try:
                conn, _ = srv.accept()  # pyright: ignore[reportAny] —— typeshed accept 元组
            except OSError:
                return
            threading.Thread(target=self._proxy_serve, args=(conn,), daemon=True).start()

    def _proxy_serve(self, conn: socket.socket) -> None:
        """TCP ↔ 管道（**单线程轮询桥**）。

        win32file/pywintypes 为函数内惰性 import：仅由 _ensure_pipe_proxy 经
        resolve() 的 IS_WINDOWS 分支调用——macOS/Linux 上此函数永不执行。
        为什么不用双泵：Windows 同步管道句柄 I/O 句柄级序列化——pending
        ReadFile 阻塞同句柄 WriteFile（跨线程亦然）——双泵必然死锁
        （CI 实证）。改为 PeekNamedPipe + select 单线程交替转发（与
        control/backend/services/ipc_listener._serve_pipe 同构，两边
        修改须同步）。约束：单次转发量 ≤ 管道缓冲（64KB）。
        """
        import select as _select

        import pywintypes
        import win32file
        import win32pipe

        win_errs = (OSError, pywintypes.error)
        try:
            # pywin32 API 实际接受 PyHANDLE；stub 窄。cast 仅类型层——
            # 必须保留 PyHANDLE 对象引用（其句柄生命周期由对象管理；int() 化会丢
            # 引用致 GC 提前关闭句柄 → 句柄号复用后对"非 socket"操作报 WinError 10038）
            pipe = cast(int, win32file.CreateFile(
                _ipc_address(),
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0, None, win32file.OPEN_EXISTING, 0, None,
            ))
        except win_errs as e:
            print(f"[control_url] 管道连接失败（控制台未起或管道未就绪）: {e}",
                  file=sys.stderr)
            conn.close()
            return
        try:
            while True:
                # 管道 → TCP
                try:
                    # size=1 而非 0：C 层 malloc(0) 可能返回 NULL 误报 NoMemory
                    _, avail, _ = win32pipe.PeekNamedPipe(pipe, 1)  # pyright: ignore[reportAny] —— pywin32 stub（Windows-only，CI 裁决）
                except win_errs:
                    break
                if avail:
                    try:
                        _, data = win32file.ReadFile(pipe, min(avail, _BUF))
                    except win_errs:
                        break
                    if not data:
                        break
                    conn.sendall(data)  # pyright: ignore[reportArgumentType]
                # TCP → 管道
                r, _, _ = _select.select([conn], [], [], 0.001)
                if r:
                    data = conn.recv(_BUF)
                    if not data:
                        break
                    try:
                        win32file.WriteFile(pipe, data)
                    except win_errs:
                        break
        except win_errs as e:
            # TCP 侧异常（conn sendall/recv/select——httpx 关闭连接/RST）收尾。
            # 薄壳无 logging 基建：stderr 是 MCP 的日志流（stdout 为协议流，
            # 写入即污染 JSON-RPC——禁止）。
            print(f"[control_url] 管道桥 TCP 侧异常收尾: {e}", file=sys.stderr)
        finally:
            try:
                win32file.CloseHandle(pipe)
            except win_errs:
                pass
            conn.close()


# 模块级单例 + 同名委托（消费方 knowledge/events/ocr 零改动）
_control_ipc = ControlIpc()


def resolve_control() -> ControlAddr | None:
    return _control_ipc.resolve()


def make_control_client(timeout: "httpx.Timeout | float" = 30.0) -> httpx.AsyncClient:
    return _control_ipc.make_client(timeout=timeout)
