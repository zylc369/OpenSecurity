"""事件库 MCP server（薄壳，不驻模型/Docker/Graphiti）。

六个工具经 HTTP 代理到控制台（对齐 ocr/server.py 薄壳模式）：
  - 5 个搜索（time / entity_relationships / diverse_results / episode_context / entity）
  - delete_session_events（session 删除时清理事件分区）

业务实现在控制台 services/event_store.py（单 Graphiti 实例，
Docker/容器/模型生命周期由控制台 docker_manager + model_loader 管理）。
端口发现：control_url.py（读端口文件，事实来源）；控制台重启换端口自动自愈。
"""
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import Field

sys.path.insert(0, str(Path(__file__).parent.parent))  # control_url 同级
from control_url import resolve_control, make_control_client

_CONTROL: dict = {"base": None}
_client: httpx.AsyncClient | None = None


def _base_url() -> str:
    """控制台地址（延迟解析 + 失败自愈：换端口后下次重新解析）。"""
    if _CONTROL["base"] is None:
        addr = resolve_control()
        if addr is None:
            raise RuntimeError("控制台未启动（IPC 地址不可达）")
        _CONTROL["base"] = addr.url
    return _CONTROL["base"]


@asynccontextmanager
async def _lifespan(server: FastMCP):
    """只建 HTTP 客户端（无 Docker/模型生命周期，全在控制台）。"""
    global _client
    _client = make_control_client(timeout=200.0)  # 覆盖控制台侧 Docker 冷启动+初始化
    try:
        yield
    finally:
        await _client.aclose()
        _client = None


async def _post(path: str, payload: dict) -> dict:
    """POST 控制台返回 dict；HTTP 层失败返回降级空结构。"""
    if _client is None:
        return {"edges": [], "nodes": [], "episodes": [], "error": "MCP 未完成初始化（lifespan 未启动）"}
    try:
        r = await _client.post(f"{_base_url()}{path}", json=payload)
        _CONTROL["base"] = None if r.status_code in (404, 502) else _CONTROL["base"]
        if r.status_code == 200:
            return r.json()
        return {"edges": [], "nodes": [], "episodes": [], "error": f"控制台返回 {r.status_code}: {r.text[:200]}"}
    except httpx.HTTPError as e:
        _CONTROL["base"] = None  # 清缓存 → 下次重新解析端口（控制台重启自愈）
        return {"edges": [], "nodes": [], "episodes": [], "error": f"控制台不可达: {e}"}


mcp = FastMCP("events", lifespan=_lifespan)

# ── node_labels 统一描述（entity_search + entity_relationships_search 共用）──
NODE_LABELS_DESCRIPTION = (
    "实体类型过滤，可选值："
    "Tool（工具）、Host（主机）、Vulnerability（漏洞/CVE）、"
    "File（文件/二进制）、Endpoint（Web 端点）、"
    "Algorithm（加密算法）、Model（AI 模型）、Prompt（提示词）。"
    "不传则搜全部类型。"
)


@mcp.tool(
    description="按时间搜索事件图谱。不传时间=搜全部；只传 time_start=从指定时间起；传 time_start+time_end=指定区间。",
)
async def time_search(
    query: Annotated[str, Field(description="中文自然语言查询，描述要查找的事件。")],
    group_id: Annotated[str, Field(description="当前任务的 Flow ID，从 $OPENSECURITY_FLOW_ID 获取。限定搜索范围到当前任务。")],
    time_start: Annotated[str, Field(description="可选：起始时间，ISO 8601 格式（如 2026-01-01T00:00:00Z）。不传则不限起始。")] = "",
    time_end: Annotated[str, Field(description="可选：结束时间，ISO 8601 格式。不传则不限结束。")] = "",
    max_results: Annotated[int, Field(description="最大返回结果数。", ge=1, le=100)] = 15,
    message: Annotated[str, Field(description="操作日志，1-2 句中文描述你正在做什么")] = "",
) -> str:
    """Search by time range. time_start/time_end are optional."""
    r = await _post("/api/events/time-search", {
        "query": query, "group_id": group_id,
        "time_start": time_start, "time_end": time_end, "max_results": max_results})
    return json.dumps(r, ensure_ascii=False, default=str)


@mcp.tool(
    description="从中心节点出发搜索实体关系。需要已知 center_node_uuid（从前序搜索结果获取）。",
)
async def entity_relationships_search(
    query: Annotated[str, Field(description="中文自然语言查询。")],
    group_id: Annotated[str, Field(description="当前任务的 Flow ID，从 $OPENSECURITY_FLOW_ID 获取。")],
    center_node_uuid: Annotated[str, Field(description="中心实体 UUID，从前序搜索结果获取。必填。")],
    max_depth: Annotated[int, Field(description="图遍历最大深度（默认 2，最大 3）。", ge=1, le=3)] = 2,
    node_labels: Annotated[list[str] | None, Field(description=NODE_LABELS_DESCRIPTION)] = None,
    edge_types: Annotated[list[str] | None, Field(description="按关系类型过滤。")] = None,
    max_results: Annotated[int, Field(description="最大返回结果数。")] = 20,
    message: Annotated[str, Field(description="操作日志，1-2 句中文描述你正在做什么")] = "",
) -> str:
    """BFS from a center node within max_depth."""
    r = await _post("/api/events/entity-relationships-search", {
        "query": query, "group_id": group_id, "center_node_uuid": center_node_uuid,
        "max_depth": max_depth, "node_labels": node_labels, "edge_types": edge_types,
        "max_results": max_results})
    return json.dumps(r, ensure_ascii=False, default=str)


