"""事件库 MCP server（Graphiti 后端）。

存储过往 LLM 响应和工具执行记录的事件库。7 个搜索方法通过 graphiti-core 查询 Neo4j。
Neo4j 不可用时降级为空返回，不影响 agent 基本功能。

LLM：DeepSeek API（deepseek-v4-pro/flash，实体提取）
Embedding：BGE-M3 本地模型（向量搜索）
CrossEncoder：bge-reranker-v2-m3 本地模型（搜索结果重排序）
存储：Neo4j（bolt://localhost:7687）

搜索工具的 group_id 参数：
  限定搜索范围到当前分析任务的事件分区（OPENSECURITY_FLOW_ID）。
  主任务和它的所有子任务共享同一个 group_id。
"""
import json
from datetime import datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

# 延迟初始化的 Graphiti 连接
_graphiti = None
_initialized = False


async def _ensure_ready():
    """首次调用时初始化 Graphiti 连接 + 建索引。后续调用跳过。"""
    global _graphiti, _initialized
    if _initialized:
        return
    from graphiti_config import create_graphiti

    graphiti, err = create_graphiti()
    if err:
        raise RuntimeError(err)
    _graphiti = graphiti
    await _graphiti.build_indices_and_constraints()
    _initialized = True


def _empty_result(error: str | None = None) -> str:
    """降级空返回（Neo4j 不可用时）。"""
    payload: dict[str, Any] = {"edges": [], "nodes": [], "episodes": []}
    if error:
        payload["error"] = error
    return json.dumps(payload, ensure_ascii=False)


def _format_results(results: Any, query: str) -> str:
    """统一序列化 SearchResults 为 JSON。"""
    return json.dumps({
        "query": query,
        "edges": [{
            "name": e.name,
            "fact": e.fact,
            "uuid": e.uuid,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "source_node_uuid": e.source_node_uuid,
            "target_node_uuid": e.target_node_uuid,
        } for e in results.edges],
        "edge_scores": list(results.edge_reranker_scores),
        "nodes": [{
            "name": n.name,
            "uuid": n.uuid,
            "labels": list(n.labels) if hasattr(n, "labels") else [],
            "summary": getattr(n, "summary", None),
            "created_at": n.created_at.isoformat() if hasattr(n, "created_at") and n.created_at else None,
        } for n in results.nodes],
        "node_scores": list(results.node_reranker_scores),
        "episodes": [{
            "source": getattr(ep, "source", None),
            "content": getattr(ep, "content", None),
            "source_description": getattr(ep, "source_description", None),
            "created_at": ep.created_at.isoformat() if hasattr(ep, "created_at") and ep.created_at else None,
            "uuid": getattr(ep, "uuid", None),
        } for ep in results.episodes],
        "episode_scores": list(results.episode_reranker_scores),
    }, ensure_ascii=False, default=str)


mcp = FastMCP("events")


@mcp.tool(
    description=(
        "Search the temporal knowledge graph for facts within a time window. "
        "Use when you need events/entities bounded by a start and end time."
    ),
)
async def temporal_window_search(
    query: str,
    group_id: str,
    time_start: str,
    time_end: str,
    max_results: int = 15,
) -> str:
    """Search by temporal window."""
    from graphiti_core.search.search_config import (
        SearchConfig, EdgeSearchConfig, NodeSearchConfig,
        EdgeSearchMethod, NodeSearchMethod,
    )
    from graphiti_core.search.search_filters import SearchFilters, DateFilter, ComparisonOperator

    try:
        await _ensure_ready()
        ts = datetime.fromisoformat(time_start.replace("Z", "+00:00"))
        te = datetime.fromisoformat(time_end.replace("Z", "+00:00"))
        results = await _graphiti.search_(
            query=query,
            group_ids=[group_id],
            config=SearchConfig(
                limit=max_results,
                edge_config=EdgeSearchConfig(
                    search_methods=[EdgeSearchMethod.bm25, EdgeSearchMethod.cosine_similarity],
                ),
                node_config=NodeSearchConfig(
                    search_methods=[NodeSearchMethod.bm25, NodeSearchMethod.cosine_similarity],
                ),
            ),
            search_filter=SearchFilters(
                created_at=[[
                    DateFilter(date=ts, comparison_operator=ComparisonOperator.greater_than_equal),
                    DateFilter(date=te, comparison_operator=ComparisonOperator.less_than_equal),
                ]],
            ),
        )
        return _format_results(results, query)
    except Exception as e:
        return _empty_result(f"temporal_window_search failed: {e}")


