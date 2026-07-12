"""基于 SQLite + sqlite-vec 的向量存储（knowledge MCP server 后端）。

双表设计：
  - answers（普通 SQLite 表）：id, question, answer, type, doc_type, created_at
  - answer_vectors（vec0 虚拟表）：rowid <-> answers.id，embedding float[1024]

doc_type 区分两种知识类型（与 PentAGI 一致）：
  - "answer"：答案知识库（searcher 用 search_answer 查 / store_answer 写）
  - "memory"：执行记忆库（memorist 用 search_in_memory 查；写入由框架自动完成）

Embedding 模型：BAAI/bge-m3（1024 维，归一化输出，多语言）。
距离度量：cosine（sqlite-vec 返回 1 - cosine_similarity）。

分数阈值（基于 BGE-M3 标定，见 retrieval-strategy.md）：
  - >= 0.75：强匹配，可直接引用
  - 0.50-0.75：中等匹配，使用前需校验
  - < 0.50：弱匹配，忽略
"""
import sqlite3
import sqlite_vec
import struct
import time
from pathlib import Path
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer

EMBEDDING_DIM = 1024
DEFAULT_TOP_K = 5

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    type TEXT NOT NULL,
    doc_type TEXT NOT NULL DEFAULT 'answer',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_answers_type ON answers(type);
CREATE INDEX IF NOT EXISTS idx_answers_doc_type ON answers(doc_type);
"""


class MemoryDB:
    """向量存储：answers 表 + answer_vectors vec0 虚拟表。"""

    def __init__(self, db_path: Path, embedder: SentenceTransformer):
        self.db_path = db_path
        self.embedder = embedder
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(SCHEMA_SQL)
        self._conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS answer_vectors "
            f"USING vec0(embedding float[{EMBEDDING_DIM}] distance_metric=cosine)"
        )
        self._conn.commit()

    def _embed(self, text: str) -> bytes:
        """将文本编码为 384 维归一化向量，打包为小端序浮点数字节流。"""
        vec = self.embedder.encode(text, convert_to_numpy=True)
        return struct.pack(f"{EMBEDDING_DIM}f", *vec.tolist())

    def store(self, question: str, answer: str, type: str, doc_type: str = "answer") -> int:
        """插入一行 (question, answer, type, doc_type) 及其 question 的 embedding。

        不做去重 —— 由 LLM 在调用前判断该 answer 是否"新"。
        返回新行 id。
        """
        embedding = self._embed(question)
        cur = self._conn.execute(
            "INSERT INTO answers(question, answer, type, doc_type, created_at) VALUES (?, ?, ?, ?, ?)",
            (question, answer, type, doc_type, time.time()),
        )
        row_id = cur.lastrowid
        # lastrowid 是 int；转换为 int 以满足 vec0 rowid 的类型要求
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
        top_k: int = DEFAULT_TOP_K,
    ) -> list[dict[str, Any]]:
        """对每个查询：按 cosine 找最近的 top_k 个，按 doc_type + type（可选）过滤，再合并。

        返回至多 top_k 个去重后的结果，按跨查询的最高分排序。
        Score = 1 - distance（即 cosine 相似度）。

        参数：
          - type: 如果不为 None，按 type 硬过滤（guide/vulnerability/code/tool/other）。
                  如果为 None，跳过 type 过滤（用于 doc_type=memory 的通用查询）。
          - doc_type: "answer"（答案知识库）或 "memory"（执行记忆库）。
        """
        if not questions:
            return []

        # 构建候选集：对每个查询，取 top_k*3 行（留出余量，
        # 因为 doc_type/type 过滤会丢弃一部分）。
        per_query = max(top_k * 3, top_k)
        seen: dict[int, dict[str, Any]] = {}
        for q in questions:
            q_emb = self._embed(q)
            rows = self._conn.execute(
                "SELECT rowid, distance FROM answer_vectors "
                "WHERE embedding MATCH ? AND k = ? "
                "ORDER BY distance",
                (q_emb, per_query),
            ).fetchall()
            for row_id, distance in rows:
                score = 1.0 - float(distance)
                # 跟踪跨查询的最高分
                if row_id in seen:
                    if score > seen[row_id]["score"]:
                        seen[row_id]["score"] = score
                    continue
                seen[row_id] = {"id": int(row_id), "score": score}

        if not seen:
            return []

        # 按 id 取 answers 行，按 doc_type + type（可选）过滤
        ids = list(seen.keys())
        placeholders = ",".join("?" * len(ids))
        if type is not None:
            rows = self._conn.execute(
                f"SELECT id, question, answer, type FROM answers "
                f"WHERE id IN ({placeholders}) AND doc_type = ? AND type = ?",
                (*ids, doc_type, type),
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT id, question, answer, type FROM answers "
                f"WHERE id IN ({placeholders}) AND doc_type = ?",
                (*ids, doc_type),
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

        # 按分数降序排序，取 top_k 个
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    def close(self) -> None:
        self._conn.close()
