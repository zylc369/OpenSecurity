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

from services.config_manager import ConfigManager

_PROBE_TIMEOUT_SEC = 0.3


class FrontendPortRegistry:
    """前端可达端口的注册、查询与生命周期（全局单例）。"""

    _instance: "FrontendPortRegistry | None" = None
    _instance_lock: "threading.Lock" = __import__("threading").Lock()  # pyright: ignore[reportAny] —— __import__ 动态模块成员，类型不可知

    def __new__(cls) -> "FrontendPortRegistry":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._init_once()
                    cls._instance = inst
        return cls._instance

    @classmethod
    def get_instance(cls) -> "FrontendPortRegistry":
        return cls()

    @classmethod
    def _reset_for_tests(cls) -> None:
        with cls._instance_lock:
            cls._instance = None

    def _init_once(self) -> None:
        self._lock: "threading.Lock" = __import__("threading").Lock()  # pyright: ignore[reportAny] —— __import__ 动态模块成员，类型不可知
        self._tcp_port: int | None = None        # 控制台浏览器通道（bind 后注册）
        self._vite_port: int | None = None       # vite dev（IPC 上报）
        self._launch_lock: "threading.Lock" = __import__("threading").Lock()  # vite 拉起防并发双拉  # pyright: ignore[reportAny] —— __import__ 动态模块成员，类型不可知
        self._vite_proc: "subprocess.Popen[bytes] | None" = None  # 本代拉起的 vite（收割判定基准）

    @staticmethod
    def _port_alive(port: int) -> bool:
        """TCP 探测（双栈：vite/Node 17+ 可能只监听 [::1]）。无共享态，模块级纯函数。"""
        for host in ("127.0.0.1", "::1"):
            try:
                with socket.create_connection((host, port), timeout=_PROBE_TIMEOUT_SEC):
                    return True
            except OSError:
                continue
        return False


    @staticmethod
    def effective_bind_host() -> str:
        """实际绑定地址: 节点角色（CONTROL_API_KEY 已配置）→ 0.0.0.0（局域网可入）;
        否则维持 127.0.0.1（默认仅本机，安全约束）。"""
        try:
            cm = ConfigManager.get_instance()
            if (cm.get(cm.Keys.CONTROL_API_KEY) or "").strip():
                return "0.0.0.0"
        except Exception as e:  # noqa: BLE001 —— 配置读取异常 → 安全默认
            logger.warning("bind host 配置读取异常（安全默认）: %s", e)
        return ConfigManager.Protocol.BIND_HOST

    # ── 控制台 TCP 通道 ────────────────────────────────────

    def bind_and_register_tcp(self) -> "socket.socket":
        """在候选段内 bind（起点被占则顺延），成功后注册真实端口。

        Returns:
            已 bind 的 socket（由调用方负责 listen/detach）。
        Raises:
            RuntimeError: 候选段全部被占。
        """
        bind_host = self.effective_bind_host()
        last_err: OSError | None = None
        for port in self.tcp_candidates():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((bind_host, port))
                with self._lock:
                    self._tcp_port = port
                logger.info("浏览器 TCP 绑定 %s:%d（%s）", bind_host, port,
                            "节点模式-局域网开放" if bind_host == "0.0.0.0" else "仅本机")
                return sock
            except OSError as e:
                last_err = e
                continue
        raise RuntimeError(
            f"TCP 候选段 {self.tcp_candidates()[0]}-{self.tcp_candidates()[-1]} "
            f"全部被占用（exit code = {ConfigManager.Protocol.EXIT_CODE_PORT_EXHAUSTED}）：{last_err}"
        )

    @staticmethod
    def tcp_candidates() -> list[int]:
        """候选端口列表（CONTROL_TCP_PORT 环境变量可重定向起点，测试沙箱用）。"""
        return list(range(ConfigManager.get_instance().tcp_port_start(),
                           ConfigManager.get_instance().tcp_port_start()
                           + ConfigManager.Protocol.TCP_CANDIDATE_COUNT))

    def tcp_port(self) -> int | None:
        """控制台真实 TCP 端口（未 bind 返回 None）。"""
        with self._lock:
            return self._tcp_port

    def register_tcp(self, port: int, verify_alive: bool = True) -> bool:
        """直接注册 TCP 端口（测试场景：uvicorn 自行 listen 后注册）。

        生产路径走 bind_and_register_tcp；本方法供测试/特殊编排复用。
        verify_alive=True 时探测端口有监听才注册（防误注册死端口）。
        """
        if verify_alive and not self._port_alive(port):
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
        if registered and self._port_alive(registered):
            return registered
        for p in (5173, 5174, 5175):  # vite 冲突自动递增的候选段
            if self._port_alive(p):
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
        if ConfigManager.get_instance().is_dev_mode:
            vp = self.vite_port()
            if vp:
                return f"http://localhost:{vp}"
        tp = self.tcp_port() or self.tcp_candidates()[0]
        return f"http://localhost:{tp}"

    # ── vite 拉起（开发态）─────────────────────────────────

    def ensure_vite_dev(self) -> bool:
        """确保 5173 上是本代拉起的 vite（控制台启动级联重启前端）。

        收割策略: 5173 上任何非本代 Popen 的 vite（上代孤儿/exec 遗留/用户残留）
        一律 kill 重拉。理由: 控制台重启窗口恰是 vite 代理损坏高危期（后端短暂
        不可达可致 http-proxy 永久失效），TCP 存活探测不出代理健康——唯一可靠
        策略是级联重启，vite 永不带陈旧状态跨代存活。dev 工具重启代价仅页面闪连。

        Returns:
            True = 已在运行或本次已拉起；False = 无法拉起（依赖未装）。
        """
        if not ConfigManager.get_instance().opencode_root:
            return False
        with self._launch_lock:
            own_alive = (self._vite_proc is not None
                         and self._vite_proc.poll() is None)
            if own_alive and self.vite_running():
                return True
            self._reap_stale_vite()
            frontend_dir = Path(ConfigManager.get_instance().opencode_root) / "control" / "frontend"
            vite_bin = frontend_dir / "node_modules" / ".bin" / "vite"
            if not vite_bin.is_file():
                return False  # 依赖未装——dev 提示页指路
            # 日志落盘（替换原 DEVNULL——vite 层故障必须有现场可查）
            log_dir = Path(os.environ.get(
                "OPENSECURITY_HOME", str(Path.home() / "bw-security-analysis"))) / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_fh = open(log_dir / "vite-dev.log", "ab")  # noqa: SIM115 —— 生命周期=主进程, 由 OS 回收
            self._vite_proc = subprocess.Popen(  # type: ignore[assignment]
                [str(vite_bin)],
                cwd=str(frontend_dir),
                stdout=log_fh, stderr=log_fh,
                start_new_session=True,
            )
            logger.info("[frontend] vite dev 已拉起 (pid=%s, 日志=%s)",
                        self._vite_proc.pid, log_dir / "vite-dev.log")
            return True

    def _reap_stale_vite(self) -> None:
        """收割 5173 上的非本代 vite（孤儿/上代遗留）。找不到 PID 则跳过。"""
        import signal
        try:
            r = subprocess.run(["lsof", "-ti", "tcp:5173", "-sTCP:LISTEN"],
                               capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return
        own_pid = self._vite_proc.pid if self._vite_proc is not None else -1
        for pid_str in r.stdout.split():
            try:
                pid = int(pid_str)
            except ValueError:
                continue
            if pid == own_pid:
                continue  # 本代（poll 已判死——由下方重拉覆盖）
            try:
                os.kill(pid, signal.SIGTERM)
                logger.info("[frontend] 收割非本代 vite (pid=%s)", pid)
            except OSError:
                continue