@mcp.tool(
    description=(
        "Search for entities/relationships within max_depth hops of a center "
        "node. Requires a known center_node_uuid from a prior search result."
    ),
)
async def entity_relationships_search(
    query: str,
    group_id: str,
    center_node_uuid: str,
    max_depth: int = 2,
    node_labels: list[str] | None = None,
    edge_types: list[str] | None = None,
    max_results: int = 20,
) -> str:
    """BFS from a center node within max_depth."""
    from graphiti_core.search.search_config import (
        SearchConfig, EdgeSearchConfig,
        EdgeSearchMethod,
    )
    from graphiti_core.search.search_filters import SearchFilters

    try:
        await _ensure_ready()
        results = await _graphiti.search_(
            query=query,
            group_ids=[group_id],
            center_node_uuid=center_node_uuid,
            config=SearchConfig(
                limit=max_results,
                edge_config=EdgeSearchConfig(
                    search_methods=[EdgeSearchMethod.breadth_first_search],
                    bfs_max_depth=min(max_depth, 3),
                ),
            ),
            search_filter=SearchFilters(
                node_labels=node_labels,
                edge_types=edge_types,
            ),
        )
        return _format_results(results, query)
    except Exception as e:
        return _empty_result(f"entity_relationships_search failed: {e}")


@mcp.tool(
    description=(
        "Diverse (MMR-ranked) results search - balances relevance against "
        "redundancy. Use when you want broad coverage of distinct topics."
    ),
)
async def diverse_results_search(
    query: str,
    group_id: str,
    diversity_level: str = "medium",
    max_results: int = 10,
) -> str:
    """MMR-ranked diverse search with cross-encoder reranking."""
    from graphiti_core.search.search_config import (
        SearchConfig, EdgeSearchConfig,
        EdgeSearchMethod, EdgeReranker,
    )

    try:
        await _ensure_ready()
        mmr_map = {"low": 0.3, "medium": 0.5, "high": 0.7}
        mmr_lambda = mmr_map.get(diversity_level, 0.5)
        results = await _graphiti.search_(
            query=query,
            group_ids=[group_id],
            config=SearchConfig(
                limit=max_results,
                edge_config=EdgeSearchConfig(
                    search_methods=[EdgeSearchMethod.bm25, EdgeSearchMethod.cosine_similarity],
                    reranker=EdgeReranker.cross_encoder,
                    mmr_lambda=mmr_lambda,
                ),
            ),
        )
        return _format_results(results, query)
    except Exception as e:
        return _empty_result(f"diverse_results_search failed: {e}")


@mcp.tool(
    description=(
        "Search for episodes (event clusters) and the nodes they mention. "
        "Use when you need chronological context of what happened in past engagements."
    ),
)
async def episode_context_search(
    query: str,
    group_id: str,
    max_results: int = 10,
) -> str:
    """Episode-centric search."""
    from graphiti_core.search.search_config import (
        SearchConfig, EpisodeSearchConfig,
        EpisodeSearchMethod,
    )

    try:
        await _ensure_ready()
        results = await _graphiti.search_(
            query=query,
            group_ids=[group_id],
            config=SearchConfig(
                limit=max_results,
                episode_config=EpisodeSearchConfig(
                    search_methods=[EpisodeSearchMethod.bm25],
                ),
            ),
        )
        return _format_results(results, query)
    except Exception as e:
        return _empty_result(f"episode_context_search failed: {e}")


