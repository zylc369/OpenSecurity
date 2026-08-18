"""事件库端点（MCP 薄壳与 plugin 共用）。

  - POST /api/events/entry | /api/events/delete：plugin fire-and-forget（入队即返 202）
  - POST /api/events/{time,entity-relationships,diverse-results,episode-context,entity}-search：
    agent 搜索工具。异常时返回与 MCP 降级一致的空结构（{"edges": [], ..., "error": ...}）。
"""
from __future__ import annotations

import time

from fastapi import APIRouter
from pydantic import BaseModel, Field

from services import event_store

router = APIRouter(prefix="/api/events")


class EventEntryIn(BaseModel):
    name: str
    body: str
    source: str
    group_id: str
    timestamp: float | None = None  # ms epoch；缺省取服务端当前时间


class EventDeleteIn(BaseModel):
    group_id: str


class TimeSearchIn(BaseModel):
    query: str
    group_id: str
    time_start: str = ""
    time_end: str = ""
    max_results: int = Field(default=15, ge=1, le=100)


class EntityRelationsIn(BaseModel):
    query: str
    group_id: str
    center_node_uuid: str
    max_depth: int = Field(default=2, ge=1, le=3)
    node_labels: list[str] | None = None
    edge_types: list[str] | None = None
    max_results: int = 20


class DiverseIn(BaseModel):
    query: str
    group_id: str
    diversity_level: str = "medium"
    max_results: int = 10


class EpisodeContextIn(BaseModel):
    query: str
    group_id: str
    max_results: int = 10


class EntitySearchIn(BaseModel):
    query: str
    group_id: str
    node_labels: list[str]
    min_mentions: int = Field(default=0, ge=0)
    edge_types: list[str] | None = None
    max_results: int = 25


@router.post("/entry", status_code=202)
async def events_entry(req: EventEntryIn) -> dict:
    queued = event_store.submit_entry(
        event_store.EventEntry(
            name=req.name, body=req.body, source=req.source,
            group_id=req.group_id,
            timestamp=req.timestamp if req.timestamp is not None else time.time() * 1000))
    return {"queued": queued}


@router.post("/delete", status_code=202)
async def events_delete(req: EventDeleteIn) -> dict:
    queued = event_store.submit_entry(event_store.DeleteGroup(group_id=req.group_id))
    return {"queued": queued}


@router.post("/time-search")
async def time_search(req: TimeSearchIn) -> dict:
    try:
        return await event_store.service_instance().search_time(
            req.query, req.group_id,
            time_start=req.time_start, time_end=req.time_end,
            max_results=req.max_results)
    except Exception as e:
        return event_store.empty_result(f"time_search failed: {e}")


@router.post("/entity-relationships-search")
async def entity_relationships_search(req: EntityRelationsIn) -> dict:
    try:
        return await event_store.service_instance().search_entity_relationships(
            req.query, req.group_id,
            center_node_uuid=req.center_node_uuid, max_depth=req.max_depth,
            node_labels=req.node_labels, edge_types=req.edge_types,
            max_results=req.max_results)
    except Exception as e:
        return event_store.empty_result(f"entity_relationships_search failed: {e}")


@router.post("/diverse-results-search")
async def diverse_results_search(req: DiverseIn) -> dict:
    try:
        return await event_store.service_instance().search_diverse(
            req.query, req.group_id,
            diversity_level=req.diversity_level, max_results=req.max_results)
    except Exception as e:
        return event_store.empty_result(f"diverse_results_search failed: {e}")


@router.post("/episode-context-search")
async def episode_context_search(req: EpisodeContextIn) -> dict:
    try:
        return await event_store.service_instance().search_episode_context(
            req.query, req.group_id, max_results=req.max_results)
    except Exception as e:
        return event_store.empty_result(f"episode_context_search failed: {e}")


@router.post("/entity-search")
async def entity_search(req: EntitySearchIn) -> dict:
    try:
        return await event_store.service_instance().search_entities(
            req.query, req.group_id,
            node_labels=req.node_labels, min_mentions=req.min_mentions,
            edge_types=req.edge_types, max_results=req.max_results)
    except Exception as e:
        return event_store.empty_result(f"entity_search failed: {e}")
