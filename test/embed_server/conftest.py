"""embed_server / embed_client 共享 fixtures。

测试分两类：
1. 单元测试（不需要运行 embed_server）：bind_available_port、_read_port、health handler
2. 集成测试（需要运行 embed_server）：encode/predict、分层超时
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

# embed_server.py 和 embed_client.py 在 mcp-servers/
MCP_DIR = Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers"
sys.path.insert(0, str(MCP_DIR))


@pytest.fixture
def tmp_port_file(tmp_path):
    """临时端口文件（内容：端口\nPID）。"""
    port_file = tmp_path / ".embed_server_port"
    return port_file


@pytest.fixture
def running_embed_server(tmp_port_file):
    """启动真实的 embed_server（用于集成测试）。

    fixture 做了以下事：
    1. 创建临时 DATA_DIR
    2. 用子进程启动 embed_server.py（传入 DATA_DIR）
    3. 等待 /health 返回 200
    4. yield (port, pid)
    5. teardown: kill 进程

    如果 embed_server 无法启动（如模型未下载），pytest.skip。
    """
    import subprocess
    import time
    import httpx

    venv_python = Path.home() / "bw-security-analysis" / ".venv" / "bin" / "python"
    if not venv_python.exists():
        pytest.skip("venv python 不存在")

    embed_script = MCP_DIR / "embed_server.py"
    if not embed_script.exists():
        pytest.skip("embed_server.py 不存在")

    tmp_dir = str(tmp_port_file.parent)
    env = {**os.environ, "DATA_DIR": tmp_dir, "HF_HUB_OFFLINE": "1"}

    proc = subprocess.Popen(
        [str(venv_python), str(embed_script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    try:
        # 等端口文件出现
        port = None
        for _ in range(10):
            if tmp_port_file.exists():
                content = tmp_port_file.read_text().strip()
                port = int(content.split("\n")[0])
                break
            time.sleep(1)

        if port is None:
            pytest.skip("embed_server 端口文件 10s 内未出现")

        # 等 /health 200
        url = f"http://127.0.0.1:{port}/health"
        for _ in range(30):
            try:
                r = httpx.get(url, timeout=3)
                if r.status_code == 200:
                    yield port, proc.pid
                    return
            except Exception:
                pass
            time.sleep(2)

        pytest.skip("embed_server /health 60s 内未就绪")
    finally:
        proc.kill()
        proc.wait(timeout=5)
