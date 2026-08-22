"""控制台前端 URL 解析（唯一计算点在 FrontendPortRegistry.console_url）。

消费方：routes/deps.py（summary.console_url）等。本模块保留 get_console_url
入口（委托 frontend_ports），消费方零改动。
"""
from __future__ import annotations

from services.frontend_port import frontend_ports


def get_console_url() -> str:
    """返回当前可打开的控制台前端 URL。"""
    return frontend_ports.console_url()
