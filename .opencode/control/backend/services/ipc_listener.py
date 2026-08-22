"""IPC 监听器：程序间通信通道（无端口、无发现文件）。

语义（两个平台完全一致）：
  • 会合地址编译期固定（Unix: sock 路径 / Windows: 管道名），无需发现机制
  • 单例互斥 = 内核排他（Unix: bind EADDRINUSE / Windows: FIRST_PIPE_INSTANCE）
  • 并发启动的败者在 start() 内轮询等待胜者就绪后复用（不报错）——
    胜者 bind 完成前 connect 拒绝是正常启动窗口，不是故障
  • 活性判断 = connect 一次（ipc_probe_alive）
  • 残留自愈：Unix 下死 socket 文件 = connect 失败 = unlink 后重 bind

start() 返回 IpcStartStatus 枚举（调用方按语义处理，不用裸 bool 猜）：
  LISTENING         本实例成为监听者（继续运行）
  EXISTING_INSTANCE 已有活实例（应复用退出——含并发败者等到胜者的场景）
  BIND_TIMEOUT      bind 不上且等待窗口耗尽（真异常，进程不应继续）

实现：独立线程 accept IPC 连接，双向字节泵到进程内 TCP（uvicorn 监听的
浏览器通道，真实端口由 frontend_port 注册中心管理）。

线程模型（锁的边界——不是一把大锁）：
  • _lifecycle_lock 只保护 start/cleanup 的状态转移（_listener/_running
    的读写互斥）；连接服务（accept/泵）不持锁——每连接状态自包含
    （socket 对 + Event），并发连接互不阻塞
  • probe 无共享可变状态，无锁

日志：全路径经 logging 打到 DATA_DIR/logs/control.log（stdio=ignore 下
print 不可见——见 services/logging_setup.py）。

模块级单例 ipc_listener + 同名委托（消费方零改动）。
"""
from __future__ import annotations

import enum
import socket
import threading
import time

from config import (
    IS_WINDOWS,
    ipc_addr,
    ipc_unix_socket_path,
    BIND_HOST,
    IPC_BIND_WAIT_SEC,
)
from services.frontend_port import frontend_ports

_BUF = 65536

import logging

logger = logging.getLogger(__name__)


class IpcStartStatus(enum.Enum):
    """start() 的结果语义（调用方按枚举分支，不用 bool 猜）。"""

    LISTENING = "listening"                # 本实例成为监听者
    EXISTING_INSTANCE = "existing"         # 已有活实例，应复用退出
    BIND_TIMEOUT = "bind_timeout"          # 等待窗口耗尽仍无法 bind（真异常）


def ipc_probe_alive(timeout: float = 1.0) -> bool:
    """IPC 通道上是否有活着的控制台（connect 一次，通 = 活）。无共享态。"""
    if IS_WINDOWS:
        return IpcListener._pipe_connect_ok()
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(ipc_addr())
        s.close()
        return True
    except OSError:
        return False


