"""BGE-Reranker-v2-m3 CrossEncoder — 本地 cross-encoder 模型用于搜索结果重排序。

替代 graphiti-core 的 OpenAIRerankerClient（依赖 logprobs + logit_bias，DeepSeek 不支持 logit_bias）。

工作原理：
  bge-reranker-v2-m3 是 XLMRoBERTa 架构的专用 cross-encoder（568M 参数），
  输入 (query, passage) 对，输出标量相关性分数。
  专为 reranking 训练（MS-MARCO + 多语言数据），MTEB reranking top 3。

模型实例经 model_loader.get_reranker()（进程内单例，与 /rerank 端点同源）。
"""
import asyncio
import logging

import numpy as np

from graphiti_core.cross_encoder.client import CrossEncoderClient

logger = logging.getLogger(__name__)


class BgeRerankerClient(CrossEncoderClient):
    """使用 bge-reranker-v2-m3 本地模型实现 CrossEncoderClient 接口。"""

    @property
    def model(self):
        """CrossEncoder 单例（延迟加载，model_loader 内部线程安全）。"""
        from services import model_loader
        return model_loader.get_reranker()

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

        from services import model_loader
        scores = await asyncio.to_thread(model_loader.rerank_sync, query, passages)
        scores_array = np.asarray(scores)

        results = list(zip(passages, scores_array.tolist()))
        results.sort(reverse=True, key=lambda x: x[1])
        return results
