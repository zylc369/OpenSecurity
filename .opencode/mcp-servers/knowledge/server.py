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
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

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
    description="从向量库检索已有答案。必须首先调用，避免重复研究。返回最多 5 条语义相似的答案，按 type 过滤。",
)
async def search_answer(
    questions: Annotated[list[str], Field(description="1-5 个中文语义查询问句。")],
    type: Annotated[Literal["guide", "vulnerability", "code", "tool", "other"], Field(description="硬过滤。guide=操作指南, vulnerability=漏洞分析, code=代码相关, tool=工具用法, other=其他")] = "other",
    message: Annotated[str, Field(description="操作日志，1-2 句中文描述你正在做什么")] = "",
) -> str:
    """从向量库检索已有答案，按 type 过滤。"""
    await _ensure_ready()
    if type not in VALID_ANSWER_TYPES:
        return json.dumps({"error": f"invalid type '{type}'", "results": [], "count": 0})
    if not questions:
        return json.dumps({"error": "questions must be non-empty", "results": [], "count": 0})
    results = _state["db"].search(questions, type=type, doc_type="answer", top_k=DEFAULT_TOP_K)
    return json.dumps({"results": results, "count": len(results)})


@mcp.tool(
    description="存储新的(问题, 答案)到向量库供未来检索。仅在发现知识库中不存在的新知识时调用。存储前自动匿名化。",
)
async def store_answer(
    question: Annotated[str, Field(description='关联问句。用"未来谁会查这条知识、他会怎么问"的角度表述（中文）。例：发现栈溢出后，question 写 "Windows x64 栈溢出漏洞的利用方法"')],
    answer: Annotated[str, Field(description="答案正文（中文叙述）。英文技术标识符原样保留（CVE 编号、函数名、payload、shell 命令、URL）。存储前自动匿名化。")],
    type: Annotated[Literal["guide", "vulnerability", "code", "tool", "other"], Field(description="guide=操作指南, vulnerability=漏洞分析, code=代码相关, tool=工具用法, other=其他")] = "other",
    message: Annotated[str, Field(description="操作日志，1-2 句中文描述你正在做什么")] = "",
) -> str:
    """存储新的(问题, 答案)。存储前自动匿名化。"""
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
    description="从向量库搜索操作指南。需要操作指引时使用（区别于 search_answer 的知识）。返回最多 5 条。",
)
async def search_guide(
    questions: Annotated[list[str], Field(description="1-5 个中文语义查询问句。")],
    type: Annotated[Literal["install", "configure", "use", "pentest", "development", "other"], Field(description="必填硬过滤。install=安装步骤, configure=配置方法, use=使用方法, pentest=渗透测试方法, development=开发指南, other=其他")],
    message: Annotated[str, Field(description="操作日志，1-2 句中文描述你正在做什么")] = "",
) -> str:
    """按 guide_type 过滤搜索操作指南。"""
    await _ensure_ready()
    if type not in VALID_GUIDE_TYPES:
        return json.dumps({"error": f"invalid guide type '{type}'", "results": [], "count": 0})
    if not questions:
        return json.dumps({"error": "questions must be non-empty", "results": [], "count": 0})
    results = _state["db"].search(questions, type=None, doc_type="guide", guide_type=type, top_k=DEFAULT_TOP_K)
    return json.dumps({"results": results, "count": len(results)})


@mcp.tool(
    description="存储操作指南到向量库供未来检索。存储前自动匿名化（IP、域名、凭证）。",
)
async def store_guide(
    guide: Annotated[str, Field(description="指南正文，markdown 格式。操作步骤或配置方法。")],
    question: Annotated[str, Field(description='关联问句。用"未来谁会查这条指南"的角度表述（中文）。')],
    type: Annotated[Literal["install", "configure", "use", "pentest", "development", "other"], Field(description="install=安装步骤, configure=配置方法, use=使用方法, pentest=渗透测试方法, development=开发指南, other=其他")],
    message: Annotated[str, Field(description="操作日志，1-2 句中文描述你正在做什么")] = "",
) -> str:
    """存储操作指南。存储前自动匿名化。"""
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
    description="从向量库搜索代码片段，按编程语言过滤。返回最多 5 条语义相似的代码。",
)
async def search_code(
    questions: Annotated[list[str], Field(description="1-5 个中文语义查询问句。")],
    lang: Annotated[str, Field(description="编程语言（python、bash、golang 等）。")],
    message: Annotated[str, Field(description="操作日志，1-2 句中文描述你正在做什么")] = "",
) -> str:
    """按编程语言过滤搜索代码片段。"""
    await _ensure_ready()
    if not questions:
        return json.dumps({"error": "questions must be non-empty", "results": [], "count": 0})
    if not lang.strip():
        return json.dumps({"error": "lang must be non-empty", "results": [], "count": 0})
    results = _state["db"].search(questions, type=None, doc_type="code", code_lang=lang, top_k=DEFAULT_TOP_K)
    return json.dumps({"results": results, "count": len(results)})


@mcp.tool(
    description="存储代码片段到向量库供未来检索。存储前自动匿名化（IP、域名、凭证、API key）。",
)
async def store_code(
    code: Annotated[str, Field(description="源代码。")],
    question: Annotated[str, Field(description='关联问句。用"未来谁会查这段代码"的角度表述（中文）。')],
    lang: Annotated[str, Field(description="编程语言（python、bash、golang 等）。")],
    explanation: Annotated[str, Field(description="代码的详细说明。")],
    description: Annotated[str, Field(description="代码的简短摘要。")],
    message: Annotated[str, Field(description="操作日志，1-2 句中文描述你正在做什么")] = "",
) -> str:
    """存储代码片段。存储前自动匿名化。"""
    await _ensure_ready()
    if not code.strip() or not question.strip():
        return json.dumps({"stored": False, "error": "code and question must be non-empty"})
    safe_code = anonymize(code)
    safe_q = anonymize(question)
    safe_explanation = anonymize(explanation)
    content = f"{safe_code}\n\n{safe_explanation}"
    row_id = _state["db"].store(safe_q, content, "code", doc_type="code", code_lang=lang)
    return json.dumps({"stored": True, "id": row_id})


# ── memory 工具 ──────────────────────────────────────────


@mcp.tool(
    description="从向量库检索执行记忆（doc_type=memory）。用于回顾当前任务中执行过哪些工具、得到了什么结果。按 flow_id 隔离，只返回当前任务的记录。",
)
async def search_in_memory(
    questions: Annotated[list[str], Field(description="1-5 个中文语义查询问句，关于之前的工具执行和结果。")],
    flow_id: Annotated[str | None, Field(description="当前任务的 Flow ID，从 $OPENSECURITY_FLOW_ID 获取。memory 按此隔离，只返回当前任务的记录。")] = None,
    message: Annotated[str, Field(description="操作日志，1-2 句中文描述你正在做什么")] = "",
) -> str:
    """检索执行记忆（doc_type=memory），按 flow_id 隔离。"""
    await _ensure_ready()
    if not questions:
        return json.dumps({"error": "questions must be non-empty", "results": [], "count": 0})
    results = _state["db"].search(
        questions, type=None, doc_type="memory", top_k=DEFAULT_TOP_K,
        flow_id=flow_id,
    )
    return json.dumps({"results": results, "count": len(results)})


if __name__ == "__main__":
    mcp.run()