class IpcListener:
    """IPC 监听生命周期管理（线程安全单例语义由模块级实例保证）。"""

    def __init__(self) -> None:
        self._lifecycle_lock = threading.Lock()
        self._listener: object | None = None   # Unix: socket / Windows: 管道名 str
        self._running = False

    # ── 生命周期 ──────────────────────────────────────────

    def start(self) -> IpcStartStatus:
        """启动 IPC 监听（当前平台）。

        Returns:
            LISTENING = 本实例成为监听者，继续运行；
            EXISTING_INSTANCE = 已有活实例（含并发败者等到胜者），复用退出；
            BIND_TIMEOUT = bind 失败且等待窗口耗尽，真异常。
        """
        with self._lifecycle_lock:
            if self._running:
                return IpcStartStatus.LISTENING
            logger.info("IPC start: 尝试监听 %s（platform=%s）", ipc_addr(),
                        "win32" if IS_WINDOWS else "unix")
            obj = self._do_start_platform()
            if obj is not None:
                self._listener = obj
                self._running = True
                logger.info("IPC start: bind 成功，本实例成为监听者")
                return IpcStartStatus.LISTENING
            logger.info("IPC start: bind 被占（已有实例或并发胜者），进入等待/复用流程")
            return self._wait_or_retry()

    def cleanup(self) -> None:
        """退出清理：Unix 删 socket 文件；Windows 管道无文件实体，仅关句柄。"""
        with self._lifecycle_lock:
            obj, self._listener = self._listener, None
            was_running, self._running = self._running, False
        if not was_running:
            return
        logger.info("IPC cleanup: 开始（platform=%s）", "win32" if IS_WINDOWS else "unix")
        if obj is None or IS_WINDOWS:
            return
        try:
            if hasattr(obj, "close"):
                obj.close()
        except OSError as e:
            logger.warning("IPC cleanup: 关闭监听 socket 异常: %s", e)
        try:
            ipc_unix_socket_path().unlink(missing_ok=True)
            logger.info("IPC cleanup: socket 文件已删除")
        except OSError as e:
            logger.warning("IPC cleanup: 删除 socket 文件异常: %s", e)

    # ── 并发启动的等待语义 ─────────────────────────────────

    def _wait_or_retry(self) -> IpcStartStatus:
        """bind 失败后的处置：等胜者就绪复用 / 清残留重 bind。全路径打日志。"""
        deadline = time.monotonic() + IPC_BIND_WAIT_SEC
        poll_count = 0
        while time.monotonic() < deadline:
            poll_count += 1
            if ipc_probe_alive(timeout=0.5):
                logger.info(
                    "IPC wait: 第 %d 次探测发现活实例（%.1fs 内），复用退出",
                    poll_count, IPC_BIND_WAIT_SEC - (deadline - time.monotonic()),
                )
                return IpcStartStatus.EXISTING_INSTANCE
            path = ipc_unix_socket_path()
            if not IS_WINDOWS and not path.exists():
                logger.info("IPC wait: sock 文件已消失（胜者放弃），立即重试 bind")
                break
            time.sleep(0.25)
        else:
            logger.warning(
                "IPC wait: 等待窗口 %.1fs 耗尽（探测 %d 次），尝试清残留重 bind",
                IPC_BIND_WAIT_SEC, poll_count,
            )
        # 清理可能的死残留后重 bind
        if not IS_WINDOWS:
            try:
                ipc_unix_socket_path().unlink(missing_ok=True)
            except OSError:
                pass
        obj = self._do_start_platform()
        if obj is not None:
            self._listener = obj
            self._running = True
            logger.info("IPC wait: 重 bind 成功（残留已清理），本实例成为监听者")
            return IpcStartStatus.LISTENING
        if ipc_probe_alive(timeout=0.5):
            logger.info("IPC wait: 重 bind 仍失败但探测到活实例，复用退出")
            return IpcStartStatus.EXISTING_INSTANCE
        logger.error("IPC wait: bind 失败且无活实例（窗口 %.1fs），真异常", IPC_BIND_WAIT_SEC)
        return IpcStartStatus.BIND_TIMEOUT

    # ── 平台分支 ──────────────────────────────────────────

    def _do_start_platform(self):
        """bind 当前平台 IPC 地址。成功返回监听对象，被占返回 None。"""
        if IS_WINDOWS:
            return self._start_windows()
        return self._start_unix()

    def _start_unix(self) -> socket.socket | None:
        path = ipc_unix_socket_path()
        # 父目录兜底创建（DATA_DIR 首次运行可能不存在；缺目录时 bind 报 OSError
        # 会被误判为"地址被占"）
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error("IPC bind: 创建父目录失败 %s: %s", path.parent, e)
            return None
        # 死残留自愈：connect 不通但文件存在 = 死残留，unlink
        if path.exists() and not ipc_probe_alive(timeout=0.3):
            logger.info("IPC bind: 发现死残留 %s（probe 不通），unlink 后重 bind", path)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(str(path))
            srv.listen(16)
        except OSError as e:
            logger.info("IPC bind: %s bind 失败: %s（被占，走等待/复用流程）", path, e)
            return None
        threading.Thread(target=self._unix_accept_loop, args=(srv,), daemon=True).start()
        return srv

    def _start_windows(self) -> str | None:
        """FILE_FLAG_FIRST_PIPE_INSTANCE：管道名被占（已有实例）→ None。"""
        import win32pipe
        import win32file
        import pywintypes

        try:
            handle = win32pipe.CreateNamedPipe(
                ipc_addr(),
                win32pipe.PIPE_ACCESS_DUPLEX | win32file.FILE_FLAG_FIRST_PIPE_INSTANCE,
                win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
                win32pipe.PIPE_UNLIMITED_INSTANCES,
                _BUF, _BUF,
                0, None,
            )
        except pywintypes.error as e:
            logger.info("IPC bind: 管道 %s 创建失败: %s（被占，走等待/复用流程）",
                        ipc_addr(), e)
            return None
        threading.Thread(target=self._pipe_accept_loop, args=(handle,), daemon=True).start()
        logger.info("IPC bind: 管道创建成功（FIRST_PIPE_INSTANCE）")
        return ipc_addr()

    # ── Unix accept / 泵 ──────────────────────────────────

    def _unix_accept_loop(self, srv: socket.socket) -> None:
        logger.info("IPC accept loop: 启动（unix）")
        while True:
            try:
                conn, _ = srv.accept()
            except OSError as e:
                logger.info("IPC accept loop: 退出（监听 socket 关闭: %s）", e)
                return  # 进程退出
            logger.debug("IPC accept: 新连接")
            threading.Thread(target=self._serve_conn, args=(conn,), daemon=True).start()

    def _serve_conn(self, conn: socket.socket) -> None:
        upstream = self._connect_upstream()
        if upstream is None:
            logger.error(
                "IPC serve: 上游 TCP 不可达（frontend_ports 未注册端口？），关闭连接",
            )
            conn.close()
            return
        self._bridge(
            lambda: conn.recv(_BUF),
            conn.sendall,
            conn.close,
            lambda: upstream.recv(_BUF),
            upstream.sendall,
            upstream.close,
        )

    # ── Windows accept / 泵 ───────────────────────────────

    def _pipe_accept_loop(self, first_handle) -> None:
        """阻塞等首个客户端，同时创建下一实例（否则后续客户端连不上）。"""
        import win32pipe
        handle = first_handle
        logger.info("IPC accept loop: 启动（windows pipe）")
        while True:
            try:
                win32pipe.ConnectNamedPipe(handle, None)
            except OSError as e:
                logger.info("IPC accept loop: 退出（%s）", e)
                return
            logger.debug("IPC accept: 管道客户端连入")
            try:
                nxt = win32pipe.CreateNamedPipe(
                    ipc_addr(),
                    win32pipe.PIPE_ACCESS_DUPLEX,
                    win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
                    win32pipe.PIPE_UNLIMITED_INSTANCES,
                    _BUF, _BUF,
                    0, None,
                )
            except OSError as e:
                logger.error("IPC accept: 创建下一管道实例失败: %s（本监听器停止接新连接）", e)
                nxt = None
            threading.Thread(target=self._serve_pipe, args=(handle,), daemon=True).start()
            if nxt is None:
                return
            handle = nxt

    def _serve_pipe(self, handle) -> None:
        import win32file
        upstream = self._connect_upstream()
        if upstream is None:
            logger.error("IPC serve: 上游 TCP 不可达，关闭管道连接")
            win32file.CloseHandle(handle)
            return

        def pipe_read():
            _, data = win32file.ReadFile(handle, _BUF)
            return data

        def pipe_write(data):
            win32file.WriteFile(handle, data)

        def pipe_close():
            try:
                win32file.CloseHandle(handle)
            except OSError:
                pass

        self._bridge(
            pipe_read,
            pipe_write,
            pipe_close,
            lambda: upstream.recv(_BUF),
            upstream.sendall,
            upstream.close,
        )

    @staticmethod
    def _pipe_connect_ok() -> bool:
        """Windows：CreateFile 打开管道，成功 = 服务端在监听。"""
        import win32file
        try:
            handle = win32file.CreateFile(
                ipc_addr(),
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0,
                None,
                win32file.OPEN_EXISTING,
                0,
                None,
            )
            win32file.CloseHandle(handle)
            return True
        except OSError:
            return False

    # ── 通用泵 ────────────────────────────────────────────

    @staticmethod
    def _connect_upstream() -> socket.socket | None:
        """连到 uvicorn 的浏览器 TCP（真实端口从注册中心取，顺延后自动跟随）。

        连接后必须 settimeout(None) 恢复阻塞模式：create_connection 的 timeout
        会成为 socket 默认超时，若不清除，泵线程 recv 在长请求（如事件库等
        Docker 自愈 ~36s）期间 5s 无数据即抛 timeout → 误判 EOF → 双侧断连
        （真链路 E2E 抓出：TCP 直连 36s 正常 200，泵路径 5.1s 断）。
        """
        port = frontend_ports.tcp_port()
        if port is None:
            return None
        try:
            sock = socket.create_connection((BIND_HOST, port), timeout=5)
            sock.settimeout(None)  # 关键：清除连接超时，恢复纯阻塞
            return sock
        except OSError as e:
            logger.warning("IPC upstream: 连 127.0.0.1:%d 失败: %s", port, e)
            return None

    @staticmethod
    def _bridge(read_a, write_a, close_a, read_b, write_b, close_b) -> None:
        """双向桥接 A<->B。

        方向 1（线程）：A 读 → B 写；方向 2（当前线程）：B 读 → A 写。
        任一方向结束 → 关闭两侧，另一方向随之报错退出。
        连接局部状态（socket 对 + Event），不持全局锁。
        """
        finished = threading.Event()

        def finish():
            if finished.is_set():
                return
            finished.set()
            close_a()
            close_b()

        t = threading.Thread(
            target=IpcListener._run_pump, args=(read_a, write_b, finish), daemon=True
        )
        t.start()
        IpcListener._run_pump(read_b, write_a, finish)

    @staticmethod
    def _run_pump(read_fn, write_fn, on_finish) -> None:
        """单方向泵：read_fn() 返回空即 EOF；异常/EOF 后调 on_finish() 收尾。"""
        try:
            while True:
                data = read_fn()
                if not data:
                    break
                write_fn(data)
        except OSError:
            pass
        finally:
            on_finish()


# 模块级单例 + 同名委托（消费方零改动）
ipc_listener = IpcListener()


def start_ipc_listener() -> IpcStartStatus:
    """启动 IPC 监听。返回 IpcStartStatus（见枚举定义）。"""
    return ipc_listener.start()


def cleanup_ipc_listener() -> None:
    ipc_listener.cleanup()
