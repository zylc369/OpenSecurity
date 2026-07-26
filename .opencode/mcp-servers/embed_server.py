"""本地模型 HTTP 服务。

加载 BGE-M3（嵌入）和 BGE-Reranker（重排序），通过 HTTP 对外提供推理服务。
所有 MCP 进程通过 embed_client.py 调用本服务，避免重复加载模型（4×1GB → 1×1GB）。

启动：python embed_server.py（由 TS Plugin spawn）
端口：动态分配（9776 起，冲突则递增），写入 $DATA_DIR/.embed_server_port

并发模型：starlette ASGI + asyncio.to_thread
  - encode/predict 是 CPU-bound 同步调用，用 to_thread 交给线程池
  - 不阻塞 event loop，多个 MCP 进程可并发请求
"""
import asyncio
import os
import socket
from pathlib import Path

# 避免 SentenceTransformer 加载时向 HuggingFace 发 HEAD 请求（网络不通会卡 120s+）
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import threading

import numpy as np
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

EMBED_MODEL = "BAAI/bge-m3"
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"

# DATA_DIR 由 TS Plugin spawn 时传入环境变量
DATA_DIR = os.environ.get("DATA_DIR", str(Path.home() / "bw-security-analysis"))

# 懒加载模型（线程安全 double-check）
_embedder = None
_reranker = None
_embed_lock = threading.Lock()
_rerank_lock = threading.Lock()

# 模型就绪状态：embedder 加载完成后置 True，/health 据此返回 200
# 注意：embedder 一定先于 reranker 被请求（向量搜索是基础操作），
# 所以 _models_ready 只追踪 embedder 状态即可
_models_ready = False


def bind_available_port(start: int = 9776, max_tries: int = 30):
    """绑定并返回 socket（不关闭），调用方负责 detach 或 close。"""
    for port in range(start, start + max_tries):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            return sock, port
        except OSError:
            sock.close()
    raise RuntimeError(f"无可用端口（尝试了 {start}-{start + max_tries - 1}）")


def get_embedder():
    """延迟加载 BGE-M3（线程安全）。"""
    global _embedder, _models_ready
    if _embedder is None:
        with _embed_lock:
            if _embedder is None:
                from sentence_transformers import SentenceTransformer

                print(f"[embed-server] loading {EMBED_MODEL}...", flush=True)
                _embedder = SentenceTransformer(EMBED_MODEL)
                _models_ready = True
                print(f"[embed-server] {EMBED_MODEL} ready", flush=True)
    return _embedder


def get_reranker():
    """延迟加载 BGE-Reranker（线程安全）。"""
    global _reranker
    if _reranker is None:
        with _rerank_lock:
            if _reranker is None:
                from sentence_transformers import CrossEncoder

                print(f"[embed-server] loading {RERANKER_MODEL}...", flush=True)
                _reranker = CrossEncoder(RERANKER_MODEL, max_length=512)
                print(f"[embed-server] {RERANKER_MODEL} ready", flush=True)
    return _reranker


# ── 同步推理函数（在线程池中执行）──────────────────────────


def _do_embed(inputs: list[str]) -> list[list[float]]:
    """BGE-M3 推理：输入文本列表，返回向量列表（每个 1024 维）。"""
    model = get_embedder()
    vecs = model.encode(inputs, convert_to_numpy=True)
    return [v.tolist() for v in vecs]


def _do_rerank(query: str, texts: list[str]) -> list[float]:
    """BGE-Reranker 推理：输入 query + 候选文本列表，返回 score 列表。"""
    model = get_reranker()
    pairs = [(query, t) for t in texts]
    scores = model.predict(pairs)
    return [float(s) for s in np.asarray(scores)]


# ── ASGI 路由处理（async，推理交线程池）────────────────────


async def embed(request: Request):
    """POST /embed — 向量化文本。

    请求体: {"inputs": "text"} 或 {"inputs": ["text1", "text2"]}
    响应体: [[0.1, 0.2, ...], ...]  (1024 维向量的列表)
    """
    data = await request.json()
    inputs = data.get("inputs") or data.get("input")
    if not inputs:
        return JSONResponse({"error": "missing 'inputs'"}, status_code=400)
    if isinstance(inputs, str):
        inputs = [inputs]
    result = await asyncio.to_thread(_do_embed, inputs)
    return JSONResponse(result)


async def rerank(request: Request):
    """POST /rerank — 重排序候选文本。

    请求体: {"query": "查询文本", "texts": ["候选1", "候选2"]}
    响应体: [0.9, 0.1]  (与 texts 等长的 score 列表，越高越相关)
    """
    data = await request.json()
    query = data.get("query")
    texts = data.get("texts")
    if not query or not texts:
        return JSONResponse({"error": "missing 'query' or 'texts'"}, status_code=400)
    result = await asyncio.to_thread(_do_rerank, query, texts)
    return JSONResponse(result)


async def health(request: Request):
    """GET /health — 健康检查。模型加载中返回 503，就绪返回 200。"""
    if not _models_ready:
        return JSONResponse(
            {"status": "loading"},
            status_code=503,
            headers={"Retry-After": "5"},
        )
    return JSONResponse({"status": "ok"})


app = Starlette(
    routes=[
        Route("/embed", embed, methods=["POST"]),
        Route("/rerank", rerank, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
    ]
)


if __name__ == "__main__":
    # 1. 预绑定 socket（消除端口竞争窗口）
    sock, PORT = bind_available_port()

    # 2. 写端口文件（socket 还开着，端口被占着）
    port_file = Path(DATA_DIR) / ".embed_server_port"
    port_file.parent.mkdir(parents=True, exist_ok=True)
    port_file.write_text(f"{PORT}\n{os.getpid()}")
    print(f"[embed-server] 端口 {PORT} 已写入 {port_file}", flush=True)

    # 3. 预加载 embedder（同步阻塞，加载完后 /health 才能返回 200）
    # 必须在 uvicorn.run 之前加载——否则 /health 返回 503 但没人调 /embed 来触发加载，
    # 导致 pollEmbedServerHealth 永远等不到 200（启动死锁）。
    get_embedder()

    # 4. detach socket fd，交给 uvicorn
    fd = sock.detach()
    uvicorn.run(app, fd=fd, log_level="warning")
