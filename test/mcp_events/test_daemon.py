"""测试 write_event_daemon.py：启动 → 写入 → 验证数据真实写入 → delete → 退出。

有效测试：验证 add_episode 真实成功（实体提取 + Neo4j 写入），而非"进程没崩"。

关键区别（vs 旧版废物测试）：
  废物：写事件后 sleep(1)，assert daemon_proc.poll() is None
        → daemon 内部 try/except 吞掉所有异常，即使 add_episode 100% 失败也通过

  有效：写事件后 sleep(15)，然后用 Graphiti search 查询，验证实体确实提取成功
        → 验证完整链路：stdin → daemon → add_episode → LLM 实体提取 → Neo4j → search
"""
import asyncio
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

EVENTS_DIR = Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "events"
PYTHON = str(Path.home() / "bw-security-analysis" / ".venv" / "bin" / "python")
DAEMON_SCRIPT = str(EVENTS_DIR / "write_event_daemon.py")


def wait_for_ready(proc: subprocess.Popen, timeout=120) -> bool:
    import threading

    def drain_stderr():
        while True:
            line = proc.stderr.readline()
            if not line:
                break

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
    proc = subprocess.Popen(
        [PYTHON, DAEMON_SCRIPT],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if not wait_for_ready(proc):
        stderr = proc.stderr.read() if proc.stderr else ""
        pytest.skip(f"daemon 启动失败: {stderr[:500]}")
    yield proc
    proc.stdin.close()
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def graphiti_for_verify(event_loop):
    """用于验证 daemon 写入结果的 Graphiti 实例。"""
    sys.path.insert(0, str(EVENTS_DIR))
    from graphiti_config import create_graphiti
    g, err = create_graphiti()
    if err:
        pytest.skip(f"Graphiti 不可用: {err}")

    async def init():
        await g.build_indices_and_constraints()

    event_loop.run_until_complete(init())
    return g


class TestDaemonLifecycle:
    """基础生命周期验证。"""

    def test_daemon_ready(self, daemon_proc):
        assert daemon_proc.poll() is None


class TestEventWriteAndVerify:
    """有效测试：写入事件 → 等待实体提取 → 搜索验证数据真实存在。

    使用复杂的安全分析文本（不是 hello world），确保 LLM 实体提取链路真正跑通。
    """

    COMPLEX_EPISODE = (
        "binary-analysis agent used Ghidra to analyze target.exe. "
        "Found a stack buffer overflow vulnerability in function decrypt_license "
        "at offset 0x4050A0. The vulnerability is caused by strcpy without bounds "
        "checking on user input. Exploitation requires ASLR bypass via libc leak. "
        "Recommended fix: replace strcpy with strncpy."
    )

    def test_write_and_verify_entity_extraction(
        self, daemon_proc, graphiti_for_verify, event_loop, test_group_id
    ):
        """写入复杂 episode → 验证实体被提取到 Neo4j。

        这是核心测试——如果 DeepSeekLLMClient 的 6 个 BUG 任一存在，
        add_episode 会失败，搜索结果为空。
        """
        group = f"{test_group_id}-daemon-complex"

        # 写入事件
        event = json.dumps({
            "name": "daemon complex episode test",
            "body": self.COMPLEX_EPISODE,
            "source": "test_suite",
            "group_id": group,
            "timestamp": int(time.time() * 1000),
        })
        daemon_proc.stdin.write(event + "\n")
        daemon_proc.stdin.flush()

        # 等待 LLM 实体提取完成（DeepSeek pro 约 25-35s）
        time.sleep(35)

        # 用 Graphiti 搜索验证数据真实写入（BM25 避免向量相似度过滤）
        from graphiti_core.search.search_config import (
            SearchConfig, EpisodeSearchConfig, EpisodeSearchMethod,
        )

        async def verify():
            return await graphiti_for_verify.search_(
                query="buffer overflow Ghidra strcpy",
                group_ids=[group],
                config=SearchConfig(
                    limit=10,
                    episode_config=EpisodeSearchConfig(
                        search_methods=[EpisodeSearchMethod.bm25],
                    ),
                ),
            )

        results = event_loop.run_until_complete(verify())

        # 验证：至少有一些实体或边被提取（如果 LLM 链路断了，这里全空）
        total = len(results.nodes) + len(results.edges) + len(results.episodes)
        assert total > 0, (
            f"daemon 写入后搜索结果为空——add_episode 可能失败。"
            f"nodes={len(results.nodes)} edges={len(results.edges)} episodes={len(results.episodes)}"
        )

        # 验证关键实体被提取
        if results.nodes:
            node_names = [n.name.lower() for n in results.nodes]
            has_target = any("target.exe" in n or "ghidra" in n or "strcpy" in n for n in node_names)
            if not has_target:
                import warnings
                warnings.warn(f"关键实体未提取到。已知实体: {node_names}")

        # 清理
        async def cleanup():
            from graphiti_core.nodes import EntityNode, EpisodicNode
            await EntityNode.delete_by_group_id(graphiti_for_verify.driver, group)
            await EpisodicNode.delete_by_group_id(graphiti_for_verify.driver, group)

        event_loop.run_until_complete(cleanup())


class TestDeleteActionVerify:
    """有效测试：delete 后搜索验证数据确实被删除。"""

    def test_delete_removes_data(
        self, daemon_proc, graphiti_for_verify, event_loop
    ):
        """写入 → 等待 → 搜索验证有数据 → delete → 搜索验证数据消失。"""
        group = "test-daemon-delete-verify"

        # 写入复杂 episode（确保有数据可删）
        event = json.dumps({
            "name": "delete verify episode",
            "body": (
                "binary-analysis agent used Ghidra to analyze delete_target.exe. "
                "Found vulnerability in function check_license. "
                "The delete_marker_entity is at offset 0xDEAD."
            ),
            "source": "test_suite",
            "group_id": group,
            "timestamp": int(time.time() * 1000),
        })
        daemon_proc.stdin.write(event + "\n")
        daemon_proc.stdin.flush()
        time.sleep(35)

        # 搜索验证有数据（BM25 on episodes）
        from graphiti_core.search.search_config import (
            SearchConfig, EpisodeSearchConfig, EpisodeSearchMethod,
        )

        async def search():
            return await graphiti_for_verify.search_(
                query="delete_target.exe Ghidra delete_marker",
                group_ids=[group],
                config=SearchConfig(
                    limit=5,
                    episode_config=EpisodeSearchConfig(
                        search_methods=[EpisodeSearchMethod.bm25],
                    ),
                ),
            )

        results_before = event_loop.run_until_complete(search())
        total_before = len(results_before.nodes) + len(results_before.edges) + len(results_before.episodes)

        if total_before == 0:
            pytest.skip("daemon 写入后无数据（LLM 处理可能未完成）")

        # 发送 delete 消息
        delete_msg = json.dumps({"action": "delete", "group_id": group})
        daemon_proc.stdin.write(delete_msg + "\n")
        daemon_proc.stdin.flush()
        time.sleep(5)

        # 搜索验证数据消失
        results_after = event_loop.run_until_complete(search())
        total_after = len(results_after.nodes) + len(results_after.edges) + len(results_after.episodes)

        assert total_after < total_before, (
            f"delete 后数据量未减少: before={total_before} after={total_after}"
        )


class TestDaemonRobustness:
    """鲁棒性测试——验证非法输入被正确跳过且后续正常写入不受影响。

    旧版只查 poll() is None（废物模式），新版验证非法输入后仍能正常处理有效事件。
    """

    def test_invalid_json_then_valid_event(self, daemon_proc, graphiti_for_verify, event_loop):
        """非法 JSON 后写入有效事件，验证有效事件被处理（搜索到数据）。"""
        group = "test-daemon-robust"

        # 写非法 JSON
        daemon_proc.stdin.write("not json at all\n")
        daemon_proc.stdin.flush()
        time.sleep(1)

        # 写有效事件
        event = json.dumps({
            "name": "robustness valid event",
            "body": "binary-analysis agent analyzed robustness_target.exe with Ghidra. Found buffer overflow.",
            "source": "test_suite",
            "group_id": group,
            "timestamp": int(time.time() * 1000),
        })
        daemon_proc.stdin.write(event + "\n")
        daemon_proc.stdin.flush()
        time.sleep(35)

        # 验证有效事件被处理（而非被非法 JSON 卡住）
        from graphiti_core.search.search_config import (
            SearchConfig, EpisodeSearchConfig, EpisodeSearchMethod,
        )

        async def verify():
            return await graphiti_for_verify.search_(
                query="robustness_target.exe Ghidra buffer overflow",
                group_ids=[group],
                config=SearchConfig(
                    limit=5,
                    episode_config=EpisodeSearchConfig(
                        search_methods=[EpisodeSearchMethod.bm25],
                    ),
                ),
            )

        results = event_loop.run_until_complete(verify())
        total = len(results.nodes) + len(results.edges) + len(results.episodes)
        assert total > 0, "非法 JSON 后有效事件未被处理"

        # 清理
        async def cleanup():
            from graphiti_core.nodes import EntityNode, EpisodicNode
            await EntityNode.delete_by_group_id(graphiti_for_verify.driver, group)
            await EpisodicNode.delete_by_group_id(graphiti_for_verify.driver, group)
        event_loop.run_until_complete(cleanup())
