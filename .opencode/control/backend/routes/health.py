"""/health 路由。

模型加载中返回 503（带 Retry-After），加载完成返回 200。
embed_client.py 通过本路由判断控制台是否就绪。

注意：uvicorn 启动后 /health 立即可访问（B 方案），即使模型还在加载。

识别字段（service/pid/start_time）：200 和 503 都返回。
用途：port_manager.probe_live_control() 在端口文件丢失时，通过这些字段
识别候选端口上是否有本体系控制台（孤儿实例），避免误判其他服务。
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


def _identity() -> dict:
    """控制台实例身份字段（探测协议）。"""
    return {
        "service": "opencode-control",
        "pid": os.getpid(),
        "start_time": get_process_start_time(os.getpid()) or 0,
        "boot_token": BOOT_TOKEN,
    }


@router.get("/health")
@router.get("/api/health")
async def health() -> JSONResponse:
    """健康检查（/api/health 是前端轮询别名——vite dev 代理只转发 /api 前缀）。"""
    if not model_loader.is_models_ready():
        return JSONResponse(
            {"status": "loading", **_identity()},
            status_code=503,
            headers={"Retry-After": "5"},
        )
    return JSONResponse({"status": "ok", **_identity()})
