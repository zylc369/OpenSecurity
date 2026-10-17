"""本机网络地址探测工具（client / gateway 共用）。

绑定 ("0.0.0.0", 0) 的 UDP socket 其 sockname 恒为 0.0.0.0（macOS 等平台），
上报/广播自身端点前需用本工具替换为真实可达地址。
"""
from __future__ import annotations

import logging
import socket
from typing import cast

logger = logging.getLogger(__name__)


def probe_lan_ip() -> "str | None":
    """探测默认出站接口的 IPv4 地址（UDP connect 技巧——不实际发包）。

    connect 仅触发内核路由决策以选择源地址；无默认路由/无网络时返回 None。
    永不抛异常。
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 53))
        ip = cast("str", probe.getsockname()[0])
        if ip and ip not in ("0.0.0.0", "127.0.0.1"):
            return ip
        return None
    except OSError as e:
        logger.debug("LAN IP 探测失败: %r", e)
        return None
    finally:
        probe.close()
