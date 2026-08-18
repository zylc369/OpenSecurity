"""事件库服务：单 Graphiti 实例 + 写队列 + 读路径（5 种搜索）。

消费两路：
  - plugin fire-and-forget 写入/删除（POST /api/events/entry|delete → 队列）
  - agent 搜索（POST /api/events/*-search → 同步方法经跨循环桥执行）

并发模型：专用线程 + 独立事件循环——graphiti 的 async neo4j driver 绑定
创建时的循环；FastAPI 协程经 asyncio.run_coroutine_threadsafe 桥接进该循环。
初始化序列（首次使用时，专用线程内阻塞执行）：ensure Docker daemon →
ensure neo4j-events 容器（docker_manager）→ create_graphiti → build_indices。
写并发 Semaphore(10)。
"""
from __future__ import annotations

import asyncio
import queue
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any

MAX_CONCURRENT = 10
BRIDGE_TIMEOUT = 600.0  # 桥接调用上限（覆盖 daemon 冷启动 180s + bolt 90s + 初始化）


def log(msg: str) -> None:
    print(f"[event-store] {msg}", flush=True)


@dataclass(frozen=True)
class EventEntry:
    """一条待写入的事件（timestamp 由 plugin 生成保证时序）。"""
    name: str
    body: str
    source: str
    group_id: str
    timestamp: float  # ms epoch


@dataclass(frozen=True)
class DeleteGroup:
    """删除指定 group 的全部事件数据。"""
    group_id: str


