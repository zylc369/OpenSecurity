"""OpenSecurity searcher/memorist agent 的知识库 MCP server。

提供七个工具（对齐 PentAGI）：
  - search_answer / store_answer：答案知识库（doc_type=answer）
  - search_guide / store_guide：指南知识库（doc_type=guide）
  - search_code / store_code：代码片段库（doc_type=code）
  - search_in_memory：执行记忆库（doc_type=memory）

store 工具在存储前调 anonymize() 清洗敏感信息（IP/凭证/域名）。
embed 目标是 content（answer/guide/code 文本），不是 question。

启动模式（lazy 加载）：
  - 模块顶层不加载 BGE-M3，stdio 握手快（<1s）
  - lifespan startup 内 run_in_executor 后台加载模型（fire-and-forget）
  - 工具函数调用前 await _ensure_ready()：模型已就绪立即返回；未就绪则等待
"""
import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).parent))
from anonymizer import anonymize  # noqa: E402
from db import MemoryDB, DEFAULT_TOP_K  # noqa: E402

DATA_DIR = Path.home() / "bw-security-analysis"
DB_PATH = DATA_DIR / "db" / "knowledge" / "knowledge.db"
MODEL_NAME = "BAAI/bge-m3"

VALID_ANSWER_TYPES = ("guide", "vulnerability", "code", "tool", "other")
VALID_GUIDE_TYPES = ("install", "configure", "use", "pentest", "development", "other")

# ── lazy 加载共享状态 ─────────────────────────────────────
_state: dict = {"embedder": None, "db": None}
_ready = asyncio.Event()
_init_error: list[Exception] = []
_loop: asyncio.AbstractEventLoop | None = None
_load_future = None  # 保存 run_in_executor 返回的 Future，避免 GC


def _load_blocking() -> None:
    """子线程同步加载模型 + 初始化 DB。完成后通过 call_soon_threadsafe 唤醒 Event。

    任何异常存入 _init_error 列表，工具调用时检查并抛出（不 hang）。
    """
    try:
        print(f"[knowledge-mcp] loading embedder {MODEL_NAME}...", file=sys.stderr)
        from sentence_transformers import SentenceTransformer
        embedder = SentenceTransformer(MODEL_NAME)
        db = MemoryDB(DB_PATH, embedder)
        _state["embedder"] = embedder
        _state["db"] = db
        print(f"[knowledge-mcp] ready, db={DB_PATH}", file=sys.stderr)
    except Exception as e:
        _init_error.append(e)
        print(f"[knowledge-mcp] 加载失败: {e}", file=sys.stderr)
    finally:
        # Event 是主 loop 的对象，子线程必须用 call_soon_threadsafe 唤醒
        if _loop is not None:
            _loop.call_soon_threadsafe(_ready.set)


@asynccontextmanager
async def lifespan(app):
    """FastMCP lifespan：startup 内启动后台加载任务，立即 yield 让 stdio 握手快速完成。

    lifespan 在 stdio initialize 请求处理之前进入（vendor lowlevel/server.py:663）。
    yield 不等待模型加载，握手 → tools/list → plugin.setup 都不阻塞。
    """
    global _loop, _load_future
    _loop = asyncio.get_running_loop()
    _load_future = _loop.run_in_executor(None, _load_blocking)  # fire-and-forget
    yield


async def _ensure_ready() -> None:
    """工具函数开头调用：等待模型加载完成。加载失败则抛 RuntimeError。"""
    await _ready.wait()
    if _init_error:
        raise RuntimeError(f"BGE-M3 加载失败: {_init_error[0]}")


mcp = FastMCP("knowledge", lifespan=lifespan)


# ── answer 工具 ──────────────────────────────────────────


