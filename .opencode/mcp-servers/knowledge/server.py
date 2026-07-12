"""OpenSecurity searcher/memorist agent 的知识库 MCP server。

提供三个工具：
  - search_answer：从答案知识库（doc_type=answer）检索 —— searcher 用
  - store_answer：持久化新答案到答案知识库（doc_type=answer）—— searcher 用
  - search_in_memory：从执行记忆库（doc_type=memory）检索 —— memorist 用

嵌入模型（BAAI/bge-m3，1024 维，多语言）在启动时加载一次（约 16 秒）。
"""
import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from sentence_transformers import SentenceTransformer

# 将本文件所在目录加入 sys.path，以便 opencode 从任意 cwd 启动时
# db.py 都能正常导入。
sys.path.insert(0, str(Path(__file__).parent))
from db import MemoryDB, DEFAULT_TOP_K  # noqa: E402

DATA_DIR = Path.home() / "bw-security-analysis"
DB_PATH = DATA_DIR / "knowledge.db"
MODEL_NAME = "BAAI/bge-m3"

VALID_TYPES = ("guide", "vulnerability", "code", "tool", "other")

# 模型与数据库在启动时加载一次，后续工具调用复用它们。
print(f"[knowledge-mcp] loading embedder {MODEL_NAME}...", file=sys.stderr)
_embedder = SentenceTransformer(MODEL_NAME)
_db = MemoryDB(DB_PATH, _embedder)
print(f"[knowledge-mcp] ready, db={DB_PATH}", file=sys.stderr)

mcp = FastMCP("knowledge")


@mcp.tool(
    description=(
        "Retrieve prior answers from the vector store. ALWAYS call this FIRST "
        "before external searches to avoid re-researching known facts. "
        "Returns up to 5 semantically similar stored answers, filtered by type."
    ),
)
def search_answer(
    questions: list[str],
    type: str = "other",
    message: str = "",
) -> str:
    """Retrieve prior answers from the vector store.

    Args:
        questions: 1-5 English semantic queries (each with context and intent).
        type: Hard filter - one of: guide, vulnerability, code, tool, other.
        message: Engagement log entry in the engagement language; narrates
            what you are about to do (1-2 short sentences).

    Returns:
        JSON string: {"results": [{id, question, answer, type, score}], "count": N}
        Empty results list if no matches.
    """
    if type not in VALID_TYPES:
        return json.dumps({
            "error": f"invalid type '{type}', must be one of {VALID_TYPES}",
            "results": [],
            "count": 0,
        })
    if not questions:
        return json.dumps({
            "error": "questions must be a non-empty list",
            "results": [],
            "count": 0,
        })
    results = _db.search(questions, type=type, doc_type="answer", top_k=DEFAULT_TOP_K)
    return json.dumps({"results": results, "count": len(results)})


@mcp.tool(
    description=(
        "Retrieve prior execution memory from the vector store (doc_type=memory). "
        "Use this to recall what tools were run, what results were obtained, and "
        "what the team has previously done on related topics. "
        "Returns up to 5 semantically similar stored memory records."
    ),
)
def search_in_memory(
    questions: list[str],
    message: str = "",
) -> str:
    """Retrieve prior execution memory from the vector store.

    Unlike search_answer (which queries curated Q&A pairs), this queries
    raw tool execution logs automatically stored during agent operations.

    Args:
        questions: 1-5 semantic queries (each with context and intent).
        message: Engagement log entry in the engagement language; narrates
            what you are about to do (1-2 short sentences).

    Returns:
        JSON string: {"results": [{id, question, answer, type, score}], "count": N}
        Empty results list if no matches.
    """
    if not questions:
        return json.dumps({
            "error": "questions must be a non-empty list",
            "results": [],
            "count": 0,
        })
    results = _db.search(questions, type=None, doc_type="memory", top_k=DEFAULT_TOP_K)
    return json.dumps({"results": results, "count": len(results)})


@mcp.tool(
    description=(
        "Persist a new (question, answer) pair to the vector store for future "
        "retrieval. ONLY call when you discovered information not already in "
        "the knowledge base. Indexes the question for semantic retrieval."
    ),
)
def store_answer(
    question: str,
    answer: str,
    type: str = "other",
    message: str = "",
) -> str:
    """Persist a new (question, answer) pair to the vector store.

    No deduplication: the LLM is expected to call search_answer first and
    decide whether the new info is "new knowledge" before storing.

    Args:
        question: English question (co-indexed with the answer for retrieval).
        answer: English markdown answer with full technical detail.
        type: guide, vulnerability, code, tool, or other.
        message: Engagement log entry in the engagement language.

    Returns:
        JSON string: {"stored": true, "id": <int>}
    """
    if type not in VALID_TYPES:
        return json.dumps({
            "stored": False,
            "error": f"invalid type '{type}', must be one of {VALID_TYPES}",
        })
    if not question.strip() or not answer.strip():
        return json.dumps({
            "stored": False,
            "error": "question and answer must be non-empty",
        })
    row_id = _db.store(question, answer, type, doc_type="answer")
    return json.dumps({"stored": True, "id": row_id})


if __name__ == "__main__":
    mcp.run()
