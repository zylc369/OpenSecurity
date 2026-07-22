"""单元测试：Docker 启动路径 + events MCP lifespan 完整初始化序列。

验证改造后的核心契约：
- _ensure_docker_daemon_blocking：Docker 已运行时立即返回；未运行时尝试启动
- _ensure_neo4j_container_blocking：容器已运行时立即返回；停止/不存在时启动/创建
- _preload_models_blocking：完整序列（Docker → 容器 → 模型）
- _ensure_ready：等待所有基础设施就绪
"""
import asyncio
import os
import sys
import time
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

VENV_PYTHON = Path.home() / "bw-security-analysis" / ".venv" / "bin" / "python"
SERVER = Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "events" / "server.py"
ENV = {**os.environ, "PYTHONPATH": str(SERVER.parent)}


class TestDockerHelpers(unittest.IsolatedAsyncioTestCase):
    """Layer 1：Docker 辅助函数单元测试（直接 import server 模块）。"""

    async def test_ensure_docker_daemon_returns_fast_if_running(self):
        """Docker daemon 已运行时 _ensure_docker_daemon_blocking 应 <5s 返回。"""
        sys.path.insert(0, str(SERVER.parent))
        import importlib
        import server
        importlib.reload(server)  # 确保最新代码

        t0 = time.time()
        # 直接调用（在主线程跑，仅用于验证 daemon 已运行的快速路径）
        await asyncio.to_thread(server._ensure_docker_daemon_blocking)
        elapsed = time.time() - t0
        print(f"\n  _ensure_docker_daemon_blocking 耗时: {elapsed:.2f}s")
        self.assertLess(elapsed, 5.0, f"daemon 已运行时应 <5s，实际 {elapsed:.2f}s")

    async def test_ensure_neo4j_container_returns_fast_if_running(self):
        """容器已运行时 _ensure_neo4j_container_blocking 应 <5s 返回。"""
        sys.path.insert(0, str(SERVER.parent))
        import importlib
        import server
        importlib.reload(server)

        t0 = time.time()
        await asyncio.to_thread(server._ensure_neo4j_container_blocking)
        elapsed = time.time() - t0
        print(f"\n  _ensure_neo4j_container_blocking 耗时: {elapsed:.2f}s")
        self.assertLess(elapsed, 5.0, f"容器已运行时应 <5s，实际 {elapsed:.2f}s")


class TestLifespanFullSequence(unittest.IsolatedAsyncioTestCase):
    """Layer 2：lifespan 完整初始化序列（Docker + 容器 + 模型）。"""

    async def test_lifespan_with_docker_already_running(self):
        """Docker + 容器已运行时，lifespan 子线程完整执行（Docker 检查 + 容器检查 + 模型加载）。

        预期：
        - 握手快（<2s，lifespan fire-and-forget）
        - 工具调用等待 _ready（含 BGE-M3 加载 ~10s）
        - 工具调用成功（基础设施全部就绪）
        """
        params = StdioServerParameters(command=str(VENV_PYTHON), args=[str(SERVER)], env=ENV)

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                t0 = time.time()
                await session.initialize()
                handshake = time.time() - t0
                print(f"\n  握手: {handshake:.2f}s（含 lifespan startup，不等子线程）")

                # 立即调用工具——等待 Docker 检查 + 容器检查 + BGE-M3 加载
                t0 = time.time()
                r = await session.call_tool("entity_by_label_search", {
                    "query": "frida", "group_id": "cmp-5-r0", "node_labels": ["Tool"],
                })
                first_call = time.time() - t0
                print(f"  首次调用: {first_call:.2f}s（含 _ready.wait + build_indices + 网络）")

                # 关键断言：调用成功（Docker + 容器 + 模型全部就绪）
                self.assertFalse(r.isError, "工具调用应成功（基础设施已就绪）")

    async def test_ensure_ready_waits_for_all_infra(self):
        """_ensure_ready 等待所有基础设施（Docker + 容器 + 模型）就绪。

        通过启动 server 后立即并发调用 2 个工具验证：
        - 都应该等待 _ready
        - _ready set 后都成功（说明 Docker + 容器 + 模型都就绪）
        """
        params = StdioServerParameters(command=str(VENV_PYTHON), args=[str(SERVER)], env=ENV)

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                t0 = time.time()
                results = await asyncio.gather(
                    session.call_tool("entity_by_label_search", {
                        "query": "q1", "group_id": "cmp-5-r0", "node_labels": ["Tool"],
                    }),
                    session.call_tool("entity_by_label_search", {
                        "query": "q2", "group_id": "cmp-5-r0", "node_labels": ["Tool"],
                    }),
                )
                elapsed = time.time() - t0
                print(f"\n  并发 2 个调用总耗时: {elapsed:.2f}s")
                for i, r in enumerate(results):
                    self.assertFalse(r.isError, f"并发调用 #{i} 应成功")


class TestUserScenarioWithDelay(unittest.IsolatedAsyncioTestCase):
    """Layer 3：用户实际场景——启动后等 20s（模拟用户思考+Docker 就绪）再调用。"""

    async def test_call_after_delay_is_instant(self):
        """启动后等 20s（用户思考），所有后台初始化完成，调用应立即返回。"""
        params = StdioServerParameters(command=str(VENV_PYTHON), args=[str(SERVER)], env=ENV)

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                t0 = time.time()
                await session.initialize()
                handshake = time.time() - t0

                # 模拟用户思考 20s（让 Docker/容器/BGE-M3 全部后台就绪）
                print(f"\n  握手 {handshake:.2f}s，等待 20s 模拟用户思考...")
                await asyncio.sleep(20)

                t0 = time.time()
                r = await session.call_tool("entity_by_label_search", {
                    "query": "frida", "group_id": "cmp-5-r0", "node_labels": ["Tool"],
                })
                call_time = time.time() - t0
                print(f"  20s 后调用: {call_time:.3f}s")

                # 关键断言：用户思考后调用应立即返回
                self.assertLess(call_time, 2.0, f"调用 {call_time:.3f}s 应 <2s（基础设施已就绪）")
                self.assertFalse(r.isError, "工具调用应成功")


if __name__ == "__main__":
    unittest.main(verbosity=2)
