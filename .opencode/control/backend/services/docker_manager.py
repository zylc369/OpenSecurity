"""Docker 操作收口模块。

迁移自 detect_env.py（_check_docker_binary_and_daemon / _check_container_status /
_check_image_exists）和 events/server.py（_pull_image_with_progress / _ensure_neo4j_container_blocking）。

其他模块禁止直接 subprocess 调 docker CLI（grep 唯一性）。

控制台管理的容器/镜像清单在 KNOWN_CONTAINERS / KNOWN_IMAGES 常量中，
后续增加新容器/镜像只改这里，不需要改业务代码。
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from dataclasses import dataclass
from typing import AsyncIterator


# ─── 已知容器/镜像清单 ───────────────────────────────────
# 后续增加新容器/镜像只改这里。

@dataclass
class KnownContainer:
    """已知容器元数据。"""
    name: str
    image: str
    description: str
    ports: list[str]           # 端口映射（如 ["7474:7474"]）
    env: list[str]             # 环境变量（如 ["NEO4J_AUTH=neo4j/neo4j_password"]）
    volumes: list[str]         # 卷映射（如 ["$DATA_DIR/neo4j:/data"]）
    auto_start: bool = True    # 是否允许控制台自动启动（False = 只能手动）


@dataclass
class KnownImage:
    """已知镜像元数据。"""
    name: str                  # neo4j:5
    description: str
    size_hint: str             # 大小提示（如 "~988MB"）


KNOWN_CONTAINERS: list[KnownContainer] = [
    KnownContainer(
        name="neo4j-events",
        image="neo4j:5",
        description="events MCP 使用的 Neo4j 知识图谱存储",
        ports=["7474:7474", "7687:7687"],
        env=["NEO4J_AUTH=neo4j/neo4j_password"],
        volumes=[],  # events/server.py 自己处理 volume
    ),
]

KNOWN_IMAGES: list[KnownImage] = [
    KnownImage(
        name="neo4j:5",
        description="Neo4j 5.x 社区版",
        size_hint="~988MB",
    ),
]


# ─── Docker CLI 封装 ─────────────────────────────────────


def _run_docker(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
    """执行 docker 命令，返回 CompletedProcess。失败抛 CalledProcessError。"""
    return subprocess.run(
        ["docker"] + args,
        capture_output=True, text=True, timeout=timeout, check=True,
    )


def is_docker_installed() -> bool:
    """检测 docker 二进制是否在 PATH。"""
    return shutil.which("docker") is not None


def is_daemon_running() -> bool:
    """检测 Docker daemon 是否运行。"""
    try:
        _run_docker(["info"], timeout=5)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def check_status() -> dict:
    """返回 Docker 整体状态。"""
    return {
        "installed": is_docker_installed(),
        "daemon_running": is_daemon_running() if is_docker_installed() else False,
    }


# ─── 容器操作 ─────────────────────────────────────────────


def list_containers(all_: bool = False) -> list[dict]:
    """列出容器。

    Args:
        all_: True 包括停止的容器，False 只列运行中的。
    """
    if not is_daemon_running():
        return []
    args = ["ps", "--format", "{{json .}}"]
    if all_:
        args.append("-a")
    try:
        r = _run_docker(args, timeout=10)
        # 每行一个 JSON
        import json
        return [json.loads(line) for line in r.stdout.splitlines() if line.strip()]
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []


def get_container_status(name: str) -> str:
    """返回容器状态：running / stopped / not_exists / unknown。"""
    if not is_daemon_running():
        return "unknown"
    try:
        r = _run_docker(
            ["ps", "-a", "--filter", f"name=^{name}$",
             "--format", "{{.Status}}"],
            timeout=5,
        )
        status = r.stdout.strip()
        if not status:
            return "not_exists"
        if status.startswith("Up"):
            return "running"
        return "stopped"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "unknown"


def start_container(name: str) -> tuple[bool, str]:
    """启动已存在的容器。返回 (success, message)。"""
    if not is_daemon_running():
        return False, "Docker daemon 未运行"
    try:
        _run_docker(["start", name], timeout=30)
        return True, f"容器 {name} 已启动"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return False, f"启动失败: {e}"


def stop_container(name: str) -> tuple[bool, str]:
    """停止容器。"""
    if not is_daemon_running():
        return False, "Docker daemon 未运行"
    try:
        _run_docker(["stop", name], timeout=30)
        return True, f"容器 {name} 已停止"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return False, f"停止失败: {e}"


def create_container(spec: KnownContainer) -> tuple[bool, str]:
    """根据 KnownContainer spec 创建并启动容器。"""
    if not is_daemon_running():
        return False, "Docker daemon 未运行"
    args = ["run", "-d", f"--name={spec.name}"]
    for p in spec.ports:
        args.append("-p")
        args.append(p)
    for e in spec.env:
        args.append("-e")
        args.append(e)
    for v in spec.volumes:
        args.append("-v")
        args.append(v)
    args.append(spec.image)
    try:
        _run_docker(args, timeout=60)
        return True, f"容器 {spec.name} 已创建并启动"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return False, f"创建失败: {e}"


# ─── 镜像操作 ─────────────────────────────────────────────


def list_images() -> list[dict]:
    """列出本地镜像。"""
    if not is_daemon_running():
        return []
    try:
        r = _run_docker(
            ["images", "--format", "{{json .}}"],
            timeout=10,
        )
        import json
        return [json.loads(line) for line in r.stdout.splitlines() if line.strip()]
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []


def image_exists(name: str) -> bool | None:
    """检测镜像是否已下载。None = 检测失败。"""
    if not is_daemon_running():
        return None
    try:
        r = _run_docker(
            ["images", name, "--format", "{{.Repository}}"],
            timeout=5,
        )
        return r.stdout.strip() != ""
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


async def pull_image_stream(name: str) -> AsyncIterator[str]:
    """拉取镜像，流式 yield 进度行（用于 SSE 推送）。

    用法：
        async for line in pull_image_stream("neo4j:5"):
            # yield 到 SSE 客户端
    """
    proc = await asyncio.create_subprocess_exec(
        "docker", "pull", name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None
    async for raw_line in proc.stdout:
        yield raw_line.decode(errors="ignore").strip()
    await proc.wait()
    yield f"__done__ exit_code={proc.returncode}"


# ─── 扫描协调（供 scanner.py 调用）───────────────────────


def scan_global() -> dict:
    """扫描 Docker 全局状态（容器 + 镜像），供 scanner.py 调用。"""
    docker_ok = check_status()
    if not docker_ok["installed"]:
        return {
            "docker": {"installed": False, "daemon_running": False},
            "containers": [],
            "images": [],
        }

    containers = []
    for spec in KNOWN_CONTAINERS:
        status = get_container_status(spec.name)
        containers.append({
            "name": spec.name,
            "image": spec.image,
            "description": spec.description,
            "status": status,
            "auto_start": spec.auto_start,
        })

    images = []
    for spec in KNOWN_IMAGES:
        exists = image_exists(spec.name)
        images.append({
            "name": spec.name,
            "description": spec.description,
            "size_hint": spec.size_hint,
            "pulled": bool(exists),
        })

    return {
        "docker": docker_ok,
        "containers": containers,
        "images": images,
    }
