"""心跳路由: opencode 插件周期上报存活。

协议见 services/heartbeat.py 模块注释。表空自杀判定在 HeartbeatTask，
本路由只做 O(1) 记录。
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from services.heartbeat import heartbeats

router = APIRouter(prefix="/api")


class HeartbeatBody(BaseModel):
    """心跳请求体。"""

    pid: int = Field(gt=0, description="opencode 进程 PID")


@router.post("/heartbeat")
async def heartbeat(body: HeartbeatBody) -> dict[str, object]:
    heartbeats.record(body.pid)
    return {"ok": True, "active": heartbeats.active_count()}
