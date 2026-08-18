"""graphiti-core 配置：DeepSeek Anthropic API + BGE-M3 本地 Embedding + BGE-Reranker + Neo4j 存储。

使用 DeepSeek 的 Anthropic API 端点（https://api.deepseek.com/anthropic），
通过 tool use 机制实现服务端强制结构化输出，无需应用层补丁。

模型可通过 .ai_env 环境变量切换：
  DEEPSEEK_MODEL=deepseek-v4-flash     （核心提取模型；需要更强提取质量可改 deepseek-v4-pro）
  DEEPSEEK_SMALL_MODEL=deepseek-v4-flash（时间戳推断模型）

实体类型（CUSTOM_ENTITY_TYPES）：
  定义安全分析专用的 8 种实体类型，graphiti 提取时从这些类型 + Entity（兜底）中选择。
  覆盖 5 个领域（binary/mobile/web/crypto/ai-security）的高频过滤维度。
  冷门实体类型会被标为 Entity（兜底），语义搜索仍可找到。
"""
import asyncio
import os
from pathlib import Path

import numpy as np
from graphiti_core.embedder.client import EmbedderClient
from pydantic import BaseModel

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


CUSTOM_ENTITY_TYPES = {
    "Tool": ToolEntity,
    "Host": HostEntity,
    "Vulnerability": VulnerabilityEntity,
    "File": FileEntity,
    "Endpoint": EndpointEntity,
    "Algorithm": AlgorithmEntity,
    "Model": ModelEntity,
    "Prompt": PromptEntity,
}


def load_ai_env() -> None:
    """读取 .opencode/.ai_env，setdefault 合并到 os.environ。

    优先级：
      1. 系统 env（最高，Plugin shell.env hook 注入的 DEEPSEEK_API_KEY 等）
      2. .ai_env 文件（兜底，仅用于用户直接跑相关 MCP 不通过 Plugin 的场景）

    日常运行时 Plugin 已经把 .ai_env 的配置注入到子进程环境变量，
    此函数 setdefault 不会覆盖已存在的 key，只是兜底。
    """
    ai_env = Path(__file__).resolve().parents[3] / ".ai_env"  # services/ → backend/ → control/ → .opencode/
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

    from services.llm_client import DeepSeekLLMClient
    from services.reranker import BgeRerankerClient

    api_key = get_deepseek_api_key()
    if not api_key:
        return None, "DEEPSEEK_API_KEY 未配置（请在 .opencode/.ai_env 中设置）"

    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
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

    模型实例经 model_loader.get_embedder()（进程内单例，与 /embed 端点同源）。
    encode 是同步 CPU 调用，async 方法用 asyncio.to_thread 包装。
    """

    def __init__(self):
        self._embedding_dim = 1024

    @property
    def model(self):
        """SentenceTransformer 单例（延迟加载，model_loader 内部线程安全）。"""
        from services import model_loader
        return model_loader.get_embedder()

    def _encode_locked(self, text: str) -> "list[float]":
        from services import model_loader
        return model_loader.embed_sync(text)

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
            return await asyncio.to_thread(self._encode_locked, input_data[0])

        if isinstance(input_data, str):
            return await asyncio.to_thread(self._encode_locked, input_data)

        # 预计算向量（Iterable[int]）→ 原样返回
        return [float(x) for x in input_data]

    async def create_batch(self, input_data: list[str]) -> list[list[float]]:
        """批量生成 embedding 向量（async）。

        self.model 必须在主线程解析（避免工作线程竞态导致重复加载模型），
        只把 encode 调用交给 to_thread。
        """
        from services import model_loader
        return await asyncio.to_thread(model_loader.embed_batch_sync, input_data)
