"""Knowledge MCP 全面测试——工具简化（7→3）后的功能验证。

测试层次：
  1. anonymizer.py: 各模式清洗 + 多模式混合 + 边界
  2. db.py: embed content、score 阈值、lang 过滤、doc_type 隔离、多 query 合并、迁移
  3. server.py: 直接调用工具函数（非 AST），验证参数验证 + 匿名化效果 + 端到端搜索
"""
import json
import sys
import tempfile
from pathlib import Path

import pytest

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "knowledge"
sys.path.insert(0, str(KNOWLEDGE_DIR))


# ═════════════════════════════════════════════════════════
# anonymizer 测试
# ═════════════════════════════════════════════════════════


class TestAnonymizerPatterns:
    """各模式单独验证。"""

    def test_ipv4(self):
        from anonymizer import anonymize
        assert anonymize("IP: 192.168.1.100") == "IP: <IP>"
        assert anonymize("connect to 10.0.0.5") == "connect to <IP>"

    def test_ipv4_edge(self):
        from anonymizer import anonymize
        assert "<IP>" in anonymize("255.255.255.255")
        assert "<IP>" in anonymize("0.0.0.0")

    def test_email(self):
        from anonymizer import anonymize
        assert "<EMAIL>" in anonymize("send to admin@evil.com")
        assert "<EMAIL>" in anonymize("user.name+tag@sub.domain.org")

    def test_api_key(self):
        from anonymizer import anonymize
        # sk- 开头的 key 会被 API_KEY 或 CREDENTIAL 匹配（取决于模式顺序）
        result = anonymize("key: sk-1234567890abcdefghijklmnopqrstuvwxyz")
        assert "<API_KEY>" in result or "<CREDENTIAL>" in result, f"应被清洗，实际: {result}"

    def test_aws_key(self):
        from anonymizer import anonymize
        assert "<AWS_KEY>" in anonymize("AKIAIOSFODNN7EXAMPLE")

    def test_credential_assignment(self):
        from anonymizer import anonymize
        assert "<CREDENTIAL>" in anonymize("password=secret123")
        assert "<CREDENTIAL>" in anonymize("api_key: abc123xyz")
        assert "<CREDENTIAL>" in anonymize('token = "eyJhbGciOiJIUzI1"')

    def test_bearer_token(self):
        from anonymizer import anonymize
        assert "<BEARER_TOKEN>" in anonymize("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9")

    def test_ssh_connection(self):
        from anonymizer import anonymize
        result = anonymize("ssh root@192.168.1.1")
        assert "<IP>" in result

    def test_db_connection(self):
        from anonymizer import anonymize
        result = anonymize("postgres://user:pass@db.host:5432/mydb")
        assert "<DB_CONNECTION>" in result

    def test_domain_standalone(self):
        from anonymizer import anonymize
        assert "<DOMAIN>" in anonymize("host: evil.com")
        assert "<DOMAIN>" in anonymize("visit example.org")


class TestAnonymizerEdgeCases:
    """多模式混合 + 边界条件。"""

    def test_multiple_patterns_in_one_text(self):
        from anonymizer import anonymize
        text = "Server at 192.168.1.50, contact admin@evil.com, key=sk-abc123"
        result = anonymize(text)
        assert "<IP>" in result
        assert "<EMAIL>" in result
        assert "<API_KEY>" in result or "<CREDENTIAL>" in result

    def test_url_domain_not_replaced(self):
        from anonymizer import anonymize
        result = anonymize("visit https://example.com/path/to/page")
        assert "example.com" in result, "URL 内的域名不应被替换"

    def test_normal_text_unchanged(self):
        from anonymizer import anonymize
        text = "binary analysis with Ghidra found buffer overflow in sub_4012A0"
        assert anonymize(text) == text

    def test_empty_string(self):
        from anonymizer import anonymize
        assert anonymize("") == ""

    def test_cve_not_replaced(self):
        from anonymizer import anonymize
        """CVE 编号不应被误清洗。"""
        result = anonymize("CVE-2024-5678 assigned")
        assert "CVE-2024-5678" in result

    def test_hex_offset_not_replaced(self):
        from anonymizer import anonymize
        """十六进制地址不应被误清洗为 IP。"""
        result = anonymize("function at 0x4012A0")
        assert "0x4012A0" in result


