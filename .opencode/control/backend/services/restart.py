"""控制台自重启（POST /api/system/restart）。

动机：代码更新后需要重启控制台生效；此前只能手动 kill 再拉起。
自重启按钮让用户在页面上自助完成。

POSIX 方案（延迟 1.5s 后 os.execv）：
  - 同 PID、同进程组、同环境——plugin 侧零感知
  - socket fd 因 CLOEXEC 在 exec 瞬间关闭 → TCP 短暂释放 → 新实例重绑
  - 关键陷阱：exec 不改变 PID，若不删 IPC socket 文件，新实例的
    残留自愈（connect 失败 → unlink）虽然兜得住，但显式清理更干净
    → exec 前 unlink IPC socket（Windows 管道无文件实体，无需清理）
  - MLX 子进程独立进程组（start_new_session）不受影响

Windows 方案（subprocess + os._exit，与 detect_py_deps 自举同模式）：
  - spawn 分离的 helper：轮询等旧 PID 死亡后再 exec server
    （避免新旧实例竞争单例检测导致双实例/重启失败）
  - 本进程退出（管道随进程消失，零残留）

延迟重启的原因：HTTP 响应需要先送达前端（Timer 线程 1.5s 后执行 exec，
exec 从任意线程发起都会原子替换整个进程）。

前端重启完成检测：health 路由的 boot_token（每次进程镜像启动生成新随机值，
exec 后必变；PID/start_time 在 exec 下均不变，不能作为重启信号）。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import os
import subprocess
import sys
import threading
import time

from config import EXIT_CODE_NORMAL, IS_WINDOWS, ipc_unix_socket_path

RESTART_DELAY_SEC = 1.5   # 等 HTTP 响应送达前端
WIN_HELPER_POLL_SEC = 0.2


class ConsoleRestarter:
    """控制台自重启调度器（模块级单例 console_restarter）。

    _scheduled 防重复调度：重启按钮连点只生效一次。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._scheduled = False

    def schedule(self) -> bool:
        """调度延迟重启。返回 False = 已有重启在途（重复调用）。"""
        with self._lock:
            if self._scheduled:
                return False
            self._scheduled = True
        logger.info("自重启已调度，%.1fs 后执行", RESTART_DELAY_SEC)
        threading.Timer(RESTART_DELAY_SEC, self.perform).start()
        return True

    def perform(self) -> None:
        """执行重启（单独成方法：单测 monkeypatch 本方法验证调度链路）。"""
        if not IS_WINDOWS:
            try:
                ipc_unix_socket_path().unlink(missing_ok=True)
            except OSError:
                pass
        if sys.platform == "win32":
            self._restart_windows()
        else:
            argv = [sys.executable, os.path.abspath(sys.argv[0])] + sys.argv[1:]
            logger.info("execv 重启: %s", " ".join(argv))
            os.execv(sys.executable, argv)

    @staticmethod
    def _restart_windows() -> None:
        """Windows：helper 等本进程死亡后接管，本进程立即退出。

        helper 不能直接 spawn server（会与本实例竞争单例检测），
        必须等旧 PID 消失后再 exec。
        """
        helper = (
            "import os,sys,time\n"
            "pid=int(sys.argv[1])\n"
            "while True:\n"
            "    try:\n"
            "        os.kill(pid, 0); time.sleep(" + str(WIN_HELPER_POLL_SEC) + ")\n"
            "    except OSError:\n"
            "        break\n"
            "server=sys.argv[2]\n"
            "os.execv(sys.executable, [sys.executable, server] + sys.argv[3:])\n"
        )
        argv = [sys.executable, "-c", helper,
                str(os.getpid()), os.path.abspath(sys.argv[0])] + sys.argv[1:]
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | \
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(argv, creationflags=flags,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info("Windows 重启：helper 已 spawn，本进程退出")
        os._exit(EXIT_CODE_NORMAL)


console_restarter = ConsoleRestarter()
