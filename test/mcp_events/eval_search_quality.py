#!/usr/bin/env python3
"""events MCP 搜索质量评估。

写入 6 条多样化的安全分析 episode → 定义 20+ 查询 + 期望结果 → 搜索 → 评分。

评估指标：
  - Recall@5: 前 5 个结果中有多少是相关的
  - Precision@5: 前 5 个结果中有多少比例是相关的
  - MRR: 第一个相关结果的平均倒数排名
  - 搜索方法对比: BM25 vs BM25+cosine vs BM25+cosine+cross-encoder

成本估算：~¥0.5（6 条 episode × pro 模型写入 + 本地搜索 ¥0）

用法：
  ~/bw-security-analysis/.venv/bin/python test/mcp_events/eval_search_quality.py
"""
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

EVENTS_DIR = Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "events"
sys.path.insert(0, str(EVENTS_DIR))

# 加载 .ai_env
ai_env = Path(__file__).resolve().parents[2] / ".opencode" / ".ai_env"
for line in ai_env.read_text("utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

EVAL_GROUP = "eval-search-quality"


# ═══════════════════════════════════════════════════
# 测试数据：6 条多样化安全分析 episode
# ═══════════════════════════════════════════════════

EPISODES = [
    {
        "id": "binary",
        "name": "binary-analysis buffer overflow",
        "body": (
            "binary-analysis agent used Ghidra to analyze sample.exe. "
            "Found a stack buffer overflow vulnerability in function sub_4012A0 "
            "at offset 0x4012A0. The vulnerability is triggered by sprintf "
            "without size limit on argv[1]. Exploitation requires ASLR bypass "
            "via libc leak from puts@GOT. Fix: replace sprintf with snprintf. "
            "CVE-2024-5678 assigned."
        ),
        "expected_entities": ["sample.exe", "Ghidra", "sub_4012A0", "sprintf", "ASLR", "CVE-2024-5678"],
    },
    {
        "id": "web",
        "name": "web-analysis SQL injection",
        "body": (
            "web-analysis agent tested https://example.com/login. "
            "Detected SQL injection in username parameter. Backend uses MySQL 8.0. "
            "Exploited using sqlmap with --dump, extracted users table (1500 records). "
            "Database has tables: products, orders, payments, admin_logs. "
            "Application runs on nginx 1.24 with PHP 8.2."
        ),
        "expected_entities": ["example.com", "SQL injection", "sqlmap", "MySQL", "nginx", "PHP"],
    },
    {
        "id": "crypto",
        "name": "crypto-analysis RSA weak key",
        "body": (
            "crypto-analysis agent examined RSA public key (n=0xa1b2c3..., e=65537). "
            "Found that n factors into two primes p and q that are too close together. "
            "Successfully factored n using Fermat's factorization method. "
            "Private key recovered. The encryption scheme is RSA-2048 but with weak prime generation."
        ),
        "expected_entities": ["RSA", "Fermat", "factorization", "private key"],
    },
    {
        "id": "mobile",
        "name": "mobile-analysis APK repackaging",
        "body": (
            "mobile-analysis agent decompiled target.apk using apktool. "
            "Found the app was repackaged with a malicious Frida hook injected into "
            "the MainActivity.onCreate method. The original signing certificate was "
            "replaced. Smali code shows the hook exfiltrates device IMEI to "
            "evil.example.net via HTTP POST."
        ),
        "expected_entities": ["target.apk", "apktool", "Frida", "MainActivity", "IMEI"],
    },
    {
        "id": "network",
        "name": "network-analysis nmap scan",
        "body": (
            "network-analysis agent ran nmap scan on 10.0.0.0/24. "
            "Host 10.0.0.5 has ports 22 (SSH), 80 (HTTP), 443 (HTTPS), 3306 (MySQL) open. "
            "Host 10.0.0.8 has port 445 (SMB) open with SMBv1 enabled (vulnerable to EternalBlue). "
            "OS detection shows Linux 5.x on 10.0.0.5 and Windows Server 2019 on 10.0.0.8."
        ),
        "expected_entities": ["nmap", "10.0.0.5", "SSH", "EternalBlue", "SMB"],
    },
    {
        "id": "reverse",
        "name": "reverse-engineering malware analysis",
        "body": (
            "reverse-engineering agent analyzed malware.bin with IDA Pro. "
            "Identified C2 communication at sub_402000 using HTTP GET to "
            "c2.evil.com/beacon. The malware decrypts configuration data using AES-256-CBC "
            "with hardcoded key 0xDEADBEEF. Persistence via registry key "
            "HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Run."
        ),
        "expected_entities": ["IDA Pro", "malware.bin", "AES", "C2", "c2.evil.com"],
    },
]


# ═══════════════════════════════════════════════════
# 查询 + 期望结果（ground truth）
# ═══════════════════════════════════════════════════

QUERIES = [
    # --- 精确匹配（应该高 precision）---
    {"query": "buffer overflow sprintf", "expected_episodes": ["binary"], "category": "精确-漏洞类型"},
    {"query": "SQL injection sqlmap", "expected_episodes": ["web"], "category": "精确-攻击工具"},
    {"query": "RSA factorization", "expected_episodes": ["crypto"], "category": "精确-密码学"},
    {"query": "APK Frida hook", "expected_episodes": ["mobile"], "category": "精确-移动端"},
    {"query": "nmap port scan", "expected_episodes": ["network"], "category": "精确-网络扫描"},
    {"query": "malware C2 beacon", "expected_episodes": ["reverse"], "category": "精确-恶意软件"},

    # --- 模糊匹配（测试语义理解）---
    {"query": "memory corruption vulnerability", "expected_episodes": ["binary"], "category": "模糊-语义"},
    {"query": "database exploitation technique", "expected_episodes": ["web"], "category": "模糊-语义"},
    {"query": "cryptographic weakness", "expected_episodes": ["crypto"], "category": "模糊-语义"},
    {"query": "code injection attack", "expected_episodes": ["mobile", "web"], "category": "模糊-跨域"},

    # --- 实体特定查询 ---
    {"query": "sample.exe", "expected_episodes": ["binary"], "category": "实体-文件名"},
    {"query": "CVE-2024-5678", "expected_episodes": ["binary"], "category": "实体-CVE"},
    {"query": "10.0.0.5", "expected_episodes": ["network"], "category": "实体-IP"},
    {"query": "c2.evil.com", "expected_episodes": ["reverse"], "category": "实体-域名"},

    # --- 跨域查询（多个 episode 相关）---
    {"query": "vulnerability exploitation", "expected_episodes": ["binary", "web", "network"], "category": "跨域"},
    {"query": "security analysis tool", "expected_episodes": ["binary", "web", "reverse", "network"], "category": "跨域"},
    {"query": "encryption decryption", "expected_episodes": ["crypto", "reverse"], "category": "跨域"},

    # --- 无关查询（应该返回低相关结果）---
    {"query": "weather forecast today", "expected_episodes": [], "category": "无关"},
    {"query": "recipe for pasta", "expected_episodes": [], "category": "无关"},
    {"query": "how to learn python", "expected_episodes": [], "category": "无关"},
]


# ═══════════════════════════════════════════════════
# 评估逻辑
# ═══════════════════════════════════════════════════

async def setup_data(graphiti):
    """写入测试数据（单条失败不影响其他）。"""
    from graphiti_core.nodes import EpisodeType

    print("\n写入测试数据...")
    success = []
    for ep in EPISODES:
        print(f"  写入: {ep['name']}...", end=" ")
        try:
            await graphiti.add_episode(
                name=ep["name"],
                episode_body=ep["body"],
                source_description="eval",
                reference_time=datetime.now(),
                source=EpisodeType.message,
                group_id=EVAL_GROUP,
            )
            print("✅")
            success.append(ep)
        except Exception as e:
            print(f"⚠️ 跳过 ({type(e).__name__})")
            # episode 的实体和边可能已写入 Neo4j，只是属性提取失败

    print(f"成功写入 {len(success)}/{len(EPISODES)} 条，等待索引（30s）...")
    await asyncio.sleep(30)
    return success


def evaluate_search_results(results, expected_episode_ids, k=5):
    """评估搜索结果。

    Args:
        results: SearchResults 对象
        expected_episode_ids: 期望命中的 episode ID 列表
        k: 评估前 K 个结果

    Returns:
        dict: {precision@k, recall@k, mrr, hit_count}
    """
    # 从搜索结果提取 episode 名称（用于匹配）
    result_episodes = []
    for ep in results.episodes:
        content = getattr(ep, "content", "") or ""
        name = getattr(ep, "name", "") or ""
        result_episodes.append({"content": content, "name": name})

    # 从搜索结果提取实体名称
    result_nodes = [getattr(n, "name", "") for n in results.nodes]

    # 从搜索结果提取 fact 文本
    result_edges = [getattr(e, "fact", "") for e in results.edges]

    # 将所有结果文本合并用于匹配
    all_text = " ".join(
        ep["content"] + " " + ep["name"] for ep in result_episodes
    ) + " ".join(result_nodes) + " ".join(result_edges)

    # 检查每个期望的 episode 是否被命中
    hits = []
    for ep_id in expected_episode_ids:
        ep_data = next(e for e in EPISODES if e["id"] == ep_id)
        # 检查 episode 的特征词是否出现在搜索结果中
        keywords = ep_data["expected_entities"][:3]  # 取前 3 个实体作为关键词
        found = any(kw.lower() in all_text.lower() for kw in keywords)
        hits.append(found)

    hit_count = sum(hits)
    expected_count = len(expected_episode_ids)

    # Precision@k: 返回结果中有多少比例是相关的
    # 如果期望 0 个，precision = 1 if no results else penalize
    if expected_count == 0:
        precision = 1.0 if (len(results.episodes) + len(results.nodes) + len(results.edges)) == 0 else 0.3
    else:
        # 粗略估计：返回的结果中相关的比例
        total_results = min(k, len(results.episodes) + len(results.nodes) + len(results.edges))
        precision = hit_count / max(total_results, 1) if total_results > 0 else 0.0

    # Recall@k: 期望结果中有多少被找到
    recall = hit_count / expected_count if expected_count > 0 else 1.0

    # MRR: 第一个命中结果的倒数排名
    mrr = 0.0
    for i, found in enumerate(hits):
        if found:
            mrr = 1.0 / (i + 1)
            break

    return {
        "precision": precision,
        "recall": recall,
        "mrr": mrr,
        "hit_count": hit_count,
        "expected_count": expected_count,
        "total_results": len(results.episodes) + len(results.nodes) + len(results.edges),
    }


async def run_query(graphiti, query_text, search_config_name="default"):
    """运行单个查询。"""
    from graphiti_core.search.search_config import (
        SearchConfig, EdgeSearchConfig, NodeSearchConfig,
        EpisodeSearchConfig, EdgeSearchMethod, NodeSearchMethod,
        EpisodeSearchMethod, EdgeReranker,
    )

    if search_config_name == "bm25":
        config = SearchConfig(
            limit=5,
            edge_config=EdgeSearchConfig(search_methods=[EdgeSearchMethod.bm25]),
            node_config=NodeSearchConfig(search_methods=[NodeSearchMethod.bm25]),
            episode_config=EpisodeSearchConfig(search_methods=[EpisodeSearchMethod.bm25]),
        )
    elif search_config_name == "hybrid":
        config = SearchConfig(
            limit=5,
            edge_config=EdgeSearchConfig(
                search_methods=[EdgeSearchMethod.bm25, EdgeSearchMethod.cosine_similarity],
            ),
            node_config=NodeSearchConfig(
                search_methods=[NodeSearchMethod.bm25, NodeSearchMethod.cosine_similarity],
            ),
            episode_config=EpisodeSearchConfig(search_methods=[EpisodeSearchMethod.bm25]),
        )
    elif search_config_name == "cross_encoder":
        config = SearchConfig(
            limit=5,
            edge_config=EdgeSearchConfig(
                search_methods=[EdgeSearchMethod.bm25, EdgeSearchMethod.cosine_similarity],
                reranker=EdgeReranker.cross_encoder,
            ),
            node_config=NodeSearchConfig(
                search_methods=[NodeSearchMethod.bm25, NodeSearchMethod.cosine_similarity],
            ),
            episode_config=EpisodeSearchConfig(search_methods=[EpisodeSearchMethod.bm25]),
        )
    else:  # default
        config = SearchConfig(limit=5)

    return await graphiti.search_(
        query=query_text,
        group_ids=[EVAL_GROUP],
        config=config,
    )


async def main():
    from graphiti_config import create_graphiti

    graphiti, err = create_graphiti()
    if err:
        print(f"❌ Graphiti 不可用: {err}")
        return

    await graphiti.build_indices_and_constraints()

    # 清理旧数据
    from neo4j import AsyncGraphDatabase as Neo4jDriver
    driver = Neo4jDriver.driver("bolt://localhost:7687", auth=("neo4j", "neo4j_password"))
    await driver.execute_query(
        "MATCH (n {group_id: $g}) DETACH DELETE n", g=EVAL_GROUP,
    )
    await driver.close()

    # 写入数据
    await setup_data(graphiti)

    # 运行查询评估
    search_methods = ["bm25", "hybrid", "cross_encoder"]
    all_results = {}

    for method in search_methods:
        print(f"\n{'='*60}")
        print(f"搜索方法: {method}")
        print(f"{'='*60}")

        method_scores = []
        category_scores = {}

        for q in QUERIES:
            try:
                results = await run_query(graphiti, q["query"], method)
                scores = evaluate_search_results(results, q["expected_episodes"])
                method_scores.append(scores)

                cat = q["category"]
                if cat not in category_scores:
                    category_scores[cat] = []
                category_scores[cat].append(scores)

                status = "✅" if scores["recall"] >= 0.5 else "⚠️" if scores["recall"] > 0 else "❌"
                print(
                    f"  {status} [{q['category']:<12}] recall={scores['recall']:.0%} "
                    f"precision={scores['precision']:.2f} mrr={scores['mrr']:.2f} "
                    f"hits={scores['hit_count']}/{scores['expected_count']} "
                    f"results={scores['total_results']} "
                    f"q=\"{q['query'][:40]}\""
                )
            except Exception as e:
                print(f"  ❌ [{q['category']:<12}] ERROR: {e}  q=\"{q['query'][:40]}\"")
                method_scores.append({"precision": 0, "recall": 0, "mrr": 0, "hit_count": 0, "expected_count": len(q["expected_episodes"]), "total_results": 0})

        # 汇总
        avg_recall = sum(s["recall"] for s in method_scores) / len(method_scores)
        avg_precision = sum(s["precision"] for s in method_scores) / len(method_scores)
        avg_mrr = sum(s["mrr"] for s in method_scores) / len(method_scores)

        all_results[method] = {
            "avg_recall": avg_recall,
            "avg_precision": avg_precision,
            "avg_mrr": avg_mrr,
            "category_scores": category_scores,
        }

        print(f"\n  汇总: recall={avg_recall:.1%} precision={avg_precision:.2f} mrr={avg_mrr:.2f}")

    # 对比报告
    print(f"\n{'='*70}")
    print("搜索方法对比")
    print(f"{'='*70}")
    print(f"{'方法':<20} {'Recall':>10} {'Precision':>10} {'MRR':>10}")
    print(f"{'-'*50}")
    for method, scores in all_results.items():
        print(f"  {method:<18} {scores['avg_recall']:>10.1%} {scores['avg_precision']:>10.2f} {scores['avg_mrr']:>10.2f}")

    # 分类报告
    print(f"\n{'='*70}")
    print("分类表现（hybrid 方法）")
    print(f"{'='*70}")
    hybrid_cats = all_results["hybrid"]["category_scores"]
    print(f"{'类别':<20} {'Recall':>10} {'查询数':>8}")
    print(f"{'-'*40}")
    for cat, scores in sorted(hybrid_cats.items()):
        cat_recall = sum(s["recall"] for s in scores) / len(scores)
        print(f"  {cat:<18} {cat_recall:>10.1%} {len(scores):>8}")

    # 清理
    driver = Neo4jDriver.driver("bolt://localhost:7687", auth=("neo4j", "neo4j_password"))
    await driver.execute_query("MATCH (n {group_id: $g}) DETACH DELETE n", g=EVAL_GROUP)
    await driver.close()
    await graphiti.close()

    print("\n✅ 评估完成（测试数据已清理）")


if __name__ == "__main__":
    asyncio.run(main())
