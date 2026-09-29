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

    def make_client(self, **kwargs) -> httpx.AsyncClient:
        """构造连控制台 IPC 的 httpx AsyncClient（薄壳 lifespan 用）。

        kwargs 透传 httpx.AsyncClient（timeout 等）。
        """
        self.resolve()  # 确保 Windows 代理线程已启动
        if IS_WINDOWS:
            return httpx.AsyncClient(**kwargs)
        kwargs.pop("base_url", None)
        return httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=_ipc_address()),
            **kwargs,
        )

    # ── Windows 管道代理（127.0.0.1 随机端口 → 管道）──────

    def _ensure_pipe_proxy(self) -> int:
        """启动（一次性）本地代理线程，返回其监听端口。"""
        with self._proxy_lock:
            if self._proxy_port:
                return self._proxy_port
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.bind(("127.0.0.1", 0))          # 随机端口：进程内实现细节
            srv.listen(8)
            self._proxy_port = srv.getsockname()[1]
            threading.Thread(target=self._proxy_accept_loop, args=(srv,), daemon=True).start()
            return self._proxy_port

    def _proxy_accept_loop(self, srv: socket.socket) -> None:
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=self._proxy_serve, args=(conn,), daemon=True).start()

    def _proxy_serve(self, conn: socket.socket) -> None:
        """一条 TCP 连接 ↔ 一条管道连接的双向泵。

        win32file/pywintypes 为**函数内惰性 import**：_proxy_serve 仅由
        _ensure_pipe_proxy 经 resolve() 的 IS_WINDOWS 分支调用——macOS/Linux
        上此函数永不执行，import 永不触发，模块加载不受影响（对比
        ipc_listener.py 的模块级 try-import：那里 _PLATFORM_OS_ERRORS 被
        跨平台代码共用，必须模块级定义 + 平台退化）。
        """
        import win32file
        import pywintypes

        # pywintypes.error 不继承 OSError（pywin32 源码 "class error(Exception)"）
        # ——管道路径的捕获必须含它，否则代理线程以未捕获异常终止
        win_errs = (OSError, pywintypes.error)
        try:
            pipe = win32file.CreateFile(
                _ipc_address(),
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0, None, win32file.OPEN_EXISTING, 0, None,
            )
        except win_errs:
            conn.close()
            return

        def pipe_read():
            _, data = win32file.ReadFile(pipe, _BUF)
            return data

        def finish():
            try:
                win32file.CloseHandle(pipe)
            except win_errs:
                pass
            conn.close()

        def run(read_fn, write_fn):
            try:
                while True:
                    data = read_fn()
                    if not data:
                        break
                    write_fn(data)
            except win_errs:
                pass
            finally:
                finish()

        t = threading.Thread(
            target=run, args=(pipe_read, lambda d: win32file.WriteFile(pipe, d)),
            daemon=True,
        )
        t.start()
        run(lambda: conn.recv(_BUF), conn.sendall)


# 模块级单例 + 同名委托（消费方 knowledge/events/ocr 零改动）
_control_ipc = ControlIpc()


def resolve_control() -> ControlAddr | None:
    return _control_ipc.resolve()


def make_control_client(**kwargs) -> httpx.AsyncClient:
    return _control_ipc.make_client(**kwargs)
