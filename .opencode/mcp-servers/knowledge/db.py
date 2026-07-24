"""基于 SQLite + sqlite-vec 的向量存储（knowledge MCP server 后端）。

双表设计：
  - answers（普通 SQLite 表）：id, question, answer(content), doc_type, lang, flow_id, created_at
  - answer_vectors（vec0 虚拟表）：rowid <-> answers.id，embedding float[1024]

doc_type 区分两种类型：
  - "knowledge"：知识库（search_knowledge 查 / store_knowledge 写；合并原 answer/guide/code）
  - "memory"：执行记忆库（search_in_memory 查；写入由 memory_writer_daemon 自动完成）

Embedding 目标：embed content（answer 列存储的文本），不是 question。
  question 存在 answers 表但不 embed——作为元数据供展示。

Embedding 模型：BAAI/bge-m3（1024 维，归一化输出，多语言）。
距离度量：cosine（sqlite-vec 返回 1 - cosine_similarity）。

分数阈值：
  - score < 0.2 的结果被过滤（不返回）
  - >= 0.75：强匹配，可直接引用
  - 0.50-0.75：中等匹配，使用前需校验
  - 0.20-0.50：弱匹配，仅供参考

向后兼容：旧列 type/guide_type/code_lang 仍保留在 schema 中（INDEX_SQL 建索引），
但新数据不再使用它们的有意义值（type 写 doc_type 值，guide_type 写空字符串，code_lang 写 lang 值）。
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
    doc_type TEXT NOT NULL DEFAULT 'knowledge',
    guide_type TEXT NOT NULL DEFAULT '',
    code_lang TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_answers_doc_type ON answers(doc_type);
CREATE INDEX IF NOT EXISTS idx_answers_code_lang ON answers(code_lang);
"""

MIGRATE_COLUMNS = [
    ("guide_type", "TEXT NOT NULL DEFAULT ''"),
    ("code_lang", "TEXT NOT NULL DEFAULT ''"),
    ("flow_id", "TEXT DEFAULT NULL"),
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
        col_info = {row[1]: row for row in self._conn.execute("PRAGMA table_info(answers)").fetchall()}
        columns = set(col_info.keys())
        for col_name, col_def in MIGRATE_COLUMNS:
            if col_name not in columns:
                self._conn.execute(f"ALTER TABLE answers ADD COLUMN {col_name} {col_def}")
            elif col_name == "flow_id":
                # flow_id 列已存在——检查是否允许 NULL（旧版是 NOT NULL DEFAULT ''）
                # PRAGMA table_info 第 4 列 = notnull（1 = NOT NULL）
                if col_info[col_name][3] == 1:  # notnull = 1
                    # SQLite 3.35+ 支持 DROP COLUMN
                    self._conn.execute("ALTER TABLE answers DROP COLUMN flow_id")
                    self._conn.execute("ALTER TABLE answers ADD COLUMN flow_id TEXT DEFAULT NULL")
                    self._conn.commit()
        self._conn.commit()

    def _embed(self, text: str) -> bytes:
        """将文本编码为 1024 维归一化向量，打包为小端序浮点数字节流。"""
        vec = self.embedder.encode(text, convert_to_numpy=True)
        return struct.pack(f"{EMBEDDING_DIM}f", *vec.tolist())

    def store(
        self,
        question: str,
        content: str,
        doc_type: str = "knowledge",
        lang: str = "",
        flow_id: str | None = None,
    ) -> int:
        """插入一行及其 content 的 embedding。

        embed 目标是 content（answer 列存储的文本），不是 question。
        flow_id 仅 memory 类型用（按任务隔离）；knowledge 为 None（全局共享）。
        """
        embedding = self._embed(content)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO answers(question, answer, type, doc_type, guide_type, code_lang, flow_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                # 旧列兼容：type 写 doc_type 值，guide_type 写空字符串，code_lang 写 lang 值
                (question, content, doc_type, doc_type, "", lang, flow_id, time.time()),
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
        doc_type: str = "knowledge",
        lang: str = "",
        top_k: int = DEFAULT_TOP_K,
        flow_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """对每个查询：按 cosine 找最近的，按 doc_type + lang/flow_id 过滤，再合并。

        score < SCORE_THRESHOLD 的结果被过滤（不返回）。
        flow_id 仅 doc_type=memory 且非 None 时生效（按任务隔离）；其他 doc_type 忽略 flow_id。
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

            if lang:
                conditions.append("code_lang = ?")
                params.append(lang)
            # flow_id 过滤：仅 doc_type=memory 且 flow_id 非 None 时生效（按任务隔离）
            if doc_type == "memory" and flow_id is not None:
                conditions.append("flow_id = ?")
                params.append(flow_id)

            where_clause = " AND ".join(conditions)
            rows = self._conn.execute(
                f"SELECT id, question, answer FROM answers WHERE {where_clause}",
                params,
            ).fetchall()

            results = []
            for row_id, question, answer in rows:
                entry = seen[row_id]
                results.append({
                    "id": int(row_id),
                    "question": question,
                    "answer": answer,
                    "score": round(entry["score"], 4),
                })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
