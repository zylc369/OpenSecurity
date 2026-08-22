"""跨平台文件/进程工具收口模块。

控制台启动互斥：IPC bind 内核排他（services/ipc_listener.py）。

辅助函数：
  • atomic_write(path, content)：原子写（临时文件 + rename）
  • get_process_start_time(pid)：跨平台获取进程启动时间（/health boot identity 用）
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


# ─── 进程启动时间（跨平台）────────────────────────────────


def get_process_start_time(pid: int) -> float | None:
    """跨平台获取进程启动时间戳（秒）。

    macOS/Linux：ps -p PID -o lstart=
    Windows：PowerShell Get-Process -Id PID | Select-Object StartTime

    返回 None 表示获取失败。
    """
    if sys.platform == "win32":
        return _get_start_time_windows(pid)
    return _get_start_time_unix(pid)


def _get_start_time_unix(pid: int) -> float | None:
    """Unix（mac/Linux）：解析 ps 输出。

    强制 LC_ALL=C 避免 macOS 中文 locale 返回"二 7月/28..."无法 strptime。
    """
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


def atomic_write(path: Path, content: str) -> None:
    """原子写文件：临时文件 + rename。

    避免写到一半崩溃导致文件损坏（POSIX rename 原子保证）。
    自动创建父目录（避免 FileNotFound）。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    os.rename(str(tmp), str(path))
