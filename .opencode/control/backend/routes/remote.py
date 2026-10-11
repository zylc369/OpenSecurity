"""远程资源管理 API（模型远程化一期）。

主控端点（本机; guard 默认仅放行本机访问管理面）:
  • GET  /api/remote/status   状态机快照（前端 TAB 单一事实源; token 脱敏）
  • POST /api/remote/switch   切换远程（先校验）/ 切换本地
  • PUT  /api/remote/config   写 URL/TOKEN（ENABLED 不可经此写）+ 热重载

节点端点（局域网 + token; ?node=remote 时主控转发到远程节点）:
  • GET  /api/remote/health      轻量健康 + 三模型指纹
  • GET/PUT /api/remote/node-config  节点三 KEY（RESIDENT/AUTOSTART/API_KEY）
  • GET/POST /api/remote/autostart   LaunchAgent 安装/卸载/状态
"""
from __future__ import annotations

import dataclasses
import platform
from typing import Any, Callable, ParamSpec, TypeVar

from dataclasses import asdict, dataclass, field

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.config_manager import ConfigManager
from services.remote_client import ModelFingerprint, RemoteConsoleClient
from services.remote_link import RemoteLinkService, RemoteLinkStatus

router = APIRouter(prefix="/api/remote", tags=["remote"])


# ─── 主控端点 ─────────────────────────────────────────

@router.get("/status")
async def get_status() -> "RemoteLinkStatus":
    """状态机快照（RemoteLinkStatus 序列化; token 仅回传前 6 位）。"""
    return RemoteLinkService.get_instance().status()


class SwitchRequest(BaseModel):
    transport: str  # "p2p" | "http"（切换到对应管道）| ""（关闭——清空模式）


@dataclass
class SwitchOutcome:
    ok: bool
    error: str = ""
    warnings: "list[str]" = field(default_factory=list)
    detail: "str | None" = None   # 仅失败时（前端 axios 拦截器读 detail 展示）


@dataclass
class FingerprintPayload:
    service: str
    version: str
    models: "list[ModelFingerprint]"


@router.post("/switch")
async def switch(req: SwitchRequest) -> SwitchOutcome:
    """切换远程管道（先校验——失败返回原因不置位）/ 关闭（清空模式）。"""
    from services.config_manager import RemoteTransportMode
    svc = RemoteLinkService.get_instance()
    if req.transport == "p2p":
        result = await svc.switch_transport(RemoteTransportMode.P2P)
    elif req.transport == "http":
        result = await svc.switch_transport(RemoteTransportMode.HTTP)
    elif req.transport == "":
        result = svc.switch_off()
    else:
        raise HTTPException(status_code=422, detail="transport 须是 p2p、http 或空串（关闭）")
    return SwitchOutcome(ok=result.ok, error=result.error, warnings=result.warnings,
                         detail=result.error if not result.ok else None)


# ─── 节点端点（本机直连 = 操作本机; node=remote = 主控转发）────

def _forward_or_local(node: str):
    """node=remote 时返回远程转发 client; 否则 None（操作本机）。"""
    if node != "remote":
        return None
    if not RemoteLinkService.get_instance().should_use_remote() and not _remote_url_configured():
        raise HTTPException(status_code=409, detail="先配置远程连接（URL+TOKEN）再管理远程节点")
    try:
        return RemoteLinkService.get_instance().get_client()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


def _remote_url_configured() -> bool:
    return bool((ConfigManager.get_instance().get(ConfigManager.Keys.REMOTE_CONSOLE_URL) or "").strip())


def _fingerprint_payload() -> FingerprintPayload:
    """本机三模型指纹（HF snapshot hash; 不加载模型）。"""
    
    from services.model_loader import ModelInferenceService
    from services.ocr_service import OcrService
    fps = RemoteLinkService.get_instance()._local_fingerprints()
    return FingerprintPayload(
        service="opencode-control",
        version=f"{platform.system()}/{ConfigManager.Protocol.EMBED_MODEL}",
        models=[
            ModelFingerprint(repo_id=ConfigManager.Protocol.EMBED_MODEL,
                             snapshot=fps.get(ConfigManager.Protocol.EMBED_MODEL, ""),
                             loaded=ModelInferenceService.get_instance().embedder_status().state == "ready"),
            ModelFingerprint(repo_id=ConfigManager.Protocol.RERANKER_MODEL,
                             snapshot=fps.get(ConfigManager.Protocol.RERANKER_MODEL, ""),
                             loaded=ModelInferenceService.get_instance().reranker_status().state == "ready"),
            ModelFingerprint(repo_id="glm-ocr",
                             snapshot=fps.get("glm-ocr", ""),
                             loaded=OcrService.get_instance().status().state == "ready"),
        ],
    )


@router.get("/health")
async def node_health(node: str = Query(default="local")) -> JSONResponse:
    """轻量健康（心跳探测目标; 局域网 + token）。transit 端点：JSON 直通。"""
    client = _forward_or_local(node)
    if client is not None:
        return JSONResponse(content=await _forward_get(client, "/api/remote/health"))
    return JSONResponse(content=asdict(_fingerprint_payload()))


async def _forward_get(client: RemoteConsoleClient, path: str) -> "dict[str, object]":
    """经 remote_client 的底层 GET 转发（to_thread——同步 httpx 禁跑事件循环，
    节点网络黑洞时冻结整个控制台是 B2 级故障）。"""
    import asyncio
    try:
        return await asyncio.to_thread(client._get_json, path)  # noqa: SLF001 —— 转发通道
    except Exception as e:  # noqa: BLE001 —— RemoteUnavailable/httpx 统一 502
        raise HTTPException(status_code=502, detail=f"远程节点不可达: {e}")


