"""控制台后端纯单元测试（不起进程）。

历史注记: 本文件原含 port_manager（bind 顺延/端口文件/probe）三组测试——
IPC 化（2026-08-20）删除该机制时遗漏清理，2026-08-22 OCR 进程内化回归时发现并移除。
"""
import os

# 与生产 spawn env 对齐：跳过 HF 联网版本检查（否则 httpx 在无网/代理环境下报 client closed）
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / ".opencode" / "control" / "backend"
sys.path.insert(0, str(BACKEND))


class TestHealthLogic:
    """/health 状态由模型加载状态决定（503 loading → 200 ok）。

    不起 HTTP——直接验证 model_loader 的就绪标志 is_models_ready（routes/health.py 消费同一状态）。
    """

    def test_preload_flag_starts_false_then_true(self):
        from services import model_loader

        model_loader.get_embedder()  # 同步加载（模型在 HF cache，秒级）
        assert model_loader.is_models_ready() is True


class TestHardwareCpuInfo:
    """CPU 频率查询的降级路径：平台不支持时必须返回 None，端点不得 500。"""

    def test_cpu_freq_unsupported_degrades_to_none(self, monkeypatch):
        import psutil

        from routes import hardware

        for exc in (
            FileNotFoundError("[Errno 2] sysctl(HW_CPU_FREQ)"),
            NotImplementedError("platform does not support cpu_freq"),
        ):

            def raise_exc(_exc=exc):
                raise _exc

            monkeypatch.setattr(psutil, "cpu_freq", raise_exc)
            info = hardware._get_cpu_info()
            assert info["frequency_mhz"] is None
            assert info["physical_cores"] >= 1
            assert info["logical_cores"] >= 1

    def test_hardware_endpoint_200_when_cpu_freq_unsupported(self, monkeypatch):
        """回归：Apple Silicon macOS 无 sysctl(HW_CPU_FREQ)，曾使 /api/hardware 整体 500。"""
        import psutil
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from routes import hardware

        def unsupported():
            raise FileNotFoundError("[Errno 2] sysctl(HW_CPU_FREQ)")

        monkeypatch.setattr(psutil, "cpu_freq", unsupported)
        monkeypatch.setattr(hardware, "_get_gpu_info", lambda: [])

        app = FastAPI()
        app.include_router(hardware.router)
        r = TestClient(app).get("/api/hardware")

        assert r.status_code == 200
        assert r.json()["cpu"]["frequency_mhz"] is None