@mcp.tool(
    description="多元搜索（MMR 排序），平衡相关性和多样性。需要广泛覆盖不同主题时使用。",
)
async def diverse_results_search(
    query: Annotated[str, Field(description="中文自然语言查询。")],
    group_id: Annotated[str, Field(description="当前任务的 Flow ID，从 $OPENSECURITY_FLOW_ID 获取。")],
    diversity_level: Annotated[Literal["low", "medium", "high"], Field(description="多样性优先级。low=更相似，high=更多样。")] = "medium",
    max_results: Annotated[int, Field(description="最大返回结果数。")] = 10,
    message: Annotated[str, Field(description="操作日志，1-2 句中文描述你正在做什么")] = "",
) -> str:
    """MMR-ranked diverse search with cross-encoder reranking."""
    r = await _post("/api/events/diverse-results-search", {
        "query": query, "group_id": group_id,
        "diversity_level": diversity_level, "max_results": max_results})
    return json.dumps(r, ensure_ascii=False, default=str)


@mcp.tool(
    description="搜索事件片段及其关联节点。需要了解过往分析的时间线上下文时使用。",
)
async def episode_context_search(
    query: Annotated[str, Field(description="中文自然语言查询，关于过往 agent 的推理和工具输出。")],
    group_id: Annotated[str, Field(description="当前任务的 Flow ID，从 $OPENSECURITY_FLOW_ID 获取。")],
    max_results: Annotated[int, Field(description="最大返回结果数。")] = 10,
    message: Annotated[str, Field(description="操作日志，1-2 句中文描述你正在做什么")] = "",
) -> str:
    """Episode-centric search."""
    r = await _post("/api/events/episode-context-search", {
        "query": query, "group_id": group_id, "max_results": max_results})
    return json.dumps(r, ensure_ascii=False, default=str)


@mcp.tool(
    description="按实体标签搜索实体。知道实体类型（如 Vulnerability、Host、Tool）时使用。可选按提及次数过滤（搜成功工具时传 min_mentions=2）。",
)
async def entity_search(
    query: Annotated[str, Field(description="中文自然语言查询。")],
    group_id: Annotated[str, Field(description="当前任务的 Flow ID，从 $OPENSECURITY_FLOW_ID 获取。")],
    node_labels: Annotated[list[str], Field(description=NODE_LABELS_DESCRIPTION)],
    min_mentions: Annotated[int, Field(description="可选：实体被提及的最少次数。不传或传0则不过滤。搜成功工具时传2。", ge=0)] = 0,
    edge_types: Annotated[list[str] | None, Field(description="可选：按关系类型过滤。")] = None,
    max_results: Annotated[int, Field(description="最大返回结果数。")] = 25,
    message: Annotated[str, Field(description="操作日志，1-2 句中文描述你正在做什么")] = "",
) -> str:
    """Search entities filtered by labels, optionally by mention count."""
    r = await _post("/api/events/entity-search", {
        "query": query, "group_id": group_id, "node_labels": node_labels,
        "min_mentions": min_mentions, "edge_types": edge_types, "max_results": max_results})
    return json.dumps(r, ensure_ascii=False, default=str)


@mcp.tool(
    description="删除指定 group_id 的所有事件数据（节点、边、事件片段）。session 删除时自动调用。",
)
async def delete_session_events(
    group_id: Annotated[str, Field(description="要删除的任务 Flow ID。该 group_id 下所有数据将被移除。")],
) -> str:
    """Delete all graph data for a group_id."""
    if _client is None:
        return json.dumps({"error": "MCP 未完成初始化（lifespan 未启动）"}, ensure_ascii=False)
    try:
        r = await _client.post(f"{_base_url()}/api/events/delete", json={"group_id": group_id})
        _CONTROL["base"] = None if r.status_code in (404, 502) else _CONTROL["base"]
        if r.status_code == 202:
            return json.dumps({"deleted": group_id}, ensure_ascii=False)
        return json.dumps({"error": f"控制台返回 {r.status_code}: {r.text[:200]}"}, ensure_ascii=False)
    except httpx.HTTPError as e:
        _CONTROL["base"] = None
        return json.dumps({"error": f"delete_session_events failed: 控制台不可达: {e}"}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
