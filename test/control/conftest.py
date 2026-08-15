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
def control_server(tmp_path_factory):
    """启动发布态沙箱控制台实例（E2E/API 共享）。

    隔离铁律：
      • DATA_DIR → tmp 沙箱（端口/users/lock 全隔离）
      • CONTROL_FRONTEND_DEV=0（env 优先级，不碰真实 .ai_env）
      • CONTROL_PORT 随机高位（bind 候选 + 孤儿探测范围整体避开生产 9776）
      • users 写入测试进程引用（防周期清洗自杀）
    """
    if not VENV_PYTHON.exists():
        pytest.skip("venv python 不存在")

    import random

    data_dir = tmp_path_factory.mktemp("frontend_test")
    rand_port = random.randint(41000, 49000)
    env = {
        **os.environ,
        "DATA_DIR": str(data_dir),
        "CONTROL_FRONTEND_DEV": "0",
        "CONTROL_PORT": str(rand_port),
    }

    proc = subprocess.Popen(
        [str(VENV_PYTHON), str(BACKEND_DIR / "server.py")],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    port = None
    try:
        port_file = data_dir / ".opencode-control.port"
        for _ in range(20):
            if port_file.exists():
                port = int(port_file.read_text().strip().split("\n")[0])
                break
            time.sleep(0.5)
        assert port, "控制台端口文件 10s 内未出现"

        users = data_dir / ".opencode-control.users"
        users.write_text(f"pid={os.getpid()} start_time={time.time()}\n")

        yield port
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
