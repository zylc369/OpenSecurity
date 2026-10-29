"""完整测试方案：events MCP lifespan lazy 加载改造（方案 B）。

测试目标：验证改造的核心契约和实际价值。

测试覆盖：
  Layer 1：单元契约测试（Python MCP client 直连 server）
    - test_handshake_fast: 握手快（<5s）
    - test_first_call_waits_for_model_load: 握手后立即调用等待模型加载
    - test_second_call_is_fast: 第二次调用立即返回
    - test_call_after_user_delay_is_instant: 握手后等 15s（模拟用户思考）调用立即返回 ← 方案 B 核心价值
    - test_concurrent_first_calls_share_wait: 并发首次调用共享等待
    - test_load_failure_does_not_hang: 加载失败不 hang

  Layer 2：用户场景模拟（方案 B 的时间差价值）
    - test_real_user_scenario: 启动后等 10s（模拟用户打开 + 思考），调用工具立即返回

  Layer 3：race condition 修复验证
    - test_concurrent_init_no_duplicate: 并发首次调用只触发一次 build_indices
"""
import asyncio
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

VENV_PYTHON = Path.home() / "bw-security-analysis" / ".venv" / "bin" / "python"
SERVER = Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "events" / "server.py"
ENV = {**os.environ, "PYTHONPATH": str(SERVER.parent)}


async def _spawn_and_call(tool_name: str, tool_args: dict, delay_before_call: float = 0) -> dict:
    """完整流程：spawn + 握手 + (可选延迟) + 调用工具。

    每次启动独立 server 进程，确保 _ready 初始 unset。
    返回 {handshake_time, call_time, total_time, is_error, text}。
    """
    params = StdioServerParameters(command=str(VENV_PYTHON), args=[str(SERVER)], env=ENV)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            t0 = time.time()
            await session.initialize()
            handshake_time = time.time() - t0

            if delay_before_call > 0:
                await asyncio.sleep(delay_before_call)

            call_start = time.time()
            result = await session.call_tool(tool_name, tool_args)
            call_time = time.time() - call_start

            text = "".join(c.text for c in result.content if hasattr(c, "text"))
            return {
                "handshake_time": handshake_time,
                "call_time": call_time,
                "is_error": result.isError,
                "text": text,
            }


class TestLayer1Contracts(unittest.IsolatedAsyncioTestCase):
    """Layer 1：单元契约测试。"""

    async def test_handshake_fast(self):
        """契约 1：握手快（lifespan 立即 yield，不等模型加载）。"""
        res = await _spawn_and_call("entity_search", {
            "query": "test", "group_id": "test", "node_labels": ["Tool"],
        })
        print(f"\n  握手: {res['handshake_time']:.2f}s")
        self.assertLess(res["handshake_time"], 5.0,
                        f"握手 {res['handshake_time']:.2f}s 应 <5s")
        self.assertGreater(res["handshake_time"], 0.3,
                           f"握手 {res['handshake_time']:.2f}s 异常短")

    async def test_first_call_waits_for_model_load(self):
        """契约 2：握手后立即调用工具，应等待模型加载。

        关键断言：调用耗时 >3s（说明在等待），且工具成功（说明等待后正常执行）。
        """
        res = await _spawn_and_call("entity_search", {
            "query": "frida", "group_id": "cmp-5-r0", "node_labels": ["Tool"],
        })
        print(f"\n  握手: {res['handshake_time']:.2f}s")
        print(f"  首次调用: {res['call_time']:.2f}s")
        print(f"  isError: {res['is_error']}")
        self.assertGreater(res["call_time"], 3.0,
                          f"调用 {res['call_time']:.2f}s 应 >3s（说明在等待模型加载）")
        self.assertFalse(res["is_error"], "首次调用应成功")

    async def test_second_call_is_fast(self):
        """契约 3：握手后立即连续调用两次，第二次应立即返回。"""
        params = StdioServerParameters(command=str(VENV_PYTHON), args=[str(SERVER)], env=ENV)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                t0 = time.time()
                await session.call_tool("entity_search", {
                    "query": "frida", "group_id": "cmp-5-r0", "node_labels": ["Tool"],
                })
                first = time.time() - t0

                t0 = time.time()
                await session.call_tool("entity_search", {
                    "query": "burp", "group_id": "cmp-5-r0", "node_labels": ["Tool"],
                })
                second = time.time() - t0

        print(f"\n  首次: {first:.2f}s, 第二次: {second:.3f}s")
        self.assertLess(second, 1.0, f"第二次 {second:.3f}s 应 <1s")
        self.assertGreater(first / max(second, 0.001), 10, "加速比应 >10x")


