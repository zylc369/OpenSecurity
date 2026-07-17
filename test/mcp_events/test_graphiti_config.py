"""测试 graphiti_config.py 的组件：create_graphiti / BgeM3Embedder / DummyCrossEncoder。

不 mock，测试真实的组件创建和基本功能。
"""
import asyncio
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

    def test_llm_client_is_openai_client(self, graphiti_instance):
        from graphiti_core.llm_client.openai_client import OpenAIClient
        assert isinstance(graphiti_instance.llm_client, OpenAIClient)

    def test_embedder_is_bge_m3(self, graphiti_instance):
        from graphiti_config import BgeM3Embedder
        assert isinstance(graphiti_instance.embedder, BgeM3Embedder)

    def test_cross_encoder_is_openai_reranker(self, graphiti_instance):
        from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
        assert isinstance(graphiti_instance.cross_encoder, OpenAIRerankerClient)


class TestBgeM3Embedder:
    """测试 BGE-M3 embedding 生成。"""

    def test_single_string_embedding(self):
        from graphiti_config import BgeM3Embedder
        emb = BgeM3Embedder()
        result = emb.create("hello world")
        assert isinstance(result, list)
        assert len(result) == 1024, f"期望 1024 维，实际 {len(result)}"

    def test_batch_embedding(self):
        from graphiti_config import BgeM3Embedder
        emb = BgeM3Embedder()
        result = emb.create(["hello", "world"])
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(len(r) == 1024 for r in result)

    def test_embedding_consistency(self):
        """相同输入应该产生相同向量。"""
        from graphiti_config import BgeM3Embedder
        emb = BgeM3Embedder()
        v1 = emb.create("test consistency")
        v2 = emb.create("test consistency")
        assert v1 == v2, "相同输入的 embedding 不一致"


class TestCrossEncoder:
    """测试 OpenAIRerankerClient 配置（验证实例可用，不做实际 API 调用）。"""

    def test_reranker_has_client(self, graphiti_instance):
        """reranker 应该有内部 client（AsyncOpenAI 实例）。"""
        ce = graphiti_instance.cross_encoder
        assert hasattr(ce, "client"), "OpenAIRerankerClient 应该有 client 属性"

    def test_reranker_config_has_zhipuai_base_url(self, graphiti_instance):
        """reranker config 应该指向 ZhipuAI 端点。"""
        ce = graphiti_instance.cross_encoder
        assert hasattr(ce, "config"), "OpenAIRerankerClient 应该有 config 属性"
        assert "bigmodel.cn" in str(ce.config.base_url), \
            f"base_url 应该指向 ZhipuAI，实际: {ce.config.base_url}"
