"""端到端测试：knowledge MCP lazy 加载的工具调用 await 行为。

验证三个关键场景：
1. 首次工具调用：模型后台加载中，工具调用 await，最终成功返回
2. 第二次工具调用：模型已就绪，立即返回（<0.5s）
3. 加载失败场景：工具调用不 hang，返回错误

测试原理：通过 MCP stdio client 连接真实 server，调用真实工具。
"""
import asyncio
import sys
import time
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

VENV_PYTHON = Path.home() / "bw-security-analysis" / ".venv" / "bin" / "python"
SERVER = Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "knowledge" / "server.py"
ENV = {**os.environ, "PYTHONPATH": str(SERVER.parent)}


async def test_first_call_takes_model_load_time(session):
    """首次工具调用：模型后台加载中，工具调用 await，最终成功返回。"""
    print("\n[测试 1] 首次工具调用（模型加载中）...")
    t0 = time.time()
    result = await session.call_tool("search_answer", {
        "questions": ["how to exploit buffer overflow"],
        "type": "vulnerability",
    })
    elapsed = time.time() - t0
    print(f"  耗时: {elapsed:.2f}s")
    # 预期：包含模型加载时间（约 10-15s）
    assert elapsed > 3.0, f"首次调用耗时 {elapsed:.2f}s 应该 >3s（含模型加载）"
    print(f"  ✅ 首次调用等待模型加载完成（{elapsed:.2f}s）")
    return elapsed


async def test_second_call_is_fast(session):
    """第二次工具调用：模型已就绪，立即返回。"""
    print("\n[测试 2] 第二次工具调用（模型已就绪）...")
    t0 = time.time()
    result = await session.call_tool("search_answer", {
        "questions": ["another query"],
        "type": "other",
    })
    elapsed = time.time() - t0
    print(f"  耗时: {elapsed:.3f}s")
    # 预期：<0.5s
    assert elapsed < 0.5, f"第二次调用耗时 {elapsed:.3f}s 应 <0.5s"
    print(f"  ✅ 第二次调用立即返回（{elapsed:.3f}s）")
    return elapsed


async def test_store_and_search_end_to_end(session):
    """store + search 端到端：验证 lazy 加载后的 db 操作正确。"""
    print("\n[测试 3] store + search 端到端...")
    # store
    store_result = await session.call_tool("store_answer", {
        "question": "what is frida hook",
        "answer": "Frida is a dynamic instrumentation toolkit. It lets you inject JavaScript into native apps.",
        "type": "tool",
    })
    store_text = "".join(c.text for c in store_result.content if hasattr(c, "text"))
    print(f"  store: {store_text}")
    assert '"stored": true' in store_text or '"stored": true' in store_text.replace(" ", ""), \
        f"store 失败: {store_text}"

    # search（应该能搜到刚存的）
    search_result = await session.call_tool("search_answer", {
        "questions": ["dynamic instrumentation"],
        "type": "tool",
    })
    search_text = "".join(c.text for c in search_result.content if hasattr(c, "text"))
    print(f"  search 返回长度: {len(search_text)} 字符")
    # 预期：能搜到（Frida 相关）
    assert "Frida" in search_text or "frida" in search_text, \
        f"search 没搜到刚存的 Frida 答案: {search_text[:200]}"
    print(f"  ✅ store + search 端到端正确")


async def test_concurrent_calls_during_loading():
    """并发场景：握手后立即并发多个工具调用，都等待模型加载完成。"""
    print("\n[测试 4] 握手后立即并发 3 个工具调用...")
    params = StdioServerParameters(command=str(VENV_PYTHON), args=[str(SERVER)], env=ENV)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 立即并发 3 个调用
            t0 = time.time()
            results = await asyncio.gather(
                session.call_tool("search_answer", {"questions": ["q1"], "type": "other"}),
                session.call_tool("search_answer", {"questions": ["q2"], "type": "other"}),
                session.call_tool("search_answer", {"questions": ["q3"], "type": "other"}),
            )
            elapsed = time.time() - t0
            print(f"  3 个并发调用总耗时: {elapsed:.2f}s")
            # 预期：等待模型加载（10-15s），而非 3× 加载时间
            assert elapsed < 30, f"并发调用耗时 {elapsed:.2f}s 过长，可能未正确共享 _ready"
            assert len(results) == 3
            print(f"  ✅ 3 个并发调用共享 _ready Event（{elapsed:.2f}s）")


