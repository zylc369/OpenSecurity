"""/embed 和 /rerank 路由。

迁移自 mcp-servers/embed_server.py，请求/响应格式严格保持兼容：
  请求体: {"inputs": "text"} 或 {"inputs": ["text1", "text2"]}
  响应体: [[0.1, 0.2, ...], ...]  (1024 维向量的列表)

graphiti_config.py / knowledge_store.py 直接调 model_loader（进程内单例）。
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from services import model_loader

router = APIRouter()


class EmbedRequest(BaseModel):
    """兼容 sentence-transformers 的 encode() 调用约定。"""
    inputs: str | list[str] | None = None
    # 兼容：部分调用方传 input（单数）
    input: str | list[str] | None = None


class RerankRequest(BaseModel):
    query: str
    texts: list[str]


@router.post("/embed")
async def embed(req: EmbedRequest) -> list[list[float]]:
    """向量化文本。"""
    inputs = req.inputs if req.inputs is not None else req.input
    if inputs is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="missing 'inputs'")
    if isinstance(inputs, str):
        inputs = [inputs]
    return await model_loader.embed_async(inputs)


@router.post("/rerank")
async def rerank(req: RerankRequest) -> list[float]:
    """重排序候选文本。"""
    if not req.texts:
        return []
    return await model_loader.rerank_async(req.query, req.texts)
