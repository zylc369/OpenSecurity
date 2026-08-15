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
from dataclasses import dataclass, field

from services import tools_detector, docker_manager, config_store


@dataclass
class ScanResult:
    """全量扫描结果。"""
    agents: dict[str, list[dict]] = field(default_factory=dict)  # {agent_name: [tool_status]}
    global_: dict = field(default_factory=dict)                  # 全局资源（docker + configs）
    timestamp: float = 0


class Scanner:
    """扫描协调器（单例）。"""

    def __init__(self):
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
            agent_task = loop.run_in_executor(executor, tools_detector.scan_all)
            docker_task = loop.run_in_executor(executor, docker_manager.scan_global)
            config_task = loop.run_in_executor(executor, config_store.required_status)

            agents = await agent_task
            docker = await docker_task
            configs = await config_task

        return ScanResult(
            agents=agents,
            global_={
                "docker": docker,
                "required_configs": configs,
                "models": await self._scan_models(),
            },
            timestamp=time.time(),
        )

    async def _scan_models(self) -> list[dict]:
        """扫描模型加载状态（BGE-M3 + Reranker）。"""
        from services import model_loader
        return [
            {
                "name": "BGE-M3",
                "type": "embedder",
                "loaded": model_loader.is_models_ready(),
            },
            {
                "name": "BGE-Reranker-v2-m3",
                "type": "reranker",
                # reranker 是懒加载，没有公开的就绪状态。
                # 简化处理：和 embedder 一致（实际首次 /rerank 调用时加载）
                "loaded": model_loader.is_models_ready(),
            },
        ]


# 模块级单例
scanner = Scanner()


def get_scanner() -> Scanner:
    """获取扫描器单例。"""
    return scanner