class EventStoreService:
    """常驻事件库服务：专用线程 + 独立事件循环 + 无界写队列。

    线程安全：submit() 只做 queue.put；graphiti 仅专用线程触碰。
    注入点：graphiti_factory（测试 fake；生产 services.graphiti_config.create_graphiti）。
    """

    def __init__(self, graphiti_factory=None) -> None:
        self._graphiti_factory = graphiti_factory
        self._queue: queue.Queue[EventEntry | DeleteGroup | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._reader: threading.Thread | None = None
        self._loop_ready = threading.Event()   # _loop 就绪信号（消除 start 竞态）
        self._graphiti = None    # 仅专用循环内触碰
        self._loop: asyncio.AbstractEventLoop | None = None  # 专用循环（_thread_main 设置）
        self._stop_event: asyncio.Event | None = None        # 专用循环内创建
        self._tasks: list[asyncio.Task] = []                 # 专用循环内维护
        self._semaphore: asyncio.Semaphore | None = None     # 专用循环内创建

    # ── 生命周期 ──────────────────────────────────────────

    def start(self) -> None:
        """启动专用线程（幂等；lifespan startup 调用；stop 后可重启）。"""
        if self._thread and self._thread.is_alive():
            return
        # 排空残留哨兵（stop 的 join 超时场景下哨兵留在队列，会让读者线程立即退出）
        while True:
            try:
                if self._queue.get_nowait() is None:
                    continue
            except queue.Empty:
                break
        self._loop_ready.clear()
        self._thread = threading.Thread(
            target=self._thread_main, name="event-store", daemon=True)
        self._thread.start()
        self._loop_ready.wait(timeout=10)  # 等 _loop 就绪再返回（消除竞态）

    def stop(self, timeout: float = 5.0) -> None:
        """优雅收尾：哨兵值驱动排空（读者线程读到 None → 停循环 → 等队列任务完成）。"""
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=timeout)
        if self._reader:
            self._reader.join(timeout=timeout)

    # ── plugin fire-and-forget 写路径 ──────────────────────

    def submit(self, entry: EventEntry | DeleteGroup) -> bool:
        """入队；字段非法返回 False。"""
        if isinstance(entry, DeleteGroup):
            if not entry.group_id:
                log("跳过 delete 消息: 缺少 group_id")
                return False
        else:
            if not (entry.name and entry.body and entry.group_id):
                log(f"跳过非法事件: name={entry.name!r} group_id={entry.group_id!r}")
                return False
        self._queue.put(entry)
        return True

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    # ── 跨循环桥（任意线程/循环 → 专用循环）───────────────

    async def _on_loop(self, coro):
        """在专用事件循环上执行 coro（FastAPI 协程/worker 线程均可调用）。"""
        if self._loop is None or self._thread is None or not self._thread.is_alive():
            self.start()
        assert self._loop is not None
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return await asyncio.wait_for(asyncio.wrap_future(fut), timeout=BRIDGE_TIMEOUT)
        except asyncio.TimeoutError:
            fut.cancel()
            raise RuntimeError(f"事件库操作超时（{BRIDGE_TIMEOUT:.0f}s，可能卡在 Docker 冷启动）")

    async def _ensure_graphiti(self):
        """惰性初始化（专用循环内执行）：Docker → 容器 → Graphiti → 索引。

        graphiti_factory 注入（测试）时跳过基础设施 ensure——fake 场景
        无需 Docker，也保证单测不依赖真实 Docker 状态。
        """
        if self._graphiti is not None:
            return self._graphiti
        from services.graphiti_config import create_graphiti
        if self._graphiti_factory is None:
            from services import docker_manager
            docker_manager.ensure_neo4j_events_blocking()  # 阻塞（专用线程内，不卡主循环）
        factory = self._graphiti_factory or create_graphiti
        graphiti, err = factory()
        if err or graphiti is None:
            raise RuntimeError(f"create_graphiti 失败: {err}")
        await graphiti.build_indices_and_constraints()
        self._graphiti = graphiti
        log("Graphiti 就绪")
        return self._graphiti

    async def _reset_graphiti(self) -> None:
        """关旧连接并置 None（异常路径调用；必须已在专用循环内）。"""
        if self._graphiti is not None:
            try:
                await self._graphiti.close()
            except Exception:
                pass
            self._graphiti = None

    # ── worker（写路径）────────────────────────────────────

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._loop_ready.set()
        try:
            loop.run_until_complete(self._main(loop))
        finally:
            loop.close()
            self._loop = None
            log("worker 退出")

    def _reader_main(self, loop: asyncio.AbstractEventLoop) -> None:
        """读者线程：阻塞 get 队列 → call_soon_threadsafe 喂给专用循环。

        不用 run_in_executor(get)：executor 线程会永久阻塞在 get 上，
        导致进程无法退出（ThreadPoolExecutor 线程非 daemon）。
        """
        while True:
            entry = self._queue.get()
            if entry is None:
                self._queue.task_done()
                loop.call_soon_threadsafe(self._stop_event.set)
                return
            loop.call_soon_threadsafe(self._dispatch, entry)

    def _dispatch(self, entry) -> None:
        """专用循环内：为一条写消息建任务（task_done 在任务完成回调里）。"""
        semaphore = self._semaphore

        async def _run() -> None:
            try:
                await self._handle_write(entry, semaphore)
            finally:
                self._queue.task_done()

        self._tasks.append(asyncio.ensure_future(_run()))

    async def _handle_write(self, entry, semaphore: asyncio.Semaphore):
        """处理单条写消息（add_episode / delete_by_group_id）。"""
        from services.graphiti_config import CUSTOM_ENTITY_TYPES
        try:
            graphiti = await self._ensure_graphiti()
            if isinstance(entry, DeleteGroup):
                from graphiti_core.nodes import EntityNode, EpisodicNode
                async with semaphore:
                    await EntityNode.delete_by_group_id(graphiti.driver, entry.group_id)
                    await EpisodicNode.delete_by_group_id(graphiti.driver, entry.group_id)
                log(f"group deleted: {entry.group_id}")
            else:
                from graphiti_core.nodes import EpisodeType
                async with semaphore:
                    await graphiti.add_episode(
                        name=entry.name,
                        episode_body=entry.body,
                        source_description=entry.source,
                        reference_time=datetime.fromtimestamp(entry.timestamp / 1000),
                        source=EpisodeType.message,
                        group_id=entry.group_id,
                        entity_types=CUSTOM_ENTITY_TYPES,
                    )
                log(f"episode added: {entry.name}")
        except Exception as e:
            log(f"写入失败（{entry.name if isinstance(entry, EventEntry) else 'delete'}）: {type(e).__name__}: {e}")
            await self._reset_graphiti()

    async def _main(self, loop: asyncio.AbstractEventLoop):
        """专用循环主体：等 stop 事件 → 收尾（等全部写任务完成 + 关 graphiti）。"""
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        self._tasks = []
        self._stop_event = asyncio.Event()
        # 读者线程在本循环就绪后启动（_dispatch/_stop_event 已建好）
        self._reader = threading.Thread(
            target=self._reader_main, args=(loop,), name="event-store-reader", daemon=True)
        self._reader.start()
        await self._stop_event.wait()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._graphiti is not None:
            await self._reset_graphiti()

    # ── 读路径（5 种搜索；FastAPI 协程调用，经桥进专用循环）──

    async def _search(self, **kwargs) -> Any:
        """graphiti.search_ 的桥接执行（kwargs 原样透传）。

        连接类失败（容器停/daemon 死）→ 重置实例重试一次：
        重试路径的 _ensure_graphiti 会走完整 ensure 链（拉 daemon → 起容器 →
        等 bolt 握手）实现读路径自愈。写路径的自愈在 _handle_write 的 reset。
        """
        try:
            graphiti = await self._on_loop(self._ensure_graphiti())
            return await self._on_loop(graphiti.search_(**kwargs))
        except Exception:
            await self._on_loop(self._reset_graphiti())
            graphiti = await self._on_loop(self._ensure_graphiti())
            return await self._on_loop(graphiti.search_(**kwargs))

    async def search_time(self, query: str, group_id: str,
                          time_start: str = "", time_end: str = "",
                          max_results: int = 15) -> dict:
        from graphiti_core.search.search_config import (
            SearchConfig, EdgeSearchConfig, NodeSearchConfig,
            EdgeSearchMethod, NodeSearchMethod,
        )
        from graphiti_core.search.search_filters import SearchFilters, DateFilter, ComparisonOperator

        date_filters: list[DateFilter] = []
        if time_start:
            ts = datetime.fromisoformat(time_start.replace("Z", "+00:00"))
            date_filters.append(DateFilter(date=ts, comparison_operator=ComparisonOperator.greater_than_equal))
        if time_end:
            te = datetime.fromisoformat(time_end.replace("Z", "+00:00"))
            date_filters.append(DateFilter(date=te, comparison_operator=ComparisonOperator.less_than_equal))
        search_filter = SearchFilters(created_at=[date_filters]) if date_filters else None

        results = await self._search(
            query=query, group_ids=[group_id],
            config=SearchConfig(
                limit=max_results,
                edge_config=EdgeSearchConfig(
                    search_methods=[EdgeSearchMethod.bm25, EdgeSearchMethod.cosine_similarity]),
                node_config=NodeSearchConfig(
                    search_methods=[NodeSearchMethod.bm25, NodeSearchMethod.cosine_similarity]),
            ),
            search_filter=search_filter,
        )
        return self._results_payload(results, query)

    async def search_entity_relationships(self, query: str, group_id: str,
                                          center_node_uuid: str, max_depth: int = 2,
                                          node_labels: list[str] | None = None,
                                          edge_types: list[str] | None = None,
                                          max_results: int = 20) -> dict:
        """从中心实体 BFS 遍历关系。

        注意: graphiti 的 BFS 走 bfs_origin_node_uuids 参数（列表），
        center_node_uuid 只用于高级封装 search() 的 NODE_DISTANCE recipe——
        直接传给 search_() 不生效（BFS origin 为 None → 恒空）。
        """
        from graphiti_core.search.search_config import SearchConfig, EdgeSearchConfig, EdgeSearchMethod
        from graphiti_core.search.search_filters import SearchFilters

        results = await self._search(
            query=query, group_ids=[group_id],
            bfs_origin_node_uuids=[center_node_uuid],
            config=SearchConfig(
                limit=max_results,
                edge_config=EdgeSearchConfig(
                    search_methods=[EdgeSearchMethod.bfs],
                    bfs_max_depth=min(max_depth, 3)),
            ),
            search_filter=SearchFilters(node_labels=node_labels, edge_types=edge_types),
        )
        return self._results_payload(results, query)

    async def search_diverse(self, query: str, group_id: str,
                             diversity_level: str = "medium", max_results: int = 10) -> dict:
        from graphiti_core.search.search_config import (
            SearchConfig, EdgeSearchConfig, EdgeSearchMethod, EdgeReranker,
        )

        mmr_lambda = {"low": 0.3, "medium": 0.5, "high": 0.7}.get(diversity_level, 0.5)
        results = await self._search(
            query=query, group_ids=[group_id],
            config=SearchConfig(
                limit=max_results,
                edge_config=EdgeSearchConfig(
                    search_methods=[EdgeSearchMethod.bm25, EdgeSearchMethod.cosine_similarity],
                    reranker=EdgeReranker.cross_encoder, mmr_lambda=mmr_lambda),
            ),
        )
        return self._results_payload(results, query)

    async def search_episode_context(self, query: str, group_id: str,
                                     max_results: int = 10) -> dict:
        from graphiti_core.search.search_config import (
            SearchConfig, EpisodeSearchConfig, EpisodeSearchMethod,
        )

        results = await self._search(
            query=query, group_ids=[group_id],
            config=SearchConfig(
                limit=max_results,
                episode_config=EpisodeSearchConfig(search_methods=[EpisodeSearchMethod.bm25]),
            ),
        )
        return self._results_payload(results, query)

    async def search_entities(self, query: str, group_id: str, node_labels: list[str],
                              min_mentions: int = 0, edge_types: list[str] | None = None,
                              max_results: int = 25) -> dict:
        from graphiti_core.search.search_config import (
            SearchConfig, NodeSearchConfig, NodeSearchMethod,
        )
        from graphiti_core.search.search_filters import SearchFilters

        fetch_limit = max_results * 2 if min_mentions > 0 else max_results
        results = await self._search(
            query=query, group_ids=[group_id],
            config=SearchConfig(
                limit=fetch_limit,
                node_config=NodeSearchConfig(
                    search_methods=[NodeSearchMethod.bm25, NodeSearchMethod.cosine_similarity]),
            ),
            search_filter=SearchFilters(node_labels=node_labels, edge_types=edge_types),
        )
        if min_mentions > 0:
            # 原地过滤（SearchResults 是 pydantic 模型，原地赋值免重建）
            aligned = len(results.node_reranker_scores) == len(results.nodes)
            indices = [i for i, n in enumerate(results.nodes)
                       if getattr(n, "attributes", {}).get("mention_count", 0) >= min_mentions][:max_results]
            results.nodes = [results.nodes[i] for i in indices]
            if aligned:
                results.node_reranker_scores = [
                    results.node_reranker_scores[i] for i in indices]
        else:
            results.nodes = results.nodes[:max_results]
        return self._results_payload(results, query)

    # ── 结果格式化（与 MCP 工具原返回结构逐字段一致）────────

    @staticmethod
    def _results_payload(results: Any, query: str) -> dict:
        return {
            "query": query,
            "edges": [{
                "name": e.name,
                "fact": e.fact,
                "uuid": e.uuid,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "source_node_uuid": e.source_node_uuid,
                "target_node_uuid": e.target_node_uuid,
            } for e in results.edges],
            "edge_scores": list(results.edge_reranker_scores),
            "nodes": [{
                "name": n.name,
                "uuid": n.uuid,
                "labels": list(n.labels) if hasattr(n, "labels") else [],
                "summary": getattr(n, "summary", None),
                "created_at": n.created_at.isoformat() if hasattr(n, "created_at") and n.created_at else None,
            } for n in results.nodes],
            "node_scores": list(results.node_reranker_scores),
            "episodes": [{
                "source": getattr(ep, "source", None),
                "content": getattr(ep, "content", None),
                "source_description": getattr(ep, "source_description", None),
                "created_at": ep.created_at.isoformat() if hasattr(ep, "created_at") and ep.created_at else None,
                "uuid": getattr(ep, "uuid", None),
            } for ep in results.episodes],
            "episode_scores": list(results.episode_reranker_scores),
        }


def empty_result(error: str | None = None) -> dict:
    """搜索降级空返回（初始化失败/异常时端点层使用）。"""
    payload: dict[str, Any] = {"edges": [], "nodes": [], "episodes": []}
    if error:
        payload["error"] = error
    return payload


# 模块级单例 + 同名委托（消费方零改动；测试可替换实例）
_service = EventStoreService()


def start() -> None:
    _service.start()


def submit_entry(entry: EventEntry | DeleteGroup) -> bool:
    return _service.submit(entry)


def service_instance() -> EventStoreService:
    return _service


def set_service(svc: EventStoreService) -> None:
    """测试注入入口：替换模块级单例。"""
    global _service
    _service = svc
