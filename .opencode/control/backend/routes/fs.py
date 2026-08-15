"""/api/fs/check 路由：路径存在性检查。

用途：前端配置表单对路径类配置实时校验（输入框后绿"存在"/红"不存在"徽标）。
安全：控制台仅监听 127.0.0.1，本接口只做存在性判断不返回目录内容。
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/fs", tags=["fs"])


@router.get("/check")
async def check_path(path: str = Query(..., min_length=1)) -> dict:
    """检查路径存在性（支持 ~ 展开）。"""
    resolved = str(Path(path).expanduser())
    p = Path(resolved)
    return {
        "path": path,
        "resolved": resolved,
        "exists": p.exists(),
        "is_dir": p.is_dir() if p.exists() else False,
    }
