import socket

from . import config
from . import adb
from .log import log


def find_free_host_port(start: int = config.DEFAULT_PORT_START,
                        max_tries: int = config.PORT_MAX_TRIES) -> int:
    """Check host ports starting from `start`.

    Uses socket.bind(('127.0.0.1', port)) to test availability.
    Returns first free port.
    Raises RuntimeError if all ports in range are occupied.
    """
    for port in range(start, start + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                log.info("找到空闲主机端口: %d", port)
                return port
            except OSError:
                continue
    raise RuntimeError(
        f"在范围 {start}-{start + max_tries - 1} 内未找到空闲主机端口"
    )


def find_free_android_port(serial: str,
                           start: int = config.DEFAULT_PORT_START,
                           max_tries: int = config.PORT_MAX_TRIES) -> int:
    """Check Android ports starting from `start`.

    Uses adb.check_android_port_used(serial, port) to test.
    Returns first free port.
    Raises RuntimeError if all ports in range are occupied.
    """
    for port in range(start, start + max_tries):
        if not adb.check_android_port_used(serial, port):
            log.info("找到空闲 Android 端口: %d", port)
            return port
    raise RuntimeError(
        f"在范围 {start}-{start + max_tries - 1} 内未找到空闲 Android 端口"
    )
