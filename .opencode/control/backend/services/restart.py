"""控制台自重启（POST /api/system/restart）。

动机：代码更新后需要重启控制台生效；此前只能手动 kill 再拉起。
自重启按钮让用户在页面上自助完成。

POSIX 方案（延迟 1.5s 后 os.execv）：
  - 同 PID、同进程组——plugin 侧零感知（IPC/socket 连续）
  - execv 继承当前 os.environ：运行期 load_ai_env 的 setdefault 已把启动期旧值
    固化，若不在 exec 前按 .ai_env 刷新，改配置后重启不生效
    （2026/9/22 实测：DEEPSEEK_MODEL 改文件后重启仍是旧模型）
  - socket fd 因 CLOEXEC 在 exec 瞬间关闭 → TCP 短暂释放 → 新实例重绑
  - 关键陷阱：exec 不改变 PID，若不删 IPC socket 文件，新实例的
    残留自愈（connect 失败 → unlink）虽然兜得住，但显式清理更干净
    → exec 前 unlink IPC socket（Windows 管道无文件实体，无需清理）
  - OCR 模型进程内加载：exec 后随新实例自然重新初始化

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


def _refresh_env_from_ai_env() -> None:
    """重启前把 .ai_env 的当前值刷新进 os.environ（覆盖启动期旧值）。

    execv / Windows helper 均继承当前进程环境：运行期 load_ai_env 的
    setdefault 已把旧值固化进 os.environ，不刷新则改 .ai_env 后重启不生效
    （2026/9/22 实测：DEEPSEEK_MODEL 改文件后重启仍是旧模型）。
    .ai_env 读取收口在 config_store（唯一读写方）。
    """
    from services import config_store
    for key, value in config_store.read_all().items():
        os.environ[key] = value


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
        try:
            _refresh_env_from_ai_env()
        except Exception as e:  # 刷新失败不能阻断重启（按旧环境继续）
            logger.warning("重启前 .ai_env 刷新失败: %s", e)
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
