"""控制台统一日志：写 DATA_DIR/logs/control.log。

背景：控制台由 plugin spawn（stdio=ignore），stdout/stderr 的 print 全部
丢弃——8/20 竞态事故时旧控制台的自杀过程无任何遗言可查，全靠旁证推断。
本模块在 server.py 入口调用 setup_logging() 一次，此后所有模块用
logging.getLogger(__name__) 打点（print 不再直接用于排查类信息）。
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from config import DATA_DIR

LOG_FILE = Path(DATA_DIR) / "logs" / "control.log"
_MAX_BYTES = 5 * 1024 * 1024   # 单文件 5MB
_BACKUP_COUNT = 3              # 保留 3 个轮转

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """配置 root logger（文件轮转 + 镜像到 stderr）。幂等，重复调用无副作用。

    Returns:
        控制台主 logger（server / services 各模块经 __name__ 挂到同一 root）。
    """
    root = logging.getLogger()
    if getattr(root, "_opensecurity_configured", False):
        return logging.getLogger("control")

    root.setLevel(level)
    formatter = logging.Formatter(_FORMAT)

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # stderr 镜像：手动调试（前台跑 server.py）时可见；spawn 态丢弃无副作用
    if sys.stderr is not None:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(formatter)
        root.addHandler(stderr_handler)

    root._opensecurity_configured = True  # type: ignore[attr-defined]
    return logging.getLogger("control")
