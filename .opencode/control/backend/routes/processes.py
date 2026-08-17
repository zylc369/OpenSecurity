"""进程清单 API（GET /api/processes）。

返回控制台后端管理的全部进程快照：主进程（含 BGE 模型说明）、
OCR MLX 子进程（引用计数 + 持有者明细 + 最后活跃时间）、vite dev。
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter

from services.process_registry import collect_processes

router = APIRouter(prefix="/api", tags=["processes"])


@router.get("/processes")
def get_processes() -> dict:
    """受管进程清单（前端进程页 10s 轮询）。"""
    view = collect_processes()
    return asdict(view)
