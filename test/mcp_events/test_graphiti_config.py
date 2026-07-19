"""测试 graphiti_config.py 的组件：create_graphiti / DeepSeekLLMClient / BgeM3Embedder / BgeRerankerClient。

不 mock，测试真实的组件创建和基本功能。
前置条件：.ai_env 有 DEEPSEEK_API_KEY（完整测试需要 Neo4j 运行中）。
"""
import asyncio
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "events"))


class TestCreateGraphiti:
    """测试 create_graphiti() 工厂函数。"""

    def test_returns_graphiti_instance(self):
        from graphiti_config import create_graphiti
        g, err = create_graphiti()
        assert err is None, f"create_graphiti 返回错误: {err}"
        assert g is not None

    def test_llm_client_is_deepseek_client(self, graphiti_instance):
        from llm_client import DeepSeekLLMClient
        assert isinstance(graphiti_instance.llm_client, DeepSeekLLMClient), \
            f"期望 DeepSeekLLMClient，实际 {type(graphiti_instance.llm_client)}"

    def test_llm_client_inherits_anthropic_client(self, graphiti_instance):
        from graphiti_core.llm_client.anthropic_client import AnthropicClient
        assert isinstance(graphiti_instance.llm_client, AnthropicClient), \
            "DeepSeekLLMClient 应继承 AnthropicClient"

    def test_embedder_is_bge_m3(self, graphiti_instance):
        from graphiti_config import BgeM3Embedder
        assert isinstance(graphiti_instance.embedder, BgeM3Embedder)

    def test_cross_encoder_is_bge_reranker(self, graphiti_instance):
        from reranker import BgeRerankerClient
        assert isinstance(graphiti_instance.cross_encoder, BgeRerankerClient), \
            f"期望 BgeRerankerClient，实际 {type(graphiti_instance.cross_encoder)}"

    def test_llm_config_uses_deepseek_anthropic_endpoint(self, graphiti_instance):
        """LLM config 的 base_url 应该指向 DeepSeek Anthropic API。"""
        config = graphiti_instance.llm_client.config
        assert "deepseek.com/anthropic" in str(config.base_url), \
            f"base_url 应指向 DeepSeek Anthropic 端点，实际: {config.base_url}"

    def test_llm_config_temperature_zero(self, graphiti_instance):
        """temperature 应该为 0（graphiti 需要确定性输出）。"""
        config = graphiti_instance.llm_client.config
        assert config.temperature == 0, f"temperature 应为 0，实际: {config.temperature}"


class TestBgeM3Embedder:
    """测试 BGE-M3 embedding 生成（async 接口）。"""

    def test_create_is_async(self):
        from graphiti_config import BgeM3Embedder
        assert inspect.iscoroutinefunction(BgeM3Embedder.create), \
            "create 应该是 async（graphiti 调 await embedder.create()）"

    def test_create_batch_is_async(self):
        from graphiti_config import BgeM3Embedder
        assert inspect.iscoroutinefunction(BgeM3Embedder.create_batch)

    def test_single_string_embedding(self):
        from graphiti_config import BgeM3Embedder
        emb = BgeM3Embedder()
        result = asyncio.run(emb.create("hello world"))
        assert isinstance(result, list)
        assert len(result) == 1024, f"期望 1024 维，实际 {len(result)}"

    def test_batch_embedding(self):
        """create_batch 返回多个 embedding（每个 1024 维）。"""
        from graphiti_config import BgeM3Embedder
        emb = BgeM3Embedder()
        result = asyncio.run(emb.create_batch(["hello", "world"]))
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(len(r) == 1024 for r in result)

    def test_create_single_element_list(self):
        """create 传入单元素列表 [text] 应返回扁平 list[float]（graphiti 的调用方式）。"""
        from graphiti_config import BgeM3Embedder
        emb = BgeM3Embedder()
        result = asyncio.run(emb.create(["single text"]))
        assert isinstance(result, list)
        assert len(result) == 1024
        assert all(isinstance(x, float) for x in result)

    def test_create_batch_method(self):
        from graphiti_config import BgeM3Embedder
        emb = BgeM3Embedder()
        result = asyncio.run(emb.create_batch(["test1", "test2", "test3"]))
        assert isinstance(result, list)
        assert len(result) == 3
        assert all(len(r) == 1024 for r in result)

    def test_embedding_consistency(self):
        """相同输入应该产生相同向量。"""
        from graphiti_config import BgeM3Embedder
        emb = BgeM3Embedder()
        v1 = asyncio.run(emb.create("test consistency"))
        v2 = asyncio.run(emb.create("test consistency"))
        assert v1 == v2, "相同输入的 embedding 不一致"


class TestBgeRerankerClientIntegration:
    """测试 BgeRerankerClient 在 Graphiti 实例中的集成。"""

    def test_reranker_lazy_loaded(self, graphiti_instance):
        """reranker 创建时模型不应加载（lazy）。"""
        ce = graphiti_instance.cross_encoder
        assert ce._model is None, "BgeRerankerClient 创建时不应加载模型"
