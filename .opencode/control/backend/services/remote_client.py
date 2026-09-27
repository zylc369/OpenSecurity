"""远程控制台推理客户端（模型远程化一期）。

职责: 主控侧对远程节点（如 Mac Mini 上运行的同款控制台）的推理类
API 调用——embed / rerank / ocr / 健康探测 / 节点配置转发。

调用域: 同步 httpx（调用点均在 worker 线程 / to_thread 池线程）;
async 消费方经 asyncio.to_thread 包装。

失败语义: 连接失败 / 超时 / 401 / 5xx / 响应畸形统一抛 RemoteUnavailable
（路由层捕获后 fallback 本地——调用方不需要区分失败原因的种类）。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)


class RemoteUnavailable(RuntimeError):
    """远程节点不可用（连接/超时/鉴权/服务端错误/响应畸形统一面）。"""


@dataclass(frozen=True)
class ModelFingerprint:
    """单模型版本指纹（repo + HF snapshot hash + 加载态）。"""

    repo_id: str
    snapshot: str
    loaded: bool


@dataclass(frozen=True)
class RemoteHealthInfo:
    """远程节点健康快照（心跳探测结果）。"""

    service: str
    version: str
    models: list[ModelFingerprint] = field(default_factory=list)
    latency_ms: float = 0.0


class RemoteConsoleClient:
    """远程控制台 HTTP 客户端（线程安全: httpx.Client 连接池可并发）。"""

    def __init__(self, base_url: str, token: str = "",
                 infer_timeout: float = 30.0, probe_timeout: float = 3.0) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._infer_timeout = infer_timeout
        self._probe_timeout = probe_timeout
        self._http = httpx.Client(timeout=infer_timeout)

    # ─── 内部 ─────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _post_json(self, path: str, payload: dict, timeout: float | None = None):
        """POST 并解析 JSON; 任何失败统一 RemoteUnavailable。"""
        url = f"{self._base}{path}"
        try:
            r = self._http.post(url, json=payload, headers=self._headers(),
                                timeout=timeout or self._infer_timeout)
        except httpx.HTTPError as e:
            raise RemoteUnavailable(f"连接远程失败: {e}") from e
        return self._parse(r, url)

    def _get_json(self, path: str, timeout: float | None = None):
        url = f"{self._base}{path}"
        try:
            r = self._http.get(url, headers=self._headers(),
                               timeout=timeout or self._infer_timeout)
        except httpx.HTTPError as e:
            raise RemoteUnavailable(f"连接远程失败: {e}") from e
        return self._parse(r, url)

    def _put_json(self, path: str, payload: dict, timeout: float | None = None):
        """PUT 并解析 JSON; 任何失败统一 RemoteUnavailable。"""
        url = f"{self._base}{path}"
        try:
            r = self._http.put(url, json=payload, headers=self._headers(),
                               timeout=timeout or self._infer_timeout)
        except httpx.HTTPError as e:
            raise RemoteUnavailable(f"连接远程失败: {e}") from e
        return self._parse(r, url)

    @staticmethod
    def _parse(r: httpx.Response, url: str) -> dict:
        if r.status_code == 401:
            raise RemoteUnavailable(f"远程拒绝令牌（401）: {url}")
        if r.status_code >= 500:
            raise RemoteUnavailable(f"远程服务端错误（{r.status_code}）: {url}")
        if r.status_code >= 400:
            raise RemoteUnavailable(f"远程客户端错误（{r.status_code}）: {r.text[:200]}")
        try:
            return r.json()
        except ValueError as e:
            raise RemoteUnavailable(f"远程响应非 JSON: {url}: {e}") from e

    # ─── 推理 API ─────────────────────────────────────────

    def embed(self, texts: list[str]) -> list[list[float]]:
        """向量化（POST /embed，兼容 sentence-transformers 调用约定）。"""
        data = self._post_json("/embed", {"inputs": texts})
        if not isinstance(data, list) or (data and not isinstance(data[0], list)):
            raise RemoteUnavailable(f"远程 /embed 响应畸形: {str(data)[:120]}")
        return data

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        """重排序（POST /rerank）。"""
        data = self._post_json("/rerank", {"query": query, "texts": texts})
        if not isinstance(data, list):
            raise RemoteUnavailable(f"远程 /rerank 响应畸形: {str(data)[:120]}")
        return data

    def ocr_extract(self, image_b64: str, prompt: str) -> str:
        """识图（POST /api/ocr/extract）。"""
        data = self._post_json("/api/ocr/extract", {"image_b64": image_b64, "prompt": prompt})
        text = data.get("text") if isinstance(data, dict) else None
        if not isinstance(text, str):
            raise RemoteUnavailable(f"远程 /api/ocr/extract 响应畸形: {str(data)[:120]}")
        return text

    # ─── 健康探测 ─────────────────────────────────────────

    def probe_health(self) -> RemoteHealthInfo:
        """轻量健康探测（GET /api/remote/health，短超时）。

        供心跳周期调用——延迟纳入返回值（前端健康度展示）。
        """
        t0 = time.monotonic()
        data = self._get_json("/api/remote/health", timeout=self._probe_timeout)
        latency = round((time.monotonic() - t0) * 1000, 1)
        models = [
            ModelFingerprint(
                repo_id=str(m.get("repo_id", "")),
                snapshot=str(m.get("snapshot", "")),
                loaded=bool(m.get("loaded", False)),
            )
            for m in data.get("models", []) if isinstance(m, dict)
        ]
        return RemoteHealthInfo(
            service=str(data.get("service", "")),
            version=str(data.get("version", "")),
            models=models,
            latency_ms=latency,
        )

    # ─── 节点管理转发（主控代理调远程节点，routes/remote.py 用）───

    def get_node_config(self) -> dict:
        """读取远程节点的三项节点配置。"""
        return self._get_json("/api/remote/node-config")

    def put_node_config(self, updates: dict[str, str]) -> dict:
        """更新远程节点配置（PUT /api/remote/node-config，仅三 KEY）。

        载荷契约: {"configs": {...}}（NodeConfigUpdate pydantic 模型）。
        """
        return self._put_json("/api/remote/node-config", {"configs": updates})

    def get_autostart(self) -> dict:
        return self._get_json("/api/remote/autostart")

    def post_autostart(self, enable: bool) -> dict:
        return self._post_json("/api/remote/autostart", {"enable": enable})

    # ─── 生命周期 ─────────────────────────────────────────

    def close(self) -> None:
        self._http.close()
