"""BGE-M3 + BGE-Reranker 加载与推理。

迁移自 mcp-servers/embed_server.py，收口模型实例（线程安全单例）。
其他模块禁止直接 SentenceTransformer / CrossEncoder，必须通过本模块。

并发模型：
  - encode/predict 是 CPU-bound 同步调用
  - 通过 asyncio.to_thread 交给线程池，不阻塞 event loop
  - 多条管道（/embed、/rerank、graphiti 事件、memory 写入、同步搜索）
    并发到达，推理经 LockedEmbedder/LockedReranker 包装串行执行

推理串行化的构造保证（2026-09-25 重构）：
  torch/MPS 后端多线程并发推理会数据竞争——MetalShaderLibrary 的 kernel
  缓存（std::unordered_map）无锁，两线程并行进入 MPS 计算即堆损坏
  （两次 SIGSEGV 实证：崩溃瞬间双线程同处 MPS 原生代码，其一为
  MemoryDB._embed 绕锁直调裸模型）。因此串行不再依赖"每个调用点记得
  持锁"的纪律，而是下沉到访问层：get_embedder()/get_reranker() 只返回
  持锁包装，模块外不存在锁概念，绕过在结构上无路可走。

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


# ─── 线程安全包装（串行不变量的唯一落点）────────────────
#
# _infer_lock 的全部获取点收敛在两个包装方法内部（验收口径：全模块
# `with _infer_lock` 恰好 2 处）。裸模型引用不流出本模块。

_infer_lock = threading.Lock()


class LockedEmbedder:
    """SentenceTransformer 的线程安全包装：encode 内部持锁串行。

    duck-type 面与 SentenceTransformer.encode / 测试 fake 一致
    （encode(sentences, **kwargs)），消费方（MemoryDB 等）无感知替换。
    """

    __slots__ = ("_inner",)

    def __init__(self, inner: "SentenceTransformer") -> None:
        self._inner = inner

    def encode(self, sentences, **kwargs):
        with _infer_lock:
            return self._inner.encode(sentences, **kwargs)


class LockedReranker:
    """CrossEncoder 的线程安全包装：predict 内部持锁串行（语义同 LockedEmbedder）。"""

    __slots__ = ("_inner",)

    def __init__(self, inner: "CrossEncoder") -> None:
        self._inner = inner

    def predict(self, pairs, **kwargs):
        with _infer_lock:
            return self._inner.predict(pairs, **kwargs)


# ─── 单例状态（线程安全）────────────────────────────────
# 双重检查锁定（double-check）模式，避免重复加载。
# 裸引用（_embedder/_reranker）仅供本模块加载管理与就绪判断；
# 对外唯一出口是 _locked_embedder/_locked_reranker 包装。
_embedder: "SentenceTransformer | None" = None
_locked_embedder: "LockedEmbedder | None" = None
_reranker: "CrossEncoder | None" = None
_locked_reranker: "LockedReranker | None" = None
_embed_lock = threading.Lock()
_rerank_lock = threading.Lock()

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


def get_embedder() -> "LockedEmbedder":
    """延迟加载 BGE-M3（线程安全），返回线程安全包装（永不返回裸模型）。"""
    global _embedder, _locked_embedder, _models_ready
    if _locked_embedder is None:
        with _embed_lock:
            if _locked_embedder is None:
                from sentence_transformers import SentenceTransformer

                logger.info("loading %s...", EMBED_MODEL)
                _embedder = SentenceTransformer(EMBED_MODEL)
                _locked_embedder = LockedEmbedder(_embedder)
                with _models_ready_lock:
                    _models_ready = True
                logger.info("%s ready", EMBED_MODEL)
    return _locked_embedder


def get_reranker() -> "LockedReranker":
    """延迟加载 BGE-Reranker（线程安全），返回线程安全包装（永不返回裸模型）。"""
    global _reranker, _locked_reranker
    if _locked_reranker is None:
        with _rerank_lock:
            if _locked_reranker is None:
                from sentence_transformers import CrossEncoder

                logger.info("loading %s...", RERANKER_MODEL)
                _reranker = CrossEncoder(RERANKER_MODEL, max_length=512)
                _locked_reranker = LockedReranker(_reranker)
                logger.info("%s ready", RERANKER_MODEL)
    return _locked_reranker


# ─── 同步推理函数（在线程池中执行）──────────────────────
# 锁在包装内部获取，此处不再出现任何手动持锁。


def embed_sync(text: str) -> list[float]:
    """同步单文本 embed（graphiti embedder 的 to_thread 路径用）。"""
    vec = get_embedder().encode(text, convert_to_numpy=True)
    return np.asarray(vec).tolist()


def embed_batch_sync(texts: list[str]) -> list[list[float]]:
    """同步批量 embed（/embed 路由）：一次前向，返回向量列表（每个 1024 维）。"""
    vecs = get_embedder().encode(texts, convert_to_numpy=True)
    return [np.asarray(v).tolist() for v in vecs]


def rerank_sync(query: str, passages: list[str]) -> list[float]:
    """同步 rerank：输入 query + 候选文本列表，返回 score 列表。"""
    pairs = [(query, p) for p in passages]
    scores = get_reranker().predict(pairs)
    return [float(s) for s in np.asarray(scores)]


# ─── 异步包装（供路由层调用，在线程池中跑 CPU-bound）─────


async def embed_async(inputs: list[str]) -> list[list[float]]:
    """异步 embed：把同步推理交给线程池，不阻塞 event loop。"""
    return await asyncio.to_thread(embed_batch_sync, inputs)


async def rerank_async(query: str, texts: list[str]) -> list[float]:
    """异步 rerank。"""
    return await asyncio.to_thread(rerank_sync, query, texts)


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
