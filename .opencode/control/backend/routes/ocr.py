"""/api/ocr 路由：本地图像文字识别（glm-ocr，控制台持有模型）。

消费方：mcp-servers/ocr/server.py（MCP 薄壳，lifespan acquire/close）。
生命周期语义见 services/ocr_service.py（引用计数 + 30s 空闲释放，进程内加载）。
"""
from __future__ import annotations

from dataclasses import asdict

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dataclasses import asdict

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.ocr_service import ocr_service

router = APIRouter(prefix="/api/ocr", tags=["ocr"])


class AcquireRequest(BaseModel):
    pid: int             # MCP 进程 pid（client 身份）
    start_time: float    # 进程启动时间（防 pid 复用）


class ExtractRequest(BaseModel):
    image_b64: str       # 图片 base64（PNG/JPEG）
    prompt: str = ""     # 可选引导（如"注意保持表格结构"）


@router.post("/acquire")
async def acquire(req: AcquireRequest) -> dict:
    """引用+1（首次触发模型加载；并发请求等同一就绪事件）。"""
    try:
        await ocr_service.acquire(req.pid, req.start_time)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"ok": True, **asdict(ocr_service.status())}


@router.post("/extract")
async def extract(req: ExtractRequest) -> dict:
    """识图。自动刷新活跃时间（复用窗口）。"""
    try:
        text = await ocr_service.extract(req.image_b64, req.prompt)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"OCR 后端返回 {e.response.status_code}: {e.response.text[:200]}",
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"OCR 后端不可达: {e}")
    return {"text": text}


@router.post("/close")
async def close(req: AcquireRequest) -> dict:
    """引用-1（归零后由后台线程在空闲窗口后释放模型内存）。"""
    await ocr_service.close(req.pid, req.start_time)
    return {"ok": True, **asdict(ocr_service.status())}


@router.get("/status")
async def get_status() -> dict:
    """状态快照（前端模型页：backend/state/clients/错误/依赖就绪）。"""
    return asdict(ocr_service.status())


@router.post("/release")
async def release() -> dict:
    """强制释放（前端模型页停止按钮）。"""
    await ocr_service.force_release()
    return {"ok": True, **asdict(ocr_service.status())}
