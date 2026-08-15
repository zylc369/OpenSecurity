"""控制台端口发现（Python 侧唯一入口）。

所有需要访问 control/backend 的 Python 代码（embed_client、events/server、
测试脚本）都通过本模块获取控制台地址，不再各自读环境变量或端口文件。

设计：
  • 端口文件 $DATA_DIR/.opencode-control.port 是事实来源——
    每个新控制台启动时覆写（port_manager.py 原子写），永远反映最新端口。
  • 本模块只做"读取事实"：解析第一行端口号。
    PID 存活校验、引用计数、重启决策等逻辑在 Plugin 侧
    （control-manager.ts），Python 不做决策——决策收口不变。
  • 优先级：环境变量 OPENCODE_CONTROL_PORT（测试覆盖用） > 端口文件。

控制台重启换端口后：调用方在请求失败时重新调用 resolve_control()
即可拿到新地址（端口文件已被新控制台覆写）。
"""
import os
from dataclasses import dataclass
from pathlib import Path

BIND_HOST = "127.0.0.1"


@dataclass(frozen=True)
class ControlAddr:
    """控制台地址。port 和 url 同时返回（一次解析两个都有）。"""
    port: int
    url: str  # 如 http://127.0.0.1:9776


def _port_file() -> Path:
    data_dir = os.environ.get("DATA_DIR", str(Path.home() / "bw-security-analysis"))
    return Path(data_dir) / ".opencode-control.port"


def resolve_control() -> ControlAddr | None:
    """解析当前控制台地址；找不到返回 None。

    优先级：
    1. 环境变量 OPENCODE_CONTROL_PORT（测试覆盖；生产环境 Plugin 不注入）
    2. 端口文件第一行（事实来源）
    """
    port_str = os.environ.get("OPENCODE_CONTROL_PORT")
    if not (port_str and port_str.isdigit()):
        port_str = ""
        try:
            port_str = _port_file().read_text().strip().split("\n")[0]
        except OSError:
            # 文件不存在或不可读
            return None
    if not port_str.isdigit():
        return None
    port = int(port_str)
    return ControlAddr(port=port, url=f"http://{BIND_HOST}:{port}")
