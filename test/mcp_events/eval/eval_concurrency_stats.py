#!/usr/bin/env python3
"""并发性能统计可靠测试——每个并发级别跑 10 轮，计算均值/标准差/置信区间。

用统计方法消除单次波动，得出可靠结论。

用法：
  ~/bw-security-analysis/.venv/bin/python test/mcp_events/eval/eval_concurrency_stats.py
"""
import asyncio
import os
import resource
import sys
import time
from datetime import datetime
from pathlib import Path
from statistics import mean, median, stdev

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / ".opencode" / "mcp-servers" / "events"))

ai_env = Path(__file__).resolve().parents[3] / ".opencode" / ".ai_env"
for line in ai_env.read_text("utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

EPISODES = [
    "binary-analysis agent used Ghidra to analyze sample.exe. Found buffer overflow in function sub_4012A0. CVE-2024-5678 assigned.",
    "web-analysis agent tested SQL injection in login form. Backend uses MySQL 8.0. sqlmap exploitation detected.",
    "crypto-analysis agent examined RSA key. Found weak primes. Factored using Fermat method.",
    "network-analysis agent ran nmap scan. Host 10.0.0.5 has ports 22 80 443 open.",
    "reverse-engineering agent analyzed malware.bin with IDA Pro. Found C2 beacon.",
    "mobile-analysis agent decompiled target.apk with apktool. Found Frida hook.",
]

ROUNDS = 10
CONCURRENCY_LEVELS = [1, 3, 5, 8, 10, 15]
EPISODES_PER_ROUND = 6  # 固定 6 个，消除 episode 数量的变量


def get_rss():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024


async def run_one_round(graphiti, concurrency, round_idx):
    """单轮测试：固定 concurrency 并发跑 EPISODES_PER_ROUND 个 episode。"""
    from graphiti_core.nodes import EpisodeType
    from neo4j import AsyncGraphDatabase

    group = f"stats-{concurrency}-r{round_idx}"

    driver = AsyncGraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "neo4j_password"))
    await driver.execute_query("MATCH (n {group_id: $g}) DETACH DELETE n", g=group)
    await driver.close()

    sem = asyncio.Semaphore(concurrency)
    durations = []

    async def run_ep(idx):
        async with sem:
            t0 = time.time()
            await graphiti.add_episode(
                name=f"{group}-{idx}",
                episode_body=EPISODES[idx % len(EPISODES)],
                source_description="eval",
                reference_time=datetime.now(),
                source=EpisodeType.message,
                group_id=group,
            )
            durations.append(time.time() - t0)

    t_start = time.time()
    await asyncio.gather(*[run_ep(i) for i in range(EPISODES_PER_ROUND)])
    wall_time = time.time() - t_start

    driver = AsyncGraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "neo4j_password"))
    await driver.execute_query("MATCH (n {group_id: $g}) DETACH DELETE n", g=group)
    await driver.close()

    return {
        "wall_time": wall_time,
        "throughput": EPISODES_PER_ROUND / wall_time,
        "ep_avg": mean(durations) if durations else 0,
        "ep_max": max(durations) if durations else 0,
        "ep_min": min(durations) if durations else 0,
    }


def stats_summary(values):
    """计算统计摘要。"""
    n = len(values)
    m = mean(values)
    if n >= 2:
        s = stdev(values)
        # 95% 置信区间半宽 = 1.96 * s / sqrt(n)
        ci_half = 1.96 * s / (n ** 0.5)
    else:
        s = 0
        ci_half = 0
    return {
        "mean": m,
        "median": median(values),
        "stdev": s,
        "min": min(values),
        "max": max(values),
        "ci_low": m - ci_half,
        "ci_high": m + ci_half,
        "n": n,
    }


