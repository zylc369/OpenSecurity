"""HTTP 端点下载吞吐测速器（通用组件——候选端点择优场景复用）。

用途: 同一资源存在多个候选源（官方/镜像、多个 CDN）时, 实测各端点吞吐择优。
方法: stream 读取 N 秒（读多少算多少, 不要求读完文件）——速率即真实下载速率
的近似; 不可达/异常 = 0.0（探测失败不抛出, 以数据表达）。

典型用法:
    from services.endpoint_probe import EndpointProber, ProbeSpec

    spec = ProbeSpec(path="BAAI/bge-m3/resolve/main/pytorch_model.bin")
    speeds = EndpointProber.probe_all(
        ["https://huggingface.co", "https://hf-mirror.com"], spec)
    best = EndpointProber.fastest(speeds)
    if best and EndpointProber.significantly_faster(speeds[1], speeds[0]):
        ...  # 镜像显著更快（>2x）才切换, 防抖动

设计约束:
- 纯 stdlib（urllib）——可被任何进程单独 import, 无三方依赖;
- 探测期间阻塞（秒级）——只在引导/低频决策点调用, 不要放请求热路径;
- 串行探测（简单可控; 端点多时的并行化按需后续追加）。
"""
from __future__ import annotations

import http.client
import time
import urllib.request
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True)
class EndpointSpeed:
    """单端点测速结果（mbps=0 且 error 非空 = 探测失败）。"""

    endpoint: str
    mbps: float          # 实测下载吞吐（MB/s）
    error: str = ""      # 非空 = 不可达/异常（此时 mbps 恒 0.0）


@dataclass(frozen=True)
class ProbeSpec:
    """测速参数（path 拼到各端点后构成完整 URL——各端点须服务同构资源）。"""

    path: str                     # 资源相对路径（如 "owner/repo/resolve/main/config.json"）
    duration_sec: float = 4.0     # stream 读取时长（秒）
    timeout_sec: float = 5.0      # 连接超时（秒）
    chunk_bytes: int = 64 * 1024  # 单次 read 块大小


class EndpointProber:
    """HTTP 端点下载吞吐测速（stream 读 N 秒; 全静态方法, 无状态可复用）。"""

    @staticmethod
    def probe(endpoint: str, spec: ProbeSpec) -> EndpointSpeed:
        """实测单端点吞吐。失败不抛出——以 EndpointSpeed(error=...) 表达。"""
        url = f"{endpoint.rstrip('/')}/{spec.path.lstrip('/')}"
        try:
            # urlopen 重载返回 Any——https URL 的实际类型是 HTTPResponse（read->bytes）
            resp = cast("http.client.HTTPResponse",
                        urllib.request.urlopen(url, timeout=spec.timeout_sec))  # pyright: ignore[reportAny]
            with resp:
                deadline = time.monotonic() + spec.duration_sec
                total = 0
                while time.monotonic() < deadline:
                    chunk = resp.read(spec.chunk_bytes)
                    if not chunk:
                        break
                    total += len(chunk)
            return EndpointSpeed(
                endpoint=endpoint,
                mbps=round(total / 1024 / 1024 / spec.duration_sec, 2))
        except OSError as e:
            return EndpointSpeed(endpoint=endpoint, mbps=0.0, error=str(e))

    @classmethod
    def probe_all(cls, endpoints: list[str], spec: ProbeSpec) -> list[EndpointSpeed]:
        """按入参顺序逐一测速（结果顺序与 endpoints 对齐, 便于按下标比较）。"""
        return [cls.probe(ep, spec) for ep in endpoints]

    @staticmethod
    def fastest(speeds: list[EndpointSpeed]) -> EndpointSpeed | None:
        """吞吐最高者（全失败/空列表 → None）。"""
        return max(speeds, key=lambda s: s.mbps) if speeds else None

    @staticmethod
    def significantly_faster(candidate: EndpointSpeed, baseline: EndpointSpeed,
                             ratio: float = 2.0) -> bool:
        """candidate 是否比 baseline 显著快（>ratio 倍; 防抖动阈值）。

        baseline 失败（0.0）且 candidate 有速度 → 恒为 True（0 之上的任何
        倍数都显著）; 双双失败 → False（无依据不决策）。
        """
        if candidate.error or candidate.mbps <= 0:
            return False
        if baseline.mbps <= 0:
            return not baseline.error or baseline.mbps < candidate.mbps
        return candidate.mbps > baseline.mbps * ratio
