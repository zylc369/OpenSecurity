"""graphiti-core 配置：DeepSeek Anthropic API + BGE-M3 本地 Embedding + BGE-Reranker + Neo4j 存储。

使用 DeepSeek 的 Anthropic API 端点（https://api.deepseek.com/anthropic），
通过 tool use 机制实现服务端强制结构化输出，无需应用层补丁。

模型可通过 .ai_env 环境变量切换：
  DEEPSEEK_MODEL=deepseek-v4-pro       （核心提取模型，可改为 deepseek-v4-flash 省钱）
  DEEPSEEK_SMALL_MODEL=deepseek-v4-flash（时间戳推断模型）
"""
import asyncio
import os
from pathlib import Path

import numpy as np
from graphiti_core.embedder.client import EmbedderClient


def load_ai_env() -> None:
    """读取 .opencode/.ai_env，setdefault 合并到 os.environ。"""
    ai_env = Path(__file__).resolve().parents[2] / ".ai_env"  # events/ → mcp-servers/ → .opencode/
    if not ai_env.is_file():
        return
    for line in ai_env.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip())


def get_deepseek_api_key() -> str | None:
    """获取 DeepSeek API key（从 .ai_env 或环境变量）。"""
    load_ai_env()
    return os.environ.get("DEEPSEEK_API_KEY")


def create_graphiti():
    """创建配置好的 Graphiti 实例（DeepSeek LLM + BGE-M3 embedding + BGE-Reranker）。

    必须在 async 上下文中调用（graphiti-core 的初始化是 async）。
    返回 (graphiti, error)：
    - 成功：(graphiti_instance, None)
    - 失败（缺 API key / 缺依赖）：(None, error_message)
    """
    from graphiti_core import Graphiti
    from graphiti_core.llm_client.config import LLMConfig

    from llm_client import DeepSeekLLMClient
    from reranker import BgeRerankerClient

    api_key = get_deepseek_api_key()
    if not api_key:
        return None, "DEEPSEEK_API_KEY 未配置（请在 .opencode/.ai_env 中设置）"

    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
    small_model = os.environ.get("DEEPSEEK_SMALL_MODEL", "deepseek-v4-flash")

    llm_config = LLMConfig(
        api_key=api_key,
        base_url="https://api.deepseek.com/anthropic",
        model=model,
        small_model=small_model,
        temperature=0,
    )
    llm_client = DeepSeekLLMClient(config=llm_config)

    embedder = BgeM3Embedder()

    cross_encoder = BgeRerankerClient()

    graphiti = Graphiti(
        uri="bolt://localhost:7687",
        user="neo4j",
        password="neo4j_password",
        llm_client=llm_client,
        embedder=embedder,
        cross_encoder=cross_encoder,
    )
    return graphiti, None


class BgeM3Embedder(EmbedderClient):
    """使用 BGE-M3 本地模型实现 graphiti-core 的 EmbedderClient 接口。

    替代 OpenAI embedding API——零成本、无网络依赖。
    输出 1024 维向量，与 graphiti-core 默认 EMBEDDING_DIM=1024 一致。

    create 方法是 async（graphiti-core 的 EntityNode.generate_name_embedding
    调 await embedder.create()）。同步的 model.encode 用 asyncio.to_thread 包装。
    """

    def __init__(self):
        self._model = None
        self._embedding_dim = 1024

    @property
    def model(self):
        """延迟加载 BGE-M3 模型（首次调用时加载，约 10 秒）。"""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer("BAAI/bge-m3")
        return self._model

    async def create(self, input_data) -> list[float]:
        """生成 embedding 向量（async）。

        graphiti 的 EntityNode/EntityEdge 调 await embedder.create(input_data=[text])，
        传入单元素列表，期望返回扁平的 list[float]（不是 list[list[float]]）。

        Args:
            input_data: 字符串、单元素字符串列表 [text]、或预计算向量

        Returns:
            list[float]（1024 维扁平向量）
        """
        # 空输入 → 报错（而非返回 [] 导致后续 cosine similarity 维度不匹配）
        if isinstance(input_data, (list, tuple)) and len(input_data) == 0:
            raise ValueError("Cannot generate embedding for empty input")

        # graphiti 传 [text]（单元素列表）→ 取第一个元素做 embedding
        if isinstance(input_data, list) and len(input_data) > 0 and isinstance(input_data[0], str):
            text = input_data[0]
            vec = await asyncio.to_thread(self.model.encode, text, convert_to_numpy=True)
            return np.asarray(vec).tolist()

        if isinstance(input_data, str):
            vec = await asyncio.to_thread(self.model.encode, input_data, convert_to_numpy=True)
            return np.asarray(vec).tolist()

        # 预计算向量（Iterable[int]）→ 原样返回
        return [float(x) for x in input_data]

    async def create_batch(self, input_data: list[str]) -> list[list[float]]:
        """批量生成 embedding 向量（async）。"""
        return await asyncio.to_thread(self._encode_batch, input_data)

    def _encode_batch(self, texts: list[str]) -> list[list[float]]:
        """同步批量编码（内部方法，被 async 方法通过 to_thread 调用）。"""
        vecs = self.model.encode(texts, convert_to_numpy=True)
        return [np.asarray(v).tolist() for v in vecs]
