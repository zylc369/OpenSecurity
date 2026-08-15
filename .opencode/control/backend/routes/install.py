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

router = APIRouter(prefix="/api/install", tags=["install"])


# 用户可一键安装的可选包白名单。
# 注意：这不是 detect_env.py PYTHON_PACKAGES 的同步镜像——
# PYTHON_PACKAGES 是 install.sh 必装的基础包（venv 创建时装），
# 本白名单是用户在控制台按需补装的包。
# 如需新增包，仅在此处添加即可（无需改其他文件）。
PIPPABLE_PACKAGES = {
    "frida", "frida-tools",
    "angr", "triton", "z3-solver",
    "playwright",
    "pyautogui", "pillow", "pyperclip",
    "httpx", "beautifulsoup4", "lxml", "html2text",
    "sympy", "gmpy2",
    "sse-starlette",  # 控制台自身
}


class InstallRequest(BaseModel):
    package: str          # pip 包名


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
