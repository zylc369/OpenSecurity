"""embed_client / control_url / 控制台后端共享 fixtures。

- 纯单元测试（临时目录 + 环境变量隔离），不需要真实运行控制台的模块：
  test_embed_client.py / test_control_backend.py / test_control_url.py
- 需要沙箱控制台实例的集成/E2E 测试：test_frontend.py / test_frontend_e2e.py
  共享下方 control_server fixture（session 级，一个实例两个文件复用，模型只加载一次）。
"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

MCP_DIR = Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers"
sys.path.insert(0, str(MCP_DIR))

BACKEND_DIR = Path(__file__).resolve().parents[2] / ".opencode" / "control" / "backend"
VENV_PYTHON = Path.home() / "bw-security-analysis" / ".venv" / "bin" / "python"


@pytest.fixture(scope="session")
def control_server():
    """启动发布态沙箱控制台实例（E2E/API 共享）。

    隔离铁律：
      • DATA_DIR → tmp 沙箱（IPC sock / TCP 候选段全隔离）
      • CONTROL_FRONTEND_DEV=0（env 优先级，不碰真实 .ai_env）
      • CONTROL_TCP_PORT 随机高位（bind 候选整体避开生产 9776）
      • 心跳上报测试进程引用（防心跳表空自杀）
    """
    if not VENV_PYTHON.exists():
        pytest.skip("venv python 不存在")

    import random

    import httpx

    # DATA_DIR 必须是短路径：macOS AF_UNIX sock 路径 ≤104 字节，
    # pytest tmp_path（/private/var/folders/...）+ sock 文件名会超长 → bind 必败
    rand_port = random.randint(41000, 49000)
    data_dir = Path(f"/tmp/frontend_test_{rand_port}")
    data_dir.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "DATA_DIR": str(data_dir),
        "CONTROL_FRONTEND_DEV": "0",
        "CONTROL_TCP_PORT": str(rand_port),
    }

    proc = subprocess.Popen(
        [str(VENV_PYTHON), str(BACKEND_DIR / "server.py")],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    port = None
    try:
        sock_file = data_dir / "opensecurity-control.sock"
        for _ in range(20):
            if sock_file.exists():
                try:
                    with httpx.Client(
                        transport=httpx.HTTPTransport(uds=str(sock_file)), timeout=2,
                    ) as probe:
                        probe.get("http://localhost/health")
                        # 控制台就绪——取 TCP 端口 + 首跳心跳防自杀
                        with httpx.Client(
                            transport=httpx.HTTPTransport(uds=str(sock_file)), timeout=5,
                        ) as c:
                            port = c.get("http://localhost/api/console-url").json()["tcp_port"]
                            c.post("http://localhost/api/heartbeat", json={"pid": os.getpid()})
                        break
                except OSError:
                    pass
            time.sleep(0.5)
        assert port, "控制台 IPC 通道 10s 内未就绪"

        yield port
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        import shutil
        shutil.rmtree(data_dir, ignore_errors=True)