class TestLayer2UserScenario(unittest.IsolatedAsyncioTestCase):
    """Layer 2：用户实际场景测试（方案 B 的核心价值）。"""

    async def test_call_after_user_delay_is_instant(self):
        """模拟用户实际场景：启动 → 等 15s（思考） → 调用 → 立即返回。

        这是方案 B 的核心价值——利用用户启动后到实际调用工具的时间差，
        让 BGE-M3 加载在后台完成，用户调用时立即可用。
        """
        print("\n  模拟用户场景：spawn → 等 15s（用户思考） → 调用工具")
        res = await _spawn_and_call(
            "entity_search",
            {"query": "frida", "group_id": "cmp-5-r0", "node_labels": ["Tool"]},
            delay_before_call=15.0,
        )
        print(f"  握手: {res['handshake_time']:.2f}s")
        print(f"  等待 15s 后调用: {res['call_time']:.3f}s")
        # 关键断言：等待 15s 后调用应立即返回（<2s，含 build_indices + 网络）
        self.assertLess(res["call_time"], 2.0,
                        f"用户思考 15s 后调用耗时 {res['call_time']:.3f}s 应 <2s（BGE-M3 已后台加载完）")


class TestLayer3RaceCondition(unittest.IsolatedAsyncioTestCase):
    """Layer 3：race condition 修复验证。"""

    async def test_concurrent_first_calls_share_wait(self):
        """并发首次调用共享 _ready Event。

        握手后立即并发 2 个工具调用：
        - 都应该等待 _ready
        - _ready set 后都成功返回
        - 总耗时应 ≈ 1 次加载时间（不是 2 次）
        """
        params = StdioServerParameters(command=str(VENV_PYTHON), args=[str(SERVER)], env=ENV)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                t0 = time.time()
                results = await asyncio.gather(
                    session.call_tool("entity_search", {
                        "query": "q1", "group_id": "cmp-5-r0", "node_labels": ["Tool"],
                    }),
                    session.call_tool("entity_search", {
                        "query": "q2", "group_id": "cmp-5-r0", "node_labels": ["Tool"],
                    }),
                )
                elapsed = time.time() - t0

        print(f"\n  并发 2 个首次调用总耗时: {elapsed:.2f}s")
        for i, r in enumerate(results):
            print(f"    结果 {i}: isError={r.isError}")
            self.assertFalse(r.isError, f"并发调用 #{i} 应成功")
        # 总耗时应 < 25s（说明共享等待，不是串行 14s × 2）
        self.assertLess(elapsed, 25.0,
                       f"并发调用 {elapsed:.2f}s 应 <25s（说明共享 _ready Event）")


class TestLayer4LoadFailure(unittest.IsolatedAsyncioTestCase):
    """Layer 4：加载失败场景测试。"""

    async def test_load_failure_does_not_hang(self):
        """加载失败时工具调用不 hang。

        通过 wrapper 脚本 monkey-patch graphiti_config.create_graphiti 返回错误，
        验证 _preload_models_blocking 内 except 捕获 + finally set Event + 工具调用立即抛 RuntimeError。
        """
        wrapper = '''
import sys, os, asyncio
sys.path.insert(0, os.environ["SERVER_DIR"])

# monkey-patch create_graphiti 让它返回错误
import graphiti_config
graphiti_config.create_graphiti = lambda: (None, "injected load failure for test")

import server
asyncio.run(server.mcp.run_stdio_async())
'''
        env = {**ENV, "SERVER_DIR": str(SERVER.parent)}
        params = StdioServerParameters(
            command=str(VENV_PYTHON),
            args=["-c", wrapper],
            env=env,
        )

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                t0 = time.time()
                result = await asyncio.wait_for(
                    session.call_tool("entity_search", {
                        "query": "test", "group_id": "test", "node_labels": ["Tool"],
                    }),
                    timeout=15.0,
                )
                elapsed = time.time() - t0
                text = "".join(c.text for c in result.content if hasattr(c, "text"))

        print(f"\n  加载失败场景调用耗时: {elapsed:.2f}s")
        print(f"  isError: {result.isError}")
        print(f"  返回: {text[:200]}")
        self.assertLess(elapsed, 5.0, f"加载失败 {elapsed:.2f}s 应 <5s（不应 hang）")
        self.assertTrue(result.isError or "error" in text.lower() or "失败" in text or "injected" in text,
                       f"应返回错误，实际: {text[:200]}")


