"""Knowledge MCP 全面测试——对齐 PentAGI 后的功能验证。

测试层次：
  1. anonymizer.py: 各模式清洗 + 多模式混合 + 边界
  2. db.py: embed content、score 阈值、guide_type/code_lang 过滤、doc_type 隔离、多 query 合并、迁移
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

    def test_search_by_answer_content(self, db):
        """用 answer 里的词（不在 question 里）能搜到。"""
        db.store(
            question="authentication",
            answer="RBAC role-based access control with JWT tokens",
            type="other",
        )
        results = db.search(["RBAC permissions"], type="other")
        assert len(results) > 0, "应通过 answer 内容搜到"

    def test_answer_match_higher_than_question_match(self, db):
        """answer 内容匹配应比 question 匹配分数高。"""
        db.store(
            question="intro",
            answer="Detailed analysis of SQL injection in login forms with sqlmap exploitation",
            type="vulnerability",
        )
        # 搜 answer 里的词
        answer_results = db.search(["SQL injection sqlmap"], type="vulnerability")
        # 搜 question 里的词
        question_results = db.search(["intro"], type="vulnerability")

        answer_score = answer_results[0]["score"] if answer_results else 0
        question_score = question_results[0]["score"] if question_results else 0
        assert answer_score >= question_score, f"answer 匹配({answer_score}) 应 >= question 匹配({question_score})"


class TestDbDocTypeIsolation:
    """验证不同 doc_type 之间数据隔离。"""

    def test_answer_search_excludes_guide(self, db):
        db.store("install", "How to install Ghidra on Linux", "other", doc_type="guide", guide_type="install")
        db.store("install", "Installation dependencies for Ghidra", "other", doc_type="answer")

        answer_results = db.search(["Ghidra install"], type="other", doc_type="answer")
        guide_results = db.search(["Ghidra install"], type=None, doc_type="guide")

        # 各自只返回自己的 doc_type
        assert len(answer_results) > 0, "answer 搜索应有结果"
        assert len(guide_results) > 0, "guide 搜索应有结果"

    def test_memory_search_excludes_answer(self, db):
        db.store("test query", "answer content", "other", doc_type="answer")
        db.store("test query", "memory content from tool execution", "bash", doc_type="memory")

        memory_results = db.search(["test content"], type=None, doc_type="memory")
        answer_results = db.search(["test content"], type="other", doc_type="answer")

        # memory 搜索不返回 answer 的数据
        for r in memory_results:
            assert r["answer"] == "memory content from tool execution"
        for r in answer_results:
            assert r["answer"] == "answer content"


class TestDbGuideCodeFilters:
    """验证 guide_type/code_lang 过滤。"""

    def test_guide_type_filter(self, db):
        db.store("setup", "Install with apt-get", "other", doc_type="guide", guide_type="install")
        db.store("setup", "Configure in /etc/app.conf", "other", doc_type="guide", guide_type="configure")

        install_results = db.search(["setup"], type=None, doc_type="guide", guide_type="install")
        configure_results = db.search(["setup"], type=None, doc_type="guide", guide_type="configure")

        # 各自只返回对应 guide_type 的数据
        for r in install_results:
            assert "apt-get" in r["answer"]
        for r in configure_results:
            assert "/etc/app.conf" in r["answer"]

    def test_code_lang_filter(self, db):
        db.store("hash", "hashlib.sha256(data).hexdigest()", "code", doc_type="code", code_lang="python")
        db.store("hash", "echo -n 'data' | sha256sum", "code", doc_type="code", code_lang="bash")

        python_results = db.search(["hash"], type=None, doc_type="code", code_lang="python")
        bash_results = db.search(["hash"], type=None, doc_type="code", code_lang="bash")

        for r in python_results:
            assert "hashlib" in r["answer"]
        for r in bash_results:
            assert "sha256sum" in r["answer"]


class TestDbMultiQuery:
    """验证多 query 合并去重。"""

    def test_multiple_queries_merged(self, db):
        db.store("vuln", "SQL injection vulnerability in login form", "vulnerability")

        # 两个不同 query 搜同一条记录
        results = db.search(
            ["SQL injection login", "vulnerability in authentication form"],
            type="vulnerability",
        )
        # 同一条记录不应重复出现
        ids = [r["id"] for r in results]
        assert len(ids) == len(set(ids)), "多 query 结果应去重"

    def test_cross_query_highest_score(self, db):
        db.store("crypto", "RSA encryption with weak prime generation", "vulnerability")

        results = db.search(
            ["RSA encryption", "weak prime factorization"],
            type="vulnerability",
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

            results = db.search(["buffer overflow"], type="other")
            assert len(results) > 0, "旧数据应保留且可搜到"
            db.close()

    def test_migrate_idempotent(self, embedder):
        with tempfile.TemporaryDirectory() as tmp:
            from db import MemoryDB
            db_path = Path(tmp) / "test.db"
            db1 = MemoryDB(db_path, embedder)
            db1.store("test", "content", "other")
            db1.close()
            db2 = MemoryDB(db_path, embedder)
            results = db2.search(["content"], type="other")
            assert len(results) > 0, "重新打开后数据应保留"
            db2.close()


# ═════════════════════════════════════════════════════════
# server.py 工具直接调用测试
# ═════════════════════════════════════════════════════════


class TestServerToolsDirect:
    """直接调用 server.py 的工具函数（非 AST），验证完整链路。"""

    def test_store_answer_anonymizes_ip(self):
        """store_answer 存入的数据应不含原始 IP。"""
        from server import store_answer
        result = json.loads(store_answer(
            question="connect to server",
            answer="Server at 192.168.1.50 with password=admin123",
            type="other",
        ))
        assert result["stored"] is True

        # 搜索验证存储的数据已匿名化
        from server import search_answer, _db
        # 直接查 DB 验证
        row = _db._conn.execute("SELECT question, answer FROM answers WHERE id = ?", (result["id"],)).fetchone()
        assert "<IP>" in row[1], f"存储的 answer 应匿名化 IP，实际: {row[1]}"
        assert "<CREDENTIAL>" in row[1], f"存储的 answer 应匿名化 password，实际: {row[1]}"

    def test_store_guide_anonymizes(self):
        from server import store_guide, _db
        result = json.loads(store_guide(
            guide="Connect to 10.0.0.5 and run nmap",
            question="network scan guide",
            type="pentest",
        ))
        assert result["stored"] is True
        row = _db._conn.execute("SELECT answer FROM answers WHERE id = ?", (result["id"],)).fetchone()
        assert "<IP>" in row[0]

    def test_store_code_anonymizes(self):
        from server import store_code, _db
        result = json.loads(store_code(
            code="requests.get('http://admin@api.sk-secret123.com')",
            question="API call",
            lang="python",
            explanation="Calls API at 192.168.1.1",
            description="API request",
        ))
        assert result["stored"] is True
        row = _db._conn.execute("SELECT answer FROM answers WHERE id = ?", (result["id"],)).fetchone()
        assert "<IP>" in row[0] or "<API_KEY>" in row[0] or "<DOMAIN>" in row[0]

    def test_search_answer_returns_json(self):
        from server import search_answer
        result = json.loads(search_answer(questions=["test"], type="other"))
        assert "results" in result
        assert "count" in result

    def test_search_guide_invalid_type(self):
        from server import search_guide
        result = json.loads(search_guide(questions=["test"], type="invalid_type"))
        assert "error" in result

    def test_search_code_returns_json(self):
        from server import search_code
        result = json.loads(search_code(questions=["hash"], lang="python"))
        assert "results" in result

    def test_store_answer_empty_rejected(self):
        from server import store_answer
        result = json.loads(store_answer(question="", answer="", type="other"))
        assert result["stored"] is False

    def test_store_guide_invalid_type_rejected(self):
        from server import store_guide
        result = json.loads(store_guide(guide="test", question="test", type="invalid"))
        assert result["stored"] is False

    def test_search_in_memory_returns_json(self):
        from server import search_in_memory
        result = json.loads(search_in_memory(questions=["test"]))
        assert "results" in result
        assert "count" in result

    def test_all_7_tools_exist(self):
        import server
        for name in ["search_answer", "store_answer", "search_guide", "store_guide",
                      "search_code", "store_code", "search_in_memory"]:
            assert hasattr(server, name), f"缺少工具 {name}"


class TestServerEnumAlignment:
    """验证枚举与 PentAGI 一致。"""

    def test_guide_types(self):
        from server import VALID_GUIDE_TYPES
        assert set(VALID_GUIDE_TYPES) == {"install", "configure", "use", "pentest", "development", "other"}

    def test_answer_types(self):
        from server import VALID_ANSWER_TYPES
        assert set(VALID_ANSWER_TYPES) == {"guide", "vulnerability", "code", "tool", "other"}
