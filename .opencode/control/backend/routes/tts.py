"""远端 TTS 路由（经 P2P transport 或节点本机 HTTP 调用，同一语义）。

POST /api/tts        {text, voice?, speed?} → audio/wav（bytes body）
GET  /api/tts/voices → {"voices": [VoiceAsset 字典...]}
POST /api/tts/voices → 上传新音色（multipart: wav + 表单字段）——无删除端点
失败: TtsUnavailable → 503; 文本/音色非法 → 400。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from services.tts_service import DEFAULT_SPEED, TtsService, TtsUnavailable
from services.voice_library import VoiceError, VoiceLibrary

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tts", tags=["tts"])


class TtsRequest(BaseModel):
    """合成请求（voice 省略=音色库默认; speed 1.0 原速 / <1 服务端减速）。"""

    text: str = Field(min_length=1, max_length=2000)
    voice: str = ""
    speed: float = Field(default=DEFAULT_SPEED, ge=0.5, le=3.0)
    instruct: str = Field(default="", max_length=200)  # 朗读指令(空=默认正常语速)
    seed: int = Field(default=-1, ge=-1, le=99999)     # 采样种子(≤0=默认 4)
    mode: str = Field(default="", max_length=16)       # ""=zero_shot(默认 情感饱满); "instruct"=指令控制


def get_tts_service() -> TtsService:
    """依赖注入点（测试 override 用）。"""
    return TtsService.get_instance()


@router.post("")
def synthesize(req: TtsRequest,
               svc: TtsService = Depends(get_tts_service)) -> Response:
    try:
        result = svc.synthesize(req.text, voice=req.voice, speed=req.speed,
                                instruct=req.instruct, seed=req.seed,
                                mode=req.mode)
    except TtsUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    logger.debug("TTS %dB cached=%s %.0fms voice=%s",
                 len(result.wav), result.cached, result.gen_ms, result.voice)
    return Response(content=result.wav, media_type="audio/wav",
                    headers={"X-Tts-Source": result.source})


@router.get("/voices")
def voices() -> "dict[str, list[dict[str, Any]]]":
    """音色列表（双源合并——内置在前用户在后; 含 is_default 标记）。"""
    from dataclasses import asdict
    lib = VoiceLibrary.get_instance()
    default_id = lib.default_voice().id if lib.list_voices() else ""
    items: list[dict[str, Any]] = []
    for v in lib.list_voices():
        d = dict(asdict(v))  # pyright: ignore[reportAny] —— asdict 存根 Any
        d["available"] = v.resolved_wav(lib).is_file()
        d["is_default"] = v.id == default_id
        items.append(d)  # pyright: ignore[reportUnknownArgumentType] —— asdict Any 收口
    return {"voices": items}


class DefaultVoiceRequest(BaseModel):
    """设置默认音色（HIDDEN 配置的专用端点——不入配置 TAB）。"""
    voice_id: str = Field(min_length=1, max_length=64)


@router.put("/voices/default")
def set_default_voice(req: DefaultVoiceRequest) -> "dict[str, str]":
    """设置 TTS 默认音色（持久化 .ai_env; 校验音色存在）。"""
    from services.config_manager import ConfigManager
    lib = VoiceLibrary.get_instance()
    if lib.get(req.voice_id) is None:
        raise HTTPException(status_code=404, detail=f"音色不存在: {req.voice_id}")
    ConfigManager.get_instance().set_one(
        key=ConfigManager.Keys.TTS_DEFAULT_VOICE, value=req.voice_id)
    logger.info("TTS 默认音色 → %s", req.voice_id)
    return {"ok": "true", "voice": req.voice_id}


@router.post("/voices")
async def upload_voice(
    wav: UploadFile = File(...),  # noqa: B008 —— FastAPI 声明式依赖
    name: str = Form(...),
    gender: str = Form(...),
    ref_text: str = Form(...),
    description: str = Form(""),
) -> "dict[str, Any]":
    """上传音色（服务端统一转 24kHz 单声道; 校验失败 400）。"""
    raw = await wav.read()
    try:
        asset = VoiceLibrary.get_instance().add_user_voice(
            raw, name=name, gender=gender, description=description, ref_text=ref_text)
    except VoiceError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "id": asset.id}
