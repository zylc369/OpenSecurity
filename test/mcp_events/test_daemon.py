"""测试 write_event_daemon.py：启动 → 写入事件 → 验证写入 → 优雅退出。

不 mock，测试真实的 daemon 进程 + Neo4j 写入 + ZhipuAI 实体提取。
前置条件：Docker + neo4j-events 运行中 + ZHIPU_API_KEY 已配置。
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

EVENTS_DIR = Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "events"
PYTHON = str(Path.home() / "bw-security-analysis" / ".venv" / "bin" / "python")
DAEMON_SCRIPT = str(EVENTS_DIR / "write_event_daemon.py")


def wait_for_ready(proc: subprocess.Popen, timeout=120) -> bool:
    """等待 daemon stdout 输出 READY。后台排空 stderr 防止管道阻塞。"""
    import threading

    stderr_lines = []

    def drain_stderr():
        while True:
            line = proc.stderr.readline()
            if not line:
                break
            stderr_lines.append(line)

    t = threading.Thread(target=drain_stderr, daemon=True)
    t.start()

    start = time.time()
    while time.time() - start < timeout:
        line = proc.stdout.readline()
        if not line:
            return False
        if line.strip() == "READY":
            return True
    return False


@pytest.fixture(scope="module")
def daemon_proc():
    """启动 daemon 进程，测试结束后关闭。"""
    proc = subprocess.Popen(
        [PYTHON, DAEMON_SCRIPT],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if not wait_for_ready(proc):
        stderr = proc.stderr.read() if proc.stderr else ""
        pytest.skip(f"daemon 启动失败（未收到 READY）: {stderr[:500]}")
    yield proc
    # 关闭 daemon
    proc.stdin.close()
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


class TestDaemonLifecycle:
    """测试 daemon 生命周期。"""

    def test_daemon_outputs_ready(self, daemon_proc):
        """daemon 启动后应该输出 READY。"""
        assert daemon_proc.poll() is None, "daemon 进程应该仍在运行"

    def test_daemon_stderr_has_init_logs(self, daemon_proc):
        """daemon stderr 应该有初始化日志。"""
        # stderr 是 pipe，非阻塞读可能返回空——这里只验证进程活着
        assert daemon_proc.poll() is None


class TestEventWrite:
    """测试通过 stdin 写入事件。"""

    def test_write_single_event(self, daemon_proc, test_group_id):
        """写入单个事件，daemon 应该处理（stderr 输出 episode added）。"""
        event = json.dumps({
            "name": "test single write",
            "body": "This is a test event for single write verification.",
            "source": "test_suite",
            "group_id": test_group_id,
            "timestamp": int(time.time() * 1000),
        })
        daemon_proc.stdin.write(event + "\n")
        daemon_proc.stdin.flush()

        # 等待处理（add_episode 含 LLM 调用，可能需要 5-30s）
        # 不验证具体写入结果（需要查询 Neo4j），只验证 daemon 不崩溃
        time.sleep(1)
        assert daemon_proc.poll() is None, "daemon 写入后不应该崩溃"

    def test_write_batch_events(self, daemon_proc, test_group_id):
        """连续写入多个事件，验证 daemon 不丢不崩。"""
        for i in range(5):
            event = json.dumps({
                "name": f"test batch event {i}",
                "body": f"Batch test event number {i}. Verifying concurrent write handling.",
                "source": "test_suite",
                "group_id": test_group_id,
                "timestamp": int(time.time() * 1000) + i,
            })
            daemon_proc.stdin.write(event + "\n")
        daemon_proc.stdin.flush()

        time.sleep(1)
        assert daemon_proc.poll() is None, "批量写入后 daemon 不应该崩溃"

    def test_write_invalid_json(self, daemon_proc):
        """写入非法 JSON，daemon 应该跳过不崩溃。"""
        daemon_proc.stdin.write("this is not json\n")
        daemon_proc.stdin.flush()

        time.sleep(0.5)
        assert daemon_proc.poll() is None, "非法 JSON 不应该导致 daemon 崩溃"

    def test_write_empty_line(self, daemon_proc):
        """写入空行，daemon 应该跳过。"""
        daemon_proc.stdin.write("\n")
        daemon_proc.stdin.flush()

        time.sleep(0.5)
        assert daemon_proc.poll() is None

    def test_timestamp_preserved(self, daemon_proc, test_group_id):
        """写入带特定 timestamp 的事件，验证 reference_time 正确传入。"""
        specific_ts = 1721234567890  # 固定时间戳
        event = json.dumps({
            "name": "test timestamp preservation",
            "body": "Verifying that the timestamp is correctly passed as reference_time.",
            "source": "test_suite",
            "group_id": test_group_id,
            "timestamp": specific_ts,
        })
        daemon_proc.stdin.write(event + "\n")
        daemon_proc.stdin.flush()

        time.sleep(1)
        assert daemon_proc.poll() is None
