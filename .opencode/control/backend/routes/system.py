"""/api/system 路由：运行环境信息（venv/HF 缓存/进程身份）。

用途：前端各分区头部显示安装路径（Python 依赖分区显示 venv 路径、模型分区显示 HF 缓存目录）。
"""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from dataclasses import dataclass

from services.config_manager import ConfigManager
from services.model_assets import ModelAssetRegistry

router = APIRouter(prefix="/api/system", tags=["system"])


@dataclass
class SystemInfo:
    venv_path: str
    venv_python: str
    python_version: str
    hf_cache_dir: str
    hf_endpoint: str
    control_pid: int
    control_start_time: "float | None"
    dev_mode: bool
    platform: str
    code_stale: bool


@dataclass
class RestartScheduled:
    success: bool
    scheduled: bool
    message: str


@router.get("")
async def get_system_info() -> SystemInfo:
    """运行环境信息。"""
    venv_path = str(Path(sys.prefix))
    hf_cache = str(Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")))
    from services.process_lock import ProcessLockUtil
    from routes.health import _BOOT_FINGERPRINT, _code_fingerprint
    return SystemInfo(
        venv_path=venv_path,
        venv_python=sys.executable,
        python_version=platform.python_version(),
        hf_cache_dir=hf_cache,
        hf_endpoint=ModelAssetRegistry.get_instance()._hf_endpoint(),
        control_pid=os.getpid(),
        control_start_time=ProcessLockUtil.get_process_start_time(os.getpid()),
        dev_mode=ConfigManager.get_instance().is_dev_mode,
        platform=f"{platform.system()} {platform.machine()}",
        # backend 代码陈旧检测（指纹函数与 /api/health 同源——启动时冻结 vs 当前比对）
        code_stale=_code_fingerprint() != _BOOT_FINGERPRINT,
    )


@router.post("/git-pull")
async def git_pull_repo() -> "JSONResponse":
    """git pull 仓库根（远程节点更新代码用; 成功返回最新 commit）。

    与 /restart 分离: 主控的「更新并重启」= 先 pull 后 restart（两步显式编排）。
    """
    import subprocess
    from pathlib import Path
    from typing import cast
    # 仓库根推导: backend → .opencode/control/backend → 仓库根
    repo = str(Path(__file__).resolve().parents[3])
    try:
        r = subprocess.run(["git", "pull", "--ff-only"], cwd=repo,
                           capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})
    if r.returncode != 0:
        return JSONResponse(status_code=500,
                            content={"ok": False, "error": r.stderr.strip()[:500]})
    return JSONResponse(content={"ok": True, "output": r.stdout.strip()[:500]})


@router.post("/restart")
async def restart_console() -> RestartScheduled:
    """自重启（页面按钮触发）。

    响应送达约 1.5s 后进程 execv 替换为新代码；前端轮询 /api/health 的
    boot_token 变化判定重启完成。重复点击返回 in_flight。
    """
    from services.restart import ConsoleRestarter
    scheduled = ConsoleRestarter.get_instance().schedule()
    return RestartScheduled(
        success=True,
        scheduled=scheduled,
        message="重启已调度，新实例就绪前接口短暂不可用（模型重载需几十秒）",
    )