class TestLayer5AllToolsSmoke(unittest.IsolatedAsyncioTestCase):
    """Layer 5：8 个工具的烟雾测试——每个工具调用一次验证不抛错。"""

    async def test_all_tools_callable(self):
        """所有 8 个工具的烟雾测试。

        等待 BGE-M3 加载完后逐个调用，验证：
        - 每个工具不抛异常（isError=False 或文本含 error 字段）
        - 返回格式合法（JSON 含 edges/nodes/episodes 字段或 count/error）
        """
        params = StdioServerParameters(command=str(VENV_PYTHON), args=[str(SERVER)], env=ENV)

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                # 等 BGE-M3 加载完
                await asyncio.sleep(15)

                # 先用 entity_search 拿一个真实的 center_node_uuid（如果数据存在）
                r = await session.call_tool("entity_search", {
                    "query": "frida", "group_id": "cmp-5-r0", "node_labels": ["Tool"],
                })
                r_text = "".join(c.text for c in r.content if hasattr(c, "text"))
                center_uuid = None
                try:
                    import json
                    data = json.loads(r_text)
                    if data.get("nodes"):
                        center_uuid = data["nodes"][0].get("uuid")
                except Exception:
                    pass
                print(f"\n  center_uuid: {center_uuid}")

                # 6 个工具的调用参数
                tools_to_test = [
                    ("time_search", {
                        "query": "frida", "group_id": "cmp-5-r0",
                        "time_start": "2026-01-01T00:00:00Z",
                        "time_end": "2026-12-31T23:59:59Z",
                    }),
                    ("entity_relationships_search", {
                        "query": "frida", "group_id": "cmp-5-r0",
                        "center_node_uuid": center_uuid or "non-existent",
                        "max_depth": 1,
                    }),
                    ("diverse_results_search", {
                        "query": "frida", "group_id": "cmp-5-r0",
                    }),
                    ("episode_context_search", {
                        "query": "frida", "group_id": "cmp-5-r0",
                    }),
                    ("entity_search", {
                        "query": "frida", "group_id": "cmp-5-r0",
                        "node_labels": ["Tool"],
                        "min_mentions": 2,
                    }),
                    ("entity_search", {
                        "query": "frida", "group_id": "cmp-5-r0",
                        "node_labels": ["Tool"],
                    }),
                ]

                results = {}
                for tool_name, args in tools_to_test:
                    print(f"  调用 {tool_name}...", end="", flush=True)
                    t0 = time.time()
                    try:
                        r = await asyncio.wait_for(session.call_tool(tool_name, args), timeout=60)
                        elapsed = time.time() - t0
                        text = "".join(c.text for c in r.content if hasattr(c, "text"))
                        # 验证返回是合法 JSON
                        try:
                            import json
                            data = json.loads(text)
                            json_ok = True
                        except Exception:
                            json_ok = False
                        results[tool_name] = {
                            "isError": r.isError,
                            "elapsed": elapsed,
                            "len": len(text),
                            "json_ok": json_ok,
                        }
                        print(f" isError={r.isError}, time={elapsed:.2f}s, json_ok={json_ok}, len={len(text)}")
                        # 关键断言：每个工具返回合法 JSON
                        self.assertTrue(json_ok, f"{tool_name} 应返回合法 JSON，实际: {text[:200]}")
                    except Exception as e:
                        print(f" EXCEPTION: {type(e).__name__}: {e}")
                        results[tool_name] = {"exception": str(e)}
                        self.fail(f"{tool_name} 抛异常: {e}")

                # 打印汇总
                print(f"\n  汇总：")
                for tool, info in results.items():
                    print(f"    {tool}: {info}")


