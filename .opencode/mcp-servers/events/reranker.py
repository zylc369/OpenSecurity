"""BGE-Reranker-v2-m3 CrossEncoder 客户端 — 本地 cross-encoder 模型用于搜索结果重排序。

替代 graphiti-core 的 OpenAIRerankerClient（依赖 logprobs + logit_bias，DeepSeek 不支持 logit_bias）。

工作原理：
  bge-reranker-v2-m3 是 XLMRoBERTa 架构的专用 cross-encoder（568M 参数），
  输入 (query, passage) 对，输出标量相关性分数。
  专为 reranking 训练（MS-MARCO + 多语言数据），MTEB reranking top 3。

对比 OpenAIRerankerClient：
  - OpenAI 方案：通用 LLM hack 成二分类器，用 token logprob 做连续分数
  - BGE 方案：专用模型直接输出连续分数，精度更高，速度更快（本地推理 vs API 调用）
"""
import asyncio
import logging
from typing import Any

import numpy as np

from graphiti_core.cross_encoder.client import CrossEncoderClient

logger = logging.getLogger(__name__)


class BgeRerankerClient(CrossEncoderClient):
    """使用 bge-reranker-v2-m3 本地模型实现 CrossEncoderClient 接口。

    模型延迟加载（首次 rank 调用时加载，约 3 秒），避免启动时阻塞。
    加载后常驻内存（~2GB），后续调用无加载开销。
    """

    def __init__(self):
        self._model: Any = None

    @property
    def model(self):
        """延迟加载 bge-reranker-v2-m3 模型。"""
        if self._model is None:
            from sentence_transformers import CrossEncoder

            logger.info("加载 bge-reranker-v2-m3 模型（首次调用，约 3 秒）...")
            self._model = CrossEncoder("BAAI/bge-reranker-v2-m3", max_length=512)
            logger.info("bge-reranker-v2-m3 加载完成")
        return self._model

    async def rank(
        self, query: str, passages: list[str]
    ) -> list[tuple[str, float]]:
        """对 passages 按 query 相关性排序。

        Args:
            query: 查询文本
            passages: 候选文本列表

        Returns:
            [(passage, score), ...] 按 score 降序排列。score 越高越相关。
        """
        if not passages:
            return []

        pairs = [(query, passage) for passage in passages]

        scores = await asyncio.to_thread(self.model.predict, pairs)
        scores_array = np.asarray(scores)

        results = list(zip(passages, scores_array.tolist()))
        results.sort(reverse=True, key=lambda x: x[1])
        return results
