"""/api/system 路由：运行环境信息（venv/HF 缓存/进程身份）。

用途：前端各分区头部显示安装路径（Python 依赖分区显示 venv 路径、模型分区显示 HF 缓存目录）。
"""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

from fastapi import APIRouter

from config import is_dev_mode

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("")
async def get_system_info() -> dict:
    """运行环境信息。"""
    venv_path = str(Path(sys.prefix))
    hf_cache = str(Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")))
    from services import model_assets
    return {
        "venv_path": venv_path,
        "venv_python": sys.executable,
        "python_version": platform.python_version(),
        "hf_cache_dir": hf_cache,
        "hf_endpoint": model_assets._hf_endpoint(),
        "control_pid": os.getpid(),
        "dev_mode": is_dev_mode(),
        "platform": f"{platform.system()} {platform.machine()}",
    }
