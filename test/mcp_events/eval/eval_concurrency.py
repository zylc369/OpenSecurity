#!/usr/bin/env python3
"""events daemon 并发性能实测——逐步提升并发数，测量真实资源消耗。

测试维度：
  1. 单次 BGE-M3 encode 耗时
  2. 单次 add_episode 耗时 + 内存增量
  3. 不同并发数（1/2/3/5/10/15/20）下的吞吐量 + API 调用成功率 + 内存峰值

用法：
  ~/bw-security-analysis/.venv/bin/python test/mcp_events/eval_concurrency.py
"""
import asyncio
import json
import os
import resource
import sys
import time
import tracemalloc
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / ".opencode" / "mcp-servers" / "events"))

ai_env = Path(__file__).resolve().parents[3] / ".opencode" / ".ai_env"
for line in ai_env.read_text("utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

EVAL_GROUP = "eval-concurrency"

# 真实安全分析场景的 episode 文本（从 eval_search_quality.py 复用）
EPISODES = [
    ("binary", "binary-analysis agent used Ghidra to analyze sample.exe. "
     "Found buffer overflow in function sub_4012A0. CVE-2024-5678 assigned."),
    ("web", "web-analysis agent tested https://example.com/login. "
     "Detected SQL injection in username parameter. Backend uses MySQL 8.0."),
    ("crypto", "crypto-analysis agent examined RSA key. Found weak primes. "
     "Factored using Fermat's method. Private key recovered."),
    ("network", "network-analysis agent ran nmap scan on 10.0.0.0/24. "
     "Host 10.0.0.5 has ports 22, 80, 443 open. EternalBlue on 10.0.0.8."),
    ("reverse", "reverse-engineering agent analyzed malware.bin with IDA Pro. "
     "Found C2 beacon to c2.evil.com. AES-256-CBC config decryption."),
    ("mobile", "mobile-analysis agent decompiled target.apk with apktool. "
     "Found Frida hook in MainActivity. IMEI exfiltration to evil.example.net."),
]


def get_rss_mb() -> float:
    """当前进程 RSS（常驻内存）MB。"""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024  # macOS: bytes → MB


async def test_single_encode():
    """测试 1：BGE-M3 单次 encode 耗时。"""
    print("\n" + "=" * 60)
    print("测试 1：BGE-M3 单次 encode 耗时")
    print("=" * 60)

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("BAAI/bge-m3")

    texts = [
        ("短文本（实体名）", "sample.exe"),
        ("中文短文本", "缓冲区溢出漏洞"),
        ("中等文本（fact）", "sample.exe has a buffer overflow vulnerability in sub_4012A0"),
        ("长文本（episode）", EPISODES[0][1]),
    ]

    for label, text in texts:
        times = []
        for _ in range(10):
            t0 = time.time()
            model.encode(text, convert_to_numpy=True)
            times.append((time.time() - t0) * 1000)
        avg = sum(times) / len(times)
        min_t = min(times)
        max_t = max(times)
        print(f"  {label:<25} avg={avg:.1f}ms  min={min_t:.1f}ms  max={max_t:.1f}ms  ({len(text)} chars)")

    # 批量 encode
    batch = [ep[1] for ep in EPISODES]
    t0 = time.time()
    model.encode(batch, convert_to_numpy=True)
    batch_time = (time.time() - t0) * 1000
    print(f"  {'批量（6条）':<25} {batch_time:.1f}ms  ({batch_time/6:.1f}ms/item)")


async def test_single_add_episode(graphiti):
    """测试 2：单个 add_episode 耗时 + 内存增量。"""
    print("\n" + "=" * 60)
    print("测试 2：单个 add_episode 耗时 + 内存增量")
    print("=" * 60)

    from graphiti_core.nodes import EpisodeType

    rss_before = get_rss_mb()
    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()

    t0 = time.time()
    await graphiti.add_episode(
        name="concurrency-test-single",
        episode_body=EPISODES[0][1],
        source_description="eval",
        reference_time=datetime.now(),
        source=EpisodeType.message,
        group_id=EVAL_GROUP,
    )
    elapsed = time.time() - t0

    snapshot_after = tracemalloc.take_snapshot()
    rss_after = get_rss_mb()
    tracemalloc.stop()

    # Python 堆内存增量
    stat = snapshot_after.compare_to(snapshot_before, "lineno")
    python_mem_delta = sum(s.size_diff for s in stat) / 1024 / 1024

    print(f"  耗时: {elapsed:.1f}s")
    print(f"  RSS 变化: {rss_before:.0f}MB → {rss_after:.0f}MB (Δ={rss_after-rss_before:+.0f}MB)")
    print(f"  Python 堆增量: {python_mem_delta:+.3f}MB")
    print(f"  API 调用次数（估算）: ~5-10 次 DeepSeek API")


async def test_concurrency(graphiti, max_concurrent, num_episodes):
    """测试 3：指定并发数下运行 N 个 episode，测量吞吐量。"""
    from graphiti_core.nodes import EpisodeType

    sem = asyncio.Semaphore(max_concurrent)
    results = {"success": 0, "failed": 0, "errors": []}
    durations = []

    async def run_one(idx):
        ep_id, ep_body = EPISODES[idx % len(EPISODES)]
        async with sem:
            t0 = time.time()
            try:
                await graphiti.add_episode(
                    name=f"concurrency-{max_concurrent}x-{idx}-{ep_id}",
                    episode_body=ep_body,
                    source_description="eval",
                    reference_time=datetime.now(),
                    source=EpisodeType.message,
                    group_id=EVAL_GROUP,
                )
                results["success"] += 1
                durations.append(time.time() - t0)
            except Exception as e:
                results["failed"] += 1
                err_msg = str(e)[:100]
                results["errors"].append(f"[{idx}] {type(e).__name__}: {err_msg}")

    rss_before = get_rss_mb()
    t_start = time.time()
    await asyncio.gather(*[run_one(i) for i in range(num_episodes)])
    total_time = time.time() - t_start
    rss_after = get_rss_mb()

    avg_duration = sum(durations) / len(durations) if durations else 0
    throughput = num_episodes / total_time if total_time > 0 else 0

    print(f"\n  并发数={max_concurrent}, episode 数={num_episodes}")
    print(f"  总耗时: {total_time:.1f}s")
    print(f"  吞吐量: {throughput:.2f} episode/s")
    print(f"  成功: {results['success']}, 失败: {results['failed']}")
    if durations:
        print(f"  单 episode avg={avg_duration:.1f}s  min={min(durations):.1f}s  max={max(durations):.1f}s")
    if results["errors"]:
        for err in results["errors"][:3]:
            print(f"    ❌ {err}")
    print(f"  RSS: {rss_before:.0f}MB → {rss_after:.0f}MB (Δ={rss_after-rss_before:+.0f}MB)")

    return {
        "max_concurrent": max_concurrent,
        "num_episodes": num_episodes,
        "total_time": total_time,
        "throughput": throughput,
        "success": results["success"],
        "failed": results["failed"],
        "avg_duration": avg_duration,
        "rss_delta": rss_after - rss_before,
    }


async def main():
    from graphiti_config import create_graphiti

    print("=" * 60)
    print("events daemon 并发性能实测")
    print("=" * 60)

    # 清理旧数据
    from neo4j import AsyncGraphDatabase
    driver = AsyncGraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "neo4j_password"))
    await driver.execute_query("MATCH (n {group_id: $g}) DETACH DELETE n", g=EVAL_GROUP)
    await driver.close()

    graphiti, err = create_graphiti()
    if err:
        print(f"❌ {err}")
        return
    await graphiti.build_indices_and_constraints()

    print(f"\n初始 RSS: {get_rss_mb():.0f}MB")

    # 测试 1：单次 encode
    await test_single_encode()

    # 测试 2：单个 add_episode
    await test_single_add_episode(graphiti)

    # 清理测试 2 的数据
    driver = AsyncGraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "neo4j_password"))
    await driver.execute_query("MATCH (n {group_id: $g}) DETACH DELETE n", g=EVAL_GROUP)
    await driver.close()

    # 测试 3：并发测试
    print("\n" + "=" * 60)
    print("测试 3：不同并发数下的吞吐量")
    print("=" * 60)

    all_results = []
    for concurrency in [1, 2, 3, 5, 8]:
        # 每个并发数测试 concurrency × 3 个 episode（确保排队）
        num_episodes = max(concurrency * 3, 6)

        result = await test_concurrency(graphiti, concurrency, num_episodes)
        all_results.append(result)

        # 清理本轮数据
        driver = AsyncGraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "neo4j_password"))
        await driver.execute_query("MATCH (n {group_id: $g}) DETACH DELETE n", g=EVAL_GROUP)
        await driver.close()

        # 冷却 5s（避免 API 连续高压）
        print(f"  冷却 5s...")
        await asyncio.sleep(5)

    # 汇总
    print("\n" + "=" * 60)
    print("汇总对比")
    print("=" * 60)
    print(f"{'并发':>6} {'episode':>8} {'耗时':>8} {'吞吐':>10} {'成功率':>8} {'avg':>8} {'RSSΔ':>8}")
    print("-" * 60)
    for r in all_results:
        success_rate = r["success"] / r["num_episodes"] * 100
        print(
            f"{r['max_concurrent']:>6} "
            f"{r['num_episodes']:>8} "
            f"{r['total_time']:>7.1f}s "
            f"{r['throughput']:>8.2f}/s "
            f"{success_rate:>7.0f}% "
            f"{r['avg_duration']:>7.1f}s "
            f"{r['rss_delta']:>+7.0f}MB"
        )

    # 最终清理
    driver = AsyncGraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "neo4j_password"))
    await driver.execute_query("MATCH (n {group_id: $g}) DETACH DELETE n", g=EVAL_GROUP)
    await driver.close()
    await graphiti.close()
    print(f"\n最终 RSS: {get_rss_mb():.0f}MB")
    print("✅ 测试完成")


if __name__ == "__main__":
    asyncio.run(main())
