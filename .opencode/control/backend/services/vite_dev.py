"""开发态 vite dev server 拉起器。

问题：CONTROL_FRONTEND_DEV=1 时后端不挂载 dist/，前端由 vite dev server
（5173+）服务——但 vite 此前依赖开发者手动启动，控制台重启后前端 404。

方案：控制台启动事件里检测 dev 模式 → vite 未运行则后台拉起
（frontend 目录的 node_modules/.bin/vite）。独立进程组——控制台重启
不连带杀 vite。

运行判定（幂等，不抢占开发者手动起的实例）：
  1. 端口文件存在且端口活 → 运行中
  2. 端口文件缺失/过期但 5173-5175 任一端口活着 → 运行中（vite 被
     SIGKILL 后重启的场景：新 vite 监听了端口但可能还没写完端口文件，
     或端口文件在 DATA_DIR 被清理后丢失——以实际监听为准）
"""
from __future__ import annotations

import socket
import subprocess
from pathlib import Path

from config import DATA_DIR, OPENCODE_ROOT

VITE_PORT_FILE = Path(DATA_DIR) / ".vite-dev.port"
VITE_PROBE_PORTS = (5173, 5174, 5175)   # vite 冲突自动递增的候选段


def _port_alive(port: int) -> bool:
    """双栈探测（vite/Node 17+ 可能只监听 [::1]）。"""
    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, port), timeout=0.3):
                return True
        except OSError:
            continue
    return False


def vite_running() -> bool:
    """vite dev server 是否已在服务。

    端口文件指向的端口活 → True；否则扫 vite 默认候选段
    （防端口文件丢失/滞后导致的误判重复拉起）。
    """
    try:
        port = int(VITE_PORT_FILE.read_text().strip().splitlines()[0])
        if _port_alive(port):
            return True
    except (OSError, ValueError, IndexError):
        pass
    return any(_port_alive(p) for p in VITE_PROBE_PORTS)


def start_vite_dev() -> bool:
    """拉起 vite dev server（后台、独立进程组、cwd=frontend 目录）。

    Returns:
        True = 已在运行或本次已拉起；False = 无法拉起（frontend 依赖未装）。
    """
    if vite_running():
        return True
    if not OPENCODE_ROOT:
        return False
    frontend_dir = Path(OPENCODE_ROOT) / "control" / "frontend"
    vite_bin = frontend_dir / "node_modules" / ".bin" / "vite"
    if not vite_bin.is_file():
        return False  # 依赖未装——dev 提示页指路
    subprocess.Popen(
        [str(vite_bin)],
        cwd=str(frontend_dir),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,   # 独立进程组：控制台重启不连带杀 vite
    )
    return True
