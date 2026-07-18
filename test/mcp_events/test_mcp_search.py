"""测试 events MCP server 端到端：写入复杂 episode → 验证实体提取质量。

有效测试：用真实安全分析文本（不是 hello world），验证 DeepSeek LLM + BGE-M3 embedding
+ BGE-Reranker 全链路，并检查关键实体是否被正确提取。

前置条件：Docker + neo4j-events 运行中 + DEEPSEEK_API_KEY 已配置。
"""
import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "events"))

# 复杂的测试 episode（包含多个实体、关系、技术术语——确保 LLM 实体提取链路真正跑通）
COMPLEX_EPISODES = [
    {
        "name": "binary-analysis vulnerability finding",
        "body": (
            "binary-analysis agent used Ghidra to analyze sample.exe. "
            "Found a stack buffer overflow vulnerability in function sub_4012A0 "
            "at offset 0x4012A0. The vulnerability is triggered when the program "
            "calls sprintf without size limit on user input from argv[1]. "
            "Exploitation requires bypassing ASLR via a libc leak from puts@GOT. "
            "Recommended fix: replace sprintf with snprintf. "
            "This vulnerability has been assigned CVE-2024-5678."
        ),
        "source": "binary-analysis agent response",
    },
]

# 预期关键实体（如果 LLM 提取链路正常，这些应该出现在搜索结果中）
EXPECTED_ENTITIES = [
    "sample.exe",
    "Ghidra",
    "sprintf",
    "snprintf",
    "ASLR",
    "CVE-2024-5678",
]


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def graphiti_with_complex_data(event_loop, graphiti_instance, test_group_id):
    """写入复杂测试数据，返回就绪的 graphiti 实例。"""
    from graphiti_core.nodes import EpisodeType

    async def setup():
        await graphiti_instance.build_indices_and_constraints()

        for ep in COMPLEX_EPISODES:
            await graphiti_instance.add_episode(
                name=ep["name"],
                episode_body=ep["body"],
                source_description=ep["source"],
                reference_time=datetime.now(),
                source=EpisodeType.message,
                group_id=test_group_id,
            )

        await asyncio.sleep(30)  # DeepSeek pro 实体提取 ~25-30s

    event_loop.run_until_complete(setup())
    return graphiti_instance


class TestEntityExtractionQuality:
    """验证实体提取质量——不只是"有结果"，而是"有正确结果"。"""

    def test_expected_entities_extracted(self, event_loop, graphiti_with_complex_data, test_group_id):
        """搜索应找到预期关键实体（sample.exe, Ghidra, sprintf 等）。"""
        from graphiti_core.search.search_config import (
            SearchConfig, NodeSearchConfig, NodeSearchMethod,
        )

        async def search():
            return await graphiti_with_complex_data.search_(
                query="sample.exe Ghidra sprintf vulnerability",
                group_ids=[test_group_id],
                config=SearchConfig(
                    limit=30,
                    node_config=NodeSearchConfig(
                        search_methods=[NodeSearchMethod.bm25, NodeSearchMethod.cosine_similarity],
                    ),
                ),
            )

        results = event_loop.run_until_complete(search())
        assert results is not None

        node_names = [n.name.lower() for n in results.nodes]

        # 验证至少提取到了部分预期实体
        found = []
        missing = []
        for expected in EXPECTED_ENTITIES:
            if any(expected.lower() in name for name in node_names):
                found.append(expected)
            else:
                missing.append(expected)

        coverage = len(found) / len(EXPECTED_ENTITIES)
        assert coverage >= 0.67, (
            f"实体覆盖率过低: {coverage:.0%} ({found}), 缺失: {missing}. "
            f"已知实体: {node_names}"
        )

    def test_edges_contain_facts(self, event_loop, graphiti_with_complex_data, test_group_id):
        """搜索应找到至少一条 fact（实体间关系）。"""
        from graphiti_core.search.search_config import (
            SearchConfig, EdgeSearchConfig, EdgeSearchMethod,
        )

        async def search():
            return await graphiti_with_complex_data.search_(
                query="vulnerability buffer overflow",
                group_ids=[test_group_id],
                config=SearchConfig(
                    limit=10,
                    edge_config=EdgeSearchConfig(
                        search_methods=[EdgeSearchMethod.bm25, EdgeSearchMethod.cosine_similarity],
                    ),
                ),
            )

        results = event_loop.run_until_complete(search())

        if len(results.edges) == 0:
            pytest.skip("边提取可能尚未完成（LLM 处理延迟）")

        # 验证 fact 内容包含关键信息
        facts_text = " ".join(e.fact.lower() for e in results.edges)
        assert any(kw in facts_text for kw in ["buffer", "overflow", "sprintf", "vulnerability", "ghidra"]), (
            f"fact 内容不含关键信息: {facts_text[:200]}"
        )


