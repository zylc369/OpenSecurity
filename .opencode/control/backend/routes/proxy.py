"""/api/proxy 路由：代理 IP 池控制接口（仅 127.0.0.1，控制台默认 bind）。

调用方：proxy MCP（对话流工具转发）、控制台前端（未来）。
参数校验铁则（需求 §4.3）：url 必传、无法提取 host 拒绝、mode/reason 枚举；
域名一律经 pool.normalize_domain 归一化后入表（唯一实现收口）。

错误语义：
  400 参数不合法（缺 url/mode 非法/reason 非法/无法提取 host）
  422 供应商侧不可用（凭证未配置/提取失败）——direct 模式不受影响
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import PROXY_RELAY_PORT_START
from services.proxy_pool import JuliangError, get_pool

router = APIRouter(prefix="/api/proxy", tags=["proxy"])

_VALID_REASONS = ("agent_rotate", "bad_ip")


class ModeBody(BaseModel):
    mode: str


class DomainLimitedBody(BaseModel):
    url: str = ""       # 默认空 → 缺失时由手写校验统一回 400（需求约定）
    minutes: float = 10.0


class RotateBody(BaseModel):
    reason: str = "agent_rotate"


def _relay_port() -> int:
    """relay 真实端口：优先 relay 注册值（步骤 3a 起生效），否则配置起点。"""
    try:
        from services.proxy_relay import relay_port
        return relay_port()
    except Exception:
        return PROXY_RELAY_PORT_START


@router.get("/status")
async def proxy_status() -> dict:
    """全量状态（含 rotate_history——判定 SOP 第一步，铁律一）。"""
    st = get_pool().status()
    st["relay_port"] = _relay_port()
    return st


@router.post("/rotate")
async def proxy_rotate(body: RotateBody | None = None) -> dict:
    """换出口。reason=bad_ip 时旧 IP 进黑名单（SOP 场景 C 烂 IP 淘汰）。
    成功后触发存量隧道优雅关闭（在飞响应送达，新连接走新出口）。"""
    reason = (body.reason if body else None) or "agent_rotate"
    if reason not in _VALID_REASONS:
        raise HTTPException(400, f"reason 必须为 {_VALID_REASONS}")
    try:
        info = await get_pool().rotate(reason)
        from services.proxy_relay import graceful_close_upstreams
        await graceful_close_upstreams()
    except JuliangError as e:
        raise HTTPException(422, str(e)) from e
    st = get_pool().status()
    return {"current": info.ip, "expire_in_sec": st["expire_in_sec"],
            "surplus": st["surplus"], "reason": reason}


@router.post("/mode")
async def proxy_mode(body: ModeBody) -> dict:
    """全局粗开关 direct↔proxy（校验枚举，记 history）。切换后优雅关闭存量。"""
    if body.mode not in ("direct", "proxy"):
        raise HTTPException(400, "mode 必须为 direct 或 proxy")
    result = get_pool().set_mode(body.mode)
    try:
        from services.proxy_relay import graceful_close_upstreams
        await graceful_close_upstreams()
    except Exception:
        pass  # relay 未启动时切换模式无需关连接
    return {"mode": result}


@router.post("/domain_limited")
async def proxy_domain_limited(body: DomainLimitedBody) -> dict:
    """登记域名冷却（url 必传；归一化提取域名后入表，§5.1）。"""
    if not body.url or not body.url.strip():
        raise HTTPException(400, "url 必传")
    try:
        domain = get_pool().domain_cool(body.url, body.minutes)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "domain": domain}


@router.get("/entry")
async def proxy_entry() -> dict:
    """代理入口（端口读真实值）。仅 proxy 模式下确保池内有可用 IP——
    direct 模式流量走本机不需要 IP，避免白白提取浪费配额（冷却域场景由
    relay 建隧道时惰性提取兜底）。"""
    pool = get_pool()
    warning = None
    if pool.status()["mode"] == "proxy":
        try:
            await pool.get()
        except JuliangError as e:
            warning = str(e)  # 提取失败不阻塞入口返回（direct 可用，附警告）
    return {"proxy": f"http://127.0.0.1:{_relay_port()}", "mode": pool.status()["mode"],
            "warning": warning}
