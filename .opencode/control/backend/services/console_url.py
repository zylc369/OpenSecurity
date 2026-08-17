"""控制台前端 URL 解析（console_url 唯一计算点）。

语义：
  发布态（非 dev mode）→ backend 端口（backend mount dist/，同源）
  开发态（is_dev_mode）→ 读 DATA_DIR/.vite-dev.port（vite 插件 listening 时
    写入实际端口，5173 被占自动跳 5174 也能感知）+ TCP 探测：
      活 → vite 端口；死（SIGKILL 残留/未启动）→ 回退 backend 端口

消费方：routes/deps.py（summary.console_url）。
"""
from __future__ import annotations

import socket

from config import PORT_FILE, is_dev_mode

VITE_PORT_FILE = PORT_FILE.parent / ".vite-dev.port"
_PROBE_TIMEOUT_SEC = 0.1


def _read_port(path) -> int | None:
    """读端口文件，容错返回 int 或 None。

    PORT_FILE 是三行格式（port/pid/start_time，见 port_manager）→ 取首行；
    .vite-dev.port 是单行端口 → 同样取首行。统一首行语义。
    """
    try:
        return int(path.read_text().strip().splitlines()[0])
    except (OSError, ValueError, IndexError):
        return None


def _port_alive(port: int) -> bool:
    """TCP 探测端口是否有监听（100ms 超时）。

    双栈探测：vite/Node 17+ 把 localhost 解析为 IPv6，只监听 [::1]；
    uvicorn 默认监听 127.0.0.1。只探一边会误判另一边的活服务为死。
    """
    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, port), timeout=_PROBE_TIMEOUT_SEC):
                return True
        except OSError:
            continue
    return False


def get_console_url() -> str:
    """返回当前可打开的控制台前端 URL。"""
    backend_port = _read_port(PORT_FILE)
    if backend_port is None:
        return "http://localhost:9776"  # 默认端口的兜底（端口文件异常时）

    if is_dev_mode():
        vite_port = _read_port(VITE_PORT_FILE)
        # vite 端口文件存在且真实监听 → 开发态前端；否则回退 backend（发布态页面或 dist）
        if vite_port and _port_alive(vite_port):
            return f"http://localhost:{vite_port}"

    return f"http://localhost:{backend_port}"
