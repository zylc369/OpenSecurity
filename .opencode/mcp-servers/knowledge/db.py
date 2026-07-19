"""基于 SQLite + sqlite-vec 的向量存储（knowledge MCP server 后端）。

双表设计：
  - answers（普通 SQLite 表）：id, question, answer, type, doc_type, guide_type, code_lang, created_at
  - answer_vectors（vec0 虚拟表）：rowid <-> answers.id，embedding float[1024]

doc_type 区分四种知识类型（与 PentAGI 一致）：
  - "answer"：答案知识库（searcher 用 search_answer 查 / store_answer 写）
  - "guide"：指南知识库（searcher 用 search_guide 查 / store_guide 写）
  - "code"：代码片段库（searcher 用 search_code 查 / store_code 写）
  - "memory"：执行记忆库（memorist 用 search_in_memory 查；写入由框架自动完成）

Embedding 目标：embed content（answer/guide/code 文本），不是 question。
  对齐 PentAGI：documentloaders.NewText(anonymizedAnswer).Load() → embed 内容文本。
  question 存在 answers 表但不 embed——作为元数据供展示。

Embedding 模型：BAAI/bge-m3（1024 维，归一化输出，多语言）。
距离度量：cosine（sqlite-vec 返回 1 - cosine_similarity）。

分数阈值（对齐 PentAGI 的 0.2）：
  - score < 0.2 的结果被过滤（不返回）
  - >= 0.75：强匹配，可直接引用
  - 0.50-0.75：中等匹配，使用前需校验
  - 0.20-0.50：弱匹配，仅供参考
"""
import sqlite3
import sqlite_vec
import struct
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer

EMBEDDING_DIM = 1024
DEFAULT_TOP_K = 5
SCORE_THRESHOLD = 0.2

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    type TEXT NOT NULL,
    doc_type TEXT NOT NULL DEFAULT 'answer',
    guide_type TEXT NOT NULL DEFAULT '',
    code_lang TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_answers_type ON answers(type);
CREATE INDEX IF NOT EXISTS idx_answers_doc_type ON answers(doc_type);
CREATE INDEX IF NOT EXISTS idx_answers_guide_type ON answers(guide_type);
CREATE INDEX IF NOT EXISTS idx_answers_code_lang ON answers(code_lang);
"""

MIGRATE_COLUMNS = [
    ("guide_type", "TEXT NOT NULL DEFAULT ''"),
    ("code_lang", "TEXT NOT NULL DEFAULT ''"),
]


class MemoryDB:
    """向量存储：answers 表 + answer_vectors vec0 虚拟表。"""

    def __init__(self, db_path: Path, embedder: SentenceTransformer):
        self.db_path = db_path
        self.embedder = embedder
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False：knowledge MCP 的 db 在子线程构造（lifespan run_in_executor），
        # 但工具函数在 asyncio loop 线程调用——必须允许跨线程访问。
        # _lock 串行化所有 SQL 操作（SQLite 默认串行，多线程并发会数据损坏）。
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA_SQL)
            self._migrate_schema()
            self._conn.executescript(INDEX_SQL)
            self._conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS answer_vectors "
                f"USING vec0(embedding float[{EMBEDDING_DIM}] distance_metric=cosine)"
            )
            self._conn.commit()

    def _migrate_schema(self) -> None:
        """检查并添加缺失的列（向后兼容旧数据库）。"""
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(answers)").fetchall()}
        for col_name, col_def in MIGRATE_COLUMNS:
            if col_name not in columns:
                self._conn.execute(f"ALTER TABLE answers ADD COLUMN {col_name} {col_def}")
        self._conn.commit()

    def _embed(self, text: str) -> bytes:
        """将文本编码为 1024 维归一化向量，打包为小端序浮点数字节流。"""
        vec = self.embedder.encode(text, convert_to_numpy=True)
        return struct.pack(f"{EMBEDDING_DIM}f", *vec.tolist())

    def store(
        self,
        question: str,
        answer: str,
        type: str,
        doc_type: str = "answer",
        guide_type: str = "",
        code_lang: str = "",
    ) -> int:
        """插入一行及其 content 的 embedding。

        embed 目标是 answer（content 文本），不是 question。
        对齐 PentAGI：embed 内容文本，question 存表不 embed。
        """
        embedding = self._embed(answer)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO answers(question, answer, type, doc_type, guide_type, code_lang, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (question, answer, type, doc_type, guide_type, code_lang, time.time()),
            )
            row_id = cur.lastrowid
            self._conn.execute(
                "INSERT INTO answer_vectors(rowid, embedding) VALUES (?, ?)",
                (int(row_id), embedding),
            )
            self._conn.commit()
            return int(row_id)

    def search(
        self,
        questions: list[str],
        type: str | None = None,
        doc_type: str = "answer",
        guide_type: str = "",
        code_lang: str = "",
        top_k: int = DEFAULT_TOP_K,
    ) -> list[dict[str, Any]]:
        """对每个查询：按 cosine 找最近的，按 doc_type + type/guide_type/code_lang 过滤，再合并。

        score < SCORE_THRESHOLD 的结果被过滤（不返回）。
        """
        if not questions:
            return []

        per_query = max(top_k * 3, top_k)
        seen: dict[int, dict[str, Any]] = {}
        # embed 在 lock 外（CPU-bound，不涉及 SQL；并发安全：embedder 内部线程安全）
        q_embs = [self._embed(q) for q in questions]
        with self._lock:
            for q_emb in q_embs:
                rows = self._conn.execute(
                    "SELECT rowid, distance FROM answer_vectors "
                    "WHERE embedding MATCH ? AND k = ? "
                    "ORDER BY distance",
                    (q_emb, per_query),
                ).fetchall()
                for row_id, distance in rows:
                    score = 1.0 - float(distance)
                    if score < SCORE_THRESHOLD:
                        continue
                    if row_id in seen:
                        if score > seen[row_id]["score"]:
                            seen[row_id]["score"] = score
                        continue
                    seen[row_id] = {"id": int(row_id), "score": score}

            if not seen:
                return []

            # 构建过滤条件
            ids = list(seen.keys())
            placeholders = ",".join("?" * len(ids))
            conditions = [f"id IN ({placeholders})", "doc_type = ?"]
            params: list[Any] = [*ids, doc_type]

            if type is not None:
                conditions.append("type = ?")
                params.append(type)
            if guide_type:
                conditions.append("guide_type = ?")
                params.append(guide_type)
            if code_lang:
                conditions.append("code_lang = ?")
                params.append(code_lang)

            where_clause = " AND ".join(conditions)
            rows = self._conn.execute(
                f"SELECT id, question, answer, type FROM answers WHERE {where_clause}",
                params,
            ).fetchall()

            results = []
            for row_id, question, answer, ans_type in rows:
                entry = seen[row_id]
                results.append({
                    "id": int(row_id),
                    "question": question,
                    "answer": answer,
                    "type": ans_type,
                    "score": round(entry["score"], 4),
                })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
