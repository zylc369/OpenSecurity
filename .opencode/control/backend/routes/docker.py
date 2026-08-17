"""/api/docker/* 路由：Docker 资源管理。

包括 daemon 状态、容器启停、镜像拉取（SSE 进度推送）。
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from dataclasses import asdict

from services import docker_manager
from routes.deps import invalidate_deps_snapshot

router = APIRouter(prefix="/api/docker", tags=["docker"])


@router.get("/status")
async def get_status() -> dict:
    """Docker daemon + 已知容器 + 已知镜像状态。"""
    return asdict(docker_manager.scan_global())


@router.get("/containers")
async def list_containers(all_: bool = True) -> list[dict]:
    """列出容器（默认包含停止的）。"""
    return docker_manager.list_containers(all_=all_)


@router.post("/containers/{name}/start")
async def start_container(name: str) -> dict:
    """启动容器。"""
    success, message = docker_manager.start_container(name)
    if success:
        invalidate_deps_snapshot()  # 容器状态变化 → 快照失效
    return {"success": success, "message": message}


@router.post("/containers/{name}/stop")
async def stop_container(name: str) -> dict:
    """停止容器。"""
    success, message = docker_manager.stop_container(name)
    if success:
        invalidate_deps_snapshot()  # 容器状态变化 → 快照失效
    return {"success": success, "message": message}


@router.get("/images")
async def list_images() -> list[dict]:
    """列出本地镜像。"""
    return docker_manager.list_images()


@router.post("/images/{image}/pull")
async def pull_image(image: str) -> StreamingResponse:
    """拉取镜像，SSE 推送进度。

    用法（前端）：
        const eventSource = new EventSource('/api/docker/images/neo4j:5/pull');
        eventSource.onmessage = (e) => console.log(e.data);
    """
    # URL 中的 image 名包含冒号（如 neo4j:5），FastAPI 路径参数能正确解析

    async def event_stream():
        async for line in docker_manager.pull_image_stream(image):
            yield f"data: {line}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