_P = ParamSpec("_P")
_R = TypeVar("_R")


async def _forward_call(fn: Callable[_P, _R], *args: _P.args, **kwargs: _P.kwargs) -> _R:
    """转发写操作（to_thread，同 _forward_get 的线程域约束）。"""
    import asyncio
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"转发失败: {e}")


_NODE_CONFIG_KEYS = frozenset({ConfigManager.Keys.CONTROL_RESIDENT, ConfigManager.Keys.CONTROL_AUTOSTART, ConfigManager.Keys.CONTROL_API_KEY})


@router.get("/node-config")
async def get_node_config(node: str = Query(default="local")) -> JSONResponse:
    """读节点三 KEY（本机或转发; API_KEY 脱敏为前 6 位）。transit 端点：JSON 直通。"""
    client = _forward_or_local(node)
    if client is not None:
        return JSONResponse(content=await _forward_get(client, "/api/remote/node-config"))
    result: dict[str, str] = {}
    for key in sorted(_NODE_CONFIG_KEYS):
        val = (ConfigManager.get_instance().get(key) or "").strip()
        if key == ConfigManager.Keys.CONTROL_API_KEY and val:
            val = val[:6]  # 脱敏
        result[key] = val
    return JSONResponse(content=result)


class NodeConfigUpdate(BaseModel):
    configs: dict[str, str]


@router.put("/node-config")
async def put_node_config(req: NodeConfigUpdate, node: str = Query(default="local")) -> JSONResponse:
    """写节点三 KEY（白名单外拒绝; API_KEY 变更提示重启生效——绑定地址）。transit 端点。"""
    illegal = sorted(set(req.configs.keys()) - _NODE_CONFIG_KEYS)
    if illegal:
        raise HTTPException(status_code=422, detail=f"仅允许 {_NODE_CONFIG_KEYS}，非法键: {illegal}")
    client = _forward_or_local(node)
    if client is not None:
        return JSONResponse(content=await _forward_call(client.put_node_config, req.configs))
    ConfigManager.get_instance().set({k: v.strip() for k, v in req.configs.items()})
    changed_binding = ConfigManager.Keys.CONTROL_API_KEY in req.configs
    return JSONResponse(content={"ok": True, "reboot_required": changed_binding,
                                  "hint": "CONTROL_API_KEY 变更后需重启控制台生效（绑定地址与鉴权）" if changed_binding else ""})


@router.post("/update-restart")
async def update_and_restart_remote() -> JSONResponse:
    """远程节点: git pull + 自重启（主控「更新并重启」按钮后端）。

    返回旧 boot_token——前端轮询远程 /api/health 直到 boot_token 变化
    （exec 重启 PID 不变、boot_token 必变——进程身份判定的唯一可靠信号）。
    """
    import asyncio
    from typing import cast
    from services.remote_link import RemoteLinkService
    client = RemoteLinkService.get_instance().get_client()
    pull = cast("dict[str, object]", await asyncio.to_thread(
        client._post_json, "/api/system/git-pull", {}))  # noqa: SLF001 —— 转发层
    if pull.get("ok") is not True:
        return JSONResponse(status_code=502,
                            content={"ok": False, "stage": "git-pull",
                                     "error": str(pull.get("error", "未知"))})
    health_before = cast("dict[str, object]", await asyncio.to_thread(
        client._get_json, "/api/health"))  # noqa: SLF001
    await asyncio.to_thread(
        client._post_json, "/api/system/restart", {})  # noqa: SLF001
    return JSONResponse(content={
        "ok": True, "old_boot_token": str(health_before.get("boot_token", "")),
        "pull_output": str(pull.get("output", ""))[:200]})


@router.get("/health-forward")
async def remote_health_forward() -> JSONResponse:
    """远程节点 /api/health 透传（前端轮询 boot_token 判定重启完成）。"""
    import asyncio
    from typing import cast
    from services.remote_link import RemoteLinkService
    client = RemoteLinkService.get_instance().get_client()
    data = cast("dict[str, object]", await asyncio.to_thread(
        client._get_json, "/api/health"))  # noqa: SLF001 —— 转发层
    return JSONResponse(content=data)


@router.get("/autostart")
async def get_autostart(node: str = Query(default="local")) -> JSONResponse:
    """LaunchAgent 安装状态。transit 端点。"""
    client = _forward_or_local(node)
    if client is not None:
        return JSONResponse(content=await _forward_get(client, "/api/remote/autostart"))
    from services.launchd_setup import LaunchdManager
    st = LaunchdManager.get_instance().status()
    return JSONResponse(content=dataclasses.asdict(st))


class AutostartRequest(BaseModel):
    enable: bool


@router.post("/autostart")
async def set_autostart(req: AutostartRequest, node: str = Query(default="local")) -> JSONResponse:
    """安装/卸载 LaunchAgent。transit 端点。"""
    client = _forward_or_local(node)
    if client is not None:
        return JSONResponse(content=await _forward_call(client.post_autostart, req.enable))
    from services.launchd_setup import LaunchdManager
    try:
        result = LaunchdManager.get_instance().install() if req.enable else LaunchdManager.get_instance().uninstall()
        return JSONResponse(content=asdict(result))
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
