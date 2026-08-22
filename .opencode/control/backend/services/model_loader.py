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

import logging

logger = logging.getLogger(__name__)

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

# 推理串行锁：torch/MPS 后端多线程并发推理会触发堆损坏（macOS nanov2 检测 SIGABRT），
# 所有 encode/predict 调用（/embed、/rerank、graphiti embedder、reranker）必须持锁串行。
_infer_lock = threading.Lock()

# 模型就绪状态：embedder 加载完成后置 True。
# 只追踪 embedder（reranker 是懒加载，首次 /rerank 才加载）。
_models_ready = False
_models_ready_lock = threading.Lock()


def is_models_ready() -> bool:
    """返回 embedder 是否就绪（供 /health 路由判断）。"""
    return _models_ready


def is_reranker_loaded() -> bool:
    """返回 reranker 是否已实际加载（懒加载——首次 rerank 才加载）。

    供模型板块显示真实加载态;与 embedder 的 is_models_ready 区分
    （历史上 reranker 复用 embedder 就绪标志导致"未加载却显示已加载"）。
    """
    return _reranker is not None


def get_embedder() -> "SentenceTransformer":
    """延迟加载 BGE-M3（线程安全）。"""
    global _embedder, _models_ready
    if _embedder is None:
        with _embed_lock:
            if _embedder is None:
                from sentence_transformers import SentenceTransformer

                logger.info("loading %s...", EMBED_MODEL)
                _embedder = SentenceTransformer(EMBED_MODEL)
                with _models_ready_lock:
                    _models_ready = True
                logger.info("%s ready", EMBED_MODEL)
    return _embedder


def get_reranker() -> "CrossEncoder":
    """延迟加载 BGE-Reranker（线程安全）。"""
    global _reranker
    if _reranker is None:
        with _rerank_lock:
            if _reranker is None:
                from sentence_transformers import CrossEncoder

                logger.info("loading %s...", RERANKER_MODEL)
                _reranker = CrossEncoder(RERANKER_MODEL, max_length=512)
                logger.info("%s ready", RERANKER_MODEL)
    return _reranker


# ─── 同步推理函数（在线程池中执行）──────────────────────


def _do_embed(inputs: list[str]) -> list[list[float]]:
    """BGE-M3 推理（持锁串行）：输入文本列表，返回向量列表（每个 1024 维）。"""
    model = get_embedder()
    with _infer_lock:
        vecs = model.encode(inputs, convert_to_numpy=True)
    return [v.tolist() for v in vecs]


def _do_rerank(query: str, texts: list[str]) -> list[float]:
    """BGE-Reranker 推理（持锁串行）：输入 query + 候选文本列表，返回 score 列表。"""
    model = get_reranker()
    pairs = [(query, t) for t in texts]
    with _infer_lock:
        scores = model.predict(pairs)
    return [float(s) for s in np.asarray(scores)]


# ─── 异步包装（供路由层调用，在线程池中跑 CPU-bound）─────


async def embed_async(inputs: list[str]) -> list[list[float]]:
    """异步 embed：把同步推理交给线程池，不阻塞 event loop。"""
    return await asyncio.to_thread(_do_embed, inputs)


async def rerank_async(query: str, texts: list[str]) -> list[float]:
    """异步 rerank。"""
    return await asyncio.to_thread(_do_rerank, query, texts)


def embed_sync(text: str) -> list[float]:
    """同步单文本 embed（持锁；graphiti embedder 的 to_thread 路径用）。"""
    model = get_embedder()
    with _infer_lock:
        vec = model.encode(text, convert_to_numpy=True)
    return np.asarray(vec).tolist()


def embed_batch_sync(texts: list[str]) -> list[list[float]]:
    """同步批量 embed（持锁）。"""
    model = get_embedder()
    with _infer_lock:
        vecs = model.encode(texts, convert_to_numpy=True)
    return [np.asarray(v).tolist() for v in vecs]


def rerank_sync(query: str, passages: list[str]) -> list[float]:
    """同步 rerank（持锁；graphiti cross-encoder 的 to_thread 路径用）。"""
    model = get_reranker()
    pairs = [(query, p) for p in passages]
    with _infer_lock:
        scores = model.predict(pairs)
    return [float(s) for s in np.asarray(scores)]


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
            logger.error("embedder 加载失败: %s", e)

    t = threading.Thread(target=_load, name="embedder-loader", daemon=True)
    t.start()
