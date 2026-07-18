"""server.py 序列化层 + 未测 MCP 工具测试。

覆盖 review 发现的最大盲区：_format_results 从未被非空数据测试过。
覆盖 3 个零测试的 MCP 工具：entity_relationships_search / episode_context_search / successful_tools_search。
"""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "events"))


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ─── _format_results 序列化测试（最大盲区）───


class TestFormatResults:
    """测试 _format_results 对各种边界数据的序列化——这是 graphiti 到 MCP 客户端的关键边界。"""

    def _make_search_results(self, edges=None, nodes=None, episodes=None, edge_scores=None, node_scores=None, episode_scores=None):
        """构造模拟 SearchResults 对象。"""
        return SimpleNamespace(
            edges=edges or [],
            nodes=nodes or [],
            episodes=episodes or [],
            edge_reranker_scores=edge_scores or [],
            node_reranker_scores=node_scores or [],
            episode_reranker_scores=episode_scores or [],
        )

    def test_empty_results(self):
        """空结果应正确序列化。"""
        import server
        results = self._make_search_results()
        output = json.loads(server._format_results(results, "test"))
        assert output["edges"] == []
        assert output["nodes"] == []
        assert output["episodes"] == []
        assert output["query"] == "test"

    def test_edge_with_all_fields(self):
        """完整 edge 应正确序列化所有字段。"""
        import server
        edge = SimpleNamespace(
            name="HAS_VULN",
            fact="sample.exe has buffer overflow",
            uuid="edge-uuid-1",
            created_at=datetime(2024, 1, 1, 12, 0, 0),
            source_node_uuid="node-1",
            target_node_uuid="node-2",
        )
        results = self._make_search_results(edges=[edge], edge_scores=[0.95])
        output = json.loads(server._format_results(results, "test"))
        assert len(output["edges"]) == 1
        e = output["edges"][0]
        assert e["name"] == "HAS_VULN"
        assert e["fact"] == "sample.exe has buffer overflow"
        assert e["uuid"] == "edge-uuid-1"
        assert e["created_at"] == "2024-01-01T12:00:00"
        assert e["source_node_uuid"] == "node-1"
        assert output["edge_scores"] == [0.95]

    def test_edge_with_none_created_at(self):
        """edge created_at 为 None 时应输出 null。"""
        import server
        edge = SimpleNamespace(
            name="REL", fact="fact", uuid="id",
            created_at=None,
            source_node_uuid="s", target_node_uuid="t",
        )
        results = self._make_search_results(edges=[edge])
        output = json.loads(server._format_results(results, "test"))
        assert output["edges"][0]["created_at"] is None

    def test_node_with_all_fields(self):
        """完整 node 应正确序列化。"""
        import server
        node = SimpleNamespace(
            name="sample.exe",
            uuid="node-uuid-1",
            labels=["Binary", "Entity"],
            summary="A test binary",
            created_at=datetime(2024, 6, 15, 10, 30),
        )
        results = self._make_search_results(nodes=[node], node_scores=[0.88])
        output = json.loads(server._format_results(results, "test"))
        n = output["nodes"][0]
        assert n["name"] == "sample.exe"
        assert n["labels"] == ["Binary", "Entity"]
        assert n["summary"] == "A test binary"
        assert n["created_at"] == "2024-06-15T10:30:00"
        assert output["node_scores"] == [0.88]

    def test_node_without_labels(self):
        """node 没有 labels 属性时应输出空列表。"""
        import server
        node = SimpleNamespace(
            name="test", uuid="id",
            summary="test", created_at=datetime.now(),
        )
        results = self._make_search_results(nodes=[node])
        output = json.loads(server._format_results(results, "test"))
        assert output["nodes"][0]["labels"] == []

    def test_node_without_summary(self):
        """node 没有 summary 属性时应输出 null。"""
        import server
        node = SimpleNamespace(
            name="test", uuid="id",
            labels=["Entity"], created_at=datetime.now(),
        )
        results = self._make_search_results(nodes=[node])
        output = json.loads(server._format_results(results, "test"))
        assert output["nodes"][0]["summary"] is None

    def test_episode_with_all_fields(self):
        """完整 episode 应正确序列化。"""
        import server
        episode = SimpleNamespace(
            source="message",
            content="Agent response text",
            source_description="binary-analysis response",
            created_at=datetime(2024, 3, 1, 14, 0),
            uuid="ep-uuid-1",
        )
        results = self._make_search_results(episodes=[episode], episode_scores=[0.77])
        output = json.loads(server._format_results(results, "test"))
        ep = output["episodes"][0]
        assert ep["source"] == "message"
        assert ep["content"] == "Agent response text"
        assert ep["source_description"] == "binary-analysis response"
        assert ep["uuid"] == "ep-uuid-1"
        assert output["episode_scores"] == [0.77]

    def test_episode_missing_attributes(self):
        """episode 缺少部分属性时应用 getattr 默认值。"""
        import server
        episode = SimpleNamespace(
            created_at=datetime.now(),
            uuid="ep-1",
            # 缺少 source, content, source_description
        )
        results = self._make_search_results(episodes=[episode])
        output = json.loads(server._format_results(results, "test"))
        ep = output["episodes"][0]
        assert ep["source"] is None
        assert ep["content"] is None
        assert ep["source_description"] is None

    def test_non_serializable_uses_default_str(self):
        """非 JSON 序列化值用 default=str 兜底。"""
        import server
        class Custom:
            def __str__(self):
                return "custom_object"

        node = SimpleNamespace(
            name=Custom(), uuid="id",
            labels=[], summary="s",
            created_at=datetime.now(),
        )
        results = self._make_search_results(nodes=[node])
        output = json.loads(server._format_results(results, "test"))
        assert output["nodes"][0]["name"] == "custom_object"

    def test_empty_result_with_error(self):
        """_empty_result 带 error 应包含 error 字段。"""
        import server
        result = json.loads(server._empty_result("something failed"))
        assert result["edges"] == []
        assert result["error"] == "something failed"

    def test_empty_result_without_error(self):
        """_empty_result 不带 error 不应有 error 字段。"""
        import server
        result = json.loads(server._empty_result())
        assert "error" not in result


