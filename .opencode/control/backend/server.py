"""opencode-control 主入口。

替代 mcp-servers/embed_server.py，提供：
  • /embed, /rerank, /health（embed_server.py 功能迁移）
  • 后续步骤会增加：/api/scan, /api/config, /api/docker/* 等

启动方式（B 方案）：
  1. FastAPI app 构造完成
  2. uvicorn.run 立即启动（不等待模型加载）
  3. 后台线程加载 BGE-M3 模型
  4. 加载期间 /health 返回 503，加载完返回 200

注意：步骤 1 只包含 embed + health 路由。
       后续步骤（2-6）会扩展 server.py 加单实例检测、配置、扫描等。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import FrameType

# 避免 SentenceTransformer 加载时向 HuggingFace 发 HEAD 请求（网络不通会卡 120s+）
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# 把 backend 目录加入 sys.path，让 routes/services 能用绝对 import
BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(BACKEND_DIR))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from services.config_manager import ConfigManager
from services.model_loader import ModelInferenceService

import asyncio  # noqa: E402 —— 供 _relay_supervise_task 注解解析（字符串注解引用）

_relay_supervise_task: "asyncio.Task | None" = None


def create_app() -> FastAPI:
    """构造 FastAPI app。

    单独抽出函数便于：
      - 单元测试（不启动 uvicorn）
      - 后续步骤扩展（加更多路由 include_router）
    """
    # 配置收口于 ConfigManager（无循环 import）

    # 首次运行创建 .ai_env 带注释模板（配置收口：ConfigManager 唯一读写方）
    ConfigManager.get_instance().ensure_template()

    app = FastAPI(
        title="OpenSecurity Control",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    # CORS：开发态允许 Vite 5173 跨域访问；发布态同源不需要
    if ConfigManager.get_instance().is_dev_mode:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # API 鉴权中间件（后注册先执行——guard 先于 CORS/路由生效）
    from services.api_guard import ApiGuardMiddleware
    app.add_middleware(ApiGuardMiddleware)

    # 路由
    from routes import embed, health, config_route, deps, docker, scan, install, hardware, fs, models, system, ocr, processes, knowledge, events, heartbeat, proxy, remote
    app.include_router(embed.router)
    app.include_router(health.router)
    app.include_router(heartbeat.router)
    app.include_router(config_route.router)
    app.include_router(deps.router)
    app.include_router(ocr.router)
    app.include_router(processes.router)
    app.include_router(docker.router)
    app.include_router(scan.router)
    app.include_router(install.router)
    app.include_router(hardware.router)
    app.include_router(fs.router)
    app.include_router(models.router)
    app.include_router(system.router)
    app.include_router(knowledge.router)
    app.include_router(events.router)
    app.include_router(proxy.router)
    app.include_router(remote.router)

    # 前端静态文件（开发态跳过，发布态挂载 dist/）
    _mount_frontend(app)

    # 依赖快照预热：启动事件 fire-and-forget，与模型加载并行。
    # plugin 首个 /api/deps 请求到达时（spawn 后 0.3~1.1s）快照大概率已就绪。
    # 冷启动首扫含 JVM/磁盘冷缓存，预热正好吸收。失败静默（请求路径会正常构建）。
    from routes.deps import warm_deps_snapshot

    @app.on_event("startup")
    async def _start_writers() -> None:
        # 库服务线程（fire-and-forget 写队列；agent 读写按需惰性初始化）
        from services.event_store import EventStoreService
        from services.knowledge_store import KnowledgeStoreService
        KnowledgeStoreService.get_instance().start()
        EventStoreService.get_instance().start()

    @app.on_event("startup")
    async def _warm_deps_snapshot() -> None:
        import asyncio
        asyncio.get_running_loop().run_in_executor(None, warm_deps_snapshot)

    @app.on_event("startup")
    async def _start_remote_link() -> None:
        # 远程链接心跳（模型远程化: 探测/降级/恢复编排）
        from services.remote_link import RemoteLinkService
        RemoteLinkService.get_instance().start()

    @app.on_event("startup")
    async def _start_proxy_relay() -> None:
        # relay（本地代理服务）supervisor：崩溃自动重拉（2 秒级），不拖垮主进程
        import asyncio
        import logging
        from services.proxy_relay import ProxyRelay
        log = logging.getLogger("proxy_relay")

        async def _supervise() -> None:
            # 持续监督：启动 + 每 2s 探活（server 对象失活 → 关闭旧的重新拉起，
            # 2 秒级自愈，不拖垮控制台主进程，需求 §8 步骤 3b 验证点）
            while True:
                try:
                    await ProxyRelay.start_relay()
                except Exception as e:
                    log.error("[proxy_relay] 启动失败(2s 后重试): %s", e)
                    await asyncio.sleep(2)
                    continue
                while True:
                    await asyncio.sleep(2)
                    srv = ProxyRelay.current_server()
                    if srv is None or not getattr(srv, "sockets", None) or srv.is_serving() is False:
                        log.warning("[proxy_relay] 服务失活，自动重拉监听")
                        await ProxyRelay.stop_relay()
                        break
                await asyncio.sleep(0.2)

        global _relay_supervise_task  # 持引用防 GC（asyncio 文档建议）
        _relay_supervise_task = asyncio.create_task(_supervise())

    # 开发态自动拉起 vite dev server（此前依赖手动启动，控制台重启后
    # 前端 404）。幂等：vite 已运行则跳过；拉起失败由 dev 提示页指路。
    # 注意不能把 ConfigManager 类当谓词调用（构造单例恒真——曾在生产
    # 每次 create_app 都 spawn vite）
    if ConfigManager.get_instance().is_dev_mode:
        from services.frontend_port import FrontendPortRegistry
        FrontendPortRegistry.get_instance().ensure_vite_dev()

    return app


def _mount_frontend(app: FastAPI) -> None:
    """根据 is_dev_mode 决定是否挂载前端 dist/。"""
    if ConfigManager.get_instance().is_dev_mode:
        # 开发态：不挂载，/ 返回 dev 提示
        @app.get("/")
        async def dev_hint():
            return {
                "mode": "dev",
                "hint": "前端开发模式（CONTROL_FRONTEND_DEV=1）。vite dev server 由控制台自动拉起",
                "url": "http://localhost:5173",
            }
        return

    # 发布态：挂载 dist/（如果存在）
    dist_path = BACKEND_DIR.parent / "frontend" / "dist"
    if dist_path.exists():
        app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="frontend")
    else:
        @app.get("/")
        async def no_dist():
            return {
                "error": "dist/ 不存在",
                "hint": "请运行 cd control/frontend && bun install && bun run build",
            }


def main() -> None:
    """控制台主入口。

    单实例检测 + TCP 顺延绑定 + IPC 监听 + B 方案启动 + 引用计数周期清洗。

    时序：
      1. 日志初始化（文件轮转 OPENSECURITY_HOME/logs/control.log——stdio=ignore 下 print 不可见）
      2. IPC 监听（内核排他互斥；按 IpcStartStatus 分支处理）
      3. bind 浏览器 TCP 候选段（9776 起顺延）+ 注册真实端口
      4. 启动引用计数后台清洗
      5. 后台线程加载模型
      6. uvicorn.run
    """
    from services.logging_setup import LogManager
    log = LogManager.get_instance().setup()
    log.info("=" * 50)
    log.info("控制台启动（pid=%d, platform=%s）", os.getpid(), sys.platform)

    from services.config_manager import ConfigManager
    from services.frontend_port import FrontendPortRegistry
    from services.ipc_listener import IpcListener, IpcStartStatus
    from services.heartbeat import HeartbeatRegistry, HeartbeatTask

    # 步骤 2: IPC 监听（按枚举语义分支，不用 bool 猜）
    status = IpcListener.get_instance().start()
    if status is IpcStartStatus.EXISTING_INSTANCE:
        log.info("IPC 通道已有实例运行（%s），本进程退出（exit code = %d）",
                 ConfigManager.get_instance().ipc_addr(), ConfigManager.Protocol.EXIT_CODE_REUSE)
        sys.exit(ConfigManager.Protocol.EXIT_CODE_REUSE)
        return
    if status is IpcStartStatus.BIND_TIMEOUT:
        log.error("IPC bind 失败且等待窗口耗尽（%s），本进程退出（exit code = %d）",
                  ConfigManager.get_instance().ipc_addr(), ConfigManager.Protocol.EXIT_CODE_PORT_EXHAUSTED)
        sys.exit(ConfigManager.Protocol.EXIT_CODE_PORT_EXHAUSTED)
        return
    log.info("IPC 监听已启动：%s", ConfigManager.get_instance().ipc_addr())

    # 步骤 3: bind 浏览器 TCP 候选段（顺延）+ 注册真实端口（/api/console-url 对外）
    try:
        sock = FrontendPortRegistry.get_instance().bind_and_register_tcp()
    except RuntimeError as e:
        log.error("%s", e)
        IpcListener.get_instance().cleanup()
        sys.exit(ConfigManager.Protocol.EXIT_CODE_PORT_EXHAUSTED)

    # 步骤 4: 启动心跳周期检测后台任务（表空过宽限 → 自杀）
    def shutdown():
        log.info("控制台 shutdown（清理 IPC + 退出）")
        IpcListener.get_instance().cleanup()
        # 用 os._exit 跳过任何 atexit hook（避免 uvicorn 优雅关闭阻塞）
        import os
        os._exit(ConfigManager.Protocol.EXIT_CODE_NORMAL)

    heartbeat_task = HeartbeatTask(HeartbeatRegistry.get_instance(), shutdown)
    heartbeat_task.start()

    # SIGTERM/SIGINT 也走 shutdown（清理 IPC socket + 退出）
    import signal

    def _on_signal(signum: int, _frame: "FrameType | None"):
        log.info("收到信号 %s，退出", signum)
        shutdown()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    # 步骤 5: 后台线程加载模型（B 方案核心）
    # - 远程已启用（ENABLED=1 且 URL 非空）→ 跳过本地预加载（由心跳判定:
    #   REMOTE 保持不加载 / DEGRADED 走预热路径）——避免"重启白白加载再卸载"
    # - 节点角色（CONTROL_API_KEY 已配置）→ 预加载全部三模型（专职资源节点）
    _cm = ConfigManager.get_instance()
    _api_key = (_cm.get(_cm.Keys.CONTROL_API_KEY) or "").strip()
    _remote_enabled = ((_cm.get(_cm.Keys.REMOTE_CONSOLE_ENABLED) or "").strip().lower() in ("1", "true")
                       and (_cm.get(_cm.Keys.REMOTE_CONSOLE_URL) or "").strip())
    if _api_key:
        log.info("节点模式（CONTROL_API_KEY 已配置）: 预加载全部三模型")
        ModelInferenceService.get_instance().preload_all_models_background()
    elif _remote_enabled:
        log.info("远程模型已启用: 跳过本地预加载（心跳判定后再决定加载）")
    else:
        ModelInferenceService.get_instance().preload_embedder_background()

    # 步骤 6: 启动 uvicorn（用预绑定的 socket；uvicorn 日志并入 root → 同文件）
    import uvicorn
    app = create_app()
    fd = sock.detach()
    uvicorn.run(app, fd=fd, log_level="info")


if __name__ == "__main__":
    main()
