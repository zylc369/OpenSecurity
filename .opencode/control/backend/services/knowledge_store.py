"""knowledge 库服务：单 MemoryDB 实例 + 队列写路径 + 同步读写方法。

消费两路：
  - plugin fire-and-forget 写入（POST /api/memory/entry → 队列 → worker 线程）
  - agent 读写（POST /api/knowledge/search|store、/api/memory/search → 同步方法，
    FastAPI 线程池执行，MemoryDB._lock 串行 SQLite 访问）

单实例：全进程只有一条 MemoryDB SQLite 连接（embedder=ModelInferenceService.get_instance().get_embedder()
返回的 LockedEmbedder，与 /embed 端点同源）。推理线程安全由 LockedEmbedder
内部持锁串行保证（torch/MPS 并发推理堆损坏——2026-09-25 双 SIGSEGV 实证），
_memory worker 与 graphiti 事件管道并发到达亦安全。非法条目（question/answer/type
为空）跳过并记日志。
"""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)


import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from services.runtime_paths import RuntimePaths
from services.knowledge_db import EmbedderLike, MemoryDB, SearchHit

DEFAULT_DB_PATH = Path(RuntimePaths.KNOWLEDGE_DB)


@dataclass(frozen=True)
class MemoryEntry:
    """一条待写入的 memory 记录（plugin 工具执行结果）。"""
    question: str
    answer: str
    type: str          # 工具名，如 "bash"；拼进 question 前缀保留来源
    flow_id: str | None = None


@dataclass
class SearchKnowledgeResponse:
    """检索响应（error/results/count; 字段名=JSON 键名）。"""
    error: str | None = None
    results: "list[SearchHit]" = field(default_factory=list)
    count: int = 0


@dataclass
class StoreKnowledgeResponse:
    stored: bool
    id: int | None = None
    error: str | None = None