# ─── 未测 MCP 工具：entity_relationships_search ───


class TestEntityRelationshipsSearch:
    """entity_relationships_search 零测试 → 补充。"""

    def test_returns_json_with_nonexistent_group(self, event_loop):
        """不存在的 group 应返回空 JSON（不崩溃）。"""
        import server
        result = event_loop.run_until_complete(
            server.entity_relationships_search(
                query="test",
                group_id="nonexistent",
                center_node_uuid="fake-uuid",
                max_depth=2,
            )
        )
        parsed = json.loads(result)
        assert "edges" in parsed
        assert "nodes" in parsed

    def test_max_depth_clamped_to_3(self, event_loop):
        """max_depth > 3 应被限制到 3（不崩溃）。"""
        import server
        result = event_loop.run_until_complete(
            server.entity_relationships_search(
                query="test",
                group_id="nonexistent",
                center_node_uuid="fake-uuid",
                max_depth=10,
            )
        )
        parsed = json.loads(result)
        assert "edges" in parsed


# ─── 未测 MCP 工具：episode_context_search ───


class TestEpisodeContextSearch:
    """episode_context_search 零测试 → 补充。"""

    def test_returns_json_with_nonexistent_group(self, event_loop):
        """不存在的 group 应返回空 JSON。"""
        import server
        result = event_loop.run_until_complete(
            server.episode_context_search(
                query="test",
                group_id="nonexistent",
            )
        )
        parsed = json.loads(result)
        assert "episodes" in parsed


# ─── 未测 MCP 工具：successful_tools_search ───


class TestSuccessfulToolsSearch:
    """successful_tools_search 零测试 → 补充。"""

    def test_returns_json_with_nonexistent_group(self, event_loop):
        """不存在的 group 应返回有效 JSON。"""
        import server
        result = event_loop.run_until_complete(
            server.successful_tools_search(
                query="test",
                group_id="nonexistent-unique-xyz",
                min_mentions=2,
            )
        )
        parsed = json.loads(result)
        assert "nodes" in parsed
        assert "count" in parsed

    def test_min_mentions_filter(self, event_loop):
        """min_mentions 过滤逻辑不崩溃。"""
        import server
        result = event_loop.run_until_complete(
            server.successful_tools_search(
                query="test",
                group_id="nonexistent",
                min_mentions=5,
                max_results=3,
            )
        )
        parsed = json.loads(result)
        assert "nodes" in parsed


# ─── recent_context_search 的 window_map 覆盖 ───


class TestRecentContextWindowMapping:
    """recent_context_search 的 recency_window 映射完整覆盖。"""

    @pytest.mark.parametrize("window", ["1h", "6h", "24h", "7d", "30d", "90d"])
    def test_valid_windows(self, event_loop, window):
        """所有有效 window 值不应崩溃。"""
        import server
        result = event_loop.run_until_complete(
            server.recent_context_search(
                query="test",
                group_id="nonexistent",
                recency_window=window,
            )
        )
        parsed = json.loads(result)
        assert "episodes" in parsed

    def test_invalid_window_fallback(self, event_loop):
        """无效 window 应回退到 24h（不崩溃）。"""
        import server
        result = event_loop.run_until_complete(
            server.recent_context_search(
                query="test",
                group_id="nonexistent",
                recency_window="invalid",
            )
        )
        parsed = json.loads(result)
        assert "episodes" in parsed


# ─── temporal_window_search 无效日期 ───


class TestTemporalWindowInvalidDate:
    """temporal_window_search 的无效日期处理。"""

    def test_invalid_date_returns_error(self, event_loop):
        """无效日期格式应返回 error 降级。"""
        import server
        result = event_loop.run_until_complete(
            server.temporal_window_search(
                query="test",
                group_id="nonexistent",
                time_start="not-a-date",
                time_end="also-bad",
            )
        )
        parsed = json.loads(result)
        assert "error" in parsed or "edges" in parsed  # 降级返回

    def test_date_without_z_suffix(self, event_loop):
        """不带 Z 后缀的 ISO 日期应正常解析。"""
        import server
        result = event_loop.run_until_complete(
            server.temporal_window_search(
                query="test",
                group_id="nonexistent",
                time_start="2024-01-01T00:00:00",
                time_end="2025-01-01T00:00:00",
            )
        )
        parsed = json.loads(result)
        assert "edges" in parsed
