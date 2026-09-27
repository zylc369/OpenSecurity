"""控制台统一日志（LogManager，全局单例）。

背景：控制台由 plugin spawn（stdio=ignore），stdout/stderr 的 print 全部
丢弃——8/20 竞态事故时旧控制台的自杀过程无任何遗言可查，全靠旁证推断。
server.py 入口调用 LogManager.get_instance().setup() 一次，此后所有模块用
logging.getLogger(__name__) 打点。

辅助日志（独立文件）: setup_auxiliary_logger 为特定子系统（如远程链接
心跳）配置独立 logger + 独立文件——不打进 control.log，propagate 关闭
（两类日志物理分离）。
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_MAX_BYTES = 5 * 1024 * 1024   # 单文件 5MB
_BACKUP_COUNT = 3              # 保留 3 个轮转


class LogManager:
    """统一日志装配（root control.log + 子系统独立文件，全局单例）。"""

    _instance: "LogManager | None" = None
    _instance_lock = __import__("threading").Lock()

    def __new__(cls) -> "LogManager":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> "LogManager":
        return cls()

    @classmethod
    def _reset_for_tests(cls) -> None:
        with cls._instance_lock:
            cls._instance = None

    def _rotating_handler(self, path: Path) -> logging.handlers.RotatingFileHandler:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8")
        handler.setFormatter(logging.Formatter(_FORMAT))
        return handler

    def setup(self, level: int = logging.INFO) -> logging.Logger:
        """配置 root logger（文件轮转 + 镜像到 stderr）。幂等。

        Returns:
            控制台主 logger（server / services 各模块经 __name__ 挂到同一 root）。
        """
        root = logging.getLogger()
        if getattr(root, "_opensecurity_configured", False):
            return logging.getLogger("control")

        from services.config_manager import ConfigManager
        log_file = Path(ConfigManager.get_instance().data_dir) / "logs" / "control.log"

        root.setLevel(level)
        root.addHandler(self._rotating_handler(log_file))

        # stderr 镜像：手动调试（前台跑 server.py）时可见；spawn 态丢弃无副作用
        if sys.stderr is not None:
            stderr_handler = logging.StreamHandler(sys.stderr)
            stderr_handler.setFormatter(logging.Formatter(_FORMAT))
            root.addHandler(stderr_handler)

        root._opensecurity_configured = True  # type: ignore[attr-defined]
        return logging.getLogger("control")

    def setup_auxiliary(self, name: str, filename: str,
                        level: int = logging.INFO) -> logging.Logger:
        """为子系统配置独立日志文件（如 remote-link.log）。

        - 独立 RotatingFileHandler（同 control.log 的轮转参数）
        - propagate=False: 不向 root 传播（不进 control.log / 不上 stderr）
        - 幂等: 重复调用不叠加 handler
        """
        logger = logging.getLogger(name)
        if getattr(logger, "_aux_configured", False):
            return logger

        from services.config_manager import ConfigManager
        aux_file = Path(ConfigManager.get_instance().data_dir) / "logs" / filename

        logger.setLevel(level)
        logger.propagate = False
        logger.addHandler(self._rotating_handler(aux_file))

        logger._aux_configured = True  # type: ignore[attr-defined]
        return logger
