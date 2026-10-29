"""测量 MCP server 启动握手耗时。

spawn server 进程 → stdio 连接 → initialize 握手 → tools/list → 关闭。
测量总耗时，用于验证 lazy 加载改造效果（基线 vs 改造后对比）。

用法：
    python measure_startup.py --server events
    python measure_startup.py --server knowledge
"""
import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

VENV_PYTHON = Path.home() / "bw-security-analysis" / ".venv" / "bin" / "python"

SERVERS = {
    "events": Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "events" / "server.py",
    "knowledge": Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "knowledge" / "server.py",
}

# 环境变量（让 server.py 能 import 同目录模块）
ENV = {**os.environ, "PYTHONPATH": str(SERVERS["events"].parent) + os.pathsep + str(SERVERS["knowledge"].parent)}


async def measure_once(server_name: str) -> dict:
    script = SERVERS[server_name]
    params = StdioServerParameters(
        command=str(VENV_PYTHON),
        args=[str(script)],
        env=ENV,
    )

    t0 = time.time()
    phases = {}

    async with stdio_client(params) as (read, write):
        phases["after_spawn"] = time.time() - t0

        t1 = time.time()
        async with ClientSession(read, write) as session:
            phases["after_session"] = time.time() - t0

            t2 = time.time()
            await session.initialize()
            phases["after_initialize"] = time.time() - t0
            phases["initialize_only"] = time.time() - t2

            t3 = time.time()
            tools = await session.list_tools()
            phases["after_list_tools"] = time.time() - t0
            phases["list_tools_only"] = time.time() - t3

            phases["tool_count"] = len(tools.tools)

    phases["total"] = time.time() - t0
    return phases


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", choices=list(SERVERS), required=True)
    parser.add_argument("--runs", type=int, default=3, help="重复次数取中位数")
    args = parser.parse_args()

    print(f"测量 {args.server} MCP 启动握手耗时（{args.runs} 次取中位数）")
    print(f"  server: {SERVERS[args.server]}")
    print(f"  python: {VENV_PYTHON}")
    print()

    results = []
    for i in range(args.runs):
        print(f"[run {i+1}/{args.runs}] 启动...", end="", flush=True)
        phases = await measure_once(args.server)
        results.append(phases)
        print(f" total={phases['total']:.2f}s (initialize={phases['initialize_only']:.2f}s, list_tools={phases['list_tools_only']:.2f}s, tools={phases['tool_count']})", flush=True)

    # 中位数
    totals = sorted(r["total"] for r in results)
    median = totals[len(totals) // 2]
    print()
    print(f"=== 总结（{args.server}）===")
    print(f"  runs: {[f'{t:.2f}s' for t in totals]}")
    print(f"  median total: {median:.2f}s")
    print(f"  min/max: {totals[0]:.2f}s / {totals[-1]:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
