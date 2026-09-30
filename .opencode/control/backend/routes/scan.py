"""/api/scan 路由：全量扫描。"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from services.scanner import Scanner, ScanResult

router = APIRouter(prefix="/api/scan", tags=["scan"])


@router.get("")
async def scan_all(force_refresh: bool = Query(False)) -> JSONResponse:
    """全量扫描所有 agent + 全局资源。

    ScanResult.global_ 字段（"global" 是 Python 关键字）序列化时键名归位。
    """
    result = await Scanner.get_instance().scan_all(force_refresh=force_refresh)
    payload = asdict(result)
    payload["global"] = payload.pop("global_")
    return JSONResponse(content=payload)
