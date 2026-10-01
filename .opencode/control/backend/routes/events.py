"""事件库端点（MCP 薄壳与 plugin 共用）。

  - POST /api/events/entry | /api/events/delete：plugin fire-and-forget（入队即返 202）
  - POST /api/events/{time,entity-relationships,diverse-results,episode-context,entity}-search：
    agent 搜索工具。异常时返回与 MCP 降级一致的空结构（{"edges": [], ..., "error": ...}）。

输入契约（按字段语义收紧，契约违规显式 422）：
  - 必填字符串字段：非空且非纯空白（group_id/query/name/body/source/center_node_uuid）；
  - 时间字段：空串=不限边界，非空必须可解析 ISO 8601；
  - diversity_level：low|medium|high 枚举；max_results：1..100。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

import time

from fastapi import APIRouter
from pydantic import AfterValidator, BaseModel, Field

from services.event_store import (
    EventStoreService, EventEntry, DeleteGroup, SearchPayload,
)

router = APIRouter(prefix="/api/events")


def _reject_blank(v: str) -> str:
    """拒绝语义为空的字符串（纯空白）；值不做变换（保持原始字节）。"""
    if not v.strip():
        raise ValueError("不能为空白字符串")
    return v


def _validate_iso_or_empty(v: str) -> str:
    """空串=不限边界；非空必须可解析 ISO 8601（与 event_store.search_time 同一解析路径）。"""
    if v == "":
        return v
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"非法 ISO 8601 时间: {v!r}") from exc
    return v


# 必填标识/内容类字段：非空且非纯空白（min_length 给标准错误，AfterValidator 覆盖空白）
NonBlankStr = Annotated[str, Field(min_length=1), AfterValidator(_reject_blank)]
# 可选时间点：空=不限；非空=可解析 ISO 8601
IsoTimeOrEmpty = Annotated[str, AfterValidator(_validate_iso_or_empty)]
# max_results 统一边界（1..100）；默认值由各字段赋值给出
MaxResults = Annotated[int, Field(ge=1, le=100)]


@dataclass
class QueuedAck:
    queued: bool


class EventEntryIn(BaseModel):
    name: NonBlankStr
    body: NonBlankStr
    source: NonBlankStr
    group_id: NonBlankStr
    timestamp: float | None = Field(default=None, gt=0, allow_inf_nan=False)  # ms epoch 有限正数；缺省取服务端当前时间


class EventDeleteIn(BaseModel):
    group_id: NonBlankStr


class TimeSearchIn(BaseModel):
    query: NonBlankStr
    group_id: NonBlankStr
    time_start: IsoTimeOrEmpty = ""
    time_end: IsoTimeOrEmpty = ""
    max_results: MaxResults = 15


class EntityRelationsIn(BaseModel):
    query: NonBlankStr
    group_id: NonBlankStr
    center_node_uuid: NonBlankStr
    max_depth: int = Field(default=2, ge=1, le=3)
    # 可选过滤器：不传=None；传了就必须是含非空白元素的有效过滤器（空列表无过滤语义）
    node_labels: list[NonBlankStr] | None = Field(default=None, min_length=1)
    edge_types: list[NonBlankStr] | None = Field(default=None, min_length=1)
    max_results: MaxResults = 20


class DiverseIn(BaseModel):
    query: NonBlankStr
    group_id: NonBlankStr
    diversity_level: Literal["low", "medium", "high"] = "medium"
    max_results: MaxResults = 10


class EpisodeContextIn(BaseModel):
    query: NonBlankStr
    group_id: NonBlankStr
    max_results: MaxResults = 10


class EntitySearchIn(BaseModel):
    query: NonBlankStr
    group_id: NonBlankStr
    # 必填 + min_length=1: 无效输入显式 422 拒绝（与 MCP 层契约一致）。
    # 空列表无过滤语义（曾混入非法 Cypher 'n:' → 空 error 结果）
    node_labels: list[NonBlankStr] = Field(min_length=1)
    min_mentions: int = Field(default=0, ge=0)
    edge_types: list[NonBlankStr] | None = Field(default=None, min_length=1)
    max_results: MaxResults = 25


@router.post("/entry", status_code=202)
async def events_entry(req: EventEntryIn) -> QueuedAck:
    queued = EventStoreService.get_instance().submit(
        EventEntry(
            name=req.name, body=req.body, source=req.source,
            group_id=req.group_id,
            timestamp=req.timestamp if req.timestamp is not None else time.time() * 1000))
    return QueuedAck(queued=queued)


@router.post("/delete", status_code=202)
async def events_delete(req: EventDeleteIn) -> QueuedAck:
    queued = EventStoreService.get_instance().submit(DeleteGroup(group_id=req.group_id))
    return QueuedAck(queued=queued)


@router.post("/time-search")
async def time_search(req: TimeSearchIn) -> SearchPayload:
    try:
        return await EventStoreService.get_instance().search_time(
            req.query, req.group_id,
            time_start=req.time_start, time_end=req.time_end,
            max_results=req.max_results)
    except Exception as e:
        return EventStoreService.empty_result(f"time_search failed: {e}")


@router.post("/entity-relationships-search")
async def entity_relationships_search(req: EntityRelationsIn) -> SearchPayload:
    try:
        return await EventStoreService.get_instance().search_entity_relationships(
            req.query, req.group_id,
            center_node_uuid=req.center_node_uuid, max_depth=req.max_depth,
            node_labels=req.node_labels, edge_types=req.edge_types,
            max_results=req.max_results)
    except Exception as e:
        return EventStoreService.empty_result(f"entity_relationships_search failed: {e}")


@router.post("/diverse-results-search")
async def diverse_results_search(req: DiverseIn) -> SearchPayload:
    try:
        return await EventStoreService.get_instance().search_diverse(
            req.query, req.group_id,
            diversity_level=req.diversity_level, max_results=req.max_results)
    except Exception as e:
        return EventStoreService.empty_result(f"diverse_results_search failed: {e}")


@router.post("/episode-context-search")
async def episode_context_search(req: EpisodeContextIn) -> SearchPayload:
    try:
        return await EventStoreService.get_instance().search_episode_context(
            req.query, req.group_id, max_results=req.max_results)
    except Exception as e:
        return EventStoreService.empty_result(f"episode_context_search failed: {e}")


@router.post("/entity-search")
async def entity_search(req: EntitySearchIn) -> SearchPayload:
    try:
        return await EventStoreService.get_instance().search_entities(
            req.query, req.group_id,
            node_labels=req.node_labels, min_mentions=req.min_mentions,
            edge_types=req.edge_types, max_results=req.max_results)
    except Exception as e:
        return EventStoreService.empty_result(f"entity_search failed: {e}")
