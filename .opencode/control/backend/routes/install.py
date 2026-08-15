"""/api/install 路由：pip 包一键安装。

安全约束：
  • 只允许安装 PIPPABLE_PACKAGES 白名单中的包（避免任意命令执行）
  • 监听 127.0.0.1 时局域网无法访问（控制台 bind 限制）

返回完整 stdout（不流式 SSE）。如需流式进度，参考 routes/docker.py 的 pull_image 实现。
"""
from __future__ import annotations

import subprocess
import sys
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.tools_detector import pip_installable_packages

router = APIRouter(prefix="/api/install", tags=["install"])


# 用户可一键安装的可选包白名单。
# 白名单 = 可选包（本表）∪ venv 必装 Python 包（tools_detector.PYTHON_PACKAGES，
# 单一数据源——加包只需在 tools_detector.py 的清单里加，此处自动放行）。
# 如需新增纯可选包，仅在此处添加即可。
PIPPABLE_PACKAGES = {
    "frida-tools",
    "pyautogui", "pillow", "pyperclip",
    "httpx", "beautifulsoup4", "lxml", "html2text",
    "sympy", "gmpy2",
    "sse-starlette",  # 控制台自身
} | pip_installable_packages()


class InstallRequest(BaseModel):
    package: str          # pip 包名


@router.get("")
async def list_pippable() -> dict:
    """可一键安装的包白名单（前端据此显示行级安装按钮，避免两端硬编码漂移）。"""
    return {"packages": sorted(PIPPABLE_PACKAGES)}


@router.post("")
async def install_package(req: InstallRequest) -> dict:
    """同步执行 pip install，返回完整 stdout + stderr。

    安全：包名必须在白名单内。
    """
    pkg = req.package.strip()
    if pkg not in PIPPABLE_PACKAGES:
        raise HTTPException(
            status_code=400,
            detail=f"包 {pkg} 不在白名单内（PIPPABLE_PACKAGES）。控制台只允许安装预定义的包。"
        )

    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg],
            capture_output=True, text=True, timeout=120,
        )
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
            "error": "安装超时（120s）",
        }