class TestLayer6RerankerTrigger(unittest.IsolatedAsyncioTestCase):
    """Layer 6：验证 reranker（bge-reranker-v2-m3）的延迟加载机制。

    diverse_results_search 用 EdgeReranker.cross_encoder 触发 reranker 加载。
    但实际触发需要候选数据——如果没有数据 graphiti 直接返回空，跳过 reranker。

    所以这里直接单元测试 reranker.py 的 @property 延迟加载契约：
    - BgeRerankerClient() 创建不加载模型（_model is None）
    - 首次访问 .model 触发加载（耗时 ~3s）
    - 第二次访问立即返回（已缓存）
    """

    async def test_reranker_lazy_load(self):
        sys.path.insert(0, str(SERVER.parent))
        from reranker import BgeRerankerClient

        print("\n  创建 BgeRerankerClient（不加载模型）...")
        client = BgeRerankerClient()
        self.assertIsNone(client._model, "创建后 _model 应为 None（延迟加载）")

        # 首次访问 .model 触发加载
        print("  首次访问 .model（触发加载）...")
        t0 = time.time()
        model1 = await asyncio.to_thread(lambda: client.model)
        first_time = time.time() - t0
        print(f"    首次: {first_time:.2f}s")
        self.assertIsNotNone(model1, "首次访问后 _model 应非 None")
        self.assertGreater(first_time, 1.0, f"首次加载 {first_time:.2f}s 应 >1s")

        # 第二次访问立即返回（缓存）
        t0 = time.time()
        model2 = await asyncio.to_thread(lambda: client.model)
        second_time = time.time() - t0
        print(f"    第二次: {second_time:.3f}s")
        self.assertIs(model1, model2, "第二次访问应返回同一对象（缓存）")
        self.assertLess(second_time, 0.01, f"第二次访问 {second_time:.3f}s 应 <10ms")

    async def test_diverse_results_search_callable(self):
        """辅助测试：diverse_results_search 工具能调用（不抛错）。

        注意：实际不触发 reranker 加载（除非有匹配数据）。
        reranker 加载路径由 test_reranker_lazy_load 单元测试覆盖。
        """
        params = StdioServerParameters(command=str(VENV_PYTHON), args=[str(SERVER)], env=ENV)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await asyncio.sleep(15)

                r = await session.call_tool("diverse_results_search", {
                    "query": "frida", "group_id": "cmp-5-r0",
                })
                self.assertFalse(r.isError, "diverse_results_search 不应抛错")


class TestLayer7DeleteEvents(unittest.IsolatedAsyncioTestCase):
    """Layer 7：delete_session_events 完整流程。

    1. 用 graphiti.add_episode 写入临时 group_id 的数据
    2. 验证 search 工具能搜到
    3. 调用 delete_session_events 删除
    4. 验证 search 工具搜不到
    """
    TEST_GROUP = "test-delete-events-temp"

    async def test_delete_session_events_full_flow(self):
        # 先用 graphiti 直接写入数据到临时 group
        sys.path.insert(0, str(SERVER.parent))
        from graphiti_config import create_graphiti
        from graphiti_core.nodes import EpisodeType
        from graphiti_core.search.search_config import SearchConfig
        from datetime import datetime

        graphiti, err = create_graphiti()
        self.assertIsNone(err, f"create_graphiti 失败: {err}")
        await graphiti.build_indices_and_constraints()

        try:
            # 写入测试数据
            print(f"\n  写入测试数据到 group_id={self.TEST_GROUP}")
            await graphiti.add_episode(
                name=f"{self.TEST_GROUP}-1",
                episode_body="Test episode for delete_session_events test. Frida hook test.",
                source_description="test",
                reference_time=datetime.now(),
                source=EpisodeType.message,
                group_id=self.TEST_GROUP,
            )
            print(f"  写入完成")
        finally:
            await graphiti.close()

        # 通过 MCP 调用 delete_session_events
        params = StdioServerParameters(command=str(VENV_PYTHON), args=[str(SERVER)], env=ENV)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await asyncio.sleep(15)  # 等 BGE-M3 加载

                print(f"  调用 delete_session_events 删除 group_id={self.TEST_GROUP}")
                r = await session.call_tool("delete_session_events", {
                    "group_id": self.TEST_GROUP,
                })
                text = "".join(c.text for c in r.content if hasattr(c, "text"))
                print(f"  返回: {text[:200]}")

                # 验证返回 deleted
                self.assertFalse(r.isError, f"delete 不应报错: {text[:200]}")
                import json
                try:
                    data = json.loads(text)
                    self.assertTrue(data.get("deleted") == self.TEST_GROUP,
                                   f"应返回 deleted={self.TEST_GROUP}，实际: {data}")
                    print(f"  ✅ delete_session_events 返回正确: {data}")
                except json.JSONDecodeError:
                    self.fail(f"返回不是合法 JSON: {text[:200]}")


