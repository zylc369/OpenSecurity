"""/api/config/* 路由。

配置 CRUD + 必要配置完整性查询。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import config_store

router = APIRouter(prefix="/api/config", tags=["config"])


class ConfigUpdate(BaseModel):
    """批量更新请求体。"""
    configs: dict[str, str]


class SingleConfigUpdate(BaseModel):
    """单条更新请求体。"""
    value: str


@router.get("")
async def get_all_configs() -> dict[str, str]:
    """获取全部配置。"""
    return config_store.read_all()


@router.get("/required-status")
async def get_required_status() -> dict[str, dict]:
    """获取必要配置完整性（前端 banner 用）。"""
    return config_store.required_status()


@router.get("/{key}")
async def get_config(key: str) -> dict[str, str]:
    """获取单个配置。"""
    value = config_store.read(key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"配置项 {key} 不存在")
    return {"key": key, "value": value}


@router.put("")
async def update_configs(req: ConfigUpdate) -> dict[str, str]:
    """批量更新配置。"""
    return config_store.write(req.configs)


@router.put("/{key}")
async def update_config(key: str, req: SingleConfigUpdate) -> dict[str, str]:
    """更新单个配置。"""
    return config_store.write_one(key, req.value)


@router.delete("/{key}")
async def delete_config(key: str) -> dict[str, str]:
    """删除单个配置。"""
    return config_store.delete(key)