async def test_load_failure_does_not_hang():
    """模型加载失败时，工具调用不 hang——5s 内返回错误。

    通过 monkey-patch SentenceTransformer 构造函数抛异常，
    验证 _load_blocking 内 except 把异常存入 _init_error、finally set Event、
    工具函数 _ensure_ready 抛 RuntimeError 而非 hang。
    """
    print("\n[测试 5] 模型加载失败时工具调用不 hang...")
    wrapper_script = """
import sys, os, asyncio
sys.path.insert(0, os.environ['SERVER_DIR'])

# 先 mock sentence_transformers，让 SentenceTransformer 构造抛异常
import sentence_transformers
original_init = sentence_transformers.SentenceTransformer.__init__
def fail_init(self, *a, **kw):
    raise RuntimeError("injected load failure for test")
sentence_transformers.SentenceTransformer.__init__ = fail_init

import server
asyncio.run(server.mcp.run_stdio_async())
"""
    env = {**ENV, "SERVER_DIR": str(SERVER.parent)}
    params = StdioServerParameters(
        command=str(VENV_PYTHON),
        args=["-c", wrapper_script],
        env=env,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            # 立即调用工具，模型加载会失败（injected load failure）
            # _load_blocking 内 except 把异常存入 _init_error，finally set Event
            # 工具函数 _ensure_ready 抛 RuntimeError
            t0 = time.time()
            result = await asyncio.wait_for(
                session.call_tool("search_answer", {"questions": ["test"], "type": "other"}),
                timeout=15.0,
            )
            elapsed = time.time() - t0
            result_text = "".join(c.text for c in result.content if hasattr(c, "text"))
            print(f"  耗时: {elapsed:.2f}s")
            print(f"  isError: {result.isError}")
            print(f"  返回: {result_text[:200]}")
            # 预期：工具返回错误（isError=True），而非 hang
            assert elapsed < 5.0, f"工具调用耗时 {elapsed:.2f}s 应 <5s（不应 hang）"
            assert result.isError or "error" in result_text.lower() or "Error" in result_text or "失败" in result_text, \
                f"工具调用应返回错误，实际 isError={result.isError}, text={result_text[:200]}"
            print(f"  ✅ 加载失败时工具调用 {elapsed:.2f}s 内返回错误（不 hang）")


async def main():
    print("=" * 70)
    print("knowledge MCP lazy 加载端到端测试")
    print(f"  server: {SERVER}")
    print("=" * 70)

    params = StdioServerParameters(command=str(VENV_PYTHON), args=[str(SERVER)], env=ENV)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            print("\n[握手] initialize...")
            t0 = time.time()
            await session.initialize()
            print(f"  握手完成: {time.time()-t0:.2f}s")

            # 测试 1+2+3
            first_time = await test_first_call_takes_model_load_time(session)
            second_time = await test_second_call_is_fast(session)
            await test_store_and_search_end_to_end(session)

    # 测试 4（独立连接，测试握手后立即并发）
    await test_concurrent_calls_during_loading()

    # 测试 5（加载失败场景）
    await test_load_failure_does_not_hang()

    print("\n" + "=" * 70)
    print("总结：")
    print(f"  首次调用（含模型加载）: {first_time:.2f}s")
    print(f"  第二次调用（已就绪）:   {second_time:.3f}s")
    print(f"  加速比: {first_time/second_time:.0f}x")
    print("✅ 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
