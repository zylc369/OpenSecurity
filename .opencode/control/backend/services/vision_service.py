"""DeepSeek 视觉识别服务——无原生视觉能力模型的"眼睛"。

deepseek-flash 经 OpenAI 兼容端点（/chat/completions + image_url data URL）
提供语义级图像理解（图表分析/截图对比/UI 布局），与本地 glm-ocr（纯文字转写）互补。

模型与参数为代码常量（不进配置——切换模型属代码变更）。
本模块框架无关（不 import fastapi）：上游失败统一抛 VisionUpstreamError，
由路由层映射 HTTP 状态码。
"""
from __future__ import annotations

import base64
import logging
import time
import typing
from dataclasses import dataclass

import httpx

from services.config_manager import ConfigManager

logger = logging.getLogger(__name__)


class VisionUpstreamError(Exception):
    """上游 DeepSeek 调用失败（路由层映射为 HTTP {status_code}）。"""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class VisionImage:
    """解码后的单张图片（字节 + 嗅探出的 media type）。"""

    data: bytes
    media_type: str


@dataclass(frozen=True)
class VisionAnalyzeResult:
    """analyze 的结构化输出。"""

    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int


# 魔数表：字节头 → media type（顺序即嗅探顺序）
_MAGIC_PREFIXES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)


def sniff_media_type(data: bytes) -> str | None:
    """魔数嗅探：PNG/JPEG/GIF/BMP 前缀匹配; WEBP 需 RIFF 头 + 偏移 8 处 WEBP 标记。"""
    for prefix, media in _MAGIC_PREFIXES:
        if data.startswith(prefix):
            return media
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _to_int(value: object) -> int:
    """JSON 数值容错转换（非数值/缺失 → 0）。"""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    return 0


class VisionService:
    """DeepSeek 视觉识别（无状态静态方法类，同 GraphitiFactory 风格）。"""

    MODEL = "deepseek-flash"
    API_URL = "https://api.deepseek.com/chat/completions"
    MAX_TOKENS = 2048
    TIMEOUT_SEC = 120.0
    MAX_IMAGES = 4
    MAX_IMAGE_BYTES = 10 * 1024 * 1024
    MAX_QUESTION_CHARS = 8000

    @classmethod
    async def analyze(
        cls,
        images: list[VisionImage],
        question: str,
        *,
        transport: "httpx.AsyncBaseTransport | None" = None,
    ) -> VisionAnalyzeResult:
        """语义级图像问答（images 已过契约层校验: 1..MAX_IMAGES 张、格式合法）。"""
        api_key = ConfigManager.get_instance().get(ConfigManager.Keys.DEEPSEEK_API_KEY)
        if not api_key:
            raise VisionUpstreamError(
                "DEEPSEEK_API_KEY 未配置（请在控制台配置页或 .opencode/.ai_env 设置）",
                status_code=503,
            )

        content: list[dict[str, object]] = [{"type": "text", "text": question}]
        for img in images:
            b64 = base64.b64encode(img.data).decode()
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{img.media_type};base64,{b64}"},
            })
        payload: dict[str, object] = {
            "model": cls.MODEL,
            "max_tokens": cls.MAX_TOKENS,
            "messages": [{"role": "user", "content": content}],
        }

        logger.info("视觉识别请求: %d 张图, 问题 %d 字符", len(images), len(question))
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=cls.TIMEOUT_SEC, transport=transport) as client:
                resp = await client.post(
                    cls.API_URL,
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
        except httpx.TimeoutException as exc:
            raise VisionUpstreamError(
                f"DeepSeek 请求超时（>{cls.TIMEOUT_SEC:.0f}s）", status_code=504
            ) from exc
        except httpx.HTTPError as exc:
            raise VisionUpstreamError(f"DeepSeek 不可达: {exc}", status_code=502) from exc

        if resp.status_code != 200:
            raise VisionUpstreamError(
                f"DeepSeek 返回 {resp.status_code}: {resp.text[:300]}", status_code=502
            )

        # 结构解析（严格: 类型不符即结构异常——不猜不补）。
        # resp.json() 返回 Any → cast 收口 object; isinstance 收窄产物再 cast 到定型 dict
        def _bad_structure() -> VisionUpstreamError:
            return VisionUpstreamError(
                f"DeepSeek 响应结构异常: {resp.text[:300]}", status_code=502
            )

        raw = typing.cast("dict[object, object]", typing.cast("object", resp.json()))
        if not isinstance(raw, dict):
            raise _bad_structure()
        choices_val: object = raw.get("choices")
        if not isinstance(choices_val, list) or not choices_val:
            raise _bad_structure()
        choices = typing.cast("list[object]", choices_val)
        first: object = choices[0]
        if not isinstance(first, dict):
            raise _bad_structure()
        first_map = typing.cast("dict[object, object]", first)
        message_val: object = first_map.get("message")
        if not isinstance(message_val, dict):
            raise _bad_structure()
        message = typing.cast("dict[object, object]", message_val)
        content_val: object = message.get("content")
        if not isinstance(content_val, str):
            raise _bad_structure()
        text = content_val.strip()
        if not text:
            raise VisionUpstreamError(
                "DeepSeek 返回空内容（可能 max_tokens 耗尽或内容被过滤）", status_code=502
            )
        usage_val: object = raw.get("usage")
        usage_map: dict[object, object] = {}
        if isinstance(usage_val, dict):
            usage_map = typing.cast("dict[object, object]", usage_val)
        model_val: object = raw.get("model")
        model = model_val if isinstance(model_val, str) else cls.MODEL

        result = VisionAnalyzeResult(
            text=text,
            model=model,
            prompt_tokens=_to_int(usage_map.get("prompt_tokens")),
            completion_tokens=_to_int(usage_map.get("completion_tokens")),
            total_tokens=_to_int(usage_map.get("total_tokens")),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        logger.info(
            "视觉识别完成: model=%s tokens=%d latency=%dms",
            result.model,
            result.total_tokens,
            result.latency_ms,
        )
        return result
