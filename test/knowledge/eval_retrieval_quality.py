"""评估 knowledge MCP 的向量检索质量。

测试方法：
  1. 存入覆盖 5 个领域的知识（binary/mobile/web/crypto/ai-security）
  2. 用不同措辞查询（模拟不同 agent 的查询风格）
  3. 计算 Recall@5（前 5 条结果中包含正确答案的比例）

指标：
  - Recall@5：目标知识出现在 top-5 的比例
  - score 分布：正确匹配 vs 错误匹配的 score 差距
  - 查询延迟
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "knowledge"))
from db import MemoryDB, DEFAULT_TOP_K
from anonymizer import anonymize
from sentence_transformers import SentenceTransformer

DB_PATH = Path.home() / "bw-security-analysis" / "db" / "knowledge" / "knowledge_eval.db"
MODEL_NAME = "BAAI/bge-m3"

# 测试数据：(question, answer, type, doc_type)
# 覆盖 5 个领域，每个领域 2 条
TEST_KNOWLEDGE = [
    # binary-analysis
    ("Windows PE x64 UPX 脱壳方法",
     "使用 UPX 工具直接脱壳：upx -d target.exe。如果修改了 magic，先修复后再脱壳。",
     "tool", "answer"),
    ("ARM64 栈溢出漏洞利用",
     "通过 ROP 链绕过 NX：用 ropper 找 gadget，构造 pivot gadget 控制 SP，跳到 system('/bin/sh')。",
     "vulnerability", "answer"),
    # mobile-analysis
    ("Android APK Frida SSL Pinning 绕过",
     "使用 frida-tools 的 objection：objection -g com.target explore -s 'android sslpinning disable'。或用 Frida 脚本 hook TrustManager。",
     "tool", "answer"),
    ("iOS IPA class-dump 提取类信息",
     "class-dump -H TargetApp -o headers/。需要先 decrypt 二进制（用 frida-ios-dump 或 clutch）。",
     "tool", "answer"),
    # web-analysis
    ("Spring Boot Actuator 信息泄露利用",
     "访问 /actuator/env 获取环境变量，/actuator/heapdump 获取内存转储。通过 /actuator/jolokia 可实现 RCE。",
     "vulnerability", "answer"),
    ("Web Cache Poisoning 攻击方法",
     "识别 unkeyed header（如 X-Forwarded-Host），注入恶意值让缓存中毒。用 Param Miner 找 unkeyed inputs。",
     "vulnerability", "answer"),
    # crypto-analysis
    ("RSA 小公钥指数攻击 Coppersmith",
     "当 e 很小（如 e=3）且消息短时，m^e < n → 直接开 e 次方。如果 m^e > n 但接近，用 Coppersmith small_roots。",
     "vulnerability", "answer"),
    ("椭圆曲线 anomalous 攻击（Smart's attack）",
     "当曲线阶等于有限域阶 p 时（anomalous），用 Smart's attack 在 O(1) 内解 ECDLP：通过 p-adic 提升计算。",
     "vulnerability", "answer"),
    # ai-security-analysis
    ("LLM 提示注入间接攻击",
     "通过网页内容注入隐藏指令（如白色文本、HTML 注释），让 LLM 执行攻击者命令。绕过用户 prompt 的安全过滤。",
     "vulnerability", "answer"),
    ("LLM 越狱攻击 DAN 模式",
     "通过角色扮演（Do Anything Now）让 LLM 忽略安全约束。变种：AIM、STAN 等角色设定。",
     "vulnerability", "answer"),
]

# 查询用例：(query, expected_match_index, description)
# query 用不同措辞——模拟不同 agent 的查询风格
TEST_QUERIES = [
    # 精确措辞（应该容易搜到）
    ("UPX 脱壳方法", 0, "精确措辞-UPX"),
    ("Frida SSL Pinning 绕过", 2, "精确措辞-SSL"),
    ("Coppersmith 攻击 RSA", 6, "精确措辞-Coppersmith"),

    # 同义措辞（考验语义匹配）
    ("如何脱壳 UPX 加壳的程序", 0, "同义措辞-脱壳"),
    ("移动端 HTTPS 证书绑定绕过", 2, "同义措辞-证书绑定"),
    ("椭圆曲线离散对数求解", 7, "同义措辞-ECDLP"),
    ("Spring 信息泄露漏洞", 4, "同义措辞-信息泄露"),
    ("AI 提示词注入攻击", 8, "同义措辞-提示注入"),

    # 模糊措辞（考验泛化能力）
    ("加壳程序的逆向分析方法", 0, "模糊措辞-加壳逆向"),
    ("HTTPS 抓包被拦截怎么办", 2, "模糊措弦-HTTPS 抓包"),
    ("密码学题目求解技巧", 6, "模糊措辞-密码学"),
    ("Web 框架安全漏洞", 4, "模糊措辞-Web 安全"),
    ("大模型安全测试方法", 8, "模糊措辞-LLM 安全"),

    # 跨领域查询（应该搜不到精确匹配，但可能有弱关联）
    ("缓冲区溢出漏洞利用", 1, "跨领域-栈溢出"),
    ("逆向分析 native 库", 1, "跨领域-native 逆向"),
]


async def main():
    import asyncio

    # 初始化（用独立的 eval 数据库，不污染生产数据）
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    print("=" * 70)
    print("knowledge MCP 向量检索质量评估")
    print("=" * 70)

    # 1. 加载模型 + 初始化 DB
    print("\n加载 BGE-M3 模型...")
    t0 = time.time()
    embedder = SentenceTransformer(MODEL_NAME)
    print(f"  模型加载: {time.time()-t0:.1f}s")

    db = MemoryDB(DB_PATH, embedder)

    # 2. 存入测试知识
    print(f"\n存入 {len(TEST_KNOWLEDGE)} 条知识...")
    for i, (q, a, t, dt) in enumerate(TEST_KNOWLEDGE):
        safe_q = anonymize(q)
        safe_a = anonymize(a)
        db.store(safe_q, safe_a, t, doc_type=dt)
    print(f"  ✅ 存入完成")

    # 3. 查询测试
    print(f"\n{'=' * 70}")
    print(f"查询测试（{len(TEST_QUERIES)} 组查询）")
    print(f"{'=' * 70}")

    results = []
    for query, expected_idx, desc in TEST_QUERIES:
        expected_q = TEST_KNOWLEDGE[expected_idx][0]
        search_results = db.search([query], type=None, doc_type="answer", top_k=5)

        # 检查 expected 是否在 top-5
        found_rank = None
        found_score = None
        for rank, r in enumerate(search_results):
            if expected_q in r.get("question", ""):
                found_rank = rank
                found_score = r["score"]
                break

        hit = found_rank is not None
        results.append({
            "query": query,
            "desc": desc,
            "expected": expected_q,
            "hit": hit,
            "rank": found_rank,
            "score": found_score,
        })

        status = f"✅ #{found_rank+1} (score={found_score:.3f})" if hit else "❌ 未命中"
        print(f"\n  [{desc}]")
        print(f"    query: {query}")
        print(f"    expected: {expected_q[:50]}")
        print(f"    result: {status}")

    # 4. 统计
    print(f"\n{'=' * 70}")
    print(f"统计")
    print(f"{'=' * 70}")

    total = len(results)
    hits = sum(1 for r in results if r["hit"])
    recall = hits / total

    # 按措辞类型分类统计
    categories = {}
    for r in results:
        cat = r["desc"].split("-")[0]
        if cat not in categories:
            categories[cat] = {"total": 0, "hits": 0}
        categories[cat]["total"] += 1
        if r["hit"]:
            categories[cat]["hits"] += 1

    print(f"\n  总 Recall@5: {recall:.1%} ({hits}/{total})")
    print(f"\n  按措辞类型:")
    for cat, stats in sorted(categories.items()):
        cat_recall = stats["hits"] / stats["total"]
        print(f"    {cat}: {cat_recall:.0%} ({stats['hits']}/{stats['total']})")

    # score 分布
    hit_scores = [r["score"] for r in results if r["hit"] and r["score"] is not None]
    if hit_scores:
        print(f"\n  命中 score 分布:")
        print(f"    min: {min(hit_scores):.3f}")
        print(f"    max: {max(hit_scores):.3f}")
        print(f"    avg: {sum(hit_scores)/len(hit_scores):.3f}")

    db.close()
    # 清理
    DB_PATH.unlink()


asyncio.run(main())
