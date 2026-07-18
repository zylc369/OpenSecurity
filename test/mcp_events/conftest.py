"""events MCP 共享 fixtures。

所有测试都需要真实的 Graphiti 实例（Neo4j + DeepSeek + BGE-M3 + BGE-Reranker），不 mock。
前置条件：Docker + neo4j-events 容器运行中 + .ai_env 有 DEEPSEEK_API_KEY。
"""
import sys
from pathlib import Path

import pytest

# 确保 events 目录在 sys.path（graphiti_config 可 import）
EVENTS_DIR = Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "events"
sys.path.insert(0, str(EVENTS_DIR))


@pytest.fixture(scope="session")
def graphiti_instance():
    """创建真实的 Graphiti 实例（session 级复用，避免重复初始化）。"""
    from graphiti_config import create_graphiti

    g, err = create_graphiti()
    if err:
        pytest.skip(f"Graphiti 初始化失败: {err}")
    return g


@pytest.fixture(scope="session")
def test_group_id():
    """测试用 group_id（隔离测试数据）。"""
    return "test-mcp-events-session"


@pytest.fixture(scope="session")
def test_group_id_2():
    """第二个测试用 group_id（测试 group 隔离）。"""
    return "test-mcp-events-other"
