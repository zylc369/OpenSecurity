"""代理 IP 管理 MCP server（proxy，薄壳）。

薄壳设计：不持有任何状态——IP 池/relay/判定依据全部在控制台：
  工具调用 → POST /api/proxy/*（控制台 proxy_pool/proxy_relay 唯一实现）

端口发现：control_url.py（读 IPC，事实来源）；控制台重启后下次调用自愈重连。

工具描述即 agent 判定的现场引导（每轮注入）：proxy_status 描述内嵌判定 SOP
（三场景：预期挑战不换 / 真限流换 / 烂 IP 淘汰），铁律一=查 rotate_history 补全时间线。
"""
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # control_url 同级
from control_url import resolve_control, make_control_client

_CONTROL: dict = {"base": None}
_client: httpx.AsyncClient | None = None


def _base_url() -> str:
    """控制台地址（延迟解析 + 失败自愈：控制台重启换端口后重新解析）。"""
    if _CONTROL["base"] is None:
        addr = resolve_control()
        if addr is None:
            raise RuntimeError("控制台未启动（IPC 地址不可达）")
        _CONTROL["base"] = addr.url
    return _CONTROL["base"]


@asynccontextmanager
async def _lifespan(server: FastMCP):
    global _client
    _client = make_control_client(timeout=30.0)
    try:
        yield
    finally:
        await _client.aclose()


mcp = FastMCP("proxy", lifespan=_lifespan)


async def _call(method: str, path: str, json_body: dict | None = None) -> str:
    """统一转发：200 返回 JSON 文本；错误返回明确错误说明（含自愈重解析）。"""
    if _client is None:
        return "[错误] MCP 未完成初始化（lifespan 未启动）"
    try:
        r = await _client.request(method, f"{_base_url()}{path}", json=json_body)
        _CONTROL["base"] = None if r.status_code in (404, 502) else _CONTROL["base"]
        if r.status_code == 200:
            import json as _json
            return _json.dumps(r.json(), ensure_ascii=False)
        return f"[错误] 控制台返回 {r.status_code}: {r.text[:300]}"
    except httpx.HTTPError as e:
        _CONTROL["base"] = None  # 清缓存 → 下次重新解析端口（控制台重启自愈）
        return f"[错误] 控制台不可达: {e}"


@mcp.tool(
    description=(
        "查询代理状态与轮换历史（当前出口模式/代理IP/剩余秒数/订单余量/域名冷却表/累计消耗）。"
        "【判定SOP——看到任何限流迹象时的第一个动作就是调本工具】三场景判定："
        "① 1 分钟内有轮换记录（或你刚换过出口）→ 换出口后的预期挑战，"
        "浏览器正自动过（约5秒），等待/刷新即可，不要再换；"
        "② 无近期轮换且任务稳定运行中突发 429/挑战页 → 真限流 → 换出口 + "
        "冷却该域；"
        "③ 刚轮换过且已等待超过30秒仍是挑战 → 当前代理IP信誉差 → 换出口"
        "（reason=bad_ip）。写批量请求脚本前先调本工具查余量规划节奏。"
    ),
)
async def proxy_status() -> str:
    return await _call("GET", "/api/proxy/status")


@mcp.tool(
    description=(
        "换出口（提取新代理IP + 存量连接优雅关闭，在飞响应完整送达）。"
        "可选 reason：agent_rotate（默认，经SOP判定真限流后用）/ "
        "bad_ip（SOP场景③淘汰当前IP时必须传——旧IP进黑名单防再取回）。"
        "未经状态查询判定前不要直接调用（防预期挑战误判导致连环换出口烧配额）。"
    ),
)
async def proxy_rotate(
    reason: Annotated[str, Field(description="agent_rotate | bad_ip")] = "agent_rotate",
) -> str:
    return await _call("POST", "/api/proxy/rotate", {"reason": reason})


@mcp.tool(
    description=(
        "全局出口模式切换 direct↔proxy（校验枚举，切换后存量连接优雅关闭）。"
        "大轰炸任务（密码爆破/目录fuzz/批量验证）开始前切 proxy 省一次撞墙学费，"
        "任务结束切回 direct（省配额）。低频探测（<10发）不需要切。"
    ),
)
async def proxy_mode(
    mode: Annotated[str, Field(description="direct | proxy")],
) -> str:
    return await _call("POST", "/api/proxy/mode", {"mode": mode})


@mcp.tool(
    description=(
        "获取本地代理服务的入口地址（供 HTTP 客户端/浏览器作代理地址使用）。"
        "端口可能因冲突顺延——永远以本工具返回值为准，勿硬编码。"
    ),
)
async def proxy_get_entry() -> str:
    return await _call("GET", "/api/proxy/entry")


if __name__ == "__main__":
    mcp.run()
