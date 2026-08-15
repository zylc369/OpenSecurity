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

from fastapi import APIRouter
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
    }


@router.get("/health")
async def health() -> JSONResponse:
    """健康检查。"""
    if not model_loader.is_models_ready():
        return JSONResponse(
            {"status": "loading", **_identity()},
            status_code=503,
            headers={"Retry-After": "5"},
        )
    return JSONResponse({"status": "ok", **_identity()})
