"""测试 BgeRerankerClient：真实本地模型推理，不 mock。

测试链路：BgeRerankerClient → bge-reranker-v2-m3 本地模型 → 相关性分数。
前置条件：bge-reranker-v2-m3 模型已下载（~/.cache/huggingface/hub/）。
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "events"))


class TestBgeRerankerCreation:
    """测试 BgeRerankerClient 创建和接口。"""

    def test_importable(self):
        from reranker import BgeRerankerClient
        assert BgeRerankerClient is not None

    def test_inherits_cross_encoder_client(self):
        from graphiti_core.cross_encoder.client import CrossEncoderClient
        from reranker import BgeRerankerClient
        assert issubclass(BgeRerankerClient, CrossEncoderClient)

    def test_rank_is_async(self):
        import inspect
        from reranker import BgeRerankerClient
        assert inspect.iscoroutinefunction(BgeRerankerClient.rank)

    def test_lazy_loading(self):
        """模型应该延迟加载——创建实例时不加载。"""
        from reranker import BgeRerankerClient
        client = BgeRerankerClient()
        assert client._model is None, "创建实例时不应加载模型"


class TestRealRank:
    """真实 rank 调用测试（首次会加载模型，约 3 秒）。"""

    @pytest.fixture(scope="class")
    def loaded_reranker(self):
        """class 级复用——只加载模型一次。"""
        from reranker import BgeRerankerClient
        client = BgeRerankerClient()
        return client

    def test_rank_returns_sorted_list(self, loaded_reranker):
        """rank 应该返回按分数降序的列表。"""
        query = "SQL injection attack technique"
        passages = [
            "SQL injection inserts malicious SQL statements into input fields",
            "Cross-site scripting (XSS) injects malicious scripts into web pages",
            "Today's weather is sunny and warm",
            "sqlmap is a tool that automates SQL injection detection and exploitation",
        ]

        results = asyncio.run(loaded_reranker.rank(query, passages))

        assert isinstance(results, list)
        assert len(results) == 4
        assert all(isinstance(r, tuple) and len(r) == 2 for r in results)
        assert all(isinstance(r[1], float) for r in results)

        # 验证降序排列
        scores = [r[1] for r in results]
        assert scores == sorted(scores, reverse=True), "结果应按分数降序排列"

    def test_rank_sql_injection_relevance(self, loaded_reranker):
        """SQL injection 相关的 passage 分数应该高于不相关的。"""
        query = "SQL injection attack technique"
        passages = [
            "SQL injection inserts malicious SQL statements into input fields",
            "Today's weather is sunny and warm",
        ]

        results = asyncio.run(loaded_reranker.rank(query, passages))
        result_dict = {p: s for p, s in results}

        sql_score = result_dict["SQL injection inserts malicious SQL statements into input fields"]
        weather_score = result_dict["Today's weather is sunny and warm"]

        assert sql_score > weather_score, (
            f"SQL injection 相关 passage 分数应更高: sql={sql_score} weather={weather_score}"
        )

    def test_rank_empty_passages(self, loaded_reranker):
        """空 passages 应该返回空列表。"""
        results = asyncio.run(loaded_reranker.rank("query", []))
        assert results == []

    def test_rank_single_passage(self, loaded_reranker):
        """单个 passage 应该正常返回。"""
        results = asyncio.run(loaded_reranker.rank("test query", ["single passage"]))
        assert len(results) == 1
        assert isinstance(results[0][1], float)

    def test_rank_chinese_query(self, loaded_reranker):
        """中文 query 测试（BGE-Reranker 支持多语言）。"""
        query = "如何利用 SQL 注入漏洞"
        passages = [
            "SQL 注入是通过在输入中插入恶意 SQL 语句来攻击数据库的技术",
            "今天天气很好，适合户外运动",
            "可以使用 sqlmap 工具自动化检测 SQL 注入漏洞",
        ]

        results = asyncio.run(loaded_reranker.rank(query, passages))

        result_dict = {p: s for p, s in results}
        assert result_dict["SQL 注入是通过在输入中插入恶意 SQL 语句来攻击数据库的技术"] > \
               result_dict["今天天气很好，适合户外运动"], \
               "SQL 注入相关 passage 应得分更高"

    def test_model_loaded_after_rank(self, loaded_reranker):
        """rank 调用后模型应该已加载。"""
        assert loaded_reranker._model is not None, "rank 后模型应已加载"
