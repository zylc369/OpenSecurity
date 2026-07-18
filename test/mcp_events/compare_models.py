#!/usr/bin/env python3
"""DeepSeek flash vs pro 效果对比测试（events 场景）。

用相同的复杂安全分析文本，分别通过 pro 和 flash 提取实体，
对比提取数量、质量、耗时、token 消耗。

用法：
  ~/bw-security-analysis/.venv/bin/python test/mcp_events/compare_models.py

费用估算：~¥1（pro ~¥0.5 + flash ~¥0.2，各 2 个 episode）
"""
import asyncio
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# 确保 events 目录在 sys.path
EVENTS_DIR = Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "events"
sys.path.insert(0, str(EVENTS_DIR))

# 加载 .ai_env
ai_env = Path(__file__).resolve().parents[2] / ".opencode" / ".ai_env"
for line in ai_env.read_text("utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

from graphiti_core import Graphiti
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.nodes import EpisodeType
from llm_client import DeepSeekLLMClient


# 测试用的复杂安全分析文本（多实体、多关系、中英文混合）
TEST_EPISODES = [
    {
        "name": "binary-analysis complex finding",
        "body": (
            "binary-analysis agent used Ghidra to analyze sample.exe. "
            "Found a stack buffer overflow vulnerability in function sub_4012A0 at offset 0x4012A0. "
            "The vulnerability is triggered when the program calls sprintf without size limit on user input from argv[1]. "
            "The function copies data to a 256-byte stack buffer at address 0x602040. "
            "Exploitation requires bypassing ASLR via a libc leak from puts@GOT. "
            "Recommended fix: replace sprintf with snprintf, or add bounds checking on input length. "
            "This vulnerability has been assigned CVE-2024-5678."
        ),
        "source": "binary-analysis agent response",
    },
    {
        "name": "web-analysis SQL injection finding",
        "body": (
            "web-analysis agent tested the target at https://example.com/login. "
            "Detected a SQL injection vulnerability in the username parameter of the login form. "
            "The backend uses MySQL 8.0 and the vulnerable query is: SELECT * FROM users WHERE username='$input'. "
            "Successfully exploited using sqlmap with --dump flag, extracting the users table containing 1500 records. "
            "The database also contains tables: products, orders, payments, admin_logs. "
            "The application runs on nginx 1.24 with PHP 8.2 frontend. "
            "Credential hash for admin user is bcrypt with cost factor 12."
        ),
        "source": "web-analysis agent response",
    },
]


async def run_model_test(model_name: str, group_id: str) -> dict:
    """用指定模型运行测试，返回结果统计。"""
    print(f"\n{'='*60}")
    print(f"模型: {model_name}")
    print(f"{'='*60}")

    # 创建 Graphiti 实例
    config = LLMConfig(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
        model=model_name,
        small_model=model_name,  # 统一用同一个模型（测试核心提取能力）
        temperature=0,
    )
    llm_client = DeepSeekLLMClient(config=config)

    from graphiti_config import BgeM3Embedder
    from reranker import BgeRerankerClient

    graphiti = Graphiti(
        uri="bolt://localhost:7687",
        user="neo4j",
        password="neo4j_password",
        llm_client=llm_client,
        embedder=BgeM3Embedder(),
        cross_encoder=BgeRerankerClient(),
    )

    await graphiti.build_indices_and_constraints()

    results = {
        "model": model_name,
        "episodes": [],
        "total_time": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
    }

    for ep in TEST_EPISODES:
        print(f"\n写入: {ep['name']}")
        start = time.time()

        await graphiti.add_episode(
            name=f"{group_id}-{ep['name']}",
            episode_body=ep["body"],
            source_description=ep["source"],
            reference_time=datetime.now(),
            source=EpisodeType.message,
            group_id=group_id,
        )

        elapsed = time.time() - start
        token_tracker = llm_client.token_tracker

        # 获取 token 统计
        input_tokens = sum(
            info.get("input_tokens", 0)
            for info in token_tracker.token_usage_by_prompt.values()
        ) if hasattr(token_tracker, "token_usage_by_prompt") else 0
        output_tokens = sum(
            info.get("output_tokens", 0)
            for info in token_tracker.token_usage_by_prompt.values()
        ) if hasattr(token_tracker, "token_usage_by_prompt") else 0

        episode_result = {
            "name": ep["name"],
            "time": elapsed,
        }
        results["episodes"].append(episode_result)
        results["total_time"] += elapsed

        print(f"  耗时: {elapsed:.1f}s")

    # 获取 token 总量
    token_tracker = llm_client.token_tracker
    if hasattr(token_tracker, "total_input_tokens"):
        results["total_input_tokens"] = token_tracker.total_input_tokens
        results["total_output_tokens"] = token_tracker.total_output_tokens
    else:
        results["total_input_tokens"] = 0
        results["total_output_tokens"] = 0

    # 查询提取的实体和关系
    from graphiti_core.search.search_config import (
        SearchConfig, EdgeSearchConfig, NodeSearchConfig,
        EdgeSearchMethod, NodeSearchMethod,
    )

    search_results = await graphiti.search_(
        query="vulnerability exploitation function database",
        group_ids=[group_id],
        config=SearchConfig(
            limit=50,
            edge_config=EdgeSearchConfig(
                search_methods=[EdgeSearchMethod.bm25, EdgeSearchMethod.cosine_similarity],
            ),
            node_config=NodeSearchConfig(
                search_methods=[NodeSearchMethod.bm25, NodeSearchMethod.cosine_similarity],
            ),
        ),
    )

    results["nodes"] = search_results.nodes
    results["edges"] = search_results.edges
    results["node_count"] = len(search_results.nodes)
    results["edge_count"] = len(search_results.edges)

    await graphiti.close()

    return results


def print_comparison(pro_results: dict, flash_results: dict):
    """打印对比表格。"""
    print(f"\n{'='*70}")
    print("对比结果")
    print(f"{'='*70}")

    # 1. 基本统计
    print(f"\n--- 基本统计 ---")
    print(f"{'指标':<25} {'pro':>15} {'flash':>15} {'差距':>10}")
    print(f"{'-'*65}")

    print(f"{'实体数量 (nodes)':<25} {pro_results['node_count']:>15} {flash_results['node_count']:>15} {pro_results['node_count'] - flash_results['node_count']:>+10}")
    print(f"{'关系数量 (edges)':<25} {pro_results['edge_count']:>15} {flash_results['edge_count']:>15} {pro_results['edge_count'] - flash_results['edge_count']:>+10}")
    print(f"{'总耗时 (秒)':<25} {pro_results['total_time']:>15.1f} {flash_results['total_time']:>15.1f} {pro_results['total_time'] - flash_results['total_time']:>+10.1f}")
    print(f"{'输入 token':<25} {pro_results['total_input_tokens']:>15,} {flash_results['total_input_tokens']:>15,}")
    print(f"{'输出 token':<25} {pro_results['total_output_tokens']:>15,} {flash_results['total_output_tokens']:>15,}")

    # 2. 费用估算
    pro_cost = (pro_results["total_input_tokens"] * 3 + pro_results["total_output_tokens"] * 6) / 1_000_000
    flash_cost = (flash_results["total_input_tokens"] * 1 + flash_results["total_output_tokens"] * 2) / 1_000_000
    print(f"{'费用估算 (¥)':<25} {pro_cost:>15.3f} {flash_cost:>15.3f}")

    # 3. 实体对比
    print(f"\n--- pro 提取的实体 ({pro_results['node_count']} 个) ---")
    pro_names = sorted([n.name for n in pro_results["nodes"]])
    for name in pro_names:
        print(f"  • {name}")

    print(f"\n--- flash 提取的实体 ({flash_results['node_count']} 个) ---")
    flash_names = sorted([n.name for n in flash_results["nodes"]])
    for name in flash_names:
        print(f"  • {name}")

    # 4. 差异分析
    pro_set = set(pro_names)
    flash_set = set(flash_names)

    only_pro = pro_set - flash_set
    only_flash = flash_set - pro_set
    common = pro_set & flash_set

    print(f"\n--- 实体差异 ---")
    print(f"两者都提取: {len(common)} 个")
    print(f"仅 pro 提取: {len(only_pro)} 个")
    for name in sorted(only_pro):
        print(f"  ⚠ pro 独有: {name}")
    print(f"仅 flash 提取: {len(only_flash)} 个")
    for name in sorted(only_flash):
        print(f"  ⚡ flash 独有: {name}")

    # 5. 关系对比
    print(f"\n--- pro 提取的关系 ({pro_results['edge_count']} 条) ---")
    for e in pro_results["edges"][:20]:
        print(f"  • {e.fact}")
    if len(pro_results["edges"]) > 20:
        print(f"  ... 还有 {len(pro_results['edges']) - 20} 条")

    print(f"\n--- flash 提取的关系 ({flash_results['edge_count']} 条) ---")
    for e in flash_results["edges"][:20]:
        print(f"  • {e.fact}")
    if len(flash_results["edges"]) > 20:
        print(f"  ... 还有 {len(flash_results['edges']) - 20} 条")

    # 6. 关键实体覆盖度检查
    expected_entities = [
        "sample.exe", "sub_4012A0", "sprintf", "snprintf", "stack buffer overflow",
        "ASLR", "libc", "puts@GOT", "CVE-2024-5678",
        "example.com", "SQL injection", "sqlmap", "MySQL", "nginx",
        "PHP", "bcrypt", "admin", "users table",
    ]

    print(f"\n--- 关键实体覆盖度 ---")
    print(f"{'期望实体':<25} {'pro':>8} {'flash':>8}")
    print(f"{'-'*45}")
    for entity in expected_entities:
        pro_found = any(entity.lower() in n.name.lower() for n in pro_results["nodes"])
        flash_found = any(entity.lower() in n.name.lower() for n in flash_results["nodes"])
        pro_mark = "✅" if pro_found else "❌"
        flash_mark = "✅" if flash_found else "❌"
        print(f"  {entity:<23} {pro_mark:>8} {flash_mark:>8}")

    pro_coverage = sum(1 for e in expected_entities if any(e.lower() in n.name.lower() for n in pro_results["nodes"]))
    flash_coverage = sum(1 for e in expected_entities if any(e.lower() in n.name.lower() for n in flash_results["nodes"]))
    print(f"\n  覆盖率: pro {pro_coverage}/{len(expected_entities)} ({pro_coverage/len(expected_entities)*100:.0f}%)  "
          f"flash {flash_coverage}/{len(expected_entities)} ({flash_coverage/len(expected_entities)*100:.0f}%)")


async def cleanup_neo4j():
    """清理测试数据。"""
    from neo4j import AsyncGraphDatabase
    driver = AsyncGraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "neo4j_password"))
    for group in ["compare-pro", "compare-flash"]:
        await driver.execute_query(
            "MATCH (n {group_id: $group}) DETACH DELETE n",
            group=group,
        )
    await driver.close()
    print("✅ 清理旧测试数据")


async def main():
    await cleanup_neo4j()

    # 运行 pro 测试
    pro_results = await run_model_test("deepseek-v4-pro", "compare-pro")

    # 运行 flash 测试
    flash_results = await run_model_test("deepseek-v4-flash", "compare-flash")

    # 打印对比
    print_comparison(pro_results, flash_results)

    # 清理
    await cleanup_neo4j()


if __name__ == "__main__":
    asyncio.run(main())
