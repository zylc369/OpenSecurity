"""BGE-M3 + BGE-Reranker 加载与推理（ModelInferenceService，全局单例）。

生命周期收口到 services/model_lifecycle.ManagedModel（加载单飞/事件触发
卸载/状态机），推理串行保持 LockedEmbedder/LockedReranker 的锁不变量。

并发模型（分层互斥，全进程唯一串行域）:
  • 推理 ↔ 推理: LockedEmbedder/LockedReranker 内部持 _infer_lock 串行
    （torch/MPS 后端多线程并发推理会数据竞争——MetalShaderLibrary 的
    kernel 缓存无锁，两线程并行进入 MPS 计算即堆损坏，两次 SIGSEGV
    实证。串行下沉到访问层: get_embedder() 只返回持锁包装，模块外
    不存在锁概念，绕过在结构上无路可走。）
  • 加载 ↔ 加载/卸载: ManagedModel 的 worker FIFO + 单飞
  • 卸载 ↔ 推理: unload 实现内持 _infer_lock——在途推理完成后才动模型
  • 推理时的模型引用: 调用方先经 get_embedder()（内部 ensure_loaded
    阻塞至加载完成）再 encode——encode 时刻模型必已就绪; 卸载窗口内
    已取到的引用由局部变量持有，推理安全完成后释放（快照语义）。

B 方案：模型在后台线程加载，is_models_ready() 反映状态。
  /health 据此返回 503（加载中）或 200（就绪）。

对外接口稳定性承诺（消费方零语义变化）:
  • LockedEmbedder/LockedReranker 壳常驻（_inner=None 动态绑定服务裸
    引用）——MemoryDB/graphiti 长期持有壳对象，卸载/重载不换壳
  • get_embedder()/get_reranker() 签名不变; encode/predict 返回类型不变
"""
from __future__ import annotations

import asyncio
import gc
import logging
import threading
from typing import TYPE_CHECKING, Any, Callable

import numpy as np

from services.model_lifecycle import ManagedModel

# 模块级 logger（原类体绑定导致方法内裸名 NameError——类命名空间不在方法名字查找链）
logger = logging.getLogger(__name__ + ".ModelInferenceService")

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer, CrossEncoder


