"""视觉理解 MCP server（vision，DeepSeek 视觉模型）。

薄壳设计：不持模型、不持配置——控制台 vision_service 负责：
  工具调用 → POST /api/vision/analyze（严格契约校验 + DeepSeek 上游调用）

IPC 发现：control_url.py（读注入的 IPC 地址，事实来源）。

工具能力边界（防误用，描述里写明）：
  语义级图像理解（图表分析/截图对比/UI 布局/场景描述）——
  【仅限无原生视觉能力的模型使用】; 有原生视觉的模型直接 Read 图片。
  纯文字转写走 ocr server 的 extract_text（更精确）。
"""
import base64
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, cast

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import AfterValidator, Field

# control_url 与后端模块的导入路径由启动方注入（插件 mcp-manager 设置 PYTHONPATH）
from control_url import resolve_control, make_control_client

# 与控制台 vision_service 相同的单张上限（失败早报，控制台仍权威复核）
MAX_IMAGE_BYTES = 10 * 1024 * 1024

_CONTROL: dict[str, str | None] = {"base": None}
_client: httpx.AsyncClient | None = None


def _base_url() -> str:
    """控制台地址（延迟解析 + 失败自愈：换端口后下次重新解析）。"""
    if _CONTROL["base"] is None:
        addr = resolve_control()
        if addr is None:
            raise RuntimeError("控制台未启动（IPC 地址不可达）")
        _CONTROL["base"] = addr.url
    return _CONTROL["base"]


@asynccontextmanager
async def _lifespan(server: FastMCP):
    """仅建/销 HTTP 客户端——上游调用完全由控制台管理。"""
    global _client
    _client = make_control_client(timeout=300.0)
    try:
        yield
    finally:
        await _client.aclose()


mcp = FastMCP("vision", lifespan=_lifespan)


def _reject_blank(v: str) -> str:
    if not v.strip():
        raise ValueError("不能为空白字符串")
    return v


# 必填标识/内容字段：非空且非纯空白（与控制台契约同语义）
NonBlankStr = Annotated[str, Field(min_length=1), AfterValidator(_reject_blank)]


@mcp.tool(
    description=(
        "视觉理解（DeepSeek 视觉模型，语义级图像问答）。"
        "【仅限无原生视觉能力的模型使用】——有原生视觉识别的模型应直接用 Read 工具读图，"
        "调用本工具反而把路走远了。"
        "适合：图表语义分析、UI 布局理解、截图对比/差异分析、验证码/图形内容理解、场景描述。"
        "支持 1-4 张图（多图=对比/关联分析）。"
        "仅需逐字符精确转写文字（代码/十六进制/表格）→ 用 ocr_extract_text（更精确、零幻觉）。"
        "不支持：视频理解、音频。"
    ),
)
async def analyze_image(
    image_paths: Annotated[
        list[NonBlankStr],
        Field(
            description="本地图片路径列表（1-4 张，PNG/JPEG/GIF/WEBP/BMP）",
            min_length=1,
            max_length=4,
        ),
    ],
    question: Annotated[NonBlankStr, Field(description="关于图像的问题/任务描述（必填）")],
) -> str:
    """语义级看图。返回 JSON（text/model/usage/latency_ms）; 失败返回明确错误说明。"""
    if _client is None:
        return "[错误] MCP 未完成初始化（lifespan 未启动）"

    images_b64: list[str] = []
    for p in image_paths:
        path = Path(p).expanduser()
        if not path.is_file():
            return f"[错误] 图片不存在: {path}"
        data = path.read_bytes()
        if len(data) > MAX_IMAGE_BYTES:
            return f"[错误] 图片过大（{len(data) // 1048576}MB > 10MB 上限）: {path}"
        images_b64.append(base64.b64encode(data).decode())

    try:
        r = await _client.post(
            f"{_base_url()}/api/vision/analyze",
            json={"images": images_b64, "question": question},
        )
        _CONTROL["base"] = None if r.status_code in (404, 502) else _CONTROL["base"]
        if r.status_code == 200:
            return json.dumps(
                cast("dict[str, object]", r.json()), ensure_ascii=False
            )
        return f"[错误] 控制台视觉识别返回 {r.status_code}: {r.text[:200]}"
    except httpx.HTTPError as e:
        _CONTROL["base"] = None  # 清缓存 → 下次重新解析端口（控制台重启自愈）
        return f"[错误] 控制台不可达: {e}"


if __name__ == "__main__":
    mcp.run()
