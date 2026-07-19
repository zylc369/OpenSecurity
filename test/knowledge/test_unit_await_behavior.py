"""单元测试：启动后立即调用工具是否会 await 模型加载完成。

测试目标：
  验证 knowledge MCP lifespan lazy 加载的核心契约——
  握手完成后立即调用工具，工具函数应 await _ready 直到 BGE-M3 加载完成。

测试场景：
  1. spawn server 进程
  2. stdio 握手（<10s，不含模型加载）
  3. 握手完成后立即调用 search_answer（T=0+）
  4. 工具调用应：
     - 不立即返回（说明在等待）
     - 等到模型加载完后正常返回结果（说明等待成功）
     - 总耗时 ≈ 模型加载时间（~10-15s）
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
SERVER = Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "knowledge" / "server.py"
ENV = {**os.environ, "PYTHONPATH": str(SERVER.parent)}


async def _handshake_and_call(tool_args: dict, call_immediately: bool = True) -> dict:
    """完整流程：spawn + 握手 + 调用工具。

    返回 {handshake_time, call_time, elapsed, result, is_error}。
    每次调用启动独立的 server 进程，确保 _ready 初始为 unset。
    """
    params = StdioServerParameters(
        command=str(VENV_PYTHON),
        args=[str(SERVER)],
        env=ENV,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            # 握手
            t0 = time.time()
            await session.initialize()
            handshake_time = time.time() - t0

            # 立即调用工具
            call_start = time.time()
            result = await session.call_tool("search_answer", tool_args)
            call_time = time.time() - call_start

            # 提取文本
            text = "".join(c.text for c in result.content if hasattr(c, "text"))

            return {
                "handshake_time": handshake_time,
                "call_time": call_time,
                "is_error": result.isError,
                "text": text,
            }


class TestAwaitDuringLoading(unittest.IsolatedAsyncioTestCase):
    """启动后立即调用工具的等待行为测试。"""

    async def test_handshake_is_fast(self):
        """契约 1：握手快（不含模型加载）。改造前 ~15s；改造后 <10s。"""
        # 用一个轻调用确认握手 + server 可响应
        res = await _handshake_and_call({"questions": ["q"], "type": "other"})
        print(f"\n  握手耗时: {res['handshake_time']:.2f}s")
        self.assertLess(res["handshake_time"], 10.0,
                        f"握手 {res['handshake_time']:.2f}s 应 <10s（lazy 加载生效）")
        self.assertGreater(res["handshake_time"], 0.5,
                           f"握手 {res['handshake_time']:.2f}s 异常短，可能未真正建立连接")

    async def test_first_call_waits_for_model_load(self):
        """契约 2：握手后立即调用工具，应等待模型加载。

        关键断言：
        - 调用耗时 > 3s（说明在等待——若不等待会立即返回错误）
        - 工具返回成功（说明等待后正常执行）
        """
        res = await _handshake_and_call({"questions": ["frida"], "type": "tool"})
        print(f"\n  握手: {res['handshake_time']:.2f}s, 工具调用: {res['call_time']:.2f}s")
        print(f"  返回文本: {res['text'][:200]}")

        # 关键断言 1：耗时应 > 3s（说明在等待模型加载）
        self.assertGreater(res["call_time"], 3.0,
                          f"调用耗时 {res['call_time']:.2f}s 应 >3s——若立即返回说明没等待或失败")

        # 关键断言 2：工具不报错
        self.assertFalse(res["is_error"],
                         f"工具调用应成功，实际 isError=True: {res['text'][:200]}")

    async def test_second_call_is_fast_after_first(self):
        """契约 3：首次调用完成后，第二次调用应立即返回。

        通过 _handshake_and_call 已经走完了首次调用（_ready 已 set），
        但本测试需要独立测量第二次——所以用同一个 session。
        """
        params = StdioServerParameters(command=str(VENV_PYTHON), args=[str(SERVER)], env=ENV)

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # 首次调用（会等待模型加载）
                t0 = time.time()
                r1 = await session.call_tool("search_answer", {"questions": ["q1"], "type": "other"})
                first_time = time.time() - t0
                print(f"\n  首次调用: {first_time:.2f}s（含模型加载）")

                # 第二次调用（_ready 已 set，应立即返回）
                t0 = time.time()
                r2 = await session.call_tool("search_answer", {"questions": ["q2"], "type": "other"})
                second_time = time.time() - t0
                print(f"  第二次调用: {second_time:.3f}s（_ready 已 set）")

                # 两次都不应报错
                self.assertFalse(r1.isError, "首次调用不应报错")
                self.assertFalse(r2.isError, "第二次调用不应报错")

                # 第二次应 <1s
                self.assertLess(second_time, 1.0,
                               f"第二次调用 {second_time:.3f}s 应 <1s（_ready 已 set）")
                # 加速比 > 10x
                ratio = first_time / max(second_time, 0.001)
                self.assertGreater(ratio, 10,
                                  f"加速比 {ratio:.1f}x 应 >10x")


if __name__ == "__main__":
    unittest.main(verbosity=2)