class ModelInferenceService:
    """BGE-M3 + BGE-Reranker 推理服务（远程路由 + 本地生命周期，全局单例）。"""

    _instance: "ModelInferenceService | None" = None
    _instance_lock = threading.Lock()

    # ─── 单例模板 ─────────────────────────────────────────

    def __new__(cls) -> "ModelInferenceService":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._init_once()
                    cls._instance = inst
        return cls._instance

    @classmethod
    def get_instance(cls) -> "ModelInferenceService":
        return cls()

    @classmethod
    def _reset_for_tests(cls) -> None:
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance._shutdown_for_tests()
            cls._instance = None

    def _shutdown_for_tests(self) -> None:
        """测试重置收尾: 卸载两模型（还内存）。"""
        try:
            self._embedder_managed.release()
        except Exception as e:  # noqa: BLE001 —— 释放失败留痕（内存可能未回收）
            logger.warning("embedder 释放异常: %s", e)
        try:
            self._reranker_managed.release()
        except Exception as e:  # noqa: BLE001 —— 释放失败留痕（内存可能未回收）
            logger.warning("reranker 释放异常: %s", e)

    def _init_once(self) -> None:
        # 裸引用（_embedder/_reranker）仅在 ManagedModel worker 线程写
        # （load 设置 / unload 清空）; 读方动态查找（壳 encode 路径）。
        self._embedder: "SentenceTransformer | None" = None
        self._reranker: "CrossEncoder | None" = None
        self._locked_embedder: ModelInferenceService.LockedEmbedder | None = None
        self._locked_reranker: ModelInferenceService.LockedReranker | None = None
        self._embed_lock = threading.Lock()
        self._rerank_lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._embedder_managed = ManagedModel(
            name="bge-m3", load_fn=self._load_embedder_impl,
            unload_fn=self._unload_embedder_impl)
        self._reranker_managed = ManagedModel(
            name="bge-reranker-v2-m3", load_fn=self._load_reranker_impl,
            unload_fn=self._unload_reranker_impl)

    # ─── 线程安全包装（串行不变量的唯一落点）────────────────

    class LockedEmbedder:
        """SentenceTransformer 的线程安全包装：encode 内部持锁串行。

        _inner=None 时动态绑定服务的 _embedder（壳常驻，卸载/重载不换壳——
        MemoryDB/graphiti 持有的壳引用终身有效）;
        _inner 非 None 为测试注入模式（fake 直连）。
        duck-type 面与 SentenceTransformer.encode / 测试 fake 一致。
        """

        __slots__ = ("_inner",)

        def __init__(self, inner: "SentenceTransformer | None" = None) -> None:
            self._inner = inner

        def encode(self, sentences: str | list[str], **kwargs: Any):
            svc = ModelInferenceService.get_instance()
            if self._inner is not None:  # 测试注入直通（fake 直连，不经路由）
                with svc._infer_lock:
                    return self._inner.encode(sentences, **kwargs)
            return svc._route_encode(sentences, kwargs)

    class LockedReranker:
        """CrossEncoder 的线程安全包装: predict 经远程路由（失败 fallback 本地锁串行）。

        _inner 非 None 为测试注入模式（fake 直连）。
        """

        __slots__ = ("_inner",)

        def __init__(self, inner: "CrossEncoder | None" = None) -> None:
            self._inner = inner

        def predict(self, pairs: list[tuple[str, str]], **kwargs: Any):
            svc = ModelInferenceService.get_instance()
            if self._inner is not None:  # 测试注入直通
                with svc._infer_lock:
                    return self._inner.predict(pairs, **kwargs)
            return svc._route_predict(pairs, kwargs)

    # ─── 模型名（ConfigManager 协议常量）───────────────────

    @property
    def embed_model(self) -> str:
        from services.config_manager import ConfigManager
        return ConfigManager.Protocol.EMBED_MODEL

    @property
    def reranker_model(self) -> str:
        from services.config_manager import ConfigManager
        return ConfigManager.Protocol.RERANKER_MODEL

    # ─── 生命周期原语（ManagedModel worker 内执行）──────────

    def _load_embedder_impl(self) -> None:
        """加载 BGE-M3（ManagedModel worker 内执行）。"""
        from sentence_transformers import SentenceTransformer
        logger.info("loading %s...", self.embed_model)
        self._embedder = SentenceTransformer(self.embed_model)
        logger.info("%s ready", self.embed_model)

    def _unload_embedder_impl(self) -> None:
        """卸载 BGE-M3。持 _infer_lock: 等在途推理完成（卸载排队语义）。"""
        with self._infer_lock:
            self._embedder = None
            gc.collect()
        logger.info("%s unloaded", self.embed_model)

    def _load_reranker_impl(self) -> None:
        """加载 BGE-Reranker（ManagedModel worker 内执行）。"""
        from sentence_transformers import CrossEncoder
        logger.info("loading %s...", self.reranker_model)
        self._reranker = CrossEncoder(self.reranker_model, max_length=512)
        logger.info("%s ready", self.reranker_model)

    def _unload_reranker_impl(self) -> None:
        """卸载 BGE-Reranker（语义同 _unload_embedder_impl）。"""
        with self._infer_lock:
            self._reranker = None
            gc.collect()
        logger.info("%s unloaded", self.reranker_model)

    # ─── 远程路由 + 请求级 fallback ────────────────────────
    # 对 remote_link 的引用全部函数内延迟 import（循环依赖防护: remote_link
    # 的编排也要调本服务的预热/卸载）。

    def _use_remote(self) -> bool:
        """当前请求是否路由远程（remote_link 状态机快照; 异常回落本地）。"""
        try:
            from services.remote_link import RemoteLinkService
            return RemoteLinkService.get_instance().should_use_remote()
        except Exception:  # noqa: BLE001 —— remote_link 未就绪/异常 → 本地兜底
            return False

    def _note_remote_failure(self, description: str) -> None:
        """请求级失败反馈状态机（加速降级判定）。"""
        try:
            from services.remote_link import RemoteLinkService
            RemoteLinkService.get_instance().note_request_failure(description)
        except Exception as e:  # noqa: BLE001
            logger.warning("note_request_failure 通知失败: %s", e)

    def _remote_client(self):
        """获取共享远程客户端（remote_link 持有; 配置热重载时重建）。"""
        from services.remote_link import RemoteLinkService
        return RemoteLinkService.get_instance().get_client()

    @staticmethod
    def _texts_to_list(sentences: str | list[str]) -> list[str]:
        """输入归一为文本列表（str → 单元素）。"""
        if isinstance(sentences, str):
            return [sentences]
        return list(sentences)

    def _route_encode(self, sentences: str | list[str], kwargs: dict[str, Any]):
        """embed 路由: 远程优先（失败 fallback 本地，HOLD 语义=懒加载阻塞）。"""
        if self._use_remote():
            from services.remote_client import RemoteUnavailable
            try:
                vecs = self._remote_client().embed(self._texts_to_list(sentences))
                arr = np.asarray(vecs, dtype=np.float32)
                # str 输入返回 1D（与 SentenceTransformer.encode duck-type 一致）
                return arr[0] if isinstance(sentences, str) else arr
            except RemoteUnavailable as e:
                self._note_remote_failure(f"embed: {e}")
                logger.warning("远程 embed 失败，fallback 本地: %s", e)
        # 本地路径（含 fallback）: 锁内读引用——ensure_loaded 返回与拿锁之间模型
        # 可能被卸载线程清空（稳定期 Timer），锁外读会 AttributeError。锁内 None
        # → 有界重试。
        for _attempt in range(3):
            self._embedder_managed.ensure_loaded()
            with self._infer_lock:
                target = self._embedder
                if target is not None:
                    return target.encode(sentences, **kwargs)
        raise RuntimeError("embedder 竞态重试耗尽（连续卸载窗口内被清空）")

    def _route_predict(self, pairs: list[tuple[str, str]], kwargs: dict[str, Any]):
        """rerank 路由（语义同 _route_encode）。"""
        if self._use_remote():
            from services.remote_client import RemoteUnavailable
            try:
                query = pairs[0][0] if pairs else ""
                texts = [p[1] for p in pairs]
                scores = self._remote_client().rerank(query, texts)
                return np.asarray(scores, dtype=np.float32)
            except RemoteUnavailable as e:
                self._note_remote_failure(f"rerank: {e}")
                logger.warning("远程 rerank 失败，fallback 本地: %s", e)
        for _attempt in range(3):
            self._reranker_managed.ensure_loaded()
            with self._infer_lock:
                target = self._reranker
                if target is not None:
                    return target.predict(pairs, **kwargs)
        raise RuntimeError("reranker 竞态重试耗尽（连续卸载窗口内被清空）")

    # ─── 公开 API ─────────────────────────────────────────

    def is_models_ready(self) -> bool:
        """模型服务是否就绪（/health 判断）。远程模式: 远程即服务。"""
        if self._use_remote():
            return True
        return self._embedder_managed.is_loaded()

    def is_reranker_loaded(self) -> bool:
        """reranker 是否已实际加载（懒加载——首次 rerank 才加载）。"""
        return self._reranker_managed.is_loaded()

    def embedder_status(self):
        """embedder 生命周期快照（远程 TAB / 模型页）。"""
        return self._embedder_managed.status()

    def reranker_status(self):
        """reranker 生命周期快照。"""
        return self._reranker_managed.status()

    def get_embedder(self) -> "ModelInferenceService.LockedEmbedder":
        """获取 BGE-M3 线程安全包装（线程安全; 远程态不触发本地加载）。

        壳常驻: 首次调用创建，此后卸载/重载不换壳（消费方长期持有安全）。
        """
        if self._locked_embedder is None:
            with self._embed_lock:
                if self._locked_embedder is None:
                    self._locked_embedder = self.LockedEmbedder()  # inner=None 动态绑定
        if not self._use_remote():
            self._embedder_managed.ensure_loaded()
        return self._locked_embedder

    def get_reranker(self) -> "ModelInferenceService.LockedReranker":
        """获取 BGE-Reranker 线程安全包装（远程态不触发本地加载）。"""
        if self._locked_reranker is None:
            with self._rerank_lock:
                if self._locked_reranker is None:
                    self._locked_reranker = self.LockedReranker()  # inner=None 动态绑定
        if not self._use_remote():
            self._reranker_managed.ensure_loaded()
        return self._locked_reranker

    def release_all_local(self) -> None:
        """事件触发卸载 embedder + reranker（远程恢复后释放本地内存）。

        同步阻塞（卸载排队等在途推理）——调用方应在后台线程。
        """
        self._embedder_managed.release()
        self._reranker_managed.release()

    def preload_all_models_background(self) -> None:
        """后台线程预热三模型（远程降级 / 节点模式用）。"""
        def _warm():
            try:
                self._embedder_managed.ensure_loaded()
                self._reranker_managed.ensure_loaded()
                from services.ocr_service import OcrService
                OcrService.get_instance().warm_up_sync()
            except Exception:  # noqa: BLE001 —— 预热失败不致命（懒加载路径兜底）
                logger.exception("模型预热失败（懒加载路径兜底）")

        threading.Thread(target=_warm, name="model-preloader", daemon=True).start()

    # ─── 推理 API（同步在线程池执行; async 为路由层包装）────

    def embed_sync(self, text: str) -> list[float]:
        """同步单文本 embed（graphiti embedder 的 to_thread 路径用）。"""
        vec = self.get_embedder().encode(text, convert_to_numpy=True)
        return [float(x) for x in np.asarray(vec).ravel()]  # 1D 契约；numpy stub 的 tolist 保守为嵌套

    def embed_batch_sync(self, texts: list[str]) -> list[list[float]]:
        """同步批量 embed（/embed 路由）：一次前向，返回向量列表（每个 1024 维）。"""
        vecs = self.get_embedder().encode(texts, convert_to_numpy=True)
        return [np.asarray(v).tolist() for v in vecs]

    def rerank_sync(self, query: str, passages: list[str]) -> list[float]:
        """同步 rerank：输入 query + 候选文本列表，返回 score 列表。"""
        pairs = [(query, p) for p in passages]
        scores = self.get_reranker().predict(pairs)
        return [float(s) for s in np.asarray(scores)]

    async def embed_async(self, inputs: list[str]) -> list[list[float]]:
        """异步 embed：把同步推理交给线程池，不阻塞 event loop。"""
        return await asyncio.to_thread(self.embed_batch_sync, inputs)

    async def rerank_async(self, query: str, texts: list[str]) -> list[float]:
        """异步 rerank。"""
        return await asyncio.to_thread(self.rerank_sync, query, texts)

    # ─── 后台预加载（B 方案核心）────────────────────────────

    def preload_embedder_background(self) -> None:
        """在后台线程加载 embedder（B 方案: uvicorn 立即启动，模型后台加载）。"""
        def _load():
            try:
                self.get_embedder()
            except Exception as e:  # noqa: BLE001
                # 加载失败不抛出（避免线程死掉）; /health 永远 503，Plugin 60s 超时后报错
                logger.error("embedder 加载失败: %s", e)

        threading.Thread(target=_load, name="embedder-loader", daemon=True).start()
