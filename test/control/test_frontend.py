"""前端集成测试（pytest 版，替代原 control/test_frontend.sh）。

验证：控制台以发布态启动后，前端 dist 静态资源与 API 同时工作。

隔离设计（吸收 .sh 版的事故教训）：
  • DATA_DIR → tmp_path 沙箱（端口文件/users/lock 均隔离）
  • CONTROL_FRONTEND_DEV 环境变量 = "0"（经 config.is_dev_mode 的 env 优先级生效，
    不落地修改真实 .ai_env——.sh 版 kill -9 时 trap 不执行会永久污染开发机开关）
  • 假 users 条目防止控制台周期清洗自杀
"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2] / ".opencode" / "control" / "backend"
VENV_PYTHON = Path.home() / "bw-security-analysis" / ".venv" / "bin" / "python"


@pytest.fixture(scope="module")
def control_server(tmp_path_factory):
    """启动发布态控制台实例（module 级复用，模型只加载一次）。"""
    if not VENV_PYTHON.exists():
        pytest.skip("venv python 不存在")

    data_dir = tmp_path_factory.mktemp("frontend_test")
    env = {
        **os.environ,
        "DATA_DIR": str(data_dir),
        "CONTROL_FRONTEND_DEV": "0",  # 发布态：挂载 dist/（env 优先级高于 .ai_env）
    }

    proc = subprocess.Popen(
        [str(VENV_PYTHON), "-c", f"""
import sys; sys.path.insert(0, {str(BACKEND_DIR)!r})
import config
config.USERS_CLEANUP_INTERVAL_SEC = 600
from server import main
main()
"""],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    port = None
    try:
        # 等端口文件出现（最多 10s）
        port_file = data_dir / ".opencode-control.port"
        for _ in range(20):
            if port_file.exists():
                port = int(port_file.read_text().strip().split("\n")[0])
                break
            time.sleep(0.5)
        assert port, "控制台端口文件 10s 内未出现"

        # 假 users 引用，防周期清洗自杀（start_time=0 与真实不符，但 PID 99999 死条目
        # 会被 cleanup 清掉——用远 future start_time 也不行；正确做法：控制台清洗只
        # 在 users 空时自杀，保留一条死条目会被清后变空。所以用当前测试进程 PID）
        users = data_dir / ".opencode-control.users"
        users.write_text(f"pid={os.getpid()} start_time={time.time()}\n")

        yield port
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_root_returns_html(control_server):
    r = httpx.get(f"http://127.0.0.1:{control_server}/", timeout=5)
    assert r.status_code == 200
    assert "DOCTYPE html" in r.text
    assert 'id="root"' in r.text


def test_root_references_react_bundle(control_server):
    r = httpx.get(f"http://127.0.0.1:{control_server}/", timeout=5)
    assert "/assets/" in r.text, "发布态应引用构建产物"


def test_js_asset_200(control_server):
    html = httpx.get(f"http://127.0.0.1:{control_server}/", timeout=5).text
    import re
    m = re.search(r'/assets/[^"]+\.js', html)
    assert m, "HTML 中未找到 JS 资源引用"
    r = httpx.get(f"http://127.0.0.1:{control_server}{m.group(0)}", timeout=10)
    assert r.status_code == 200


def test_css_asset_200(control_server):
    html = httpx.get(f"http://127.0.0.1:{control_server}/", timeout=5).text
    import re
    m = re.search(r'/assets/[^"]+\.css', html)
    assert m, "HTML 中未找到 CSS 资源引用"
    r = httpx.get(f"http://127.0.0.1:{control_server}{m.group(0)}", timeout=10)
    assert r.status_code == 200


def test_api_health_coexists(control_server):
    """B 方案：模型加载期 503、就绪后 200——两者都证明 API 与前端共存正常。"""
    r = httpx.get(f"http://127.0.0.1:{control_server}/health", timeout=5)
    assert r.status_code in (200, 503)
    assert "status" in r.json()


def test_api_config_coexists(control_server):
    r = httpx.get(f"http://127.0.0.1:{control_server}/api/config", timeout=10)
    assert r.status_code == 200
    assert "DEEPSEEK_API_KEY" in r.json()


def test_api_scan_coexists(control_server):
    r = httpx.get(f"http://127.0.0.1:{control_server}/api/scan", timeout=30)
    assert r.status_code == 200
    assert "agents" in r.json()


def test_api_hardware_coexists(control_server):
    r = httpx.get(f"http://127.0.0.1:{control_server}/api/hardware", timeout=10)
    assert r.status_code == 200
    assert "cpu" in r.json()


def test_embed_works_after_model_load(control_server):
    """等模型加载完（503→200），/embed 仍可调（前端不影响 API）。"""
    for _ in range(40):
        try:
            if httpx.get(f"http://127.0.0.1:{control_server}/health", timeout=3).json().get("status") == "ok":
                break
        except Exception:
            pass
        time.sleep(1)
    r = httpx.post(
        f"http://127.0.0.1:{control_server}/embed",
        json={"inputs": "test"},
        timeout=60,
    )
    assert r.status_code == 200
    vecs = r.json()
    assert isinstance(vecs, list) and len(vecs[0]) == 1024
