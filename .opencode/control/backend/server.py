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

# 避免 SentenceTransformer 加载时向 HuggingFace 发 HEAD 请求（网络不通会卡 120s+）
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# 把 backend 目录加入 sys.path，让 routes/services 能用绝对 import
BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(BACKEND_DIR))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import is_dev_mode
from services import model_loader


def create_app() -> FastAPI:
    """构造 FastAPI app。

    单独抽出函数便于：
      - 单元测试（不启动 uvicorn）
      - 后续步骤扩展（加更多路由 include_router）
    """
    # 延迟绑定 validator（避免 config ↔ config_store 循环 import）
    from config import _init_validators
    _init_validators()

    app = FastAPI(
        title="OpenSecurity Control",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    # CORS：开发态允许 Vite 5173 跨域访问；发布态同源不需要
    if is_dev_mode():
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # 路由
    from routes import embed, health, config_route, deps, docker, scan, install, hardware, fs, models, system
    app.include_router(embed.router)
    app.include_router(health.router)
    app.include_router(config_route.router)
    app.include_router(deps.router)
    app.include_router(docker.router)
    app.include_router(scan.router)
    app.include_router(install.router)
    app.include_router(hardware.router)
    app.include_router(fs.router)
    app.include_router(models.router)
    app.include_router(system.router)

    # 前端静态文件（开发态跳过，发布态挂载 dist/）
    _mount_frontend(app)

    return app


def _mount_frontend(app: FastAPI) -> None:
    """根据 is_dev_mode 决定是否挂载前端 dist/。"""
    if is_dev_mode():
        # 开发态：不挂载，/ 返回 dev 提示
        @app.get("/")
        async def dev_hint():
            return {
                "mode": "dev",
                "hint": "前端开发模式（CONTROL_FRONTEND_DEV=1）。请访问 http://localhost:5173",
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

    单实例检测 + 端口分配 + B 方案启动 + 引用计数周期清洗。

    时序：
      1. 拿启动锁（防止并发启动）
      2. 检查现有实例（端口文件 + PID + 端口连通）→ 已运行则 exit 2
      3. bind 候选端口 → 全部失败 exit 3
      4. 写端口文件
      5. 释放锁
      6. 启动引用计数后台清洗
      7. 后台线程加载模型
      8. uvicorn.run
    """
    from config import (
        EXIT_CODE_REUSE, EXIT_CODE_PORT_EXHAUSTED, EXIT_CODE_NORMAL,
    )
    from services.process_lock import acquire_startup_lock
    from services.port_manager import (
        bind_port_with_fallback, write_port_file, is_control_running,
        read_port_file, delete_port_file, probe_live_control,
    )
    from services.ref_counter import UsersCleanupTask

    # 步骤 1+2: 拿锁 + 检查现有实例
    with acquire_startup_lock():
        if is_control_running():
            info = read_port_file()
            print(
                f"[control] 已有实例运行（port={info[0]}, pid={info[1]}），"
                f"本进程退出（exit code = {EXIT_CODE_REUSE}）",
                flush=True,
            )
            sys.exit(EXIT_CODE_REUSE)

        # 步骤 2.5: 端口文件缺失/失效时探测孤儿实例
        # 场景：端口文件被误删但旧控制台还活着。若不探测，本实例会 bind 到
        # 下一候选端口 → 双实例（双份模型内存）+ 旧实例退出时误删新端口文件。
        # 探测到孤儿 → 重写端口文件指向孤儿 → 本实例退出（等价"复用"路径）。
        orphan = probe_live_control()
        if orphan is not None:
            o_port, o_pid, o_start = orphan
            write_port_file(o_port, pid=o_pid, start_time=o_start)
            print(
                f"[control] 发现孤儿实例（port={o_port}, pid={o_pid}），"
                f"已重建端口文件，本进程退出（exit code = {EXIT_CODE_REUSE}）",
                flush=True,
            )
            sys.exit(EXIT_CODE_REUSE)

        # 步骤 3: bind 候选端口
        try:
            port, sock = bind_port_with_fallback()
        except RuntimeError as e:
            print(f"[control] {e}", flush=True)
            sys.exit(EXIT_CODE_PORT_EXHAUSTED)

        # 步骤 4: 写端口文件（锁持有中）
        write_port_file(port)

    # 步骤 5: 锁已释放（with 块结束）
    # 步骤 6: 启动 users 周期清洗后台任务
    def shutdown():
        delete_port_file()
        # 用 os._exit 跳过任何 atexit hook（避免 uvicorn 优雅关闭阻塞）
        import os
        os._exit(EXIT_CODE_NORMAL)

    cleanup_task = UsersCleanupTask(shutdown)
    cleanup_task.start()

    # 步骤 6.5: SIGTERM/SIGINT 也走 shutdown（删端口文件 + 退出）
    # 此前只挂在 users 空自杀路径上，kill/SIGTERM 会残留端口文件
    # （靠 PID 三重校验兜底自愈，但补上信号处理让文件生命周期完整）。
    import signal

    def _on_signal(signum, _frame):
        print(f"[control] 收到信号 {signum}，退出", flush=True)
        shutdown()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    # 步骤 7: 后台线程加载模型（B 方案核心）
    model_loader.preload_embedder_background()

    # 步骤 8: 启动 uvicorn（用预绑定的 socket）
    import uvicorn
    app = create_app()
    fd = sock.detach()
    uvicorn.run(app, fd=fd, log_level="warning")


if __name__ == "__main__":
    main()
