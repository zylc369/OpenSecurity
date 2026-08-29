"""/health 路由。

模型加载中返回 503（带 Retry-After），加载完成返回 200。
依赖方通过本路由判断控制台是否就绪。

注意：uvicorn 启动后 /health 立即可访问（B 方案），即使模型还在加载。

识别字段（service/pid/start_time）：200 和 503 都返回。
用途：依赖方通过 /health 语义判断就绪状态与实例身份。
"""
from __future__ import annotations

import os
import secrets

from fastapi import APIRouter

# 进程镜像启动令牌：每次进程启动（含 execv 自重启）生成新值。
# 用途：前端判定"重启已完成"——exec 下 PID 与 process start_time 均不变，
# 唯有本令牌必变。
BOOT_TOKEN = secrets.token_hex(4)
from fastapi.responses import JSONResponse

from services import model_loader
from services.process_lock import get_process_start_time

router = APIRouter()


@router.post("/api/dev-url")
async def report_dev_url(payload: dict) -> dict:
    """vite dev server 上报实际端口（经 IPC，取代 .vite-dev.port 文件）。

    vite 冲突自动递增（5173→5174）时上报的是递增后的真实端口。
    注册进 FrontendPortRegistry（唯一事实源）。
    """
    port = payload.get("port")
    if isinstance(port, int) and 0 < port < 65536:
        from services.frontend_port import frontend_ports
        frontend_ports.register_vite_port(port)
        return {"ok": True, "port": port}
    return {"ok": False, "error": "invalid port"}


@router.get("/api/console-url")
async def console_url() -> dict:
    """控制台前端真实地址（浏览器 TCP 顺延后插件/vite 从这里取）。"""
    from services.frontend_port import frontend_ports
    tcp_port = frontend_ports.tcp_port()
    return {
        "url": frontend_ports.console_url(),
        "tcp_port": tcp_port,
        "tcp_candidates": frontend_ports.tcp_candidates(),
    }


def _identity() -> dict:
    """控制台实例身份字段（探测协议）。"""
    return {
        "service": "opencode-control",
        "pid": os.getpid(),
        "start_time": get_process_start_time(os.getpid()) or 0,
        "boot_token": BOOT_TOKEN,
    }


def _code_fingerprint() -> tuple[int, float]:
    """backend 代码指纹: (py 文件数, max mtime)。变更任一 .py → 指纹变。"""
    import glob
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
    files = glob.glob(os.path.join(base, "**", "*.py"), recursive=True)
    return (len(files), max((os.path.getmtime(f) for f in files), default=0.0))


# 进程启动时冻结的代码指纹——与当前指纹比对检测"代码已更新但进程未重启"
_BOOT_FINGERPRINT = _code_fingerprint()


@router.get("/health")
@router.get("/api/health")
async def health() -> JSONResponse:
    """健康检查（/api/health 是前端轮询别名——vite dev 代理只转发 /api 前缀）。

    code_stale=True: backend 代码在进程启动后变更过（清单/逻辑更新未生效）——
    前端应提示重启控制台后端。
    """
    stale = _code_fingerprint() != _BOOT_FINGERPRINT
    if not model_loader.is_models_ready():
        return JSONResponse(
            {"status": "loading", "code_stale": stale, **_identity()},
            status_code=503,
            headers={"Retry-After": "5"},
        )
    return JSONResponse({"status": "ok", "code_stale": stale, **_identity()})
