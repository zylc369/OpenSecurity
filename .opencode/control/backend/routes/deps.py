"""/api/deps 路由：依赖详情（按 agent 过滤）。"""
from __future__ import annotations

from fastapi import APIRouter

from services import tools_detector

router = APIRouter(prefix="/api/deps", tags=["deps"])


@router.get("")
async def get_all_deps() -> dict[str, list[dict]]:
    """返回所有 agent 的工具状态。"""
    return tools_detector.scan_all()


@router.get("/{agent}")
async def get_agent_deps(agent: str) -> list[dict]:
    """返回指定 agent 的工具状态。"""
    return tools_detector.scan_agent(agent)
