"""事件库 MCP 服务器（桩实现）。

存储过往 LLM 响应和工具执行记录的事件库。全部 7 个搜索方法返回空结果（stub）。
二期替换为真实后端（Graphiti/Neo4j）。

方法签名对齐 PentAGI graphiti_search.go:18-24（共 7 个方法），
参数形态对齐 github.com/vxcontrol/graphiti-go-client@v0.9.0/types.go。
"""
import json
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

STUB_NOTE = "Events backend not implemented yet - returning empty results. See Phase 2 plan."

mcp = FastMCP("events")


def _empty_result(extra: dict[str, Any] | None = None) -> str:
    """返回一个规范的 Graphiti 风格空响应，并附带一条说明。"""
    payload: dict[str, Any] = {
        "edges": [],
        "nodes": [],
        "episodes": [],
        "note": STUB_NOTE,
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload)


@mcp.tool(
    description=(
        "Search the temporal knowledge graph for facts within a time window. "
        "Use when you need events/entities bounded by a start and end time."
    ),
)
def temporal_window_search(
    query: str,
    time_start: str,
    time_end: str,
    max_results: int = 15,
) -> str:
    """Search by temporal window.

    Args:
        query: English semantic query.
        time_start: ISO 8601 datetime string (inclusive).
        time_end: ISO 8601 datetime string (inclusive).
        max_results: Cap on returned edges/nodes (default 15).
    """
    return _empty_result({
        "time_window": {"start": time_start, "end": time_end},
        "max_results": max_results,
    })


@mcp.tool(
    description=(
        "Search for entities/relationships within max_depth hops of a center "
        "node. Requires a known center_node_uuid from a prior search result."
    ),
)
def entity_relationships_search(
    query: str,
    center_node_uuid: str,
    max_depth: int = 2,
    node_labels: list[str] | None = None,
    edge_types: list[str] | None = None,
    max_results: int = 20,
) -> str:
    """BFS from a center node within max_depth.

    Args:
        query: English semantic query for relevance scoring.
        center_node_uuid: UUID of the BFS root (from a prior search result).
        max_depth: Hop distance cap (default 2).
        node_labels: Optional filter - only traverse nodes with these labels.
        edge_types: Optional filter - only traverse edges with these types.
        max_results: Cap on returned edges (default 20).
    """
    return _empty_result({"center_node_uuid": center_node_uuid, "max_depth": max_depth})


@mcp.tool(
    description=(
        "Diverse (MMR-ranked) results search - balances relevance against "
        "redundancy. Use when you want broad coverage of distinct topics."
    ),
)
def diverse_results_search(
    query: str,
    diversity_level: str = "medium",
    max_results: int = 10,
) -> str:
    """MMR-ranked diverse search.

    Args:
        query: English semantic query.
        diversity_level: low/medium/high (default medium).
        max_results: Cap on returned edges (default 10).
    """
    return _empty_result({"diversity_level": diversity_level})


@mcp.tool(
    description=(
        "Search for episodes (event clusters) and the nodes they mention. "
        "Use when you need chronological context of what happened in past engagements."
    ),
)
def episode_context_search(
    query: str,
    max_results: int = 10,
) -> str:
    """Episode-centric search.

    Args:
        query: English semantic query.
        max_results: Cap on returned episodes (default 10).
    """
    return _empty_result({"max_results": max_results})


@mcp.tool(
    description=(
        "Search for tool/command executions that succeeded in past engagements. "
        "Use to recall which tools/commands previously worked for similar goals."
    ),
)
def successful_tools_search(
    query: str,
    min_mentions: int = 2,
    max_results: int = 15,
) -> str:
    """Recall successful past tool executions by query similarity.

    Args:
        query: English semantic query about what you want to do.
        min_mentions: Filter - tool must have succeeded >= this many times.
        max_results: Cap on returned tool nodes (default 15).
    """
    return _empty_result({"min_mentions": min_mentions})


@mcp.tool(
    description=(
        "Search recent context within a recency window (1h/6h/24h/7d/30d/90d). "
        "Use for 'what just happened' queries."
    ),
)
def recent_context_search(
    query: str,
    recency_window: str = "24h",
    max_results: int = 10,
) -> str:
    """Recent context search.

    Args:
        query: English semantic query.
        recency_window: 1h/6h/24h/7d/30d/90d (default 24h).
        max_results: Cap on returned edges (default 10).
    """
    return _empty_result({
        "time_window": {"recency": recency_window},
        "max_results": max_results,
    })


@mcp.tool(
    description=(
        "Search entities by their labels (Neo4j node labels). "
        "Use when you know the entity type (e.g., CVE, Host, Tool) but not the UUID."
    ),
)
def entity_by_label_search(
    query: str,
    node_labels: list[str],
    edge_types: list[str] | None = None,
    max_results: int = 25,
) -> str:
    """Search entities filtered by Neo4j labels.

    Args:
        query: English semantic query.
        node_labels: Required - which node labels to filter on (e.g., ["CVE", "Host"]).
        edge_types: Optional edge-type filter.
        max_results: Cap on returned nodes (default 25).
    """
    return _empty_result({"node_labels": node_labels, "max_results": max_results})


if __name__ == "__main__":
    mcp.run()
