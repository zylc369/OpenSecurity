"""/api/scan 路由：全量扫描。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from services.scanner import get_scanner

router = APIRouter(prefix="/api/scan", tags=["scan"])


@router.get("")
async def scan_all(force_refresh: bool = Query(False)) -> dict:
    """全量扫描所有 agent + 全局资源。

    Args:
        force_refresh: 强制刷新缓存。
    """
    result = await get_scanner().scan_all(force_refresh=force_refresh)
    return {
        "agents": result.agents,
        "global": result.global_,
        "timestamp": result.timestamp,
    }
