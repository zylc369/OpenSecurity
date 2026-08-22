"""跨平台进程工具收口模块。

控制台启动互斥：IPC bind 内核排他（services/ipc_listener.py）。

辅助函数：
  • is_process_alive(pid, start_time)：PID 存活检测 + 启动时间校验防复用
  • atomic_write(path, content)：原子写（临时文件 + rename）
  • get_process_start_time(pid)：跨平台获取进程启动时间
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


# ─── PID 存活检测（跨平台）───────────────────────────────


def is_process_alive(pid: int, start_time: float | None = None) -> bool:
    """检测 PID 是否存活。可选校验启动时间防 PID 复用。

    Args:
        pid: 目标进程 PID
        start_time: 启动时间戳（秒）。如果提供且 PID 存活但启动时间不匹配，
                    视为 PID 被复用，返回 False。

    Returns:
        True = 进程存活且（未提供 start_time 或 start_time 匹配）
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # 其他用户的进程，视为存活（不拒绝）
        return True

    # 启动时间校验（防 PID 复用）
    # 注意：start_time=0 视为"未提供"，宽容处理（不校验）
    if start_time is not None and start_time > 0:
        actual = get_process_start_time(pid)
        if actual is None:
            # 拿不到启动时间，宽容处理（视为存活）
            return True
        if abs(actual - start_time) > 1.0:
            # 启动时间相差 >1s，PID 被复用
            return False
    return True


def get_process_start_time(pid: int) -> float | None:
    """跨平台获取进程启动时间戳（秒）。

    macOS/Linux：ps -p PID -o lstart=
    Windows：PowerShell Get-Process -Id PID | Select-Object StartTime

    返回 None 表示获取失败（不应该影响存活判断）。
    """
    if sys.platform == "win32":
        return _get_start_time_windows(pid)
    return _get_start_time_unix(pid)


def _get_start_time_unix(pid: int) -> float | None:
    """Unix（mac/Linux）：解析 ps 输出。

    强制 LC_ALL=C 避免 macOS 中文 locale 返回"二 7月/28..."无法 strptime。
    """
    import time
    try:
        env = {**os.environ, "LC_ALL": "C"}
        r = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart="],
            capture_output=True, text=True, timeout=3, env=env,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return None
        # ps 输出格式："Tue Jul 28 23:15:09 2026"
        return time.mktime(time.strptime(r.stdout.strip(), "%a %b %d %H:%M:%S %Y"))
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return None


def _get_start_time_windows(pid: int) -> float | None:
    """Windows：PowerShell Get-Process。"""
    try:
        r = subprocess.run(
            ["powershell", "-Command",
             f"(Get-Process -Id {pid}).StartTime.Ticks"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return None
        # .NET Ticks 是 100ns 单位，从 0001-01-01 开始
        # 转换为 Unix 时间戳（秒）
        ticks = int(r.stdout.strip())
        return ticks / 10_000_000 - 11_644_473_600
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return None


# ─── 原子写文件 ─────────────────────────────────────────


def atomic_write(path: Path, content: str) -> None:
    """原子写文件：临时文件 + rename。

    避免写到一半崩溃导致文件损坏（POSIX rename 原子保证）。
    自动创建父目录（避免 FileNotFound）。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    os.rename(str(tmp), str(path))
