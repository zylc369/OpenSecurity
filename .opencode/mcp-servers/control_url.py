"""控制台 IPC 地址发现与 HTTP 客户端工厂（Python 侧唯一入口）。

所有需要访问 control/backend 的 Python 代码（knowledge/events/ocr 薄壳、
测试脚本）都通过本模块获取控制台地址与 httpx 客户端。

IPC 化设计（与 control/backend/config.py 常量保持一致——两处进程
sys.path 不同，常量按约定复制，修改须同步）：
  • macOS/Linux：Unix Domain Socket $DATA_DIR/opensecurity-control.sock
    httpx 原生支持：AsyncHTTPTransport(uds=...)
  • Windows：命名管道 \\\\.\\pipe\\opensecurity-control-482964
    httpx 不支持管道 → ControlIpc 内置进程内本地代理线程
    （127.0.0.1 随机端口 → 管道，双泵）。随机端口是进程内部实现
    细节（无文件、无固定占用、无发现机制）。

控制台重启后：调用方在请求失败时重新调用 resolve_control() 即可
（Unix 地址不变，重连即自愈；Windows 代理线程常驻，同样重连）。
"""
from __future__ import annotations

import os
import socket
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import httpx

IS_WINDOWS = sys.platform == "win32"  # 与 control/backend/config.py 写法统一
IPC_UNIX_SOCKET_NAME = "opensecurity-control.sock"
IPC_WINDOWS_PIPE = r"\\.\pipe\opensecurity-control-482964"
# 与 control/backend/config.py 的 IPC_WINDOWS_PIPE 常量同步修改

_BUF = 65536


def _unix_socket_path() -> Path:
    data_dir = os.environ.get("DATA_DIR", str(Path.home() / "bw-security-analysis"))
    return Path(data_dir) / IPC_UNIX_SOCKET_NAME


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
        if _unix_socket_path().exists():
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
            transport=httpx.AsyncHTTPTransport(uds=str(_unix_socket_path())),
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
        """一条 TCP 连接 ↔ 一条管道连接的双向泵。"""
        import win32file
        try:
            pipe = win32file.CreateFile(
                IPC_WINDOWS_PIPE,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0, None, win32file.OPEN_EXISTING, 0, None,
            )
        except OSError:
            conn.close()
            return

        def pipe_read():
            _, data = win32file.ReadFile(pipe, _BUF)
            return data

        def finish():
            try:
                win32file.CloseHandle(pipe)
            except OSError:
                pass
            conn.close()

        def run(read_fn, write_fn):
            try:
                while True:
                    data = read_fn()
                    if not data:
                        break
                    write_fn(data)
            except OSError:
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
