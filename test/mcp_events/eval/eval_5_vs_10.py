#!/usr/bin/env python3
"""并发 5 vs 10 可靠对比——精简版。

设计：
  - Queue + N workers 持续消费（模拟 daemon 真实模式）
  - 每轮 episode 数 = max(并发数 × 3, 15)，确保排队
  - 5 轮取统计（5% 置信区间仍然可靠）
  - 预计耗时：~20 分钟
"""
import asyncio, os, sys, time, resource
from datetime import datetime
from pathlib import Path
from statistics import mean, stdev, median

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / ".opencode" / "mcp-servers" / "events"))
ai_env = Path(__file__).resolve().parents[3] / ".opencode" / ".ai_env"
for line in ai_env.read_text("utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

EPISODES = [
    "binary-analysis agent used Ghidra to analyze sample.exe. Found buffer overflow in sub_4012A0. CVE-2024-5678.",
    "web-analysis agent detected SQL injection in login form. Backend MySQL 8.0. sqlmap exploitation.",
    "crypto-analysis agent examined RSA key. Weak primes factored via Fermat method.",
    "network-analysis agent ran nmap. Host 10.0.0.5 ports 22 80 443 open. EternalBlue on 10.0.0.8.",
    "reverse-engineering agent found C2 beacon to c2.evil.com in malware.bin. AES-256-CBC config.",
    "mobile-analysis agent decompiled target.apk. Frida hook in MainActivity. IMEI exfiltration.",
]

ROUNDS = 5

def get_rss():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024

async def run_round(graphiti, workers, episodes, round_idx):
    from graphiti_core.nodes import EpisodeType
    from neo4j import AsyncGraphDatabase

    group = f"cmp-{workers}-r{round_idx}"
    driver = AsyncGraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "neo4j_password"))
    await driver.execute_query("MATCH (n {group_id: $g}) DETACH DELETE n", g=group)
    await driver.close()

    queue = asyncio.Queue()
    for i in range(episodes):
        await queue.put((i, EPISODES[i % len(EPISODES)]))
    for _ in range(workers):
        await queue.put(None)

    durations = []
    async def worker():
        while True:
            item = await queue.get()
            if item is None:
                queue.task_done()
                break
            idx, body = item
            t0 = time.time()
            await graphiti.add_episode(
                name=f"{group}-{idx}", episode_body=body,
                source_description="eval", reference_time=datetime.now(),
                source=EpisodeType.message, group_id=group,
            )
            durations.append(time.time() - t0)
            queue.task_done()

    t0 = time.time()
    ws = [asyncio.create_task(worker()) for _ in range(workers)]
    await queue.join()
    await asyncio.gather(*ws)
    wall = time.time() - t0

    driver = AsyncGraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "neo4j_password"))
    await driver.execute_query("MATCH (n {group_id: $g}) DETACH DELETE n", g=group)
    await driver.close()

    return {
        "wall": wall, "throughput": episodes / wall,
        "ep_avg": mean(durations), "ep_max": max(durations),
    }

def ci95(vals):
    n = len(vals)
    m = mean(vals)
    s = stdev(vals) if n >= 2 else 0
    h = 1.96 * s / (n ** 0.5) if n >= 2 else 0
    return m, s, m - h, m + h

async def main():
    from graphiti_config import create_graphiti

    configs = [(5, 15), (10, 30)]  # (workers, episodes_per_round)
    total_eps = sum(e * ROUNDS for _, e in configs)
    print(f"并发 5 vs 10 对比（{ROUNDS} 轮，Queue+Workers 模式）")
    print(f"总 episode 数: {total_eps}，预计 ~{total_eps * 10 // 60} 分钟")
    print(f"并发 5: {configs[0][1]} ep/轮 | 并发 10: {configs[1][1]} ep/轮")
    print("=" * 70)

    g, err = create_graphiti()
    if err:
        print(f"❌ {err}"); return
    await g.build_indices_and_constraints()

    all_r = {}
    for workers, eps in configs:
        print(f"\n--- 并发 {workers}（{eps} ep/轮 × {ROUNDS} 轮 = {eps*ROUNDS} ep）---")
        rounds = []
        for r in range(ROUNDS):
            res = await run_round(g, workers, eps, r)
            rounds.append(res)
            print(f"  轮 {r+1}: wall={res['wall']:.1f}s  tp={res['throughput']:.2f}  "
                  f"avg={res['ep_avg']:.1f}s  max={res['ep_max']:.1f}s", flush=True)
            await asyncio.sleep(2)
        all_r[workers] = rounds

    await g.close()

    # 统计对比
    print(f"\n{'=' * 70}")
    print(f"统计对比（{ROUNDS} 轮，95% CI）")
    print(f"{'=' * 70}")

    for workers in [5, 10]:
        rounds = all_r[workers]
        tp_vals = [r["throughput"] for r in rounds]
        avg_vals = [r["ep_avg"] for r in rounds]
        max_vals = [r["ep_max"] for r in rounds]

        tp_m, tp_s, tp_lo, tp_hi = ci95(tp_vals)
        avg_m, avg_s, avg_lo, avg_hi = ci95(avg_vals)
        max_m, max_s, max_lo, max_hi = ci95(max_vals)

        print(f"\n并发 {workers}:")
        print(f"  吞吐量: {tp_m:.2f} ± {tp_s:.2f} [{tp_lo:.2f}, {tp_hi:.2f}]")
        print(f"  ep avg: {avg_m:.1f} ± {avg_s:.1f}s [{avg_lo:.1f}, {avg_hi:.1f}]")
        print(f"  ep max: {max_m:.1f} ± {max_s:.1f}s [{max_lo:.1f}, {max_hi:.1f}]")

        all_r[workers] = {"tp": (tp_m, tp_lo, tp_hi), "avg": (avg_m, avg_lo, avg_hi), "max": (max_m, max_lo, max_hi)}

    # 对比表
    d5, d10 = all_r[5], all_r[10]
    print(f"\n{'=' * 70}")
    print(f"{'指标':<20} {'并发5':>15} {'并发10':>15} {'差异':>10} {'显著?':>8}")
    print(f"{'-' * 70}")

    for key, label in [("tp", "吞吐量(ep/s)"), ("avg", "ep avg(s)"), ("max", "ep max(s)")]:
        m5, lo5, hi5 = d5[key]
        m10, lo10, hi10 = d10[key]
        delta = m10 - m5
        pct = delta / m5 * 100 if m5 else 0
        overlap = hi5 >= lo10 and hi10 >= lo5
        sig = "否" if overlap else "是"
        print(f"{label:<20} {m5:>10.2f} [{lo5:.2f}~{hi5:.2f}] {m10:>10.2f} [{lo10:.2f}~{hi10:.2f}] "
              f"{delta:>+7.2f} ({pct:>+4.0f}%) {sig:>8}")

    print(f"\nRSS: {get_rss():.0f}MB")
    print("✅ 完成")

asyncio.run(main())
