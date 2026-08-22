"""心跳路由: opencode 插件周期上报存活 + 前端查询。

协议见 services/heartbeat.py 模块注释。表空自杀判定在 HeartbeatTask，
本路由只做 O(1) 记录与快照查询。
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from services.heartbeat import collect_opencode_processes, heartbeats

router = APIRouter(prefix="/api")


class HeartbeatBody(BaseModel):
    """心跳请求体。"""

    pid: int = Field(gt=0, description="opencode 进程 PID")


@router.post("/heartbeat")
async def heartbeat(body: HeartbeatBody) -> dict[str, object]:
    heartbeats.record(body.pid)
    return {"ok": True, "active": heartbeats.active_count()}


@router.get("/heartbeats")
async def list_heartbeats() -> dict[str, Any]:
    """连接的 opencode 进程清单（「运行状态」页数据源）。

    psutil 富化见 services.collect_opencode_processes; 本路由仅序列化。
    """
    return {"opencode": [asdict(i) for i in collect_opencode_processes()]}
