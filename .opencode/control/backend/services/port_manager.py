"""端口分配 + 端口文件管理收口模块。

所有 socket.bind 和端口文件操作必须走本模块（grep 验证唯一性）。
其他模块禁止直接 socket.bind。

端口分配策略：
  • 候选端口列表（来自 config.get_port_candidates）
  • 依次尝试 bind，第一个成功就用
  • 全部失败抛 RuntimeError，控制台退出（exit code = 3）

端口文件格式（与 Plugin 端共享协议）：
  第 1 行：端口号
  第 2 行：控制台进程 PID
  第 3 行：进程启动时间戳（PID 复用防护）
"""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request

from config import PORT_FILE, BIND_HOST, EXIT_CODE_PORT_EXHAUSTED, get_port_candidates
from services.process_lock import is_process_alive, get_process_start_time, atomic_write

# /health 探测协议的身份字段值（与 routes/health.py 的 _identity 一致）
CONTROL_SERVICE_ID = "opencode-control"


def bind_port_with_fallback() -> tuple[int, "socket.socket"]:
    """尝试候选端口列表，绑定第一个可用端口。

    Returns:
        (port, sock)：sock 由调用方负责关闭或 detach。
    """
    candidates = get_port_candidates()
    for port in candidates:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            return port, sock
        except OSError:
            continue
    raise RuntimeError(
        f"端口候选 {candidates} 全部被占用（exit code = {EXIT_CODE_PORT_EXHAUSTED}）"
    )


def write_port_file(port: int, pid: int | None = None, start_time: float | None = None) -> None:
    """写端口文件（原子写）。

    pid/start_time 缺省写自己；探测到孤儿实例时传孤儿身份（孤儿接管场景）。
    """
    if pid is None:
        pid = os.getpid()
    if start_time is None:
        start_time = get_process_start_time(os.getpid()) or 0
    content = f"{port}\n{pid}\n{start_time}\n"
    atomic_write(PORT_FILE, content)
    print(f"[control] 端口文件写入 {PORT_FILE}（port={port}, pid={pid}）", flush=True)


def read_port_file() -> tuple[int, int, float] | None:
    """读端口文件。

    Returns:
        (port, pid, start_time) 或 None（文件不存在 / 格式错误）。
    """
    if not PORT_FILE.exists():
        return None
    try:
        lines = PORT_FILE.read_text().strip().split("\n")
        port = int(lines[0])
        pid = int(lines[1])
        start_time = float(lines[2]) if len(lines) > 2 else 0
        return port, pid, start_time
    except (ValueError, IndexError, OSError):
        return None


def is_control_running() -> bool:
    """检测现有控制台是否在运行。

    三重校验：端口文件存在 + PID 存活 + 启动时间匹配。
    用于步骤 3 单实例检测。
    """
    info = read_port_file()
    if info is None:
        return False
    port, pid, start_time = info
    return is_process_alive(pid, start_time if start_time > 0 else None)


def probe_live_control(timeout: float = 1.0) -> tuple[int, int, float] | None:
    """探测候选端口上是否有本体系控制台（端口文件丢失的孤儿实例）。

    遍历候选端口 GET /health，响应 JSON 含 service=="opencode-control"
    且 pid 为数字即判定为本体系控制台（200 就绪 / 503 加载中均接受，
    覆盖"孤儿正在加载模型"的场景）。

    Returns:
        (port, pid, start_time) 或 None。
    """
    for port in get_port_candidates():
        url = f"http://{BIND_HOST}:{port}/health"
        try:
            # 503（loading）会抛 HTTPError——它本身是 file-like，read() 拿响应体
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            try:
                data = json.loads(e.read().decode())
            except Exception:
                continue
        except Exception:
            continue
        if data.get("service") != CONTROL_SERVICE_ID:
            continue
        pid = data.get("pid")
        if not isinstance(pid, int):
            continue
        start_time = data.get("start_time")
        if not isinstance(start_time, (int, float)):
            start_time = 0
        return port, pid, float(start_time)
    return None


def delete_port_file() -> None:
    """删除端口文件（控制台退出时清理）。

    只删 pid 是自己的文件——防止孤儿实例退出时误删新实例的端口文件
    （端口文件丢失期间新旧实例并存的场景）。
    """
    info = read_port_file()
    if info is not None and info[1] != os.getpid():
        print(
            f"[control] 跳过删除端口文件（指向 pid={info[1]}，非本进程 {os.getpid()}）",
            flush=True,
        )
        return
    try:
        PORT_FILE.unlink()
    except FileNotFoundError:
        pass
