"""引用计数（users 文件）+ 单实例检测。

users 文件由控制台端（本模块）和 Plugin 端（plugins/lib/ref-counter.ts）
双方读写，格式严格一致（共享协议）。

格式（每行一个 PID）：
  pid=12345 start_time=1783000000
  pid=12346 start_time=1783000005

控制台端职责：
  • 启动时清洗 users（移除死 PID / start_time 不匹配的 PID 复用）
  • 周期性后台清洗（处理 opencode 被 SIGKILL 后的残留）
  • users 清洗后空 → 控制台自杀

Plugin 端职责（在 ref-counter.ts 实现，本文件不涉及）：
  • 启动时把 opencode PID 加到 users
  • 退出时（process.on exit）把 opencode PID 从 users 删
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

import logging

logger = logging.getLogger(__name__)

from config import USERS_FILE, USERS_CLEANUP_INTERVAL_SEC, EXIT_CODE_NORMAL
from services.process_lock import is_process_alive, atomic_write


@dataclass
class UserEntry:
    """users 文件一行。"""
    pid: int
    start_time: float


def _parse_users(content: str) -> list[UserEntry]:
    """解析 users 文件。容错：格式错的行跳过。"""
    entries = []
    for line in content.splitlines():
        line = line.strip()
        if not line.startswith("pid="):
            continue
        try:
            # 格式：pid=12345 start_time=1783000000
            parts = dict(p.split("=", 1) for p in line.split())
            pid = int(parts["pid"])
            start_time = float(parts.get("start_time", 0))
            entries.append(UserEntry(pid=pid, start_time=start_time))
        except (ValueError, KeyError):
            continue
    return entries


def _format_users(entries: list[UserEntry]) -> str:
    """序列化 users 文件。"""
    return "\n".join(f"pid={e.pid} start_time={e.start_time}" for e in entries) + "\n"


def read_users() -> list[UserEntry]:
    """读 users 文件。不存在返回空列表。"""
    if not USERS_FILE.exists():
        return []
    try:
        return _parse_users(USERS_FILE.read_text())
    except OSError:
        return []


def write_users(entries: list[UserEntry]) -> None:
    """原子写 users 文件。"""
    atomic_write(USERS_FILE, _format_users(entries))


def cleanup_dead_users() -> list[UserEntry]:
    """清洗 users 文件：移除死 PID。

    Returns:
        清洗后存活的 entries（也写入文件）。
    """
    entries = read_users()
    alive = [
        e for e in entries
        if is_process_alive(e.pid, e.start_time if e.start_time > 0 else None)
    ]
    if len(alive) != len(entries):
        write_users(alive)
        logger.info("users 清洗：%d → %d", len(entries), len(alive))
    return alive


def is_users_empty() -> bool:
    """users 文件是否为空（用于控制台自杀判定）。"""
    return len(cleanup_dead_users()) == 0


# ─── 周期清洗后台任务 ────────────────────────────────────


class UsersCleanupTask:
    """周期清洗 users 文件的后台任务。

    users 空时调用 shutdown_callback（控制台自杀）。
    """

    def __init__(self, shutdown_callback):
        self._shutdown_callback = shutdown_callback
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """启动后台线程。"""
        self._thread = threading.Thread(
            target=self._run, name="users-cleanup", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """停止后台线程（控制台正常退出时调用）。"""
        self._stop_event.set()

    def _run(self) -> None:
        """周期清洗 + 自杀检测。"""
        while not self._stop_event.wait(USERS_CLEANUP_INTERVAL_SEC):
            try:
                alive = cleanup_dead_users()
                if not alive:
                    logger.info("users 空，控制台自杀（exit code = %d）", EXIT_CODE_NORMAL)
                    self._shutdown_callback()
                    return
            except Exception as e:
                # 后台任务异常不能让线程死掉
                logger.warning("users 清洗异常: %s", e)
