"""OpenSecurity 知识库 MCP server（薄壳，不驻模型/DB）。

三个工具经 HTTP 代理到控制台（对齐 ocr/server.py 薄壳模式）：
  - search_knowledge / store_knowledge：知识库（doc_type=knowledge）
  - search_in_memory：执行记忆库（doc_type=memory）

业务实现在控制台 services/knowledge_store.py（单 MemoryDB 实例）。
端口发现：control_url.py（读端口文件，事实来源）；控制台重启换端口自动自愈。
"""
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import Field

sys.path.insert(0, str(Path(__file__).parent.parent))  # control_url 同级
from control_url import resolve_control, make_control_client

_CONTROL: dict = {"base": None}
_client: httpx.AsyncClient | None = None


def _base_url() -> str:
    """控制台地址（延迟解析 + 失败自愈：换端口后下次重新解析）。"""
    if _CONTROL["base"] is None:
        addr = resolve_control()
        if addr is None:
            raise RuntimeError("控制台未启动（IPC 地址不可达）")
        _CONTROL["base"] = addr.url
    return _CONTROL["base"]


@asynccontextmanager
async def _lifespan(server: FastMCP):
    """只建 HTTP 客户端（无模型/DB 生命周期，全在控制台）。"""
    global _client
    _client = make_control_client(timeout=120.0)
    try:
        yield
    finally:
        await _client.aclose()
        _client = None


async def _post(path: str, payload: dict) -> str:
    """POST 控制台并返回工具结果 JSON 字符串；失败返回与原降级一致的错误结构。"""
    if _client is None:
        return json.dumps({"error": "MCP 未完成初始化（lifespan 未启动）", "results": [], "count": 0})
    try:
        r = await _client.post(f"{_base_url()}{path}", json=payload)
        _CONTROL["base"] = None if r.status_code in (404, 502) else _CONTROL["base"]
        if r.status_code == 200:
            return json.dumps(r.json(), ensure_ascii=False)
        return json.dumps({"error": f"控制台返回 {r.status_code}: {r.text[:200]}", "results": [], "count": 0})
    except httpx.HTTPError as e:
        _CONTROL["base"] = None  # 清缓存 → 下次重新解析端口（控制台重启自愈）
        return json.dumps({"error": f"控制台不可达: {e}", "results": [], "count": 0})


mcp = FastMCP("knowledge", lifespan=_lifespan)


@mcp.tool(
    description="从向量库检索已有知识。必须首先调用，避免重复研究。返回最多 5 条语义相似的结果。可选按编程语言过滤代码。",
)
async def search_knowledge(
    questions: Annotated[list[str], Field(description="1-5 个中文语义查询问句。")],
    lang: Annotated[str, Field(description="可选：按编程语言过滤（如 python、bash）。不传则搜全部。")] = "",
    message: Annotated[str, Field(description="操作日志，1-2 句中文描述你正在做什么")] = "",
) -> str:
    """从向量库检索知识。可选按 lang 过滤。"""
    return await _post("/api/knowledge/search", {"questions": questions, "lang": lang})


@mcp.tool(
    description="存储新知识到向量库供未来检索。仅在发现知识库中不存在的新知识时调用。存储前自动匿名化。",
)
async def store_knowledge(
    question: Annotated[str, Field(description='关联问句。用"未来谁会查这条知识、他会怎么问"的角度表述（中文）。例：发现栈溢出后，question 写 "Windows x64 栈溢出漏洞的利用方法"')],
    content: Annotated[str, Field(description="知识正文（中文叙述）。英文技术标识符原样保留（CVE 编号、函数名、payload、shell 命令、URL）。代码片段需附带文字说明。存储前自动匿名化。")],
    lang: Annotated[str, Field(description="可选：内容主要语言的编程语言标记（如 python、bash）。纯文字知识不传。")] = "",
    message: Annotated[str, Field(description="操作日志，1-2 句中文描述你正在做什么")] = "",
) -> str:
    """存储新知识。存储前自动匿名化。"""
    return await _post("/api/knowledge/store", {"question": question, "content": content, "lang": lang})


@mcp.tool(
    description="从向量库检索执行记忆（doc_type=memory）。用于回顾当前任务中执行过哪些工具、得到了什么结果。按 flow_id 隔离，只返回当前任务的记录。",
)
async def search_in_memory(
    questions: Annotated[list[str], Field(description="1-5 个中文语义查询问句，关于之前的工具执行和结果。")],
    flow_id: Annotated[str | None, Field(description="当前任务的 Flow ID，从 $OPENSECURITY_FLOW_ID 获取。memory 按此隔离，只返回当前任务的记录。")] = None,
    message: Annotated[str, Field(description="操作日志，1-2 句中文描述你正在做什么")] = "",
) -> str:
    """检索执行记忆（doc_type=memory），按 flow_id 隔离。"""
    return await _post("/api/memory/search", {"questions": questions, "flow_id": flow_id})


if __name__ == "__main__":
    mcp.run()
