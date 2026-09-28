"""embed_client / control_url / 控制台后端共享 fixtures。

- 纯单元测试（临时目录 + 环境变量隔离），不需要真实运行控制台的模块：
  test_embed_client.py / test_control_backend.py / test_control_url.py
- 需要沙箱控制台实例的集成/E2E 测试：test_frontend.py / test_frontend_e2e.py
  共享下方 control_server fixture（session 级，一个实例两个文件复用，模型只加载一次）。
"""
import os
import signal
import threading
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
      • OPENSECURITY_HOME → tmp 沙箱（IPC sock / TCP 候选段全隔离）
      • OPENCODE_ROOT → 沙箱 + stub .ai_env（不读真实配置；
        CONTROL_FRONTEND_DEV=0 写文件——发布态，不起 vite）
      • PATH 剥离宿主 OpenSecurity bin（工具可用性由沙箱决定：
        宿主已装工具不泄漏为"可用"，未安装→安装提示列状态确定化）
      • CONTROL_TCP_PORT 随机高位（bind 候选整体避开生产 9776）
      • 心跳上报测试进程引用（防心跳表空自杀）
    """
    if not VENV_PYTHON.exists():
        pytest.skip("venv python 不存在")

    import random

    import httpx

    # OPENSECURITY_HOME 必须是短路径：macOS AF_UNIX sock 路径 ≤104 字节，
    # pytest tmp_path（/private/var/folders/...）+ sock 文件名会超长 → bind 必败
    rand_port = random.randint(41000, 49000)
    opensecurity_home = Path(f"/tmp/frontend_test_{rand_port}")
    opensecurity_home.mkdir(parents=True, exist_ok=True)
    # 沙箱 OPENCODE_ROOT + stub .ai_env：配置隔离（不读真实 .ai_env）；
    # 文件显式 CONTROL_FRONTEND_DEV=0 → 发布态断言有效；stub 密钥供配置页断言
    opencode_root = opensecurity_home / "opencode_root"
    opencode_root.mkdir(parents=True, exist_ok=True)
    (opencode_root / ".ai_env").write_text(
        "CONTROL_FRONTEND_DEV=0\nDEEPSEEK_API_KEY=test-stub-key\n",
        encoding="utf-8",
    )
    # PATH 隔离：剥离宿主 OpenSecurity bin——工具可用性由沙箱决定（shutil.which
    # 不再命中宿主已装工具），"未安装→安装提示列"状态确定化（E2E 截断用例依赖）
    parent_home = os.environ.get("OPENSECURITY_HOME") or str(Path.home() / "bw-security-analysis")
    host_bin = str(Path(parent_home) / "bin")
    path_kept = ":".join(
        p for p in os.environ.get("PATH", "").split(":") if p and p != host_bin
    )
    env = {
        **os.environ,
        "OPENSECURITY_HOME": str(opensecurity_home),
        "OPENCODE_ROOT": str(opencode_root),
        "CONTROL_FRONTEND_DEV": "0",
        "CONTROL_TCP_PORT": str(rand_port),
        "PATH": path_kept,
    }

    proc = subprocess.Popen(
        [str(VENV_PYTHON), str(BACKEND_DIR / "server.py")],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    port = None
    heartbeat_stop: threading.Event | None = None
    try:
        sock_file = opensecurity_home / "opensecurity-control.sock"
        for _ in range(20):
            if sock_file.exists():
                try:
                    with httpx.Client(
                        transport=httpx.HTTPTransport(uds=str(sock_file)), timeout=2,
                    ) as probe:
                        probe.get("http://localhost/health")
                        # 控制台就绪——取 TCP 端口 + 心跳线程防自杀
                        with httpx.Client(
                            transport=httpx.HTTPTransport(uds=str(sock_file)), timeout=5,
                        ) as c:
                            port = c.get("http://localhost/api/console-url").json()["tcp_port"]
                            # 持续心跳（8s 周期线程，teardown 停）：单次心跳 60s 超时移除
                            # → 表空自杀（90s 宽限），此前全靠用例总时长 <90s 兜底，CI 慢机必翻车;
                            # 持续心跳同时为 /api/heartbeats 断言供真数据（本进程 alive=True）
                            heartbeat_stop = threading.Event()

                            def _beat(stop: threading.Event) -> None:
                                while not stop.wait(8):
                                    try:
                                        c2 = httpx.Client(
                                            transport=httpx.HTTPTransport(uds=str(sock_file)),
                                            timeout=5,
                                        )
                                        try:
                                            c2.post(
                                                "http://localhost/api/heartbeat",
                                                json={"pid": os.getpid()},
                                            )
                                        finally:
                                            c2.close()
                                    except OSError:
                                        pass  # 控制台退出（teardown 竞态）静默

                            threading.Thread(target=_beat, args=(heartbeat_stop,), daemon=True).start()
                            # 首跳立即发（不等首个 8s 周期）
                            c.post("http://localhost/api/heartbeat", json={"pid": os.getpid()})
                    break
                except OSError:
                    pass
            time.sleep(0.5)
        assert port, "控制台 IPC 通道 10s 内未就绪"

        yield port
    finally:
        if heartbeat_stop is not None:
            heartbeat_stop.set()
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        import shutil
        shutil.rmtree(opensecurity_home, ignore_errors=True)
