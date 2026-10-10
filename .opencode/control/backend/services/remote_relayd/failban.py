"""relayd 准入封禁（protocol.md §8）。

同 IP 在 FAIL_WINDOW 内握手失败达 FAIL_LIMIT 次 → 封禁 BAN_SEC
（封禁期内 TCP 直接 RST，不进入握手）。clock 注入点=单测。
"""
from __future__ import annotations

import time

FAIL_WINDOW_SEC = 300.0
FAIL_LIMIT = 10
BAN_SEC = 600.0


class FailBan:
    """握手失败计数 + 封禁表（单事件循环内使用，无锁）。"""

    def __init__(self, clock: "object | None" = None) -> None:
        import typing
        self._clock: typing.Callable[[], float] = (  # type: ignore[no-any-reassign]
            clock if clock is not None else time.monotonic)
        self._fails: dict[str, list[float]] = {}
        self._banned: dict[str, float] = {}  # ip → 封禁到期时刻

    def is_banned(self, ip: str) -> bool:
        until = self._banned.get(ip)
        if until is None:
            return False
        if self._clock() >= until:
            del self._banned[ip]
            return False
        return True

    def note_fail(self, ip: str) -> bool:
        """记录一次握手失败; 返回是否触发封禁。"""
        now = self._clock()
        fails = [t for t in self._fails.get(ip, []) if now - t < FAIL_WINDOW_SEC]
        fails.append(now)
        self._fails[ip] = fails
        if len(fails) >= FAIL_LIMIT:
            self._banned[ip] = now + BAN_SEC
            self._fails.pop(ip, None)
            return True
        return False

    def reset(self, ip: str) -> None:
        """握手成功清零计数。"""
        self._fails.pop(ip, None)
