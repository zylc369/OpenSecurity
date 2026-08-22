"""后端管理的进程清单（GET /api/processes，控制台进程页）。

数据源（两个，全部已在现有服务中持有，本模块只做汇总不改状态）：
  1. 控制台主进程   — os.getpid()；BGE 双模型 + OCR（进程内加载）常驻其内
  2. vite dev      — frontend_port（独立进程组，pid 未记录，按端口识别）

OCR 引用计数/加载态的可视化在模型板块（/api/models 的 active_clients）。

内存口径（两种，前端同时展示）：
  - footprint = 活动监视器"内存"列同口径（phys_footprint：含压缩页 +
    GPU/Metal 映射）。模型权重在 Metal 缓冲区，RSS 看不见
    （实测 RSS 1.0GB vs footprint 3.7GB，差 3 倍+）
  - RSS = psutil 驻留集（未压缩页；macOS 内存压力下闲置页被压缩后会骤降）
  footprint 经 /usr/bin/footprint 获取（macOS 自带，~0.2s/进程）；
  非 darwin 或工具缺失返回 None，前端回退显示 RSS。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field

import psutil

from services.frontend_port import frontend_ports


@dataclass
class ProcessInfo:
    """单个受管进程的展示快照。"""
    key: str                          # console / vite
    name: str                         # 显示名
    pid: int | None                   # vite 未记录 pid（独立进程组）
    role: str                         # 用途说明（含内存构成解释）
    status: str                       # running / starting / stopping / stopped
    memory_mb: float | None           # RSS
    cmdline: str                      # 截断后的启动命令
    memory_footprint_mb: float | None = None   # 活动监视器口径（仅 macOS）
    ref_count: int | None = None      # 仅 OCR（引用计数）
    holders: list[dict] = field(default_factory=list)   # OCR 持有者明细
    last_active_at: float | None = None                # OCR 最后活跃时间戳
    extra: str = ""                   # 端口等附加信息


@dataclass
class ProcessRegistryView:
    """GET /api/processes 响应体。"""
    generated_at: float
    processes: list[ProcessInfo]


_FOOTPRINT_RE = re.compile(r"Footprint:\s*([\d.]+)\s*([BKMGT])")
_UNIT_TO_MB = {"B": 1 / 1048576, "K": 1 / 1024, "M": 1.0, "G": 1024.0, "T": 1048576.0}


def _footprint_mb(pid: int) -> float | None:
    """macOS phys_footprint（活动监视器"内存"列同口径）。非 darwin/失败返回 None。"""
    if sys.platform != "darwin":
        return None
    try:
        r = subprocess.run(["/usr/bin/footprint", str(pid)],
                           capture_output=True, text=True, timeout=5)
        m = _FOOTPRINT_RE.search(r.stdout)
        if not m:
            return None
        return round(float(m.group(1)) * _UNIT_TO_MB[m.group(2)], 1)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _pid_on_port(port: int) -> int | None:
    """监听指定端口的进程 PID（反查；无监听/工具不可用返回 None）。

    平台策略（实测结论）：
      - Windows/Linux: psutil.net_connections（Windows 免 admin；
        Linux 经 /proc 同用户进程免 root）
      - macOS: psutil 全局连接表需要 root（AccessDenied）→ 用 lsof
        （系统自带，可查本用户进程的 socket）
    """
    if sys.platform != "darwin":
        try:
            for c in psutil.net_connections(kind="tcp"):
                if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port:
                    return c.pid
            return None
        except (psutil.AccessDenied, psutil.Error):
            pass   # Linux 受限环境 → lsof 兜底
    try:
        r = subprocess.run(["lsof", "-ti", f":{port}", "-sTCP:LISTEN"],
                           capture_output=True, text=True, timeout=5)
        out = r.stdout.strip().splitlines()
        return int(out[0]) if out else None
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return None


def _ps_proc_info(pid: int) -> tuple[float | None, str, float | None]:
    """安全读取 pid 的 RSS(MB)、命令行、footprint(MB)。进程消失返回 (None, "", None)。"""
    try:
        p = psutil.Process(pid)
        mem = round(p.memory_info().rss / 1048576, 1)
        cmd = " ".join(p.cmdline())[:200]
        return mem, cmd, _footprint_mb(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None, "", None


def collect_processes() -> ProcessRegistryView:
    """汇总三个受管进程的当前快照。"""
    procs: list[ProcessInfo] = []

    # 1. 控制台主进程
    own = os.getpid()
    mem, cmd, fp = _ps_proc_info(own)
    procs.append(ProcessInfo(
        key="console",
        name="控制台后端",
        pid=own,
        role="FastAPI 服务（deps/docker/config/models API）。BGE-M3 + BGE-Reranker 双模型常驻本进程内（Metal/GPU 映射 + 压缩页不体现在 RSS，看内存总量以 footprint 为准）",
        status="running",
        memory_mb=mem,
        cmdline=cmd,
        memory_footprint_mb=fp,
    ))


    # 3. vite dev server（独立进程组 spawn 时未记录 PID，按监听端口反查）
    port = frontend_ports.vite_port()
    vpid = _pid_on_port(port) if port else None
    if vpid is not None:
        vmem, vcmd, vfp = _ps_proc_info(vpid)
        vstatus = "running"
    else:
        vmem, vcmd, vfp, vstatus = None, "", None, ("running" if port else "stopped")
    procs.append(ProcessInfo(
        key="vite",
        name="vite dev server",
        pid=vpid,
        role="前端开发服务器（CONTROL_FRONTEND_DEV=1 时由控制台自动拉起；独立进程组，控制台重启不连带退出）",
        status=vstatus,
        memory_mb=vmem,
        cmdline=vcmd,
        memory_footprint_mb=vfp,
        extra=f"port={port}" if port else "",
    ))

    return ProcessRegistryView(generated_at=time.time(), processes=procs)