class TestGroupIdIsolation:
    """验证 group_id 隔离——不同 group 的数据不互相污染。"""

    def test_search_isolated_group_returns_empty(self, event_loop, graphiti_with_complex_data):
        """搜索不存在的 group 应返回空。"""
        from graphiti_core.search.search_config import SearchConfig

        async def search():
            return await graphiti_with_complex_data.search_(
                query="anything",
                group_ids=["nonexistent-group-xyz-12345"],
                config=SearchConfig(limit=5),
            )

        results = event_loop.run_until_complete(search())
        assert len(results.edges) == 0
        assert len(results.nodes) == 0
        assert len(results.episodes) == 0

    def test_correct_group_has_data(self, event_loop, graphiti_with_complex_data, test_group_id):
        """搜索正确的 group 应有数据（用 BM25 避免向量相似度过滤）。"""
        from graphiti_core.search.search_config import (
            SearchConfig, EpisodeSearchConfig, EpisodeSearchMethod,
        )

        async def search():
            return await graphiti_with_complex_data.search_(
                query="sample.exe Ghidra",
                group_ids=[test_group_id],
                config=SearchConfig(
                    limit=5,
                    episode_config=EpisodeSearchConfig(
                        search_methods=[EpisodeSearchMethod.bm25],
                    ),
                ),
            )

        results = event_loop.run_until_complete(search())
        # episode 应该能搜到（BM25 纯文本匹配）
        assert len(results.episodes) > 0 or len(results.nodes) > 0 or len(results.edges) > 0, (
            "正确的 group 应有数据"
        )


class TestDiverseSearchWithReranker:
    """验证 diverse_results_search + BgeRerankerClient 正常工作（BUG 2 的端到端验证）。"""

    def test_cross_encoder_reranker_works(self, event_loop, graphiti_with_complex_data, test_group_id):
        """diverse_results_search 使用 cross-encoder reranker，应返回有效搜索结果（非 None）。"""
        from graphiti_core.search.search_config import (
            SearchConfig, EdgeSearchConfig,
            EdgeSearchMethod, EdgeReranker,
        )

        async def search():
            return await graphiti_with_complex_data.search_(
                query="buffer overflow exploitation",
                group_ids=[test_group_id],
                config=SearchConfig(
                    limit=5,
                    edge_config=EdgeSearchConfig(
                        search_methods=[EdgeSearchMethod.bm25, EdgeSearchMethod.cosine_similarity],
                        reranker=EdgeReranker.cross_encoder,
                        mmr_lambda=0.5,
                    ),
                ),
            )

        results = event_loop.run_until_complete(search())

        # 验证返回了 SearchResults 对象且有 reranker_scores 属性（cross-encoder 确实执行了）
        assert hasattr(results, "edge_reranker_scores"), "结果应有 edge_reranker_scores（cross-encoder 执行后填充）"

        # 如果有 edges，验证 reranker_scores 非空
        if len(results.edges) > 0:
            assert len(results.edge_reranker_scores) > 0, "cross-encoder reranker 应产生分数"


class TestServerToolBehavior:
    """直接调用 server.py 的 MCP 工具函数，验证 server 层逻辑（不经过 graphiti-core 搜索）。

    旧版 test_mcp_search 直接调 graphiti_instance.search_()，绕过了 server.py 的
    参数解析、group_id 传递、错误降级等逻辑。新版直接调 server 的工具函数。
    """

    def test_temporal_window_search_parses_dates(self, event_loop):
        """temporal_window_search 应正确解析 ISO 日期并返回 JSON。"""
        import importlib
        server = importlib.import_module("server")

        result = event_loop.run_until_complete(
            server.temporal_window_search(
                query="test",
                group_id="nonexistent",
                time_start="2024-01-01T00:00:00Z",
                time_end="2025-01-01T00:00:00Z",
                max_results=5,
            )
        )
        import json as _json
        parsed = _json.loads(result)
        assert "edges" in parsed
        assert "nodes" in parsed

    def test_diverse_results_search_mmr_mapping(self, event_loop):
        """diverse_results_search 的 diversity_level 映射不崩溃。"""
        import importlib
        server = importlib.import_module("server")

        for level in ("low", "medium", "high", "invalid"):
            result = event_loop.run_until_complete(
                server.diverse_results_search(
                    query="test",
                    group_id="nonexistent",
                    diversity_level=level,
                    max_results=3,
                )
            )
            # 不崩溃即可（nonexistent group 返回空结果）
            import json as _json
            parsed = _json.loads(result)
            assert "edges" in parsed

    def test_recent_context_search_window_mapping(self, event_loop):
        """recent_context_search 的 recency_window 映射不崩溃。"""
        import importlib
        server = importlib.import_module("server")

        result = event_loop.run_until_complete(
            server.recent_context_search(
                query="test",
                group_id="nonexistent",
                recency_window="24h",
                max_results=3,
            )
        )
        import json as _json
        parsed = _json.loads(result)
        assert "episodes" in parsed

    def test_entity_by_label_search_requires_labels(self, event_loop):
        """entity_by_label_search 应正确处理 node_labels 参数。"""
        import importlib
        server = importlib.import_module("server")

        result = event_loop.run_until_complete(
            server.entity_by_label_search(
                query="test",
                group_id="nonexistent",
                node_labels=["Tool", "CVE"],
                max_results=5,
            )
        )
        import json as _json
        parsed = _json.loads(result)
        assert "nodes" in parsed

    def test_delete_session_events_returns_json(self, event_loop):
        """delete_session_events 应返回 JSON（即使 group 不存在也不崩溃）。"""
        import importlib
        server = importlib.import_module("server")

        result = event_loop.run_until_complete(
            server.delete_session_events(group_id="nonexistent-delete-test")
        )
        import json as _json
        parsed = _json.loads(result)
        # 成功或错误都应返回有效 JSON
        assert "deleted" in parsed or "error" in parsed
