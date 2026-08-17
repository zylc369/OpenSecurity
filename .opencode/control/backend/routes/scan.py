"""/api/scan 路由：全量扫描。"""
from __future__ import annotations

from dataclasses import asdict

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
        "agents": {agent: [asdict(t) for t in tools]
                   for agent, tools in result.agents.items()},
        "global": {
            "docker": asdict(result.global_.docker),
            "required_configs": {c.key: asdict(c) for c in result.global_.required_configs},
            "python_packages": [asdict(p) for p in result.global_.python_packages],
            "models": [asdict(m) for m in result.global_.models],
        },
        "timestamp": result.timestamp,
    }