@mcp.tool(
    description=(
        "Retrieve prior answers from the vector store. ALWAYS call this FIRST "
        "before external searches to avoid re-researching known facts. "
        "Returns up to 5 semantically similar stored answers, filtered by type."
    ),
)
async def search_answer(
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
    await _ensure_ready()
    if type not in VALID_ANSWER_TYPES:
        return json.dumps({"error": f"invalid type '{type}'", "results": [], "count": 0})
    if not questions:
        return json.dumps({"error": "questions must be non-empty", "results": [], "count": 0})
    results = _state["db"].search(questions, type=type, doc_type="answer", top_k=DEFAULT_TOP_K)
    return json.dumps({"results": results, "count": len(results)})


@mcp.tool(
    description=(
        "Persist a new (question, answer) pair to the vector store for future "
        "retrieval. ONLY call when you discovered information not already in "
        "the knowledge base. Anonymizes sensitive data before storage."
    ),
)
async def store_answer(
    question: str,
    answer: str,
    type: str = "other",
    message: str = "",
) -> str:
    """Persist a new (question, answer) pair. Anonymizes before storage."""
    await _ensure_ready()
    if type not in VALID_ANSWER_TYPES:
        return json.dumps({"stored": False, "error": f"invalid type '{type}'"})
    if not question.strip() or not answer.strip():
        return json.dumps({"stored": False, "error": "question and answer must be non-empty"})
    safe_q = anonymize(question)
    safe_a = anonymize(answer)
    row_id = _state["db"].store(safe_q, safe_a, type, doc_type="answer")
    return json.dumps({"stored": True, "id": row_id})


# ── guide 工具 ───────────────────────────────────────────


@mcp.tool(
    description=(
        "Search guides in the vector store by type. Use when you need "
        "step-by-step procedures (install/configure/use/pentest/development). "
        "Returns up to 5 semantically similar guides."
    ),
)
async def search_guide(
    questions: list[str],
    type: str,
    message: str = "",
) -> str:
    """Search guides filtered by guide_type.

    Args:
        questions: 1-5 English semantic queries.
        type: Required filter - one of: install, configure, use, pentest, development, other.
    """
    await _ensure_ready()
    if type not in VALID_GUIDE_TYPES:
        return json.dumps({"error": f"invalid guide type '{type}'", "results": [], "count": 0})
    if not questions:
        return json.dumps({"error": "questions must be non-empty", "results": [], "count": 0})
    results = _state["db"].search(questions, type=None, doc_type="guide", guide_type=type, top_k=DEFAULT_TOP_K)
    return json.dumps({"results": results, "count": len(results)})


@mcp.tool(
    description=(
        "Store a guide to the vector store for future retrieval. "
        "Anonymizes sensitive data (IPs, domains, credentials) before storage."
    ),
)
async def store_guide(
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
    await _ensure_ready()
    if type not in VALID_GUIDE_TYPES:
        return json.dumps({"stored": False, "error": f"invalid guide type '{type}'"})
    if not guide.strip() or not question.strip():
        return json.dumps({"stored": False, "error": "guide and question must be non-empty"})
    safe_guide = anonymize(guide)
    safe_q = anonymize(question)
    row_id = _state["db"].store(safe_q, safe_guide, type, doc_type="guide", guide_type=type)
    return json.dumps({"stored": True, "id": row_id})


# ── code 工具 ────────────────────────────────────────────


@mcp.tool(
    description=(
        "Search code samples in the vector store by programming language. "
        "Returns up to 5 semantically similar code samples."
    ),
)
async def search_code(
    questions: list[str],
    lang: str,
    message: str = "",
) -> str:
    """Search code samples filtered by language.

    Args:
        questions: 1-5 English semantic queries.
        lang: Programming language (python, bash, golang, etc.).
    """
    await _ensure_ready()
    if not questions:
        return json.dumps({"error": "questions must be non-empty", "results": [], "count": 0})
    if not lang.strip():
        return json.dumps({"error": "lang must be non-empty", "results": [], "count": 0})
    results = _state["db"].search(questions, type=None, doc_type="code", code_lang=lang, top_k=DEFAULT_TOP_K)
    return json.dumps({"results": results, "count": len(results)})


@mcp.tool(
    description=(
        "Store a code sample to the vector store for future retrieval. "
        "Anonymizes sensitive data (IPs, domains, credentials, API keys) before storage."
    ),
)
async def store_code(
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
    await _ensure_ready()
    if not code.strip() or not question.strip():
        return json.dumps({"stored": False, "error": "code and question must be non-empty"})
    safe_code = anonymize(code)
    safe_q = anonymize(question)
    safe_explanation = anonymize(explanation)
    # 将 code + explanation 拼接作为 content（对齐 PentAGI embed content 的逻辑）
    content = f"{safe_code}\n\n{safe_explanation}"
    row_id = _state["db"].store(safe_q, content, "code", doc_type="code", code_lang=lang)
    return json.dumps({"stored": True, "id": row_id})


# ── memory 工具 ──────────────────────────────────────────


@mcp.tool(
    description=(
        "Retrieve prior execution memory from the vector store (doc_type=memory). "
        "Use this to recall what tools were run, what results were obtained, and "
        "what the team has previously done on related topics."
    ),
)
async def search_in_memory(
    questions: list[str],
    message: str = "",
) -> str:
    """Retrieve execution memory (doc_type=memory)."""
    await _ensure_ready()
    if not questions:
        return json.dumps({"error": "questions must be non-empty", "results": [], "count": 0})
    results = _state["db"].search(questions, type=None, doc_type="memory", top_k=DEFAULT_TOP_K)
    return json.dumps({"results": results, "count": len(results)})


if __name__ == "__main__":
    mcp.run()
