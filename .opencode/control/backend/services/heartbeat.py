"""opencode 心跳注册表 + 周期检测任务。

协议: opencode 插件每 10s POST /api/heartbeat {pid}；本模块维护内存表
{pid → last_seen(monotonic)}。HeartbeatTask 周期 sweep:
  • 超过 HEARTBEAT_TIMEOUT_SEC 未跳的条目 → 移除（opencode 正常退出/SIGKILL 均停跳）
  • 表空且已过启动宽限（HEARTBEAT_GRACE_SEC）→ 调 shutdown_callback（控制台自杀）

键 = 裸 pid：OS 保证同 pid 进程不同时存活。旧进程死 → 停跳 → 60s 后被 sweep；
新进程复用同 pid 时其心跳刷新 last_seen，语义仍为"该 pid 活着"，无歧义。

线程模型: record 来自 uvicorn 事件循环（async 路由），sweep 来自后台线程——
内部 Lock 保护复合操作。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from config import (
    EXIT_CODE_NORMAL,
    HEARTBEAT_GRACE_SEC,
    HEARTBEAT_SWEEP_INTERVAL_SEC,
    HEARTBEAT_TIMEOUT_SEC,
)

logger = logging.getLogger(__name__)


@dataclass
class HeartbeatEntry:
    """单个 opencode 进程的心跳记录。"""

    pid: int
    last_seen: float  # time.monotonic()


class HeartbeatRegistry:
    """心跳内存表。线程安全。"""

    def __init__(self) -> None:
        self._entries: dict[int, HeartbeatEntry] = {}
        self._lock = threading.Lock()

    def record(self, pid: int) -> None:
        """记录/刷新一个心跳。"""
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(pid)
            if entry is None:
                self._entries[pid] = HeartbeatEntry(pid=pid, last_seen=now)
                logger.info("心跳: 新 opencode 注册 pid=%d（当前 %d 个）", pid, len(self._entries))
            else:
                entry.last_seen = now

    def sweep(self) -> int:
        """移除超时未跳的条目。

        Returns:
            本轮移除的条目数。
        """
        now = time.monotonic()
        removed = []
        with self._lock:
            for pid, entry in self._entries.items():
                if now - entry.last_seen > HEARTBEAT_TIMEOUT_SEC:
                    removed.append(pid)
            for pid in removed:
                del self._entries[pid]
        for pid in removed:
            logger.info("心跳: pid=%d 超时（>%.0fs 未跳），移除", pid, HEARTBEAT_TIMEOUT_SEC)
        return len(removed)

    def active_count(self) -> int:
        """当前活跃心跳数。"""
        with self._lock:
            return len(self._entries)

    def snapshot(self) -> list[HeartbeatEntry]:
        """心跳表浅拷贝（锁内取副本，调用方迭代不持锁）。

        last_seen 保持 monotonic 时间戳语义不变; 距今秒数由消费方
        collect_opencode_processes 计算。
        """
        with self._lock:
            return [HeartbeatEntry(pid=e.pid, last_seen=e.last_seen) for e in self._entries.values()]


class HeartbeatTask:
    """周期 sweep + 空表自杀的后台任务。

    启动宽限: 表空时若距本任务启动不足 HEARTBEAT_GRACE_SEC 不自杀——
    spawn 者的控制台就绪等待 + 首跳需要时间，防"刚起就判空自杀"循环。
    """

    def __init__(self, registry: HeartbeatRegistry, shutdown_callback: Callable[[], None]) -> None:
        self._registry = registry
        self._shutdown_callback = shutdown_callback
        self._stop_event = threading.Event()
        self._start_monotonic = time.monotonic()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """启动后台线程。"""
        self._start_monotonic = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="heartbeat-sweep", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """停止后台线程（控制台正常退出时调用）。"""
        self._stop_event.set()

    def _run(self) -> None:
        """周期 sweep + 自杀检测。"""
        while not self._stop_event.wait(HEARTBEAT_SWEEP_INTERVAL_SEC):
            try:
                self._registry.sweep()
                elapsed = time.monotonic() - self._start_monotonic
                if self._registry.active_count() == 0:
                    if elapsed < HEARTBEAT_GRACE_SEC:
                        logger.info(
                            "心跳表空但处于启动宽限期（%.0fs < %.0fs），继续等待",
                            elapsed, HEARTBEAT_GRACE_SEC,
                        )
                        continue
                    logger.info("心跳表空，控制台自杀（exit code = %d）", EXIT_CODE_NORMAL)
                    self._shutdown_callback()
                    return
            except Exception as e:
                # 后台任务异常不能让线程死掉
                logger.warning("心跳 sweep 异常: %s", e)


# ─── 模块级单例 + 同名委托（消费方兼容）───────────────────
heartbeats = HeartbeatRegistry()


# ─── 心跳表 → 前端可视化（psutil 富化在本层; registry 保持纯内存）───
@dataclass
class OpencodeProcessInfo:
    """单个 opencode 进程的可视化信息（GET /api/heartbeats 条目）。"""

    pid: int
    last_seen_sec_ago: float  # 距最后心跳秒数
    alive: bool  # psutil 进程是否存在（SIGKILL 后 60s sweep 窗口内 False）
    cmdline: str | None  # 空格连接的完整命令行; AccessDenied → None
    cwd: str | None  # 工作目录; AccessDenied → None
    running_sec: float | None  # time.time() - create_time; 进程不存在 → None


def collect_opencode_processes() -> list[OpencodeProcessInfo]:
    """心跳表快照 + psutil 富化。

    边界:
      • NoSuchProcess/ZombieProcess → alive=False, 其余字段 None
        （心跳条目在 sweep 超时移除前的正常残留窗口，前端显示"疑似退出"）
      • AccessDenied → alive=True, 对应字段 None（不重试——同 pid 下轮仍会失败，
        属正常权限边界; 每轮仅 warning 一条）
    """
    import psutil

    now_mono = time.monotonic()
    now_wall = time.time()
    infos: list[OpencodeProcessInfo] = []
    for entry in heartbeats.snapshot():
        age = max(0.0, now_mono - entry.last_seen)
        alive = psutil.pid_exists(entry.pid)
        cmdline: str | None = None
        cwd: str | None = None
        running_sec: float | None = None
        if alive:
            try:
                proc = psutil.Process(entry.pid)
                if proc.status() == psutil.STATUS_ZOMBIE:
                    alive = False
                else:
                    cmdline = " ".join(proc.cmdline()) or None
                    cwd = proc.cwd()
                    running_sec = max(0.0, now_wall - proc.create_time())
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                alive = False
            except psutil.AccessDenied as e:
                logger.warning("心跳富化: pid=%d 信息受限（%s）", entry.pid, e)
            except Exception as e:  # psutil 兜底（富化失败不阻塞整体响应）
                logger.warning("心跳富化: pid=%d 异常（%s）", entry.pid, e)
        infos.append(
            OpencodeProcessInfo(
                pid=entry.pid,
                last_seen_sec_ago=round(age, 1),
                alive=alive,
                cmdline=cmdline,
                cwd=cwd,
                running_sec=round(running_sec, 1) if running_sec is not None else None,
            )
        )
    return infos
