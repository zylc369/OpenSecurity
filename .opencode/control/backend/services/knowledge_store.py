"""knowledge 库服务：单 MemoryDB 实例 + 队列写路径 + 同步读写方法。

消费两路：
  - plugin fire-and-forget 写入（POST /api/memory/entry → 队列 → worker 线程）
  - agent 读写（POST /api/knowledge/search|store、/api/memory/search → 同步方法，
    FastAPI 线程池执行，MemoryDB._lock 串行）

单实例：全进程只有一条 MemoryDB SQLite 连接（embedder=model_loader.get_embedder()，
与 /embed 端点同源）。非法条目（question/answer/type 为空）跳过并记日志。
"""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)


import queue
import threading
from dataclasses import dataclass
from pathlib import Path

from config import DATA_DIR
from services.knowledge_db import DEFAULT_TOP_K, MemoryDB

DEFAULT_DB_PATH = Path(DATA_DIR) / "db" / "knowledge" / "knowledge.db"


def log(msg: str) -> None:
    logger.info("%s", msg)


@dataclass(frozen=True)
class MemoryEntry:
    """一条待写入的 memory 记录（plugin 工具执行结果）。"""
    question: str
    answer: str
    type: str          # 工具名，如 "bash"；拼进 question 前缀保留来源
    flow_id: str | None = None


class KnowledgeStoreService:
    """knowledge 向量库服务：惰性单例 MemoryDB + 写队列线程。

    线程安全：submit/同步方法只依赖 MemoryDB 内部 _lock；DB 实例引用的
    读写用 _db_lock 保护（重建时不并发）。
    注入点：db_path / embedder_factory（测试用 fake）。
    """

    def __init__(self, db_path: Path | None = None, embedder_factory=None) -> None:
        self._db_path = db_path or DEFAULT_DB_PATH
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
            log(f"跳过非法条目: type={entry.type!r} question空={not entry.question.strip()} answer空={not entry.answer.strip()}")
            return False
        self._queue.put(entry)
        return True

    @property
    def pending(self) -> int:
        """当前积压条数（观测用）。"""
        return self._queue.qsize()

    # ── agent 同步读写方法（FastAPI 线程池内调用）──────────

    def search_knowledge(self, questions: list[str], lang: str = "") -> dict:
        """检索知识库（doc_type=knowledge）。"""
        if not questions:
            return {"error": "questions must be non-empty", "results": [], "count": 0}
        results = self._ensure_db().search(
            questions, doc_type="knowledge", lang=lang, top_k=DEFAULT_TOP_K)
        return {"results": results, "count": len(results)}

    def store_knowledge(self, question: str, content: str, lang: str = "") -> dict:
        """存知识（存储前 anonymize 脱敏）。"""
        from services.anonymizer import anonymize
        if not question.strip() or not content.strip():
            return {"stored": False, "error": "question and content must be non-empty"}
        row_id = self._ensure_db().store(
            anonymize(question), anonymize(content), doc_type="knowledge", lang=lang)
        return {"stored": True, "id": row_id}

    def search_memory(self, questions: list[str], flow_id: str | None = None) -> dict:
        """检索执行记忆（doc_type=memory，按 flow_id 隔离）。"""
        if not questions:
            return {"error": "questions must be non-empty", "results": [], "count": 0}
        results = self._ensure_db().search(
            questions, doc_type="memory", top_k=DEFAULT_TOP_K, flow_id=flow_id)
        return {"results": results, "count": len(results)}

    # ── 内部 ──────────────────────────────────────────────

    def _ensure_db(self) -> MemoryDB:
        """惰性初始化 MemoryDB（失败抛异常，调用方按需重试语义处理）。"""
        with self._db_lock:
            if self._db is not None:
                return self._db
            if self._embedder_factory is not None:
                embedder = self._embedder_factory()
            else:
                from services import model_loader
                embedder = model_loader.get_embedder()
            self._db = MemoryDB(self._db_path, embedder)
            log(f"MemoryDB 就绪 db={self._db_path}")
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
                log(f"store 失败: {type(e).__name__}: {e}")
                with self._db_lock:
                    if self._db is not None:
                        try:
                            self._db.close()
                        except Exception:
                            pass
                        self._db = None  # 下一条重试初始化
            finally:
                self._queue.task_done()
        with self._db_lock:
            if self._db is not None:
                try:
                    self._db.close()
                except Exception:
                    pass
                self._db = None
        log("worker 退出")


# 模块级单例 + 同名委托（消费方零改动；测试可替换实例）
_service = KnowledgeStoreService()


def start() -> None:
    _service.start()


def submit_entry(entry: MemoryEntry) -> bool:
    return _service.submit(entry)


def service_instance() -> KnowledgeStoreService:
    return _service


def set_service(svc: KnowledgeStoreService) -> None:
    """测试注入入口：替换模块级单例。"""
    global _service
    _service = svc
