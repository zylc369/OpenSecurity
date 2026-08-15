"""/api/hardware 路由：硬件规格查询。

注意：规格查询是一次性的（启动后基本不变），不是实时监控。
GPU 规格用于判断模型/功能适用性（如 Apple Silicon 可用 MLX/MPS）。
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys

import psutil
from fastapi import APIRouter

router = APIRouter(prefix="/api/hardware", tags=["hardware"])


@router.get("")
async def get_hardware_info() -> dict:
    """返回硬件规格（CPU + 内存 + GPU）。"""
    return {
        "cpu": _get_cpu_info(),
        "memory": _get_memory_info(),
        "os": _get_os_info(),
        "gpu": _get_gpu_info(),
    }


def _get_cpu_info() -> dict:
    return {
        "physical_cores": psutil.cpu_count(logical=False) or 0,
        "logical_cores": psutil.cpu_count(logical=True) or 0,
        "frequency_mhz": psutil.cpu_freq().max if psutil.cpu_freq() else None,
    }


def _get_memory_info() -> dict:
    vm = psutil.virtual_memory()
    return {
        "total_gb": round(vm.total / 1024**3, 1),
        "available_gb": round(vm.available / 1024**3, 1),
    }


def _get_os_info() -> dict:
    return {
        "system": platform.system(),    # Darwin / Linux / Windows
        "platform": sys.platform,       # darwin / linux / win32
        "machine": platform.machine(),  # arm64 / x86_64
        "version": platform.version(),
    }


def _get_gpu_info() -> list[dict]:
    """跨平台 GPU 规格查询。返回 GPU 列表。"""
    if sys.platform == "darwin":
        return _get_gpu_macos()
    elif sys.platform == "win32":
        return _get_gpu_windows()
    else:
        return _get_gpu_linux()


def _get_gpu_macos() -> list[dict]:
    """macOS: system_profiler SPDisplaysDataType。"""
    try:
        r = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True, text=True, timeout=5,
        )
        gpus = []
        current = {}
        for line in r.stdout.splitlines():
            line = line.strip()
            if "Chipset Model" in line:
                if current:
                    gpus.append(current)
                current = {"name": line.split(":", 1)[1].strip()}
            elif "Metal Support" in line and current:
                current["metal"] = line.split(":", 1)[1].strip()
            elif "VRAM" in line and current:
                current["vram"] = line.split(":", 1)[1].strip()
            elif "Vendor" in line and current:
                current["vendor"] = line.split(":", 1)[1].strip()
        if current:
            gpus.append(current)
        # 标记可用能力
        for g in gpus:
            g["capabilities"] = _infer_gpu_capabilities(g)
        return gpus
    except (subprocess.TimeoutExpired, OSError):
        return []


def _get_gpu_windows() -> list[dict]:
    """Windows: PowerShell Get-CimInstance（wmic 已弃用）。"""
    try:
        r = subprocess.run(
            ["powershell", "-Command",
             "Get-CimInstance Win32_VideoController | "
             "Select-Object Name, @{N='VRAM_GB';E={[math]::Round($_.AdapterRAM/1GB,1)}} | "
             "ConvertTo-Json"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return []
        import json
        data = json.loads(r.stdout)
        if isinstance(data, dict):
            data = [data]
        return [{
            "name": d.get("Name", ""),
            "vram_gb": d.get("VRAM_GB"),
            "capabilities": _infer_gpu_capabilities({"name": d.get("Name", "")}),
        } for d in data]
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return []


def _get_gpu_linux() -> list[dict]:
    """Linux: nvidia-smi 优先，lspci 回退。"""
    if shutil.which("nvidia-smi"):
        try:
            r = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=name,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            gpus = []
            for line in r.stdout.splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2:
                    gpus.append({
                        "name": parts[0],
                        "vram_mb": int(parts[1]),
                        "capabilities": ["cuda"] if "nvidia" in parts[0].lower() else [],
                    })
            return gpus
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass

    if shutil.which("lspci"):
        try:
            r = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5)
            gpus = []
            for line in r.stdout.splitlines():
                if "VGA compatible controller" in line or "3D controller" in line:
                    name = line.split(":", 2)[-1].strip() if ":" in line else line
                    gpus.append({"name": name, "capabilities": []})
            return gpus
        except (subprocess.TimeoutExpired, OSError):
            pass

    return []


def _infer_gpu_capabilities(gpu: dict) -> list[str]:
    """根据 GPU 信息推断可用能力（前端展示用）。"""
    caps = []
    name = gpu.get("name", "").lower()
    metal = gpu.get("metal", "").lower()
    vram = gpu.get("vram_gb") or gpu.get("vram_mb")

    if "apple" in name or "m1" in name or "m2" in name or "m3" in name or "m4" in name:
        caps.append("mlx")
        caps.append("mps")
    if metal:
        caps.append("metal")
    if "nvidia" in name or "geforce" in name or "quadro" in name:
        caps.append("cuda")
        # 显存 >= 4GB 才推荐 GPU 推理
        if isinstance(vram, (int, float)) and vram >= 4:
            caps.append("gpu_inference")
    return caps
