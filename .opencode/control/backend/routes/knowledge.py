"""knowledge 库端点（MCP 薄壳与 plugin 共用）。

  - POST /api/knowledge/search | /api/knowledge/store：知识库读写（agent 工具）
  - POST /api/memory/search：执行记忆检索（agent 工具）
  - POST /api/memory/entry：plugin fire-and-forget 写入（入队即返 202）

同步方法在 FastAPI 线程池执行（handler 用 def），MemoryDB._lock 串行。
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from routes.events import QueuedAck
from services.knowledge_store import (
    KnowledgeStoreService, MemoryEntry,
    SearchKnowledgeResponse, StoreKnowledgeResponse,
)

router = APIRouter(prefix="/api")


class KnowledgeSearchIn(BaseModel):
    questions: list[str]
    lang: str = ""


class KnowledgeStoreIn(BaseModel):
    question: str
    content: str
    lang: str = ""


class MemorySearchIn(BaseModel):
    questions: list[str]
    flow_id: str | None = None


class MemoryEntryIn(BaseModel):
    question: str
    answer: str
    type: str
    flow_id: str | None = None


@router.post("/knowledge/search")
def knowledge_search(req: KnowledgeSearchIn) -> SearchKnowledgeResponse:
    try:
        return KnowledgeStoreService.get_instance().search_knowledge(req.questions, lang=req.lang)
    except Exception as e:
        # 降级契约与 events 路由一致：200 + error 结构，错误消息直达 LLM
        return SearchKnowledgeResponse(error=f"knowledge_search failed: {e}")


@router.post("/knowledge/store")
def knowledge_store_(req: KnowledgeStoreIn) -> StoreKnowledgeResponse:
    try:
        return KnowledgeStoreService.get_instance().store_knowledge(
            req.question, req.content, lang=req.lang)
    except Exception as e:
        return StoreKnowledgeResponse(stored=False, error=f"knowledge_store failed: {e}")


@router.post("/memory/search")
def memory_search(req: MemorySearchIn) -> SearchKnowledgeResponse:
    try:
        return KnowledgeStoreService.get_instance().search_memory(req.questions, flow_id=req.flow_id)
    except Exception as e:
        return SearchKnowledgeResponse(error=f"memory_search failed: {e}")


@router.post("/memory/entry", status_code=202)
def memory_entry(req: MemoryEntryIn) -> QueuedAck:
    queued = KnowledgeStoreService.get_instance().submit(
        MemoryEntry(
            question=req.question, answer=req.answer,
            type=req.type, flow_id=req.flow_id))
    return QueuedAck(queued=queued)