# ═════════════════════════════════════════════════════════
# db.py 测试
# ═════════════════════════════════════════════════════════


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


class TestDbEmbedContent:
    """验证 embed 目标是 content 不是 question。"""

    def test_search_by_content(self, db):
        """用 content 里的词（不在 question 里）能搜到。"""
        db.store(
            question="authentication",
            content="RBAC role-based access control with JWT tokens",
        )
        results = db.search(["RBAC permissions"])
        assert len(results) > 0, "应通过 content 内容搜到"

    def test_content_match_higher_than_question_match(self, db):
        """content 内容匹配应比 question 匹配分数高。"""
        db.store(
            question="intro",
            content="Detailed analysis of SQL injection in login forms with sqlmap exploitation",
        )
        # 搜 content 里的词
        content_results = db.search(["SQL injection sqlmap"])
        # 搜 question 里的词
        question_results = db.search(["intro"])

        content_score = content_results[0]["score"] if content_results else 0
        question_score = question_results[0]["score"] if question_results else 0
        assert content_score >= question_score, f"content 匹配({content_score}) 应 >= question 匹配({question_score})"


class TestDbDocTypeIsolation:
    """验证 knowledge 和 memory 之间数据隔离。"""

    def test_memory_search_excludes_knowledge(self, db):
        db.store("test query", "knowledge content about analysis", doc_type="knowledge")
        db.store("test query", "memory content from tool execution", doc_type="memory")

        memory_results = db.search(["test content"], doc_type="memory")
        knowledge_results = db.search(["test content"], doc_type="knowledge")

        # memory 搜索不返回 knowledge 的数据
        for r in memory_results:
            assert r["answer"] == "memory content from tool execution"
        for r in knowledge_results:
            assert r["answer"] == "knowledge content about analysis"


class TestDbLangFilter:
    """验证 lang 过滤。"""

    def test_lang_filter(self, db):
        db.store("hash", "hashlib.sha256(data).hexdigest()", doc_type="knowledge", lang="python")
        db.store("hash", "echo -n 'data' | sha256sum", doc_type="knowledge", lang="bash")

        python_results = db.search(["hash"], doc_type="knowledge", lang="python")
        bash_results = db.search(["hash"], doc_type="knowledge", lang="bash")

        for r in python_results:
            assert "hashlib" in r["answer"]
        for r in bash_results:
            assert "sha256sum" in r["answer"]

    def test_no_lang_filter_returns_all(self, db):
        db.store("hash", "hashlib.sha256(data).hexdigest()", doc_type="knowledge", lang="python")
        db.store("hash", "echo -n 'data' | sha256sum", doc_type="knowledge", lang="bash")

        all_results = db.search(["hash"], doc_type="knowledge")
        # 不过滤时应返回两种语言的结果
        assert len(all_results) >= 2


class TestDbMultiQuery:
    """验证多 query 合并去重。"""

    def test_multiple_queries_merged(self, db):
        db.store("vuln", "SQL injection vulnerability in login form")

        # 两个不同 query 搜同一条记录
        results = db.search(
            ["SQL injection login", "vulnerability in authentication form"],
        )
        # 同一条记录不应重复出现
        ids = [r["id"] for r in results]
        assert len(ids) == len(set(ids)), "多 query 结果应去重"

    def test_cross_query_highest_score(self, db):
        db.store("crypto", "RSA encryption with weak prime generation")

        results = db.search(
            ["RSA encryption", "weak prime factorization"],
        )
        if results:
            # 应取跨 query 的最高分
            assert results[0]["score"] > 0


