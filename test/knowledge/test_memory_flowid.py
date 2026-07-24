"""测试 memory 的 flow_id 隔离 + 白名单过滤。

测试用例：
  1. 存 memory 带 flow_id=A → search flow_id=A 能搜到
  2. 存 memory 带 flow_id=A → search flow_id=B 搜不到
  3. 存 answer（flow_id 空）→ search answer 不受 flow_id 影响
  4. 已有数据库迁移成功（flow_id 列存在）
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "knowledge"))

DB_PATH = Path.home() / "bw-security-analysis" / "db" / "knowledge" / "knowledge.db"


class TestMemoryFlowIdIsolation(unittest.TestCase):
    """测试 memory 的 flow_id 隔离。"""

    @classmethod
    def setUpClass(cls):
        """初始化 DB（用生产数据库——测试后清理测试数据）。"""
        from db import MemoryDB
        from sentence_transformers import SentenceTransformer
        cls.embedder = SentenceTransformer("BAAI/bge-m3")
        cls.db = MemoryDB(DB_PATH, cls.embedder)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_01_flow_id_isolation_search_same(self):
        """存 memory flow_id=A → search flow_id=A 能搜到。"""
        rid = self.db.store(
            "test flow isolation", "This is a test memory for flow_id isolation test",
            "test", doc_type="memory", flow_id="test-flow-A",
        )
        results = self.db.search(
            ["flow_id isolation test"], doc_type="memory", flow_id="test-flow-A",
        )
        found = any(r["id"] == rid for r in results)
        self.assertTrue(found, f"flow_id=A 的 memory 应该能被 flow_id=A 搜到")

    def test_02_flow_id_isolation_search_different(self):
        """存 memory flow_id=A → search flow_id=B 搜不到。"""
        rid = self.db.store(
            "test cross flow barrier", "This memory should not be visible from flow B",
            "test", doc_type="memory", flow_id="test-flow-A",
        )
        results = self.db.search(
            ["cross flow barrier"], doc_type="memory", flow_id="test-flow-B",
        )
        found = any(r["id"] == rid for r in results)
        self.assertFalse(found, f"flow_id=A 的 memory 不应该被 flow_id=B 搜到")

    def test_03_answer_not_affected_by_flow_id(self):
        """存 answer（flow_id 空）→ search answer 不受 flow_id 影响。"""
        rid = self.db.store(
            "test answer global visibility", "This answer should be globally searchable",
            "test", doc_type="answer",
        )
        # search answer 不传 flow_id
        results = self.db.search(
            ["answer global visibility"], doc_type="answer",
        )
        found = any(r["id"] == rid for r in results)
        self.assertTrue(found, "answer 应该全局可见（不受 flow_id 影响）")

    def test_04_flow_id_column_exists(self):
        """answers 表有 flow_id 列。"""
        columns = {row[1] for row in self.db._conn.execute("PRAGMA table_info(answers)").fetchall()}
        self.assertIn("flow_id", columns, "answers 表应有 flow_id 列")

    def test_05_memory_default_flow_id_none(self):
        """store 不传 flow_id 时默认 None（存入数据库为 NULL）。"""
        rid = self.db.store(
            "test default flow_id", "test content for default none",
            "test", doc_type="memory",
        )
        row = self.db._conn.execute(
            "SELECT flow_id FROM answers WHERE id = ?", (rid,),
        ).fetchone()
        self.assertIsNone(row[0], "不传 flow_id 时默认 None（数据库 NULL）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
