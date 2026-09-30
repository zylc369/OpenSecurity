"""graphiti-core 配置：DeepSeek Anthropic API + BGE-M3 本地 Embedding + BGE-Reranker + Neo4j 存储。

使用 DeepSeek 的 Anthropic API 端点（https://api.deepseek.com/anthropic），
通过 tool use 机制实现服务端强制结构化输出，无需应用层补丁。

模型可通过 .ai_env 环境变量切换：
  DEEPSEEK_MODEL=deepseek-flash     （核心提取模型；需要更强提取质量可改 deepseek-v4-pro）
  DEEPSEEK_SMALL_MODEL=deepseek-flash（时间戳推断模型）

实体类型（CUSTOM_ENTITY_TYPES）：
  定义安全分析专用的 8 种实体类型，graphiti 提取时从这些类型 + Entity（兜底）中选择。
  覆盖 5 个领域（binary/mobile/web/crypto/ai-security）的高频过滤维度。
  冷门实体类型会被标为 Entity（兜底），语义搜索仍可找到。
"""
import asyncio
from collections.abc import Iterable
from pathlib import Path

import numpy as np

from services.config_manager import ConfigManager
from graphiti_core.embedder.client import EmbedderClient
from typing import TYPE_CHECKING
from pydantic import BaseModel

if TYPE_CHECKING:
    from graphiti_core.graphiti import Graphiti

# ── 安全分析专用实体类型 ────────────────────────────────────
# graphiti 的 _build_entity_types_context 会在这些基础上加 {id:0, name:"Entity"}（兜底）。
# 每个 class 的 docstring 是 graphiti 提取 prompt 中展示给 LLM 的类型描述。


class ToolEntity(BaseModel):
    """A software tool or utility used in security analysis (e.g., nmap, frida, IDA Pro, sqlmap, Ghidra)."""


class HostEntity(BaseModel):
    """A network host, server, or device identified by IP or hostname (e.g., 192.168.1.1, server.example.com)."""


class VulnerabilityEntity(BaseModel):
    """A security vulnerability, CVE, or weakness (e.g., CVE-2024-1234, buffer overflow, SQL injection)."""


class FileEntity(BaseModel):
    """A file, binary, or artifact being analyzed (e.g., target.exe, app.apk, config.yaml)."""


class EndpointEntity(BaseModel):
    """A web endpoint, URL path, or API route (e.g., /api/login, /actuator/env, /adminpanel)."""


class AlgorithmEntity(BaseModel):
    """A cryptographic algorithm or mathematical construct (e.g., RSA, AES, ECDLP, LLL lattice)."""


class ModelEntity(BaseModel):
    """An AI or LLM model being tested or attacked (e.g., GPT-4, Claude-3, Llama-3, custom model)."""


class PromptEntity(BaseModel):
    """A prompt, system instruction, or injection payload targeting AI systems (e.g., jailbreak prompt, system prompt leak)."""


CUSTOM_ENTITY_TYPES: "dict[str, type[BaseModel]]" = {
    "Tool": ToolEntity,
    "Host": HostEntity,
    "Vulnerability": VulnerabilityEntity,
    "File": FileEntity,
    "Endpoint": EndpointEntity,
    "Algorithm": AlgorithmEntity,
    "Model": ModelEntity,
    "Prompt": PromptEntity,
}





class GraphitiFactory:
    """Graphiti 实例工厂（DeepSeek LLM + ConfigManager 配置; 静态方法类）。"""

    @staticmethod
    def get_deepseek_api_key() -> str | None:
        """获取 DeepSeek API key（从 .ai_env 或环境变量）。"""
        cm = ConfigManager.get_instance()
        return cm.get(cm.Keys.DEEPSEEK_API_KEY)

    @staticmethod
    def create_graphiti() -> "tuple[Graphiti | None, str | None]":
        """创建配置好的 Graphiti 实例（DeepSeek LLM + BGE-M3 embedding + BGE-Reranker）。

        必须在 async 上下文中调用（graphiti-core 的初始化是 async）。
        返回 (graphiti, error)：
        - 成功：(graphiti_instance, None)
        - 失败（缺 API key / 缺依赖）：(None, error_message)
        """
        from graphiti_core import Graphiti
        from graphiti_core.llm_client.config import LLMConfig

        from services.llm_client import DeepSeekLLMClient
        from services.reranker import BgeRerankerClient

        api_key = GraphitiFactory.get_deepseek_api_key()
        if not api_key:
            return None, "DEEPSEEK_API_KEY 未配置（请在 .opencode/.ai_env 中设置）"

        cm = ConfigManager.get_instance()
        model = cm.get(cm.Keys.DEEPSEEK_MODEL) or "deepseek-flash"
        small_model = cm.get(cm.Keys.DEEPSEEK_SMALL_MODEL) or "deepseek-flash"

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

    模型实例经 ModelInferenceService.get_instance().get_embedder()（进程内单例，与 /embed 端点同源）。
    encode 是同步 CPU 调用，async 方法用 asyncio.to_thread 包装。
    """

    def __init__(self):
        self._embedding_dim = 1024

    def _encode(self, text: str) -> "list[float]":
        """单文本 embed（串行由 model_loader 的 LockedEmbedder 保证）。"""
        from services.model_loader import ModelInferenceService
        return ModelInferenceService.get_instance().embed_sync(text)

    async def create(self, input_data: str | list[str] | Iterable[int | float]) -> list[float]:
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
            return await asyncio.to_thread(self._encode, input_data[0])

        if isinstance(input_data, str):
            return await asyncio.to_thread(self._encode, input_data)

        # 预计算向量（Iterable[int]）→ 原样返回
        return [float(x) for x in input_data]  # pyright: ignore[reportArgumentType]  前面分支已排除 str；此处按数字向量契约（pyright 无法表达"首元素非 str 则全非 str"）

    async def create_batch(self, input_data: list[str]) -> list[list[float]]:
        """批量生成 embedding 向量（async）。

        模型解析在 model_loader 内部线程安全（双重检查锁定单例），
        只把 encode 调用交给 to_thread（串行由 LockedEmbedder 保证）。
        """
        from services.model_loader import ModelInferenceService
        return await asyncio.to_thread(
            ModelInferenceService.get_instance().embed_batch_sync, input_data)
