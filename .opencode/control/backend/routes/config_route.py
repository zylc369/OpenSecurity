"""/api/config/* 路由。

配置 CRUD + 必要配置完整性查询。

接口契约（全路由统一）:
  • 全部 POST——请求结构化（pydantic 模型承载，即使单字段也包装成类;
    原则上禁止 GET）
  • surfaces 以**列表**贯穿全链路（HTTP body → 领域模型 get_entries），
    与 ConfigManager 的场景轴签名一致; 读返回所请求场景的生效值，
    写只能写所请求场景内的键（交集语义，服务端按场景过滤与校验——
    页面组成权在服务端，前端零过滤逻辑）
  • 数据源统一为 ConfigManager 领域模型（get_entries / get_kv_list），
    路由层只做 DTO 转换
"""
from __future__ import annotations

from collections.abc import Collection
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.config_manager import (
    ConfigManager, ConfigMetaView, Surface,
)
from routes.deps import invalidate_deps_snapshot

router = APIRouter(prefix="/api/config", tags=["config"])

# 请求体值域（不含 hidden——那是存储态，不是页面身份）
SurfaceParam = Literal["config", "remote"]


class ConfigQuery(BaseModel):
    """读接口请求体（surfaces 列表与 manager 层链路一致）。"""
    surfaces: list[SurfaceParam] = Field(min_length=1)


class ConfigUpdate(BaseModel):
    """批量更新请求体。"""
    surfaces: list[SurfaceParam] = Field(min_length=1)
    configs: dict[str, str]


class ConfigDelete(BaseModel):
    """删除请求体。"""
    surfaces: list[SurfaceParam] = Field(min_length=1)
    keys: list[str] = Field(min_length=1)


def _surfaces_of(values: list[SurfaceParam]) -> list[Surface]:
    return [Surface(v) for v in values]


@router.post("/list")
async def get_config_kv_list(req: ConfigQuery) -> dict[str, str]:
    """获取指定场景列表的配置生效值 KV（配置值优先，空/缺失回退 ConfigField
    声明默认值）。

    默认值唯一权威在后端声明处——插件/前端不再各自维护默认值副本;
    无默认且未配置的键不出现，消费方按 fail-safe 处理。
    """
    return ConfigManager.get_instance().get_kv_list(_surfaces_of(req.surfaces))


@router.post("/meta")
async def get_config_meta(req: ConfigQuery) -> ConfigMetaView:
    """配置项元数据 + 生效值（前端差异化渲染的驱动数据，按请求场景过滤）。

    数据源: 统一领域模型 get_entries(surfaces)——声明字段（场景交集过滤）
    ∪ .ai_env 手写键（仅 config 面，OTHER 分类兜底）。
    type 枚举: password（密文+眼睛）/ path（存在性徽标）/ text / bool。
    响应内嵌有序 categories（code+desc; desc 服务端权威，前端原样显示）;
    readonly=true 的条目任何页面禁用态渲染; value 为生效值（单请求可渲染）。
    """
    return ConfigManager.get_instance().config_meta(_surfaces_of(req.surfaces))


@router.post("/required-status")
async def get_required_status(req: ConfigQuery) -> "dict[str, ConfigManager.ConfigStatusView]":
    """获取指定场景列表的必要配置完整性（前端 banner 用，keyed dict 契约）。"""
    return {c.key: c for c
            in ConfigManager.get_instance().required_status(_surfaces_of(req.surfaces))}


def _guard_protected_keys(keys: Collection[str]) -> None:
    """拒绝直接写远程开关（D10: ENABLED 只能经「切换远程」按钮先校验后置位）。

    通用配置写接口不得绕过 remote_link.switch_to_remote 的校验路径
    （未校方的 ENABLED=1 会让心跳直接把路由切到未验证的远程节点）。
    """
    if ConfigManager.get_instance().Keys.REMOTE_CONSOLE_ENABLED in keys:
        raise HTTPException(
            status_code=422,
            detail=f"{ConfigManager.get_instance().Keys.REMOTE_CONSOLE_ENABLED} 只能经「切换远程」按钮写入（先校验后置位）",
        )


def _guard_surface(keys: Collection[str], surfaces: list[SurfaceParam]) -> None:
    """写接口的场景归属校验（交集语义——与读过滤同一声明数据源）。

    - 未声明键 → 422（声明是配置存在的前提——新增键先在 _FIELDS 添加，
      才能被感知、被审计、被 review）
    - 声明键与请求场景无交集 → 422（页面只能写自己场景的配置）
    - readonly 键 → 422（"先只读后开放"的开关在服务端，非仅 UI 禁用）
    """
    cm = ConfigManager.get_instance()
    wanted = set(surfaces)
    for key in keys:
        field = cm.field_of(key)
        if field is None:
            raise HTTPException(
                status_code=422,
                detail=f"配置 {key} 未声明——新增键请先在 ConfigManager._FIELDS 添加声明",
            )
        if not wanted.intersection(s.value for s in field.surfaces):
            raise HTTPException(
                status_code=422,
                detail=f"配置 {key} 不属于 {sorted(wanted)} 页面（surfaces={[s.value for s in field.surfaces]}）",
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


@router.post("/update")
async def update_configs(req: ConfigUpdate) -> dict[str, str]:
    """批量更新配置（只能写所请求场景内的键）。

    响应为所请求场景的生效值 KV（与 /list 同契约）——保存方直接以响应
    为新基线，避免原始值响应覆盖默认值支撑的表单状态。
    """
    _guard_protected_keys(req.configs.keys())
    _guard_surface(req.configs.keys(), req.surfaces)
    ConfigManager.get_instance().set(req.configs)
    _after_write(req.configs.keys())
    return ConfigManager.get_instance().get_kv_list(_surfaces_of(req.surfaces))


@router.post("/delete")
async def delete_configs(req: ConfigDelete) -> dict[str, str]:
    """批量删除配置（readonly/跨场景键同样拒绝删除）。

    响应为所请求场景的生效值 KV，与 /list 同契约——删除后未配置键
    回落声明默认值）。
    """
    _guard_protected_keys(req.keys)
    _guard_surface(req.keys, req.surfaces)
    for key in req.keys:
        ConfigManager.get_instance().delete(key)
    _after_write(req.keys)
    return ConfigManager.get_instance().get_kv_list(_surfaces_of(req.surfaces))