@mcp.tool(
    description=(
        "Search for tool/command executions that succeeded in past engagements. "
        "Use to recall which tools/commands previously worked for similar goals."
    ),
)
async def successful_tools_search(
    query: str,
    group_id: str,
    min_mentions: int = 2,
    max_results: int = 15,
) -> str:
    """Recall successful past tool executions by query similarity."""
    from graphiti_core.search.search_config import (
        SearchConfig, NodeSearchConfig,
        NodeSearchMethod,
    )
    from graphiti_core.search.search_filters import SearchFilters

    try:
        await _ensure_ready()
        results = await _graphiti.search_(
            query=query,
            group_ids=[group_id],
            config=SearchConfig(
                limit=max_results * 2,
                node_config=NodeSearchConfig(
                    search_methods=[NodeSearchMethod.bm25, NodeSearchMethod.cosine_similarity],
                ),
            ),
            search_filter=SearchFilters(
                node_labels=["Tool"],
            ),
        )
        filtered = [
            n for n in results.nodes
            if getattr(n, "attributes", {}).get("mention_count", 0) >= min_mentions
        ][:max_results]
        return json.dumps({
            "query": query,
            "nodes": [{
                "name": n.name, "uuid": n.uuid,
                "summary": getattr(n, "summary", None),
                "mention_count": getattr(n, "attributes", {}).get("mention_count", 0),
            } for n in filtered],
            "count": len(filtered),
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return _empty_result(f"successful_tools_search failed: {e}")


@mcp.tool(
    description=(
        "Search recent context within a recency window (1h/6h/24h/7d/30d/90d). "
        "Use for 'what just happened' queries."
    ),
)
async def recent_context_search(
    query: str,
    group_id: str,
    recency_window: str = "24h",
    max_results: int = 10,
) -> str:
    """Recent context search."""
    from graphiti_core.search.search_config import SearchConfig
    from graphiti_core.search.search_filters import SearchFilters, DateFilter, ComparisonOperator

    try:
        await _ensure_ready()
        window_map = {"1h": 1, "6h": 6, "24h": 24, "7d": 168, "30d": 720, "90d": 2160}
        hours = window_map.get(recency_window, 24)
        since = datetime.now() - timedelta(hours=hours)
        results = await _graphiti.search_(
            query=query,
            group_ids=[group_id],
            config=SearchConfig(limit=max_results),
            search_filter=SearchFilters(
                created_at=[[DateFilter(date=since, comparison_operator=ComparisonOperator.greater_than_equal)]],
            ),
        )
        return _format_results(results, query)
    except Exception as e:
        return _empty_result(f"recent_context_search failed: {e}")


@mcp.tool(
    description=(
        "Search entities by their labels. "
        "Use when you know the entity type (e.g., CVE, Host, Tool) but not the UUID."
    ),
)
async def entity_by_label_search(
    query: str,
    group_id: str,
    node_labels: list[str],
    edge_types: list[str] | None = None,
    max_results: int = 25,
) -> str:
    """Search entities filtered by labels."""
    from graphiti_core.search.search_config import (
        SearchConfig, NodeSearchConfig,
        NodeSearchMethod,
    )
    from graphiti_core.search.search_filters import SearchFilters

    try:
        await _ensure_ready()
        results = await _graphiti.search_(
            query=query,
            group_ids=[group_id],
            config=SearchConfig(
                limit=max_results,
                node_config=NodeSearchConfig(
                    search_methods=[NodeSearchMethod.bm25, NodeSearchMethod.cosine_similarity],
                ),
            ),
            search_filter=SearchFilters(
                node_labels=node_labels,
                edge_types=edge_types,
            ),
        )
        return _format_results(results, query)
    except Exception as e:
        return _empty_result(f"entity_by_label_search failed: {e}")


@mcp.tool(
    description=(
        "Delete all events (nodes, edges, episodes) for a given group_id. "
        "Called automatically when a session is deleted to clean up orphan data."
    ),
)
async def delete_session_events(group_id: str) -> str:
    """Delete all graph data for a group_id."""
    try:
        await _ensure_ready()
        from graphiti_core.nodes import EntityNode, EpisodicNode

        await EntityNode.delete_by_group_id(_graphiti.driver, group_id)
        await EpisodicNode.delete_by_group_id(_graphiti.driver, group_id)
        return json.dumps({"deleted": group_id}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"delete_session_events failed: {e}"}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
