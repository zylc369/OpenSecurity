"""/api/docker/* 路由：Docker 资源管理。

包括 daemon 状态、容器启停、镜像拉取（SSE 进度推送）。
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from dataclasses import dataclass

from services import docker_manager
from services.docker_manager import DockerGlobal
from routes.deps import invalidate_deps_snapshot

router = APIRouter(prefix="/api/docker", tags=["docker"])


@dataclass
class ContainerAction:
    success: bool
    message: str


@router.get("/status")
async def get_status() -> DockerGlobal:
    """Docker daemon + 已知容器 + 已知镜像状态。"""
    return docker_manager.DockerManager.scan_global()


@router.get("/containers")
async def list_containers(all_: bool = True) -> JSONResponse:
    """列出容器（默认包含停止的）。docker JSON 原样直通（不经响应模型）。"""
    return JSONResponse(content=docker_manager.DockerManager.list_containers(all_=all_))


@router.post("/containers/{name}/start")
async def start_container(name: str) -> ContainerAction:
    """启动容器。"""
    success, message = docker_manager.DockerManager.start_container(name)
    if success:
        invalidate_deps_snapshot()  # 容器状态变化 → 快照失效
    return ContainerAction(success=success, message=message)


@router.post("/containers/{name}/stop")
async def stop_container(name: str) -> ContainerAction:
    """停止容器。"""
    success, message = docker_manager.DockerManager.stop_container(name)
    if success:
        invalidate_deps_snapshot()  # 容器状态变化 → 快照失效
    return ContainerAction(success=success, message=message)


@router.get("/images")
async def list_images() -> JSONResponse:
    """列出本地镜像。docker JSON 原样直通（不经响应模型）。"""
    return JSONResponse(content=docker_manager.DockerManager.list_images())


@router.post("/images/{image}/pull")
async def pull_image(image: str) -> StreamingResponse:
    """拉取镜像，SSE 推送进度。

    用法（前端）：
        const eventSource = new EventSource('/api/docker/images/neo4j:5/pull');
        eventSource.onmessage = (e) => console.log(e.data);
    """
    # URL 中的 image 名包含冒号（如 neo4j:5），FastAPI 路径参数能正确解析

    async def event_stream():
        async for line in docker_manager.DockerManager.pull_image_stream(image):
            yield f"data: {line}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
