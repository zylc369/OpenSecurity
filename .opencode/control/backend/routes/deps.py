"""/api/deps 路由：依赖详情（按 agent 过滤）+ 环境就绪 summary。

两阶段架构（DepsService 类承载）：
  阶段 1（贵，缓存）——快照层：五类原始数据全量并行扫描一次，
    结果与 agent 无关（同一台机器同一时刻的状态）。
    TTL 30s + 单飞（并发请求共享同一份构建结果）+ 主动失效
    （依赖状态变更路由调用 invalidate_deps_snapshot）+ ?refresh=1。
  阶段 2（便宜，永远现算）——组装层：按 agent 归属过滤快照 + summary 判定。
    required 缺失 → ready=False（plugin 终止对话 + 引导控制台）；
    optional 缺失 → 不拦。

summary 五分类：Python 包（detect_py_deps）/ 外部工具（detect_tools）/
编译器（detect_tools）/ Docker+镜像（docker_manager）/ 模型资产
（model_assets）——后两类为共享底座（归属 8 注册 agent，名单镜像
plugin constants.ts 的 ALL_REGISTERED_AGENTS；"all"=coordinator 语义
含底座）。后端无法 import TS 常量，plugin 侧名单变更时同步此处。

console_url 由 services/console_url.py 统一计算（唯一实现）。
"""
from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Callable, TypeVar

from fastapi import APIRouter

from services import detect_py_deps, detect_tools
from services.console_url import get_console_url
from services.detect_py_deps import PyPkgStatus
from services.detect_tools import CompilerInfo, ToolStatus
from services.docker_manager import DockerGlobal
from services.model_assets import ModelAssetStatus

router = APIRouter(prefix="/api/deps", tags=["deps"])

T = TypeVar("T")

SNAPSHOT_TTL_SEC = 30.0

# 共享底座（Docker/模型）归属 = 8 个注册 agent。
SHARED_INFRA_AGENTS = frozenset({
    "searcher",
    "memorist",
    "binary-analysis",
    "mobile-analysis",
    "web-analysis",
    "ai-security-analysis",
    "crypto-analysis",
    "security-coordinator",
})


# ─── 数据结构 ──────────────────────────────────────────────


@dataclass
class DepsSnapshot:
    """依赖快照：同一台机器同一时刻的全量依赖状态（与 agent 无关）。"""
    python: list[PyPkgStatus] = field(default_factory=list)
    tools_table: dict[str, ToolStatus] = field(default_factory=dict)
    compiler: CompilerInfo = field(default_factory=CompilerInfo.unavailable)
    docker_global: DockerGlobal = field(default_factory=DockerGlobal.unavailable)
    models: list[ModelAssetStatus] = field(default_factory=list)
    built_at: float = 0.0
    expires_at: float = 0.0

    def is_valid(self) -> bool:
        return self.expires_at > time.time()


@dataclass
class InfraItem:
    """共享底座条目（Docker 容器 / 模型资产）的 summary 视图。"""
    category: str                 # docker / model
    name: str
    available: bool
    required: bool


@dataclass
class DepsSummary:
    """环境就绪判定（plugin 只读此结构做放行/终止决策）。"""
    agent: str
    ready: bool
    required_missing: list[str]
    optional_missing: list[str]
    console_url: str


@dataclass
class AgentDepsResponse:
    """GET /api/deps/{agent} 的完整响应。"""
    summary: DepsSummary
    python: list[PyPkgStatus]
    tools: list[ToolStatus]
    compiler: CompilerInfo
    shared_infra: "SharedInfraView"


@dataclass
class SharedInfraView:
    """共享底座视图（非归属 agent 为 None）。"""
    docker: list[InfraItem] | None
    models: list[InfraItem] | None


# ─── DepsService（快照缓存 + 构建 + 组装 + 失效） ──────────


