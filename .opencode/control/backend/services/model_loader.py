"""BGE-M3 + BGE-Reranker 加载与推理。

迁移自 mcp-servers/embed_server.py，收口模型实例（线程安全单例）。
其他模块禁止直接 SentenceTransformer / CrossEncoder，必须通过本模块。

并发模型：
  - encode/predict 是 CPU-bound 同步调用
  - 通过 asyncio.to_thread 交给线程池，不阻塞 event loop
  - 多个 MCP 进程通过 HTTP 并发请求，本模块串行推理（GIL 保护）

B 方案：模型在后台线程加载，is_models_ready() 反映状态。
  /health 据此返回 503（加载中）或 200（就绪）。
"""
from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

import numpy as np

from config import EMBED_MODEL, RERANKER_MODEL

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer, CrossEncoder

# ─── 单例状态（线程安全）────────────────────────────────
# 双重检查锁定（double-check）模式，避免重复加载。
_embedder: "SentenceTransformer | None" = None
_reranker: "CrossEncoder | None" = None
_embed_lock = threading.Lock()
_rerank_lock = threading.Lock()

# 模型就绪状态：embedder 加载完成后置 True。
# 只追踪 embedder（reranker 是懒加载，首次 /rerank 才加载）。
_models_ready = False
_models_ready_lock = threading.Lock()


def is_models_ready() -> bool:
    """返回 embedder 是否就绪（供 /health 路由判断）。"""
    return _models_ready


def get_embedder() -> "SentenceTransformer":
    """延迟加载 BGE-M3（线程安全）。"""
    global _embedder, _models_ready
    if _embedder is None:
        with _embed_lock:
            if _embedder is None:
                from sentence_transformers import SentenceTransformer

                print(f"[control] loading {EMBED_MODEL}...", flush=True)
                _embedder = SentenceTransformer(EMBED_MODEL)
                with _models_ready_lock:
                    _models_ready = True
                print(f"[control] {EMBED_MODEL} ready", flush=True)
    return _embedder


def get_reranker() -> "CrossEncoder":
    """延迟加载 BGE-Reranker（线程安全）。"""
    global _reranker
    if _reranker is None:
        with _rerank_lock:
            if _reranker is None:
                from sentence_transformers import CrossEncoder

                print(f"[control] loading {RERANKER_MODEL}...", flush=True)
                _reranker = CrossEncoder(RERANKER_MODEL, max_length=512)
                print(f"[control] {RERANKER_MODEL} ready", flush=True)
    return _reranker


# ─── 同步推理函数（在线程池中执行）──────────────────────


def _do_embed(inputs: list[str]) -> list[list[float]]:
    """BGE-M3 推理：输入文本列表，返回向量列表（每个 1024 维）。"""
    model = get_embedder()
    vecs = model.encode(inputs, convert_to_numpy=True)
    return [v.tolist() for v in vecs]


def _do_rerank(query: str, texts: list[str]) -> list[float]:
    """BGE-Reranker 推理：输入 query + 候选文本列表，返回 score 列表。"""
    model = get_reranker()
    pairs = [(query, t) for t in texts]
    scores = model.predict(pairs)
    return [float(s) for s in np.asarray(scores)]


# ─── 异步包装（供路由层调用，在线程池中跑 CPU-bound）─────


async def embed_async(inputs: list[str]) -> list[list[float]]:
    """异步 embed：把同步推理交给线程池，不阻塞 event loop。"""
    return await asyncio.to_thread(_do_embed, inputs)


async def rerank_async(query: str, texts: list[str]) -> list[float]:
    """异步 rerank。"""
    return await asyncio.to_thread(_do_rerank, query, texts)


# ─── 后台预加载（B 方案核心）─────────────────────────────


def preload_embedder_background() -> None:
    """在后台线程加载 embedder。

    B 方案：uvicorn 立即启动，模型在后台线程加载。
    加载期间 /health 返回 503，加载完成后返回 200。
    """

    def _load():
        try:
            get_embedder()
        except Exception as e:
            # 加载失败打印错误，但不抛出（避免线程死掉）
            # /health 永远 503，Plugin 60s 超时后报错。
            print(f"[control] embedder 加载失败: {e}", flush=True, file=__import__("sys").stderr)

    t = threading.Thread(target=_load, name="embedder-loader", daemon=True)
    t.start()