class KnowledgeStoreService:
    """（全局单例，get_instance() 获取。）"""

    _instance: "KnowledgeStoreService | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls, db_path: "str | Path | None" = None,
                embedder_factory: Callable[[], EmbedderLike] | None = None) -> "KnowledgeStoreService":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._init_once(db_path, embedder_factory)
                    cls._instance = inst
        return cls._instance

    @classmethod
    def get_instance(cls) -> "KnowledgeStoreService":
        return cls()

    @classmethod
    def _create_fresh(cls, db_path: "str | Path | None" = None,
                     embedder_factory: "Callable[[], EmbedderLike] | None" = None):
        """构造独立实例（绕过单例——测试 fake 注入用; 生产代码禁用）。"""
        inst = object.__new__(cls)
        inst._init_once(db_path, embedder_factory)
        return inst

    @classmethod
    def _force_instance(cls, inst: "KnowledgeStoreService") -> None:
        """测试注入: 强制替换单例（fake 服务注入口）。"""
        with cls._instance_lock:
            cls._instance = inst

    @classmethod
    def _reset_for_tests(cls) -> None:
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance.stop(timeout=5)
            cls._instance = None

    """knowledge 向量库服务：惰性单例 MemoryDB + 写队列线程。

    线程安全：submit/同步方法只依赖 MemoryDB 内部 _lock；DB 实例引用的
    读写用 _db_lock 保护（重建时不并发）。
    注入点：db_path / embedder_factory（测试用 fake）。
    """

    def _init_once(self, db_path: "str | Path | None" = None,
                   embedder_factory: Callable[[], EmbedderLike] | None = None) -> None:
        self._db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
        self._embedder_factory = embedder_factory  # () -> EmbedderLike；None = model_loader
        self._queue: queue.Queue[MemoryEntry | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._db: MemoryDB | None = None
        self._db_lock = threading.Lock()

    # ── 生命周期 ──────────────────────────────────────────

    def start(self) -> None:
        """启动 worker 线程（幂等；lifespan startup 调用）。

        stop 后可重启：排空可能残留的哨兵值（stop 的 join 超时场景下
        哨兵留在队列，会让新线程秒退）。
        """
        if self._thread and self._thread.is_alive():
            return
        while True:
            try:
                if self._queue.get_nowait() is None:
                    continue
            except queue.Empty:
                break
        self._thread = threading.Thread(
            target=self._run, name="knowledge-store", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """优雅收尾：发哨兵值等队列排空（测试用；生产 daemon 线程随进程退出）。"""
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=timeout)

    # ── plugin fire-and-forget 写路径 ──────────────────────

    def submit(self, entry: MemoryEntry) -> bool:
        """入队一条 memory 记录；字段非法返回 False。"""
        if not entry.question.strip() or not entry.answer.strip() or not entry.type.strip():
            logger.info(f"跳过非法条目: type={entry.type!r} question空={not entry.question.strip()} answer空={not entry.answer.strip()}")
            return False
        self._queue.put(entry)
        return True

    @property
    def pending(self) -> int:
        """当前积压条数（观测用）。"""
        return self._queue.qsize()

    # ── agent 同步读写方法（FastAPI 线程池内调用）──────────

    def search_knowledge(self, questions: list[str], lang: str = "") -> "SearchKnowledgeResponse":
        """检索知识库（doc_type=knowledge）。"""
        if not questions:
            return SearchKnowledgeResponse(error="questions must be non-empty")
        results = self._ensure_db().search(
            questions, doc_type="knowledge", lang=lang, top_k=MemoryDB.DEFAULT_TOP_K)
        return SearchKnowledgeResponse(results=results, count=len(results))

    def store_knowledge(self, question: str, content: str, lang: str = "") -> "StoreKnowledgeResponse":
        """存知识（存储前 anonymize 脱敏）。"""
        from services.anonymizer import Anonymizer
        if not question.strip() or not content.strip():
            return StoreKnowledgeResponse(stored=False, error="question and content must be non-empty")
        row_id = self._ensure_db().store(
            Anonymizer.anonymize(question), Anonymizer.anonymize(content), doc_type="knowledge", lang=lang)
        return StoreKnowledgeResponse(stored=True, id=row_id)

    def search_memory(self, questions: list[str], flow_id: str | None = None) -> "SearchKnowledgeResponse":
        """检索执行记忆（doc_type=memory，按 flow_id 隔离）。"""
        if not questions:
            return SearchKnowledgeResponse(error="questions must be non-empty")
        results = self._ensure_db().search(
            questions, doc_type="memory", top_k=MemoryDB.DEFAULT_TOP_K, flow_id=flow_id)
        return SearchKnowledgeResponse(results=results, count=len(results))

    # ── 内部 ──────────────────────────────────────────────

    def _ensure_db(self) -> MemoryDB:
        """惰性初始化 MemoryDB（失败抛异常，调用方按需重试语义处理）。"""
        with self._db_lock:
            if self._db is not None:
                return self._db
            if self._embedder_factory is not None:
                embedder = self._embedder_factory()
            else:
                from services.model_loader import ModelInferenceService
                embedder = ModelInferenceService.get_instance().get_embedder()
            self._db = MemoryDB(self._db_path, embedder)
            logger.info(f"MemoryDB 就绪 db={self._db_path}")
            return self._db

    def _run(self) -> None:
        while True:
            entry = self._queue.get()
            try:
                if entry is None:
                    break
                self._ensure_db().store(
                    question=f"[{entry.type}] {entry.question}",
                    content=entry.answer,
                    doc_type="memory",
                    flow_id=entry.flow_id,
                )
            except Exception as e:  # 单条失败不退出 worker
                logger.info(f"store 失败: {type(e).__name__}: {e}")
                with self._db_lock:
                    if self._db is not None:
                        try:
                            self._db.close()
                        except Exception as e:
                            logger.warning("坏库重建初始化失败（下一条重试）: %s", e)
                        self._db = None  # 下一条重试初始化
            finally:
                self._queue.task_done()
        with self._db_lock:
            if self._db is not None:
                try:
                    self._db.close()
                except Exception as e:
                    logger.warning("MemoryDB close 异常: %s", e)
                self._db = None
        logger.info("worker 退出")

