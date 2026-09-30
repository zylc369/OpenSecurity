"""/api/hardware 路由：硬件规格查询。

注意：规格查询是一次性的（启动后基本不变），不是实时监控。
GPU 规格用于判断模型/功能适用性（如 Apple Silicon 可用 MLX/MPS）。
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import TypedDict, cast

import psutil
from fastapi import APIRouter

router = APIRouter(prefix="/api/hardware", tags=["hardware"])

# ── 响应模型（字段名=JSON 键名，与前端 types/index.ts 契约一致）─────────────
# 序列化说明: 全字段输出（含 null）。原 dict 实现对 GPU 可选键是"有则输出"，
# 模型化为恒定键集属加性变化（null 补位），消费方按字段读取，兼容。


@dataclass
class CpuInfo:
    physical_cores: int
    logical_cores: int
    frequency_mhz: float | None


@dataclass
class MemoryInfo:
    total_gb: float
    available_gb: float


@dataclass
class OsInfo:
    system: str
    platform: str
    machine: str
    version: str


@dataclass
class GpuInfo:
    name: str
    metal: str | None = None       # macOS: Metal 支持等级
    vram: str | None = None        # macOS: 原始串（如 "8 GB"）
    vendor: str | None = None      # macOS
    vram_gb: float | None = None   # Windows
    vram_mb: int | None = None     # Linux nvidia-smi
    capabilities: list[str] = field(default_factory=list)


@dataclass
class HardwareInfo:
    cpu: CpuInfo
    memory: MemoryInfo
    os: OsInfo
    gpu: list[GpuInfo]


class _WinGpuEntry(TypedDict):
    """Windows PowerShell JSON 输出的解析边界模型（TypedDict 仅限此层）。"""

    Name: str
    VRAM_GB: float | None


@router.get("")
async def get_hardware_info() -> HardwareInfo:
    """返回硬件规格（CPU + 内存 + GPU）。"""
    return HardwareInfo(
        cpu=_get_cpu_info(),
        memory=_get_memory_info(),
        os=_get_os_info(),
        gpu=_get_gpu_info(),
    )


def _get_cpu_info() -> CpuInfo:
    return CpuInfo(
        physical_cores=psutil.cpu_count(logical=False) or 0,
        logical_cores=psutil.cpu_count(logical=True) or 0,
        frequency_mhz=_cpu_max_frequency_mhz(),
    )


def _cpu_max_frequency_mhz() -> float | None:
    """CPU 最大频率（MHz）；平台不支持频率查询时返回 None（前端隐藏该字段）。

    已见失败模式：Apple Silicon macOS 无 sysctl(HW_CPU_FREQ)，
    psutil.cpu_freq() 抛 FileNotFoundError；受限环境可能抛 OSError/NotImplementedError。
    """
    try:
        freq = psutil.cpu_freq()
    except (OSError, NotImplementedError):
        return None
    return freq.max if freq else None


def _get_memory_info() -> MemoryInfo:
    vm = psutil.virtual_memory()
    return MemoryInfo(
        # psutil 的 svmem 字段在其类型标注中为 Any——cast(int) 为恒等声明（字节量必为 int）
        total_gb=round(cast(int, vm.total) / 1024**3, 1),
        available_gb=round(cast(int, vm.available) / 1024**3, 1),
    )


def _get_os_info() -> OsInfo:
    return OsInfo(
        system=platform.system(),    # Darwin / Linux / Windows
        platform=sys.platform,       # darwin / linux / win32
        machine=platform.machine(),  # arm64 / x86_64
        version=platform.version(),
    )


def _get_gpu_info() -> list[GpuInfo]:
    """跨平台 GPU 规格查询。返回 GPU 列表。"""
    if sys.platform == "darwin":
        return _get_gpu_macos()
    elif sys.platform == "win32":
        return _get_gpu_windows()
    else:
        return _get_gpu_linux()


def _get_gpu_macos() -> list[GpuInfo]:
    """macOS: system_profiler SPDisplaysDataType。"""
    try:
        r = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True, text=True, timeout=5,
        )
        gpus: list[GpuInfo] = []
        name: str | None = None
        metal: str | None = None
        vram: str | None = None
        vendor: str | None = None

        def _flush() -> None:
            nonlocal name, metal, vram, vendor
            if name is not None:
                gpus.append(GpuInfo(name=name, metal=metal, vram=vram, vendor=vendor))
            name = metal = vram = vendor = None

        for line in r.stdout.splitlines():
            line = line.strip()
            if "Chipset Model" in line:
                _flush()
                name = line.split(":", 1)[1].strip()
            elif "Metal Support" in line and name is not None:
                metal = line.split(":", 1)[1].strip()
            elif "VRAM" in line and name is not None:
                vram = line.split(":", 1)[1].strip()
            elif "Vendor" in line and name is not None:
                vendor = line.split(":", 1)[1].strip()
        _flush()
        # 标记可用能力
        for g in gpus:
            g.capabilities = _infer_gpu_capabilities(g)
        return gpus
    except (subprocess.TimeoutExpired, OSError):
        return []


def _get_gpu_windows() -> list[GpuInfo]:
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
        data = cast("list[_WinGpuEntry] | _WinGpuEntry", json.loads(r.stdout))
        if isinstance(data, dict):
            data = [data]
        return [
            GpuInfo(
                name=d.get("Name", ""),
                vram_gb=d.get("VRAM_GB"),
                # 原实现仅以 name 推断能力（临时 dict 不含 vram）——保持零漂移
                capabilities=_infer_gpu_capabilities(GpuInfo(name=d.get("Name", ""))),
            )
            for d in data
        ]
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return []


def _get_gpu_linux() -> list[GpuInfo]:
    """Linux: nvidia-smi 优先，lspci 回退。"""
    if shutil.which("nvidia-smi"):
        try:
            r = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=name,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            gpus: list[GpuInfo] = []
            for line in r.stdout.splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2:
                    gpus.append(GpuInfo(
                        name=parts[0],
                        vram_mb=int(parts[1]),
                        capabilities=["cuda"] if "nvidia" in parts[0].lower() else [],
                    ))
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
                    gpus.append(GpuInfo(name=name, capabilities=[]))
            return gpus
        except (subprocess.TimeoutExpired, OSError):
            pass

    return []


def _infer_gpu_capabilities(gpu: GpuInfo) -> list[str]:
    """根据 GPU 信息推断可用能力（前端展示用）。"""
    caps: list[str] = []
    name = gpu.name.lower()
    metal = (gpu.metal or "").lower()
    vram = gpu.vram_gb or gpu.vram_mb

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
