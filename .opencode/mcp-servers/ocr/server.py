"""图像文字识别 MCP server（ocr，本地 glm-ocr）。

薄壳设计：不驻模型。生命周期由控制台 ocr_service 管理——
  lifespan startup → POST /api/ocr/acquire（引用+1，首次触发模型加载）
  工具调用        → POST /api/ocr/extract（持锁串行推理，自动刷新活跃时间）
  lifespan 退出   → POST /api/ocr/close（引用-1，归零 30s 后控制台卸载模型归还内存）

端口发现：control_url.py（读端口文件，事实来源）。

工具能力边界（防误用，描述里写明）：
  提取图像中的文字（文档扫描页/UI 截图/照片/PDF 渲染页）。
  不做图表语义分析、图像对比、视频理解。
"""
import asyncio
import base64
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # control_url 同级
from control_url import resolve_control, make_control_client

_CONTROL = {"base": None}
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
    """acquire（启动）/ close（退出）——控制台引用计数的两端。"""
    global _client
    _client = make_control_client(timeout=300.0)
    pid = os.getpid()
    try:
        import psutil
        start_time = psutil.Process(pid).create_time()
    except Exception:
        start_time = 0.0
    try:
        r = await _client.post(
            f"{_base_url()}/api/ocr/acquire",
            json={"pid": pid, "start_time": start_time},
            timeout=120.0,  # 首次含模型加载（MLX ~5s / 复用孤儿 0s）
        )
        if r.status_code != 200:
            print(f"[ocr-mcp] acquire 失败: {r.status_code} {r.text[:200]}", file=sys.stderr)
        else:
            print("[ocr-mcp] acquire ok", file=sys.stderr)
    except httpx.HTTPError as e:
        print(f"[ocr-mcp] acquire 异常（控制台不可达）: {e}", file=sys.stderr)
    try:
        yield
    finally:
        try:
            await _client.post(
                f"{_base_url()}/api/ocr/close",
                json={"pid": pid, "start_time": start_time},
                timeout=10.0,
            )
        except httpx.HTTPError:
            pass  # 控制台已死则引用由 reaper 的死 pid 检测兜底清理
        await _client.aclose()


mcp = FastMCP("ocr", lifespan=_lifespan)


@mcp.tool(
    description=(
        "提取图像中的文字（本地 glm-ocr）。"
        "适合：文档扫描页、UI 截图、照片里的中英文/代码/十六进制地址/表格/路径。"
        "PDF 文件先用 pymupdf 提文本层（get_text 非空直接用），空才转图走本工具。"
        "参数 prompt 可选，用于引导输出（如'保持表格结构''逐字符精确转写'）。"
        "不支持：图表语义分析、图像内容对比、视频理解。"
    ),
)
async def extract_text(
    image_path: Annotated[str, Field(description="本地图片路径（PNG/JPEG）")],
    prompt: Annotated[str, Field(default="", description="可选引导，如'保持表格结构'")] = "",
) -> str:
    """识别图像文字。返回纯文本转写；失败返回明确错误说明。"""
    if _client is None:
        return "[错误] MCP 未完成初始化（lifespan 未启动）"
    path = Path(image_path).expanduser()
    if not path.is_file():
        return f"[错误] 图片不存在: {path}"
    data = path.read_bytes()
    if len(data) > 20 * 1024 * 1024:
        return f"[错误] 图片过大（{len(data)//1048576}MB > 20MB 上限）"
    image_b64 = base64.b64encode(data).decode()

    try:
        r = await _client.post(
            f"{_base_url()}/api/ocr/extract",
            json={"image_b64": image_b64, "prompt": prompt},
        )
        _CONTROL["base"] = None if r.status_code in (404, 502) else _CONTROL["base"]
        if r.status_code == 200:
            return r.json().get("text", "")
        return f"[错误] 控制台 OCR 返回 {r.status_code}: {r.text[:200]}"
    except httpx.HTTPError as e:
        _CONTROL["base"] = None  # 清缓存 → 下次重新解析端口（控制台重启自愈）
        return f"[错误] 控制台不可达: {e}"


if __name__ == "__main__":
    mcp.run()
