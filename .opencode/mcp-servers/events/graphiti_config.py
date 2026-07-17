"""graphiti-core 配置：ZhipuAI LLM + BGE-M3 本地 Embedding + Neo4j 存储。

从 .ai_env 读取 ZHIPU_API_KEY，配置 graphiti-core 使用：
- LLM：ZhipuAI glm-4-flash（实体提取）
- Embedding：BGE-M3 本地模型（向量搜索）
- 存储：Neo4j（bolt://localhost:7687）
"""
import os
from pathlib import Path

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


def get_zhipu_api_key() -> str | None:
    """获取 ZhipuAI API key（从 .ai_env 或环境变量）。"""
    load_ai_env()
    return os.environ.get("ZHIPU_API_KEY")


def create_graphiti():
    """创建配置好的 Graphiti 实例（ZhipuAI LLM + BGE-M3 embedding）。

    必须在 async 上下文中调用（graphiti-core 的初始化是 async）。
    返回 (graphiti, error)：
    - 成功：(graphiti_instance, None)
    - 失败（缺 API key / 缺依赖）：(None, error_message)
    """
    from graphiti_core import Graphiti

    api_key = get_zhipu_api_key()
    if not api_key:
        return None, "ZHIPU_API_KEY 未配置（请在 .opencode/.ai_env 中设置）"

    # 配置 LLM：ZhipuAI（OpenAI 兼容端点）
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.llm_client.openai_client import OpenAIClient
    from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient

    llm_config = LLMConfig(
        api_key=api_key,
        base_url="https://open.bigmodel.cn/api/paas/v4/",
        model="glm-4-flash",
    )
    llm_client = OpenAIClient(config=llm_config)

    # 配置 Embedding：BGE-M3 本地模型
    embedder = BgeM3Embedder()

    # 配置 CrossEncoder（搜索结果重排序）：复用 ZhipuAI 端点
    cross_encoder = OpenAIRerankerClient(config=llm_config)

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
    """

    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self._model = None
        self._embedding_dim = 1024

    @property
    def model(self):
        """延迟加载 BGE-M3 模型（首次调用时加载，约 10 秒）。"""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("BAAI/bge-m3")
        return self._model

    def create(self, input_data) -> list[float]:
        """生成 embedding 向量。

        Args:
            input_data: 字符串或字符串列表

        Returns:
            单个输入 → list[float]（1024 维）
            多个输入 → list[list[float]]（每个 1024 维）
        """
        import numpy as np
        if isinstance(input_data, str):
            vec = self.model.encode(input_data, convert_to_numpy=True)
            return np.asarray(vec).tolist()
        # 列表输入
        vecs = self.model.encode(list(input_data), convert_to_numpy=True)
        return [np.asarray(v).tolist() for v in vecs]