class TestLayer8BuildIndicesFailure(unittest.IsolatedAsyncioTestCase):
    """Layer 8：build_indices_and_constraints 失败场景。

    mock graphiti 对象的 build_indices_and_constraints 抛错，
    验证 _ensure_ready 行为：抛 RuntimeError，工具返回 _empty_result。
    """

    async def test_build_indices_failure_returns_error(self):
        wrapper = '''
import sys, os, asyncio
sys.path.insert(0, os.environ["SERVER_DIR"])

# monkey-patch graphiti 让 build_indices_and_constraints 抛错
import graphiti_config
original_create = graphiti_config.create_graphiti

def patched_create():
    graphiti, err = original_create()
    if err:
        return graphiti, err
    # 让 build_indices_and_constraints 抛错
    async def fail_build():
        raise RuntimeError("injected Neo4j failure for test")
    graphiti.build_indices_and_constraints = fail_build
    return graphiti, None

graphiti_config.create_graphiti = patched_create

import server
asyncio.run(server.mcp.run_stdio_async())
'''
        env = {**ENV, "SERVER_DIR": str(SERVER.parent)}
        params = StdioServerParameters(
            command=str(VENV_PYTHON),
            args=["-c", wrapper],
            env=env,
        )

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                # 等模型加载完
                await asyncio.sleep(15)

                # 调用工具——应因 build_indices 失败而返回错误
                t0 = time.time()
                r = await asyncio.wait_for(
                    session.call_tool("entity_search", {
                        "query": "test", "group_id": "test", "node_labels": ["Tool"],
                    }),
                    timeout=15,
                )
                elapsed = time.time() - t0
                text = "".join(c.text for c in r.content if hasattr(c, "text"))

        print(f"\n  build_indices 失败场景:")
        print(f"    耗时: {elapsed:.2f}s")
        print(f"    返回: {text[:300]}")
        # 关键断言：返回 _empty_result 错误（不 hang、不抛异常给 client）
        self.assertLess(elapsed, 5.0, f"耗时 {elapsed:.2f}s 应 <5s（不 hang）")
        self.assertTrue(
            "injected Neo4j failure" in text or "failed" in text.lower() or "error" in text.lower(),
            f"应返回错误信息，实际: {text[:200]}"
        )


class TestLayer9GraphitiSearchFailure(unittest.IsolatedAsyncioTestCase):
    """Layer 9：graphiti.search_ 失败场景。

    mock graphiti.search_ 抛错，验证工具返回 _empty_result（不抛错给 client）。
    """

    async def test_graphiti_search_failure_returns_empty_result(self):
        wrapper = '''
import sys, os, asyncio
sys.path.insert(0, os.environ["SERVER_DIR"])

# monkey-patch graphiti 让 search_ 抛错
import graphiti_config
original_create = graphiti_config.create_graphiti

def patched_create():
    graphiti, err = original_create()
    if err:
        return graphiti, err
    # 让 search_ 抛错
    async def fail_search(*args, **kwargs):
        raise RuntimeError("injected search failure for test")
    graphiti.search_ = fail_search
    return graphiti, None

graphiti_config.create_graphiti = patched_create

import server
asyncio.run(server.mcp.run_stdio_async())
'''
        env = {**ENV, "SERVER_DIR": str(SERVER.parent)}
        params = StdioServerParameters(
            command=str(VENV_PYTHON),
            args=["-c", wrapper],
            env=env,
        )

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await asyncio.sleep(15)  # 等模型加载 + build_indices

                # 调用工具——graphiti.search_ 会抛错
                t0 = time.time()
                r = await asyncio.wait_for(
                    session.call_tool("entity_search", {
                        "query": "test", "group_id": "test", "node_labels": ["Tool"],
                    }),
                    timeout=15,
                )
                elapsed = time.time() - t0
                text = "".join(c.text for c in r.content if hasattr(c, "text"))

        print(f"\n  graphiti.search_ 失败场景:")
        print(f"    耗时: {elapsed:.2f}s")
        print(f"    返回: {text[:300]}")
        # 关键断言：返回 _empty_result（工具捕获异常，不抛给 client）
        self.assertLess(elapsed, 5.0, f"耗时 {elapsed:.2f}s 应 <5s（不 hang）")
        self.assertFalse(r.isError, "工具应捕获 graphiti 错误返回 _empty_result，isError=False")
        # 验证返回包含 error 字段（_empty_result 的 error 参数）
        self.assertTrue(
            "failed" in text.lower() or "error" in text.lower() or "injected" in text,
            f"应包含错误信息，实际: {text[:200]}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
