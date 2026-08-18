"""knowledge 库端点（MCP 薄壳与 plugin 共用）。

  - POST /api/knowledge/search | /api/knowledge/store：知识库读写（agent 工具）
  - POST /api/memory/search：执行记忆检索（agent 工具）
  - POST /api/memory/entry：plugin fire-and-forget 写入（入队即返 202）

同步方法在 FastAPI 线程池执行（handler 用 def），MemoryDB._lock 串行。
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from services import knowledge_store

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
def knowledge_search(req: KnowledgeSearchIn) -> dict:
    return knowledge_store.service_instance().search_knowledge(req.questions, lang=req.lang)


@router.post("/knowledge/store")
def knowledge_store_(req: KnowledgeStoreIn) -> dict:
    return knowledge_store.service_instance().store_knowledge(
        req.question, req.content, lang=req.lang)


@router.post("/memory/search")
def memory_search(req: MemorySearchIn) -> dict:
    return knowledge_store.service_instance().search_memory(req.questions, flow_id=req.flow_id)


@router.post("/memory/entry", status_code=202)
def memory_entry(req: MemoryEntryIn) -> dict:
    queued = knowledge_store.submit_entry(
        knowledge_store.MemoryEntry(
            question=req.question, answer=req.answer,
            type=req.type, flow_id=req.flow_id))
    return {"queued": queued}
