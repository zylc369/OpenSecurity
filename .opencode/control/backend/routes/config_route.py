"""/api/config/* 路由。

配置 CRUD + 必要配置完整性查询。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import config_store
from routes.deps import invalidate_deps_snapshot

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


@router.get("/meta")
async def get_config_meta() -> dict[str, dict]:
    """配置项元数据（前端差异化渲染的驱动数据）。

    数据源：REQUIRED_CONFIGS ∪ EXTRA_CONFIG_META ∪ REMOTE_TAB_CONFIGS
            ∪ REMOTE_TUNABLE_CONFIGS ∪ .ai_env 实际键。
    type 枚举: password（密文+眼睛）/ path（存在性徽标）/ text / bool。
    hidden=True 的键不进配置页（专属 TAB 管理 / 仅 .ai_env 手编，如远程资源）。
    """
    from config import (
        REQUIRED_CONFIGS, EXTRA_CONFIG_META, REMOTE_TAB_CONFIGS, REMOTE_TUNABLE_CONFIGS,
    )

    meta: dict[str, dict] = {}
    for field in [*REQUIRED_CONFIGS, *EXTRA_CONFIG_META, *REMOTE_TAB_CONFIGS, *REMOTE_TUNABLE_CONFIGS]:
        meta[field.key] = {
            "label": field.label,
            "type": field.type,
            "hint": field.hint,
            "required": field.required,
            "default_value": field.default_value,  # 不配置时后端使用的默认值
            "hidden": field.hidden,
        }
    # .ai_env 中存在但无元数据的键 → text 兜底（保证 meta 覆盖全部键）
    for key in config_store.read_all():
        if key not in meta:
            meta[key] = {"label": key, "type": "text", "hint": "", "required": False,
                         "default_value": "", "hidden": False}
    return meta


@router.get("/required-status")
async def get_required_status() -> dict[str, dict]:
    """获取必要配置完整性（前端 banner 用，keyed dict 契约）。"""
    from dataclasses import asdict
    return {c.key: asdict(c) for c in config_store.required_status()}


@router.get("/{key}")
async def get_config(key: str) -> dict[str, str]:
    """获取单个配置。"""
    value = config_store.read(key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"配置项 {key} 不存在")
    return {"key": key, "value": value}


def _guard_protected_keys(keys) -> None:
    """拒绝直接写远程开关（D10: ENABLED 只能经「切换远程」按钮先校验后置位）。

    通用配置写接口不得绕过 remote_link.switch_to_remote 的校验路径
    （未校验的 ENABLED=1 会让心跳直接把路由切到未验证的远程节点）。
    """
    from config import REMOTE_ENABLED_KEY
    if REMOTE_ENABLED_KEY in keys:
        raise HTTPException(
            status_code=422,
            detail=f"{REMOTE_ENABLED_KEY} 只能经「切换远程」按钮写入（先校验后置位）",
        )


@router.put("")
async def update_configs(req: ConfigUpdate) -> dict[str, str]:
    """批量更新配置。"""
    _guard_protected_keys(req.configs.keys())
    result = config_store.write(req.configs)
    invalidate_deps_snapshot()  # IDA_PRO_HOME 等影响工具检测项
    return result


@router.put("/{key}")
async def update_config(key: str, req: SingleConfigUpdate) -> dict[str, str]:
    """更新单个配置。"""
    _guard_protected_keys([key])
    result = config_store.write_one(key, req.value)
    invalidate_deps_snapshot()
    return result


@router.delete("/{key}")
async def delete_config(key: str) -> dict[str, str]:
    """删除单个配置。"""
    result = config_store.delete(key)
    invalidate_deps_snapshot()
    return result