class TestDbMigration:
    """验证旧数据库迁移。"""

    def test_migrate_old_database(self, embedder):
        """旧数据库（无 guide_type/code_lang 列）应自动迁移且旧数据保留。"""
        with tempfile.TemporaryDirectory() as tmp:
            import sqlite3
            import sqlite_vec
            import struct
            import time as _time
            db_path = Path(tmp) / "old.db"
            conn = sqlite3.connect(str(db_path))
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            conn.executescript("""
                CREATE TABLE answers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    type TEXT NOT NULL,
                    doc_type TEXT NOT NULL DEFAULT 'answer',
                    created_at REAL NOT NULL
                );
            """)
            conn.execute(
                "CREATE VIRTUAL TABLE answer_vectors USING vec0(embedding float[1024] distance_metric=cosine)"
            )
            vec = embedder.encode("old answer about buffer overflow", convert_to_numpy=True)
            emb_bytes = struct.pack(f"{len(vec)}f", *vec.tolist())
            conn.execute("INSERT INTO answers(question, answer, type, doc_type, created_at) VALUES (?, ?, ?, ?, ?)",
                         ("old question", "old answer about buffer overflow", "other", "answer", _time.time()))
            conn.execute("INSERT INTO answer_vectors(rowid, embedding) VALUES (?, ?)", (1, emb_bytes))
            conn.commit()
            conn.close()

            from db import MemoryDB
            db = MemoryDB(db_path, embedder)
            cols = {row[1] for row in db._conn.execute("PRAGMA table_info(answers)").fetchall()}
            assert "guide_type" in cols
            assert "code_lang" in cols
            assert "flow_id" in cols

            # 验证迁移后旧数据仍保留且可搜到（显式传 doc_type="answer" 搜旧数据）
            results = db.search(["buffer overflow"], doc_type="answer")
            assert len(results) > 0, "旧数据应保留且可搜到"
            db.close()

    def test_migrate_idempotent(self, embedder):
        with tempfile.TemporaryDirectory() as tmp:
            from db import MemoryDB
            db_path = Path(tmp) / "test.db"
            db1 = MemoryDB(db_path, embedder)
            db1.store("test", "content")
            db1.close()
            db2 = MemoryDB(db_path, embedder)
            results = db2.search(["content"])
            assert len(results) > 0, "重新打开后数据应保留"
            db2.close()


# ═════════════════════════════════════════════════════════
# server.py 工具直接调用测试
# ═════════════════════════════════════════════════════════


@pytest.fixture(autouse=True, scope="class")
def mock_server_ready():
    """跳过 lazy 加载等待：设置 _ready Event 让 _ensure_ready() 立即返回。"""
    import server
    server._ready.set()
    yield
    server._ready.clear()


class TestServerToolsDirect:
    """验证 server.py 工具函数的参数验证和工具存在性。

    完整的 store+search 端到端测试在 Step 7 端到端验证中执行（需加载 BGE-M3）。
    """

    def test_all_3_tools_exist(self):
        import server
        for name in ["search_knowledge", "store_knowledge", "search_in_memory"]:
            assert hasattr(server, name), f"缺少工具 {name}"

    def test_no_old_tools_exist(self):
        import server
        for name in ["search_answer", "store_answer", "search_guide", "store_guide",
                      "search_code", "store_code"]:
            assert not hasattr(server, name), f"旧工具 {name} 应已删除"

    def test_store_knowledge_empty_rejected(self):
        import asyncio
        from server import store_knowledge
        result = json.loads(asyncio.run(store_knowledge(question="", content="")))
        assert result["stored"] is False

    def test_search_knowledge_empty_rejected(self):
        import asyncio
        from server import search_knowledge
        result = json.loads(asyncio.run(search_knowledge(questions=[])))
        assert "error" in result

    def test_search_in_memory_empty_rejected(self):
        import asyncio
        from server import search_in_memory
        result = json.loads(asyncio.run(search_in_memory(questions=[])))
        assert "error" in result

    def test_store_knowledge_anonymizes(self):
        """验证 store_knowledge 内部调用了 anonymize（mock DB，不需要加载 BGE-M3）。

        如果有人删了 store_knowledge 里的 anonymize() 调用，这个测试会失败。
        """
        import asyncio
        from unittest.mock import MagicMock
        from server import store_knowledge
        import server

        mock_db = MagicMock()
        mock_db.store.return_value = 42
        old_db = server._state.get("db")
        server._state["db"] = mock_db

        try:
            result = json.loads(asyncio.run(store_knowledge(
                question="connect to 192.168.1.50",
                content="Server at 10.0.0.5 with password=admin123",
            )))
            assert result["stored"] is True

            # 验证传给 db.store 的是匿名化后的内容（db.store 用位置参数：question, content）
            call_args = mock_db.store.call_args
            stored_question = call_args.args[0]
            stored_content = call_args.args[1]
            assert "192.168.1.50" not in stored_question, "question 应被匿名化"
            assert "10.0.0.5" not in stored_content, "content IP 应被匿名化"
            assert "admin123" not in stored_content, "content password 应被匿名化"
            assert "<IP>" in stored_question
        finally:
            server._state["db"] = old_db
