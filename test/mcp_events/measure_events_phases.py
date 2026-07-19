"""实测 events MCP 各阶段耗时（基线数据）。

阶段：
  A. 模块顶层 import（spawn server 进程）
  B. stdio 握手
  C. _ensure_ready() 首次调用：create_graphiti + build_indices_and_constraints
  D. 首次工具调用：触发 BGE-M3 + reranker 加载 + DeepSeek API + Neo4j 查询
  E. 第二次工具调用：模型已加载，只剩 DeepSeek + Neo4j

对比维度：哪些是"一次性加载"（可被 lifespan 吸收），哪些是"每次调用"（无法消除）。
"""
import asyncio
import os
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

VENV_PYTHON = Path.home() / "bw-security-analysis" / ".venv" / "bin" / "python"
SERVER = Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "events" / "server.py"
ENV = {**os.environ, "PYTHONPATH": str(SERVER.parent)}


async def measure_once() -> dict:
    params = StdioServerParameters(command=str(VENV_PYTHON), args=[str(SERVER)], env=ENV)
    phases = {}

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            # A+B: spawn + 握手
            t0 = time.time()
            await session.initialize()
            phases["handshake"] = time.time() - t0

            # C+D 合并：首次工具调用（含 _ensure_ready + 模型加载 + 网络）
            # 用一个有数据的 group_id（之前测试留下的 cmp-*）
            t0 = time.time()
            r1 = await session.call_tool("entity_by_label_search", {
                "query": "frida",
                "group_id": "cmp-5-r0",
                "node_labels": ["Tool"],
            })
            phases["first_call"] = time.time() - t0
            r1_text = "".join(c.text for c in r1.content if hasattr(c, "text"))
            phases["first_call_len"] = len(r1_text)

            # E: 第二次工具调用（模型已加载，仅网络 IO）
            t0 = time.time()
            r2 = await session.call_tool("entity_by_label_search", {
                "query": "burp",
                "group_id": "cmp-5-r0",
                "node_labels": ["Tool"],
            })
            phases["second_call"] = time.time() - t0

    return phases


async def main():
    print("=" * 60)
    print("events MCP 各阶段耗时基线")
    print("=" * 60)

    results = []
    for i in range(2):  # 跑 2 次取平均
        print(f"\n[run {i+1}/2]")
        r = await measure_once()
        results.append(r)
        print(f"  握手:        {r['handshake']:.2f}s")
        print(f"  首次调用:    {r['first_call']:.2f}s（含 _ensure_ready + 模型加载 + 网络）")
        print(f"    返回长度:  {r['first_call_len']} 字符")
        print(f"  第二次调用:  {r['second_call']:.2f}s（模型已加载，仅网络）")

    avg_first = sum(r["first_call"] for r in results) / len(results)
    avg_second = sum(r["second_call"] for r in results) / len(results)
    avg_handshake = sum(r["handshake"] for r in results) / len(results)

    print(f"\n{'=' * 60}")
    print(f"平均耗时：")
    print(f"  握手:        {avg_handshake:.2f}s")
    print(f"  首次调用:    {avg_first:.2f}s")
    print(f"  第二次调用:  {avg_second:.2f}s")
    print(f"  一次性成本:  {avg_first - avg_second:.2f}s（首次 - 第二次，可被 lifespan 吸收）")
    print(f"  每次成本:    {avg_second:.2f}s（DeepSeek + Neo4j 网络，无法消除）")


if __name__ == "__main__":
    asyncio.run(main())
