"""OpenSecurity searcher/memorist agent 的知识库 MCP server。

提供七个工具（对齐 PentAGI）：
  - search_answer / store_answer：答案知识库（doc_type=answer）
  - search_guide / store_guide：指南知识库（doc_type=guide）
  - search_code / store_code：代码片段库（doc_type=code）
  - search_in_memory：执行记忆库（doc_type=memory）

store 工具在存储前调 anonymize() 清洗敏感信息（IP/凭证/域名）。
embed 目标是 content（answer/guide/code 文本），不是 question。

嵌入模型（BAAI/bge-m3，1024 维，多语言）在启动时加载一次。
"""
import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from sentence_transformers import SentenceTransformer

sys.path.insert(0, str(Path(__file__).parent))
from anonymizer import anonymize  # noqa: E402
from db import MemoryDB, DEFAULT_TOP_K  # noqa: E402

DATA_DIR = Path.home() / "bw-security-analysis"
DB_PATH = DATA_DIR / "db" / "knowledge" / "knowledge.db"
MODEL_NAME = "BAAI/bge-m3"

VALID_ANSWER_TYPES = ("guide", "vulnerability", "code", "tool", "other")
VALID_GUIDE_TYPES = ("install", "configure", "use", "pentest", "development", "other")

print(f"[knowledge-mcp] loading embedder {MODEL_NAME}...", file=sys.stderr)
_embedder = SentenceTransformer(MODEL_NAME)
_db = MemoryDB(DB_PATH, _embedder)
print(f"[knowledge-mcp] ready, db={DB_PATH}", file=sys.stderr)

mcp = FastMCP("knowledge")


# ── answer 工具 ──────────────────────────────────────────


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
        message: Engagement log entry in the engagement language.

    Returns:
        JSON string: {"results": [{id, question, answer, type, score}], "count": N}
    """
    if type not in VALID_ANSWER_TYPES:
        return json.dumps({"error": f"invalid type '{type}'", "results": [], "count": 0})
    if not questions:
        return json.dumps({"error": "questions must be non-empty", "results": [], "count": 0})
    results = _db.search(questions, type=type, doc_type="answer", top_k=DEFAULT_TOP_K)
    return json.dumps({"results": results, "count": len(results)})


@mcp.tool(
    description=(
        "Persist a new (question, answer) pair to the vector store for future "
        "retrieval. ONLY call when you discovered information not already in "
        "the knowledge base. Anonymizes sensitive data before storage."
    ),
)
def store_answer(
    question: str,
    answer: str,
    type: str = "other",
    message: str = "",
) -> str:
    """Persist a new (question, answer) pair. Anonymizes before storage."""
    if type not in VALID_ANSWER_TYPES:
        return json.dumps({"stored": False, "error": f"invalid type '{type}'"})
    if not question.strip() or not answer.strip():
        return json.dumps({"stored": False, "error": "question and answer must be non-empty"})
    safe_q = anonymize(question)
    safe_a = anonymize(answer)
    row_id = _db.store(safe_q, safe_a, type, doc_type="answer")
    return json.dumps({"stored": True, "id": row_id})


# ── guide 工具 ───────────────────────────────────────────


@mcp.tool(
    description=(
        "Search guides in the vector store by type. Use when you need "
        "step-by-step procedures (install/configure/use/pentest/development). "
        "Returns up to 5 semantically similar guides."
    ),
)
def search_guide(
    questions: list[str],
    type: str,
    message: str = "",
) -> str:
    """Search guides filtered by guide_type.

    Args:
        questions: 1-5 English semantic queries.
        type: Required filter - one of: install, configure, use, pentest, development, other.
    """
    if type not in VALID_GUIDE_TYPES:
        return json.dumps({"error": f"invalid guide type '{type}'", "results": [], "count": 0})
    if not questions:
        return json.dumps({"error": "questions must be non-empty", "results": [], "count": 0})
    results = _db.search(questions, type=None, doc_type="guide", guide_type=type, top_k=DEFAULT_TOP_K)
    return json.dumps({"results": results, "count": len(results)})


@mcp.tool(
    description=(
        "Store a guide to the vector store for future retrieval. "
        "Anonymizes sensitive data (IPs, domains, credentials) before storage."
    ),
)
def store_guide(
    guide: str,
    question: str,
    type: str,
    message: str = "",
) -> str:
    """Store a guide. Anonymizes before storage.

    Args:
        guide: Guide text in markdown format.
        question: Question that led to this guide (co-indexed).
        type: install, configure, use, pentest, development, or other.
    """
    if type not in VALID_GUIDE_TYPES:
        return json.dumps({"stored": False, "error": f"invalid guide type '{type}'"})
    if not guide.strip() or not question.strip():
        return json.dumps({"stored": False, "error": "guide and question must be non-empty"})
    safe_guide = anonymize(guide)
    safe_q = anonymize(question)
    row_id = _db.store(safe_q, safe_guide, type, doc_type="guide", guide_type=type)
    return json.dumps({"stored": True, "id": row_id})


# ── code 工具 ────────────────────────────────────────────


@mcp.tool(
    description=(
        "Search code samples in the vector store by programming language. "
        "Returns up to 5 semantically similar code samples."
    ),
)
def search_code(
    questions: list[str],
    lang: str,
    message: str = "",
) -> str:
    """Search code samples filtered by language.

    Args:
        questions: 1-5 English semantic queries.
        lang: Programming language (python, bash, golang, etc.).
    """
    if not questions:
        return json.dumps({"error": "questions must be non-empty", "results": [], "count": 0})
    if not lang.strip():
        return json.dumps({"error": "lang must be non-empty", "results": [], "count": 0})
    results = _db.search(questions, type=None, doc_type="code", code_lang=lang, top_k=DEFAULT_TOP_K)
    return json.dumps({"results": results, "count": len(results)})


@mcp.tool(
    description=(
        "Store a code sample to the vector store for future retrieval. "
        "Anonymizes sensitive data (IPs, domains, credentials, API keys) before storage."
    ),
)
def store_code(
    code: str,
    question: str,
    lang: str,
    explanation: str,
    description: str,
    message: str = "",
) -> str:
    """Store a code sample. Anonymizes before storage.

    Args:
        code: Raw source code.
        question: Question that led to this code (co-indexed).
        lang: Programming language (python, bash, golang, etc.).
        explanation: Detailed explanation of the code.
        description: Short summary of the code.
    """
    if not code.strip() or not question.strip():
        return json.dumps({"stored": False, "error": "code and question must be non-empty"})
    safe_code = anonymize(code)
    safe_q = anonymize(question)
    safe_explanation = anonymize(explanation)
    # 将 code + explanation 拼接作为 content（对齐 PentAGI embed content 的逻辑）
    content = f"{safe_code}\n\n{safe_explanation}"
    row_id = _db.store(safe_q, content, "code", doc_type="code", code_lang=lang)
    return json.dumps({"stored": True, "id": row_id})


# ── memory 工具 ──────────────────────────────────────────


@mcp.tool(
    description=(
        "Retrieve prior execution memory from the vector store (doc_type=memory). "
        "Use this to recall what tools were run, what results were obtained, and "
        "what the team has previously done on related topics."
    ),
)
def search_in_memory(
    questions: list[str],
    message: str = "",
) -> str:
    """Retrieve execution memory (doc_type=memory)."""
    if not questions:
        return json.dumps({"error": "questions must be non-empty", "results": [], "count": 0})
    results = _db.search(questions, type=None, doc_type="memory", top_k=DEFAULT_TOP_K)
    return json.dumps({"results": results, "count": len(results)})


if __name__ == "__main__":
    mcp.run()