class DepsService:
    """依赖快照服务（模块级单例 deps_service）。

    状态封装：缓存读写全走方法；_build_lock 保护预热线程与
    请求线程池的并发写入；_singleflight 让并发请求共享一次构建。
    """

    def __init__(self, ttl_sec: float = SNAPSHOT_TTL_SEC) -> None:
        self._ttl_sec = ttl_sec
        self._snap: DepsSnapshot | None = None
        self._build_lock = threading.Lock()
        self._singleflight = asyncio.Lock()

    # ── 快照 ──

    def build_snapshot(self) -> DepsSnapshot:
        """同步构建快照并写入缓存：五项并行，单项失败降级。

        调用方：get_snapshot（请求路径，run_in_executor）与
        warm（启动预热线程）。
        """
        def _docker() -> DockerGlobal:
            from services import docker_manager
            return docker_manager.scan_global()

        def _models() -> list[ModelAssetStatus]:
            from services import model_assets
            return model_assets.get_model_assets()

        with ThreadPoolExecutor(max_workers=5) as ex:
            f_py = ex.submit(self._safe, lambda: detect_py_deps.scan("all"), [])
            f_tools = ex.submit(self._safe, detect_tools.scan_all_parallel, {})
            f_cc = ex.submit(self._safe, detect_tools.detect_compiler,
                             CompilerInfo.unavailable())
            f_docker = ex.submit(self._safe, _docker, DockerGlobal.unavailable())
            f_models = ex.submit(self._safe, _models, [])
            snap = DepsSnapshot(
                python=f_py.result(),
                tools_table=f_tools.result(),
                compiler=f_cc.result(),
                docker_global=f_docker.result(),
                models=f_models.result(),
                built_at=time.time(),
            )
        snap.expires_at = time.time() + self._ttl_sec
        with self._build_lock:
            self._snap = snap
        return snap

    async def get_snapshot(self, force: bool = False) -> DepsSnapshot:
        """取依赖快照（TTL 内直接用；过期/强制则重建，单飞）。"""
        if not force:
            snap = self._valid_snapshot()
            if snap is not None:
                return snap
        async with self._singleflight:
            if not force:
                snap = self._valid_snapshot()
                if snap is not None:
                    return snap  # 双检：排队期间已被重建
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self.build_snapshot)

    def warm(self) -> None:
        """启动预热（后台线程调用）：失败静默——首个请求会正常构建。"""
        try:
            self.build_snapshot()
        except Exception:
            pass

    def invalidate(self) -> None:
        """主动失效（依赖状态变更路由调用）。不立即重建——下个请求触发。"""
        with self._build_lock:
            self._snap = None

    def _valid_snapshot(self) -> DepsSnapshot | None:
        snap = self._snap
        return snap if snap is not None and snap.is_valid() else None

    @staticmethod
    def _safe(fn: Callable[[], T], default: T) -> T:
        """单项扫描异常兜底：失败返回 default，不拖垮整份快照。"""
        try:
            return fn()
        except Exception:
            return default

    # ── 组装 ──

    def assemble(self, agent: str, snap: DepsSnapshot) -> AgentDepsResponse:
        """从快照组装指定 agent 的完整响应（纯内存，µs 级）。"""
        infra_hit = agent == "all" or agent in SHARED_INFRA_AGENTS

        pkgs = [p for p in snap.python if self._pkg_belongs(p, agent)]
        tools = [snap.tools_table[t.name] for t in detect_tools.EXTERNAL_TOOLS
                 if self._tool_belongs(t, agent)]

        docker_items: list[InfraItem] | None = None
        model_items: list[InfraItem] | None = None
        d_req: list[str] = []
        m_opt: list[str] = []
        if infra_hit:
            docker_items, d_req = self._docker_view(snap.docker_global)
            model_items, m_opt = self._model_view(snap.models)

        required_missing = [p.name for p in pkgs if p.required and not p.available]
        optional_missing = [p.name for p in pkgs if not p.required and not p.available]
        for t in tools:
            if t.skipped:
                continue
            if t.required and not t.available:
                required_missing.append(t.name)
            elif not t.required and not t.available:
                optional_missing.append(t.name)
        if not snap.compiler.available:
            required_missing.append("compiler")
        required_missing += d_req
        optional_missing += m_opt

        return AgentDepsResponse(
            summary=DepsSummary(
                agent=agent,
                ready=not required_missing,
                required_missing=required_missing,
                optional_missing=optional_missing,
                console_url=get_console_url(),
            ),
            python=pkgs,
            tools=tools,
            compiler=snap.compiler,
            shared_infra=SharedInfraView(docker=docker_items or None,
                                         models=model_items or None),
        )

    # ── 组装内部视图 ──

    @staticmethod
    def _docker_view(g: DockerGlobal) -> tuple[list[InfraItem], list[str]]:
        """Docker → (items, required_missing)。"""
        items: list[InfraItem] = []
        required_missing: list[str] = []
        if not g.docker.installed:
            return items, ["docker"]
        if not g.docker.daemon_running:
            return items, ["docker daemon"]
        for c in g.containers:
            items.append(InfraItem(category="docker", name=c.name,
                                   available=c.status == "running", required=True))
            if c.status != "running":
                required_missing.append(f"容器 {c.name}")
        return items, required_missing

    @staticmethod
    def _model_view(models: list[ModelAssetStatus]) -> tuple[list[InfraItem], list[str]]:
        """模型 → (items, optional_missing)。模型缺失为 optional（可在线下载）。"""
        items = [InfraItem(category="model", name=m.id, available=m.cached,
                           required=False) for m in models]
        optional_missing = [m.id for m in models if not m.cached]
        return items, optional_missing

    @staticmethod
    def _pkg_belongs(p: PyPkgStatus, agent: str) -> bool:
        return agent == "all" or "all" in p.agents or agent in p.agents

    @staticmethod
    def _tool_belongs(t, agent: str) -> bool:
        return (agent == "all" or agent in t.agents) and detect_tools.ToolsScanner._platform_matches(t)


# 模块级单例
deps_service = DepsService()


def warm_deps_snapshot() -> None:
    """模块级委托（server.py 启动预热调用）。"""
    deps_service.warm()


def invalidate_deps_snapshot() -> None:
    """模块级委托（依赖状态变更路由调用）。"""
    deps_service.invalidate()


def _register_invalidation_hooks() -> None:
    """模型下载完成回调 → 快照失效（依赖方向 routes → services 合法）。"""
    from services import model_assets
    model_assets.add_change_callback(lambda _mid: deps_service.invalidate())


_register_invalidation_hooks()


# ─── 路由（薄壳） ──────────────────────────────────────────


@router.get("")
async def get_all_deps() -> dict[str, list[dict]]:
    """所有 agent 的工具状态（前端依赖页用）。"""
    return {agent: [asdict(t) for t in tools]
            for agent, tools in detect_tools.scan_all().items()}


@router.get("/{agent}")
async def get_agent_deps(agent: str, refresh: bool = False) -> dict:
    """指定 agent 的完整依赖状态 + 环境就绪 summary。

    ?refresh=1 强制重建快照（排查用；正常路径走 TTL 缓存）。
    """
    snap = await deps_service.get_snapshot(force=refresh)
    return asdict(deps_service.assemble(agent, snap))
