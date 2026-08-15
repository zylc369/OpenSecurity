"""/api/models 路由：模型资产查询 + 下载管理。

数据源：services/model_assets.py（与 /api/scan 的 models 字段同源）。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from services import model_assets

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("")
async def list_models() -> dict:
    """全部模型资产状态（缓存/硬件评估/下载进度）。"""
    return {
        "models": model_assets.get_model_assets(),
        "hf_endpoint": model_assets._hf_endpoint(),
    }


@router.post("/{model_id}/download")
async def download_model(model_id: str) -> dict:
    """启动后台下载（幂等）。"""
    ok = model_assets.start_download(model_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"未知模型 id: {model_id}")
    return {"ok": True, "model_id": model_id}
