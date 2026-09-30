"""扫描协调收口模块。

提供单一扫描入口，避免多个路由各自调底层检测函数导致并发扫描。

缓存策略：
  • 30 秒缓存，避免前端频繁刷新触发全量扫描
  • force_refresh=True 强制刷新（前端"刷新"按钮）
  • 扫描中重复请求等待结果（不重复扫描）

并发模型：
  • 工具检测是同步 IO（subprocess），用 ThreadPoolExecutor 并发
  • 全局资源（Docker）也走线程池
"""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

from services import detect_py_deps, detect_tools, docker_manager
from services.config_manager import ConfigManager, Surface
from services.detect_py_deps import PyPkgStatus
from services.detect_tools import ToolStatus
from services.docker_manager import DockerGlobal
from services.model_assets import ModelAssetStatus
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import threading


@dataclass
class GlobalResources:
    """全局资源（docker + 配置 + Python 包 + 模型）。"""
    docker: DockerGlobal = field(default_factory=DockerGlobal.unavailable)
    required_configs: "list[ConfigManager.ConfigStatusView]" = field(default_factory=list)
    python_packages: list[PyPkgStatus] = field(default_factory=list)
    models: list[ModelAssetStatus] = field(default_factory=list)


@dataclass
class ScanResult:
    """全量扫描结果。"""
    agents: dict[str, list[ToolStatus]] = field(default_factory=dict)
    global_: GlobalResources = field(default_factory=GlobalResources)
    timestamp: float = 0


class Scanner:
    """（全局单例，get_instance() 获取。）"""

    _instance: "Scanner | None" = None
    _instance_lock: "threading.Lock" = __import__("threading").Lock()  # pyright: ignore[reportAny] —— __import__ 动态模块成员，类型不可知

    def __new__(cls) -> "Scanner":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._init_once()
                    cls._instance = inst
        return cls._instance

    @classmethod
    def get_instance(cls) -> "Scanner":
        return cls()

    @classmethod
    def _reset_for_tests(cls) -> None:
        with cls._instance_lock:
            cls._instance = None

    """扫描协调器（单例）。"""

    def _init_once(self):
        self._cache: ScanResult | None = None
        self._cache_time: float = 0
        self._scanning: bool = False
        self._scanning_lock = asyncio.Lock()
        self.CACHE_TTL_SEC = 30  # 缓存有效期

    async def scan_all(self, force_refresh: bool = False) -> ScanResult:
        """全量扫描所有 agent + 全局资源。"""
        # 1. 命中缓存且未过期
        if (not force_refresh
                and self._cache
                and (time.time() - self._cache_time < self.CACHE_TTL_SEC)):
            return self._cache

        # 2. 加锁避免并发扫描
        async with self._scanning_lock:
            # 双重检查（拿到锁后可能其他协程已经完成扫描）
            if (not force_refresh
                    and self._cache
                    and (time.time() - self._cache_time < self.CACHE_TTL_SEC)):
                return self._cache

            # 3. 启动新扫描
            self._scanning = True
            try:
                result = await self._do_scan()
                self._cache = result
                self._cache_time = time.time()
                return result
            finally:
                self._scanning = False

    async def _do_scan(self) -> ScanResult:
        """实际扫描（线程池并发）。"""
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=8) as executor:
            # 并行扫描所有 agent + 全局
            agent_task = loop.run_in_executor(executor, detect_tools.ToolsScanner.get_instance().scan_all)
            docker_task = loop.run_in_executor(executor, docker_manager.DockerManager.scan_global)
            config_task = loop.run_in_executor(executor, lambda: ConfigManager.get_instance().required_status(Surface.CONFIG))
            pydeps_task = loop.run_in_executor(executor, lambda: detect_py_deps.PyDepsDetector.get_instance().scan())

            agents = await agent_task
            docker = await docker_task
            configs = await config_task
            python_packages = await pydeps_task

        return ScanResult(
            agents=agents,
            global_=GlobalResources(
                docker=docker,
                required_configs=configs,
                python_packages=python_packages,
                models=await self._scan_models(),
            ),
            timestamp=time.time(),
        )

    async def _scan_models(self) -> list[ModelAssetStatus]:
        """模型状态（收口：数据源 = services/model_assets.py，与 /api/models 同源）。"""
        from services.model_assets import ModelAssetRegistry
        return ModelAssetRegistry.get_instance().get_model_assets()

