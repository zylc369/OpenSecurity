"""/api/models 路由：模型资产查询 + 下载管理。

数据源：services/model_assets.py（与 /api/scan 的 models 字段同源）。
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, HTTPException

from services.model_assets import HardwareSummary, ModelAssetRegistry, ModelAssetStatus

router = APIRouter(prefix="/api/models", tags=["models"])


@dataclass
class ModelsPayload:
    models: "list[ModelAssetStatus]"
    hardware_summary: HardwareSummary
    hf_endpoint: str


@dataclass
class ModelDownloadAck:
    ok: bool
    model_id: str


@router.get("")
async def list_models() -> ModelsPayload:
    """全部模型资产状态（缓存/加载态/引用数）+ 整体硬件评估。"""
    return ModelsPayload(
        models=ModelAssetRegistry.get_instance().get_model_assets(),
        hardware_summary=ModelAssetRegistry.get_instance().hardware_summary(),
        hf_endpoint=ModelAssetRegistry.get_instance()._hf_endpoint(),
    )


@router.post("/{model_id}/download")
async def download_model(model_id: str) -> "ModelDownloadAck":
    """启动后台下载（幂等）。"""
    ok = ModelAssetRegistry.get_instance().start_download(model_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"未知模型 id: {model_id}")
    return ModelDownloadAck(ok=True, model_id=model_id)
