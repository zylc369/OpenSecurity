"""/api/config/* 路由。

配置 CRUD + 必要配置完整性查询。

页面声明模型: meta/写接口的 surface 参数必填（config=配置页 / remote=远程页），
服务端按请求面过滤返回与校验写入——页面组成权在服务端，前端零过滤逻辑。
"""
from __future__ import annotations

from collections.abc import Collection
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from dataclasses import dataclass

from services.config_manager import (
    ConfigManager, ConfigMetaEntry, ConfigMetaView, Surface,
)
from routes.deps import invalidate_deps_snapshot

router = APIRouter(prefix="/api/config", tags=["config"])

# 请求参数值域（不含 hidden——那是存储态，不是页面身份）
SurfaceParam = Literal["config", "remote"]


@dataclass
class KeyValue:
    key: str
    value: str



class ConfigUpdate(BaseModel):
    """批量更新请求体。"""
    configs: dict[str, str]


class SingleConfigUpdate(BaseModel):
    """单条更新请求体。"""
    value: str


@router.get("")
async def get_all_configs() -> dict[str, str]:
    """获取全部配置。"""
    return ConfigManager.get_instance().get_all()


@router.get("/meta")
async def get_config_meta(surface: SurfaceParam = Query(...)) -> ConfigMetaView:
    """配置项元数据（前端差异化渲染的驱动数据，按请求面过滤）。

    数据源: 全部 ConfigField 声明清单（surface 匹配过滤）∪ .ai_env 实际键
    （仅 config 面，OTHER 分类兜底）。
    type 枚举: password（密文+眼睛）/ path（存在性徽标）/ text / bool。
    响应内嵌有序 categories（code+desc; desc 服务端权威，前端原样显示）;
    readonly=true 的条目任何页面禁用态渲染。
    """

    return ConfigManager.get_instance().config_meta(Surface(surface))


@router.get("/required-status")
async def get_required_status() -> "dict[str, ConfigManager.ConfigStatusView]":
    """获取必要配置完整性（前端 banner 用，keyed dict 契约）。"""
    return {c.key: c for c in ConfigManager.get_instance().required_status()}


@router.get("/{key}")
async def get_config(key: str) -> KeyValue:
    """获取单个配置。"""
    value = ConfigManager.get_instance().get(key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"配置项 {key} 不存在")
    return KeyValue(key=key, value=value)


def _guard_protected_keys(keys: Collection[str]) -> None:
    """拒绝直接写远程开关（D10: ENABLED 只能经「切换远程」按钮先校验后置位）。

    通用配置写接口不得绕过 remote_link.switch_to_remote 的校验路径
    （未校验的 ENABLED=1 会让心跳直接把路由切到未验证的远程节点）。
    """
    
    if ConfigManager.get_instance().Keys.REMOTE_CONSOLE_ENABLED in keys:
        raise HTTPException(
            status_code=422,
            detail=f"{ConfigManager.get_instance().Keys.REMOTE_CONSOLE_ENABLED} 只能经「切换远程」按钮写入（先校验后置位）",
        )


def _guard_surface(keys: Collection[str], surface: SurfaceParam) -> None:
    """写接口的页面归属校验（与 meta 过滤同一声明数据源——ConfigField）。

    - 声明键 surface 不匹配请求面 → 422（页面只能写自己渲染的配置）
    - readonly 键 → 422（"先只读后开放"的开关在服务端，非仅 UI 禁用）
    - 未声明键: 仅 config 面放行（OTHER 分类兜底语义）; remote 面拒绝
    """
    cm = ConfigManager.get_instance()
    for key in keys:
        field = cm.field_of(key)
        if field is None:
            if surface != "config":
                raise HTTPException(
                    status_code=422,
                    detail=f"配置 {key} 未声明，远程页只能写已声明的远程配置",
                )
            continue
        if field.surface.value != surface:
            raise HTTPException(
                status_code=422,
                detail=f"配置 {key} 不属于 {surface} 页面（surface={field.surface.value}）",
            )
        if field.readonly:
            raise HTTPException(
                status_code=422,
                detail=f"{key} 为只读配置，不能经配置接口写入",
            )


# 远程链接键: 写后触发热重载（key 触发副作用——同 invalidate_deps_snapshot 模式）
_REMOTE_LINK_KEYS = frozenset({
    ConfigManager.Keys.REMOTE_CONSOLE_URL,
    ConfigManager.Keys.REMOTE_CONSOLE_TOKEN,
})


def _after_write(keys: Collection[str]) -> None:
    """写后副作用（key 触发）: 工具检测快照失效 + 远程链接热重载。"""
    invalidate_deps_snapshot()  # IDA_PRO_HOME 等影响工具检测项
    if any(k in _REMOTE_LINK_KEYS for k in keys):
        from services.remote_link import RemoteLinkService
        RemoteLinkService.get_instance().reload_config()


@router.put("")
async def update_configs(req: ConfigUpdate, surface: SurfaceParam = Query(...)) -> dict[str, str]:
    """批量更新配置（surface 必填——页面只能写自己面的配置）。"""
    _guard_protected_keys(req.configs.keys())
    _guard_surface(req.configs.keys(), surface)
    result = ConfigManager.get_instance().set(req.configs)
    _after_write(req.configs.keys())
    return result


@router.put("/{key}")
async def update_config(key: str, req: SingleConfigUpdate,
                        surface: SurfaceParam = Query(...)) -> dict[str, str]:
    """更新单个配置（surface 必填）。"""
    _guard_protected_keys([key])
    _guard_surface([key], surface)
    result = ConfigManager.get_instance().set({key: req.value})
    _after_write([key])
    return result


@router.delete("/{key}")
async def delete_config(key: str, surface: SurfaceParam = Query(...)) -> dict[str, str]:
    """删除单个配置（surface 必填; readonly/跨面键同样拒绝删除）。"""
    _guard_protected_keys([key])
    _guard_surface([key], surface)
    result = ConfigManager.get_instance().delete(key)
    _after_write([key])
    return result
