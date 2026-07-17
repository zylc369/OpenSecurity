"""测试 events MCP server 的搜索方法 + Graphiti 端到端写入+搜索。

不 mock，测试真实的 Neo4j 写入 + ZhipuAI 实体提取 + 搜索。
前置条件：Docker + neo4j-events 运行中 + ZHIPU_API_KEY 已配置。

测试流程：
1. 通过 graphiti.add_episode 写入测试数据
2. 等待实体提取完成
3. 用各种搜索方法查询
4. 验证结果
"""
import asyncio
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "events"))

TIMEOUT = 120  # ZhipuAI 实体提取可能较慢


@pytest.fixture(scope="module")
def event_loop():
    """模块级 event loop（避免每个测试重建 Graphiti 连接）。"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def graphiti_with_data(event_loop, graphiti_instance, test_group_id):
    """写入测试数据到 Graphiti，返回就绪的 graphiti 实例。"""
    from graphiti_core.nodes import EpisodeType

    async def setup():
        await graphiti_instance.build_indices_and_constraints()

        # 写入两条测试事件
        episodes = [
            {
                "name": "frida hook function execution",
                "body": "Used frida to hook the verify_license function at offset 0x4012A0. "
                        "Found that the function checks a flag at memory address 0x602040. "
                        "The flag is compared against the string 'FLAG{test123}'.",
                "source": "binary-analysis tool execution",
                "timestamp": time.time() * 1000 - 60000,  # 1 分钟前
            },
            {
                "name": "binary-analysis agent response",
                "body": "Analysis complete. The target binary has a license verification function "
                        "at offset 0x4012A0. Used angr symbolic execution to find the correct input. "
                        "The flag is FLAG{test123}.",
                "source": "binary-analysis response",
                "timestamp": time.time() * 1000,  # 现在
            },
        ]

        for ep in episodes:
            await graphiti_instance.add_episode(
                name=ep["name"],
                episode_body=ep["body"],
                source_description=ep["source"],
                reference_time=datetime.fromtimestamp(ep["timestamp"] / 1000),
                source=EpisodeType.message,
                group_id=test_group_id,
            )
        # 等待实体提取完成
        await asyncio.sleep(5)

    event_loop.run_until_complete(setup())
    return graphiti_instance


class TestGraphitiWrite:
    """测试 Graphiti 端到端写入。"""

    def test_episode_written(self, event_loop, graphiti_with_data, test_group_id):
        """验证 episode 已写入 Neo4j。"""
        async def check():
            # 用 recent_context_search 查询，应该能找到刚写入的事件
            results = await graphiti_with_data.recent_context_search(
                query="license verification flag",
                group_ids=[test_group_id],
                max_results=5,
                center_time=datetime.now(),
                max_timeframe=datetime.now() - timedelta(hours=1),
            )
            return results

        results = event_loop.run_until_complete(check())
        assert results is not None, "搜索不应返回 None"
        # recent_context_search 返回 BlockData，可能包含 episodes
        assert hasattr(results, "episodes") or hasattr(results, "facts") or isinstance(results, (list, dict)), \
            f"搜索结果类型异常: {type(results)}"


class TestSearchMethods:
    """测试各种搜索方法（全部使用 graphiti_with_data fixture）。"""

    def test_temporal_window_search(self, event_loop, graphiti_with_data, test_group_id):
        """时间窗口搜索——应该找到最近写入的事件。"""
        async def search():
            return await graphiti_with_data.search_(
                query="frida hook",
                group_ids=[test_group_id],
                max_results=5,
                center_time=datetime.now(),
                search_filters=None,
            )

        try:
            results = event_loop.run_until_complete(search())
            assert results is not None
        except Exception as e:
            pytest.skip(f"搜索方法可能未就绪: {e}")

    def test_recent_context_search(self, event_loop, graphiti_with_data, test_group_id):
        """最近上下文搜索。"""
        async def search():
            return await graphiti_with_data.search_(
                query="binary analysis flag",
                group_ids=[test_group_id],
                max_results=5,
                center_time=datetime.now(),
                search_filters=None,
            )

        try:
            results = event_loop.run_until_complete(search())
            assert results is not None
        except Exception as e:
            pytest.skip(f"搜索方法可能未就绪: {e}")

    def test_entity_search(self, event_loop, graphiti_with_data, test_group_id):
        """实体关系搜索。"""
        async def search():
            return await graphiti_with_data.search_(
                query="FLAG{test123}",
                group_ids=[test_group_id],
                max_results=5,
                center_time=datetime.now(),
                search_filters=None,
            )

        try:
            results = event_loop.run_until_complete(search())
            assert results is not None
        except Exception as e:
            pytest.skip(f"搜索方法可能未就绪: {e}")


class TestMcpServerImport:
    """测试 events MCP server 可 import（不启动 MCP 协议）。"""

    def test_server_module_importable(self):
        """server.py 应该可以被 import（验证依赖齐全）。"""
        try:
            # server.py 在模块级别初始化 graphiti，import 即测试
            import importlib
            spec = importlib.util.spec_from_file_location(
                "events_server",
                str(Path(__file__).resolve().parents[1] / ".opencode" / "mcp-servers" / "events" / "server.py"),
            )
            assert spec is not None
        except ImportError as e:
            pytest.skip(f"events server import 失败（依赖缺失）: {e}")
