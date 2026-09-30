"""/api/ocr 路由：本地图像文字识别（glm-ocr，控制台持有模型）。

消费方：mcp-servers/ocr/server.py（MCP 薄壳，extract 直调——懒加载对壳透明）。
生命周期语义见 services/ocr_service.py（extract 懒加载 + 纯空闲 600s 自动卸载）。
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.ocr_service import OcrService, OcrStatus

router = APIRouter(prefix="/api/ocr", tags=["ocr"])


class ExtractRequest(BaseModel):
    image_b64: str       # 图片 base64（PNG/JPEG）
    prompt: str = ""     # 可选引导（如"注意保持表格结构"）


@dataclass
class OcrExtractResult:
    text: str


@dataclass
class OcrReleaseResult:
    """release 响应（ok + 全部状态字段扁平合并——与原 dict 形状一致）。"""
    ok: bool
    backend: str
    state: str
    idle_release_sec: int
    last_activity_at: "float | None"
    error: "str | None"
    mlx_ready: bool
    model_cached: bool


@router.post("/extract")
async def extract(req: ExtractRequest) -> OcrExtractResult:
    """识图。未就绪自动加载（懒加载）; 自动刷新活跃时间。"""
    try:
        text = await OcrService.get_instance().extract(req.image_b64, req.prompt)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"OCR 后端返回 {e.response.status_code}: {e.response.text[:200]}",
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"OCR 后端不可达: {e}")
    return OcrExtractResult(text=text)


@router.get("/status")
async def get_status() -> OcrStatus:
    """状态快照（前端模型页：backend/state/空闲窗口/错误/依赖就绪）。"""
    return OcrService.get_instance().status()


@router.post("/release")
async def release() -> OcrReleaseResult:
    """强制释放（前端模型页停止按钮）。"""
    await OcrService.get_instance().force_release()
    st = OcrService.get_instance().status()
    return OcrReleaseResult(
        ok=True, backend=st.backend, state=st.state,
        idle_release_sec=st.idle_release_sec,
        last_activity_at=st.last_activity_at, error=st.error,
        mlx_ready=st.mlx_ready, model_cached=st.model_cached)
