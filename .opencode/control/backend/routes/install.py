"""/api/install 路由：Python 包一键安装（pip / conda 按清单 installer 字段分发）。

安全约束：
  • 只允许安装唯一清单（detect_py_deps.PYTHON_PACKAGES）内的包（避免任意命令执行）
  • 监听 127.0.0.1 时局域网无法访问（控制台 bind 限制）

返回完整 stdout（不流式 SSE）。如需流式进度，参考 routes/docker.py 的 pull_image 实现。
"""
from __future__ import annotations

import subprocess
import sys
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import shutil

from services.detect_py_deps import PYTHON_PACKAGES, one_click_installable
from routes.deps import invalidate_deps_snapshot


def _install_command(pip_name: str) -> list[str] | None:
    """按清单条目的 installer 字段构造安装命令。

    pip:   venv python -m pip install <name>
    conda: conda install -p <venv> -y <conda_name>（venv 由 conda 创建，PATH 上有 conda）
    未知包名返回 None（白名单二次校验兜底）。
    """
    entry = next((p for p in PYTHON_PACKAGES if p.pip_name == pip_name), None)
    if entry is None:
        return None
    if entry.installer == "conda":
        conda = shutil.which("conda")
        if not conda:
            return None
        return [conda, "install", "-p", sys.prefix, "-y", entry.conda_name or entry.pip_name]
    return [sys.executable, "-m", "pip", "install", entry.pip_name]

router = APIRouter(prefix="/api/install", tags=["install"])


# 白名单唯一数据源 = detect_py_deps.PYTHON_PACKAGES（one_click_installable：
# installer=pip 且平台适用的全部包）。加包只改清单，本路由零改动。
# installer=conda 的包（sage）不可 pip，天然不在白名单。


class InstallRequest(BaseModel):
    package: str          # pip 包名



@router.post("")
async def install_package(req: InstallRequest) -> dict:
    """同步执行 pip install，返回完整 stdout + stderr。

    安全：包名必须在白名单内。
    """
    pkg = req.package.strip()
    if pkg not in one_click_installable():
        raise HTTPException(
            status_code=400,
            detail=f"包 {pkg} 不在白名单内（唯一清单 detect_py_deps.PYTHON_PACKAGES）。控制台只允许安装预定义的包。"
        )
    cmd = _install_command(pkg)
    if cmd is None:
        raise HTTPException(status_code=500, detail=f"包 {pkg} 的安装命令构造失败（conda 不在 PATH？）")

    try:
        r = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=1800,  # conda 装 sage 是 GB 级下载
        )
        if r.returncode == 0:
            invalidate_deps_snapshot()  # 装包成功 → 快照立即失效（下条消息见新状态）
        return {
            "success": r.returncode == 0,
            "package": pkg,
            "stdout": r.stdout[-500:],  # 截取最后 500 字符避免响应过大
            "stderr": r.stderr[-500:],
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "package": pkg,
            "error": "安装超时（1800s）",
        }
