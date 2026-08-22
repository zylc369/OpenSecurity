"""前端端口注册中心（唯一事实源：控制台 TCP 端口 + vite dev 端口）。

职责：
  • 控制台浏览器通道 TCP bind（9776 起顺延候选段）+ 真实端口注册
  • vite dev 端口注册（vite 启动时经 IPC POST /api/dev-url 上报）
  • console_url 计算（发布态 = 控制台 TCP；开发态 = vite 端口，死了回退）
  • vite dev server 拉起（开发态，幂等，不抢占手动实例）

所有获取真实端口号的代码都从这里取（本模块单例 frontend_ports）。

线程模型：注册/查询走同一把锁（多请求线程并发写 vite 端口 + 主线程写 TCP 端口）；
TCP 探测无共享态不加锁；start_vite_dev 拉起有独立 _launch_lock 防并发双拉。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import os
import socket
import subprocess
import threading
from pathlib import Path

from config import (
    BIND_HOST,
    CONTROL_TCP_PORT_START,
    TCP_CANDIDATE_COUNT,
    EXIT_CODE_PORT_EXHAUSTED,
    OPENCODE_ROOT,
    is_dev_mode,
)

_PROBE_TIMEOUT_SEC = 0.3


def _port_alive(port: int) -> bool:
    """TCP 探测（双栈：vite/Node 17+ 可能只监听 [::1]）。无共享态，模块级纯函数。"""
    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, port), timeout=_PROBE_TIMEOUT_SEC):
                return True
        except OSError:
            continue
    return False


class FrontendPortRegistry:
    """前端可达端口的注册、查询与生命周期。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tcp_port: int | None = None        # 控制台浏览器通道（bind 后注册）
        self._vite_port: int | None = None       # vite dev（IPC 上报）
        self._launch_lock = threading.Lock()     # vite 拉起防并发双拉

    # ── 控制台 TCP 通道 ────────────────────────────────────

    def bind_and_register_tcp(self) -> "socket.socket":
        """在候选段内 bind（起点被占则顺延），成功后注册真实端口。

        Returns:
            已 bind 的 socket（由调用方负责 listen/detach）。
        Raises:
            RuntimeError: 候选段全部被占。
        """
        last_err: OSError | None = None
        for port in self.tcp_candidates():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((BIND_HOST, port))
                with self._lock:
                    self._tcp_port = port
                logger.info("浏览器 TCP 绑定 127.0.0.1:%d", port)
                return sock
            except OSError as e:
                last_err = e
                continue
        raise RuntimeError(
            f"TCP 候选段 {self.tcp_candidates()[0]}-{self.tcp_candidates()[-1]} "
            f"全部被占用（exit code = {EXIT_CODE_PORT_EXHAUSTED}）：{last_err}"
        )

    @staticmethod
    def tcp_candidates() -> list[int]:
        """候选端口列表（CONTROL_TCP_PORT 环境变量可重定向起点，测试沙箱用）。"""
        start = CONTROL_TCP_PORT_START
        env_val = os.environ.get("CONTROL_TCP_PORT")
        if env_val and env_val.isdigit():
            start = int(env_val)
        return list(range(start, start + TCP_CANDIDATE_COUNT))

    def tcp_port(self) -> int | None:
        """控制台真实 TCP 端口（未 bind 返回 None）。"""
        with self._lock:
            return self._tcp_port

    def register_tcp(self, port: int, verify_alive: bool = True) -> bool:
        """直接注册 TCP 端口（测试场景：uvicorn 自行 listen 后注册）。

        生产路径走 bind_and_register_tcp；本方法供测试/特殊编排复用。
        verify_alive=True 时探测端口有监听才注册（防误注册死端口）。
        """
        if verify_alive and not _port_alive(port):
            return False
        with self._lock:
            self._tcp_port = port
        return True

    def unregister_tcp(self) -> None:
        """清除 TCP 端口注册（测试隔离用）。"""
        with self._lock:
            self._tcp_port = None

    # ── vite dev 端口 ──────────────────────────────────────

    def register_vite_port(self, port: int) -> None:
        """vite 上报实际监听端口（冲突自动递增后上报的是真实值）。"""
        with self._lock:
            self._vite_port = port

    def vite_port(self) -> int | None:
        """vite 实际监听端口（未运行返回 None）。

        注册值优先 + 探活；注册缺失/过期时兜底探测候选段
        （vite 刚拉起未完成上报、或控制台重启导致注册清空——以实际监听为准）。
        """
        with self._lock:
            registered = self._vite_port
        if registered and _port_alive(registered):
            return registered
        for p in (5173, 5174, 5175):  # vite 冲突自动递增的候选段
            if _port_alive(p):
                return p
        return None

    def vite_running(self) -> bool:
        return self.vite_port() is not None

    # ── console_url（前端可达地址唯一计算点）──────────────

    def console_url(self) -> str:
        """当前可打开的控制台前端 URL。

        开发态：vite 活着 → vite 端口；否则回退控制台 TCP。
        发布态：控制台 TCP。
        """
        if is_dev_mode():
            vp = self.vite_port()
            if vp:
                return f"http://localhost:{vp}"
        tp = self.tcp_port() or self.tcp_candidates()[0]
        return f"http://localhost:{tp}"

    # ── vite 拉起（开发态）─────────────────────────────────

    def ensure_vite_dev(self) -> bool:
        """vite 未运行则后台拉起（独立进程组，控制台重启不连带杀）。

        Returns:
            True = 已在运行或本次已拉起；False = 无法拉起（依赖未装）。
        """
        if self.vite_running():
            return True
        if not OPENCODE_ROOT:
            return False
        with self._launch_lock:
            if self.vite_running():  # 双检：并发调用只拉一次
                return True
            frontend_dir = Path(OPENCODE_ROOT) / "control" / "frontend"
            vite_bin = frontend_dir / "node_modules" / ".bin" / "vite"
            if not vite_bin.is_file():
                return False  # 依赖未装——dev 提示页指路
            subprocess.Popen(
                [str(vite_bin)],
                cwd=str(frontend_dir),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True


# 模块级单例 + 同名委托（消费方 `from services.frontend_port import frontend_ports`）
frontend_ports = FrontendPortRegistry()
