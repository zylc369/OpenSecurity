"""远端 TTS 路由（D5——经 P2P transport 或节点本机 HTTP 调用，同一语义）。

POST /api/tts   {text, voice?, speed?} → audio/wav（bytes body）
GET  /api/tts/voices → {"voices": [...]}
失败: TtsUnavailable → 503; 文本非法 → 400。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from services.tts_service import (
    DEFAULT_SPEED,
    DEFAULT_VOICE,
    TtsService,
    TtsUnavailable,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tts", tags=["tts"])


class TtsRequest(BaseModel):
    """合成请求（voice/speed 可省——阅读 App 侧只传 text 亦可）。"""

    text: str = Field(min_length=1, max_length=2000)
    voice: str = DEFAULT_VOICE
    speed: float = Field(default=DEFAULT_SPEED, ge=0.5, le=3.0)


def get_tts_service() -> TtsService:
    """依赖注入点（测试 override 用）。"""
    return TtsService.get_instance()


@router.post("")
def synthesize(req: TtsRequest,
               svc: TtsService = Depends(get_tts_service)) -> Response:
    try:
        result = svc.synthesize(req.text, voice=req.voice, speed=req.speed)
    except TtsUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    logger.debug("TTS %dB cached=%s %.0fms voice=%s",
                 len(result.wav), result.cached, result.gen_ms, result.voice)
    return Response(content=result.wav, media_type="audio/wav")


@router.get("/voices")
def voices(svc: TtsService = Depends(get_tts_service)) -> "dict[str, list[str]]":
    """音色列表（引擎未就绪时仅返回默认音色——可用性优先）。"""
    if not svc.engine_ready():
        return {"voices": [DEFAULT_VOICE]}
    known = ["zf_xiaobei", "zm_yunxi", "zm_yunjian", "af_heart"]
    return {"voices": known}
