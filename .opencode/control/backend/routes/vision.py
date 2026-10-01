"""/api/vision 路由：DeepSeek 视觉识别（语义级图像理解，无原生视觉能力模型的"眼睛"）。

消费方：mcp-servers/vision/server.py（MCP 薄壳）。与 /api/ocr（glm-ocr 纯文字转写）互补。

输入契约（契约违规显式 422，风格与 routes/events.py 一致）：
  - images：1..4 张，每张为合法 base64 图片（解码后非空、单张 ≤10MB、
    魔数嗅探 PNG/JPEG/GIF/WEBP/BMP）；
  - question：必填非空白，≤8000 字符。
"""
from __future__ import annotations

import base64
import binascii
from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import AfterValidator, BeforeValidator, BaseModel, ConfigDict, Field

from services.vision_service import (
    VisionAnalyzeResult,
    VisionImage,
    VisionService,
    VisionUpstreamError,
    sniff_media_type,
)

router = APIRouter(prefix="/api/vision", tags=["vision"])


def _reject_blank(v: str) -> str:
    """拒绝语义为空的字符串（纯空白）；值不做变换。与 events.py 同语义。"""
    if not v.strip():
        raise ValueError("不能为空白字符串")
    return v


def _decode_image(b64_str: str) -> VisionImage:
    """base64 → 解码 + 尺寸/魔数校验 → 定型 VisionImage（契约层唯一解码入口）。"""
    if not isinstance(b64_str, str):
        raise ValueError("图片必须为 base64 字符串")
    try:
        data = base64.b64decode(b64_str, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("非法 base64 编码") from exc
    if not data:
        raise ValueError("图片数据为空")
    if len(data) > VisionService.MAX_IMAGE_BYTES:
        raise ValueError(
            f"图片过大（解码后 {len(data) // 1048576}MB > "
            f"{VisionService.MAX_IMAGE_BYTES // 1048576}MB 上限）"
        )
    media = sniff_media_type(data)
    if media is None:
        raise ValueError("不支持的图片格式（魔数嗅探失败，支持 PNG/JPEG/GIF/WEBP/BMP）")
    return VisionImage(data=data, media_type=media)


# base64 字符串 → 解码定型（BeforeValidator: str 输入 → VisionImage 实例）
DecodedImage = Annotated[VisionImage, BeforeValidator(_decode_image)]
# 必填问题：非空非纯空白 + 长度上限
Question = Annotated[
    str,
    Field(min_length=1, max_length=VisionService.MAX_QUESTION_CHARS),
    AfterValidator(_reject_blank),
]


class AnalyzeIn(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)  # VisionImage 非 pydantic 类型

    images: list[DecodedImage] = Field(min_length=1, max_length=VisionService.MAX_IMAGES)
    question: Question


@router.post("/analyze")
async def analyze(req: AnalyzeIn) -> VisionAnalyzeResult:
    """语义级图像问答（契约违规 422 自动; 上游失败映射 502/503/504）。"""
    try:
        return await VisionService.analyze(req.images, req.question)
    except VisionUpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