async def main():
    from graphiti_config import create_graphiti

    print("=" * 80)
    print(f"并发性能统计测试（{ROUNDS} 轮 × {EPISODES_PER_ROUND} episodes/轮）")
    print(f"并发级别: {CONCURRENCY_LEVELS}")
    print("=" * 80)

    graphiti, err = create_graphiti()
    if err:
        print(f"❌ {err}")
        return
    await graphiti.build_indices_and_constraints()

    rss_start = get_rss()
    all_data = {}

    for concurrency in CONCURRENCY_LEVELS:
        print(f"\n{'─' * 80}")
        print(f"并发 {concurrency}（{ROUNDS} 轮）")
        print(f"{'─' * 80}")

        round_results = []
        for r in range(ROUNDS):
            result = await run_one_round(graphiti, concurrency, r)
            round_results.append(result)
            print(f"  色轮 {r+1:>2}/{ROUNDS}: wall={result['wall_time']:>5.1f}s  "
                  f"throughput={result['throughput']:.2f}  "
                  f"ep_avg={result['ep_avg']:>5.1f}s  ep_max={result['ep_max']:>5.1f}s",
                  flush=True)
            # 轮间冷却 3s（避免 API 连续高压 + 让 Neo4j 清理完）
            await asyncio.sleep(3)

        # 汇总
        throughputs = [r["throughput"] for r in round_results]
        ep_avgs = [r["ep_avg"] for r in round_results]
        ep_maxs = [r["ep_max"] for r in round_results]
        walls = [r["wall_time"] for r in round_results]

        t_stats = stats_summary(throughputs)
        ea_stats = stats_summary(ep_avgs)
        em_stats = stats_summary(ep_maxs)
        w_stats = stats_summary(walls)

        all_data[concurrency] = {
            "throughput": t_stats,
            "ep_avg": ea_stats,
            "ep_max": em_stats,
            "wall_time": w_stats,
        }

        print(f"\n  汇总（{ROUNDS} 轮）:")
        print(f"    吞吐量: {t_stats['mean']:.2f} ± {t_stats['stdev']:.2f} ep/s  "
              f"[95% CI: {t_stats['ci_low']:.2f} ~ {t_stats['ci_high']:.2f}]")
        print(f"    ep avg: {ea_stats['mean']:.1f} ± {ea_stats['stdev']:.1f}s  "
              f"[95% CI: {ea_stats['ci_low']:.1f} ~ {ea_stats['ci_high']:.1f}]")
        print(f"    ep max: {em_stats['mean']:.1f} ± {em_stats['stdev']:.1f}s  "
              f"[95% CI: {em_stats['ci_low']:.1f} ~ {em_stats['ci_high']:.1f}]")

    await graphiti.close()
    rss_end = get_rss()

    # 最终对比表
    print(f"\n{'=' * 90}")
    print(f"最终对比（{ROUNDS} 轮统计，95% 置信区间）")
    print(f"{'=' * 90}")
    print(f"{'并发':>4} {'吞吐量(ep/s)':>22} {'ep avg(s)':>22} {'ep max(s)':>22}")
    print(f"{'':>4} {'mean ± stdev [CI]':>22} {'mean ± stdev [CI]':>22} {'mean ± stdev [CI]':>22}")
    print("-" * 90)
    for c in CONCURRENCY_LEVELS:
        d = all_data[c]
        t = d["throughput"]
        a = d["ep_avg"]
        m = d["ep_max"]
        print(f"{c:>4}  {t['mean']:>5.2f} ± {t['stdev']:.2f} [{t['ci_low']:>4.2f}~{t['ci_high']:>4.2f}]"
              f"  {a['mean']:>5.1f} ± {a['stdev']:.1f} [{a['ci_low']:>4.1f}~{a['ci_high']:>4.1f}]"
              f"  {m['mean']:>5.1f} ± {m['stdev']:.1f} [{m['ci_low']:>4.1f}~{m['ci_high']:>4.1f}]")

    # 统计检验：相邻并发级别的 ep_avg 置信区间是否重叠
    print(f"\n{'=' * 90}")
    print("延迟差异分析（ep avg 置信区间是否重叠）")
    print(f"{'=' * 90}")
    for i in range(1, len(CONCURRENCY_LEVELS)):
        c1 = CONCURRENCY_LEVELS[i - 1]
        c2 = CONCURRENCY_LEVELS[i]
        a1 = all_data[c1]["ep_avg"]
        a2 = all_data[c2]["ep_avg"]
        overlap = a1["ci_high"] >= a2["ci_low"] and a2["ci_high"] >= a1["ci_low"]
        delta = a2["mean"] - a1["mean"]
        verdict = "无显著差异（置信区间重叠）" if overlap else f"有显著差异（{delta:+.1f}s）"
        print(f"  并发 {c1}→{c2}: ep_avg {a1['mean']:.1f}→{a2['mean']:.1f}s (Δ={delta:+.1f}s) → {verdict}")

    print(f"\nRSS: {rss_start:.0f}MB → {rss_end:.0f}MB")
    print("✅ 测试完成")


if __name__ == "__main__":
    asyncio.run(main())
