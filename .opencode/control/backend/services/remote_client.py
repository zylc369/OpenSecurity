"""远程控制台推理客户端（模型远程化; P2P 传输扩展 P13）。

职责: 主控侧对远程节点（如 Mac Mini 上运行的同款控制台）的推理类
API 调用——embed / rerank / ocr / 健康探测 / 节点配置转发。

传输: 默认 HTTP（httpx 直连 base_url）; 传入 p2p 配置 dict 时启用
P2P 传输（remote_transport——直连 UDP 优先/中继兜底，见 protocol.md §7），
所有 _post/_get/_put 与健康探测自动切换，对外接口与失败语义不变。

调用域: 同步（调用点均在 worker 线程 / to_thread 池线程）;
async 消费方经 asyncio.to_thread 包装。

失败语义: 连接失败 / 超时 / 401 / 5xx / 响应畸形统一抛 RemoteUnavailable
（路由层捕获后 fallback 本地——调用方不需要区分失败原因的种类）。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:  # 仅类型检查（零运行时依赖——transport 延迟构建）
    from services.remote_transport import RemoteTransport, TransportConfig

import httpx

logger = logging.getLogger(__name__)


class RemoteUnavailable(RuntimeError):
    """远程节点不可用（连接/超时/鉴权/服务端错误/响应畸形统一面）。"""


class _RemoteHealthJson(TypedDict, total=False):
    """远程 /api/remote/health 响应（解析边界模型）。"""
    service: str
    version: str
    models: "list[dict[str, object]]"


@dataclass(frozen=True)
class ModelFingerprint:
    """单模型版本指纹（repo + 显示名 + snapshot hash + 加载态）。"""

    repo_id: str
    display: str = ""
    snapshot: str = ""
    loaded: bool = False


@dataclass(frozen=True)
class RemoteHealthInfo:
    """远程节点健康快照（心跳探测结果）。"""

    service: str
    version: str
    models: list[ModelFingerprint] = field(default_factory=list)
    latency_ms: float = 0.0
    code_fingerprint: str = ""


class RemoteConsoleClient:
    """远程控制台客户端（HTTP 直连 / P2P 传输双模式; 线程安全）。

    p2p 参数: TransportConfig 强类型对象（remote_link 构造注入——不再传 dict，
    字段可 review/可静态检查; 依赖方向: client → transport → crypto）。
    """

    def __init__(self, base_url: str, token: str = "",
                 infer_timeout: float = 30.0, probe_timeout: float = 3.0,
                 p2p: "TransportConfig | None" = None) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._infer_timeout = infer_timeout
        self._probe_timeout = probe_timeout
        self._http = httpx.Client(timeout=infer_timeout)
        self._p2p_cfg = p2p
        self._transport: "RemoteTransport | None" = None  # 延迟构建

    # ─── 内部 ─────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _post_json(self, path: str, payload: "dict[str, object]", timeout: float | None = None):
        """POST 并解析 JSON; 任何失败统一 RemoteUnavailable。"""
        if self._p2p_cfg is not None:
            return self._p2p_call("POST", path, payload, timeout)
        url = f"{self._base}{path}"
        try:
            r = self._http.post(url, json=payload, headers=self._headers(),
                                timeout=timeout or self._infer_timeout)
        except httpx.HTTPError as e:
            raise RemoteUnavailable(f"连接远程失败: {e}") from e
        return self._parse(r, url)

    def _get_json(self, path: str, timeout: float | None = None):
        if self._p2p_cfg is not None:
            return self._p2p_call("GET", path, None)
        url = f"{self._base}{path}"
        try:
            r = self._http.get(url, headers=self._headers(),
                               timeout=timeout or self._infer_timeout)
        except httpx.HTTPError as e:
            raise RemoteUnavailable(f"连接远程失败: {e}") from e
        return self._parse(r, url)

    def _put_json(self, path: str, payload: "dict[str, object]", timeout: float | None = None):
        """PUT 并解析 JSON; 任何失败统一 RemoteUnavailable。"""
        if self._p2p_cfg is not None:
            return self._p2p_call("PUT", path, payload)
        url = f"{self._base}{path}"
        try:
            r = self._http.put(url, json=payload, headers=self._headers(),
                               timeout=timeout or self._infer_timeout)
        except httpx.HTTPError as e:
            raise RemoteUnavailable(f"连接远程失败: {e}") from e
        return self._parse(r, url)

    # ─── P2P 传输分支（protocol.md §4.3 api.req 语义）────

    def _get_transport(self) -> "RemoteTransport":
        """延迟启动 RemoteTransport（首次 P2P 调用时）。"""
        if self._transport is None:
            from services.remote_transport import RemoteTransport
            cfg = self._p2p_cfg
            if cfg is None or not cfg.psk or not cfg.relay_host or not cfg.node_id:
                raise RemoteUnavailable("P2P 配置不完整（relay_host/node_id/psk）")
            transport = RemoteTransport(cfg)
            transport.start()
            self._transport = transport
        return self._transport

    # ─── 传输路径可见性（远程资源卡数据源）─────────────

    def transport_path(self) -> str:
        """当前 P2P 传输路径（direct/relay/""——transport 未建时空）。"""
        transport = self._transport
        if transport is None:
            return ""
        return transport.current_path or ""

    def direct_last_error(self) -> str:
        """最近一次直连尝试失败原因（空 = 无失败/非 P2P/未启动）。"""
        transport = self._transport
        if transport is None:
            return ""
        return transport.direct_last_error

    def _p2p_call(self, method: str, path: str,
                  payload: "dict[str, object] | None",
                  timeout: float | None = None) -> "dict[str, object]":
        """经 transport 的 api.req 调用; 失败语义与 _parse 对齐。

        返回与 _parse 同模式: cast 收口为 dict（embed 等 list 响应的形状
        校验由调用方的 isinstance 兜底——运行时 cast 无约束）。
        """
        from services.remote_transport import TransportError
        transport = self._get_transport()
        try:
            resp = transport.request(method, path, payload, self._token, timeout=timeout)
        except TransportError as e:
            raise RemoteUnavailable(f"远程 P2P 调用失败: {e}") from e
        if resp.status == 401:
            raise RemoteUnavailable(f"远程拒绝令牌（401）: {path}")
        if resp.status >= 500:
            raise RemoteUnavailable(f"远程服务端错误（{resp.status}）: {path}")
        if resp.status >= 400:
            raise RemoteUnavailable(
                f"远程客户端错误（{resp.status}）: {str(resp.body)[:200]}")
        return cast("dict[str, object]", resp.body)

    @staticmethod
    def _parse(r: httpx.Response, url: str) -> "dict[str, object]":
        if r.status_code == 401:
            raise RemoteUnavailable(f"远程拒绝令牌（401）: {url}")
        if r.status_code >= 500:
            raise RemoteUnavailable(f"远程服务端错误（{r.status_code}）: {url}")
        if r.status_code >= 400:
            raise RemoteUnavailable(f"远程客户端错误（{r.status_code}）: {r.text[:200]}")
        try:
            return cast("dict[str, object]", r.json())  # httpx json() 边界——cast 收口
        except ValueError as e:
            raise RemoteUnavailable(f"远程响应非 JSON: {url}: {e}") from e

    # ─── 推理 API ─────────────────────────────────────────

    def embed(self, texts: list[str]) -> list[list[float]]:
        """向量化（POST /embed，兼容 sentence-transformers 调用约定）。"""
        data = cast("list[list[float]]", self._post_json("/embed", {"inputs": texts}))  # 运行时恒等; 形状由下方 isinstance 守卫验证
        if not isinstance(data, list) or (data and not isinstance(data[0], list)):
            raise RemoteUnavailable(f"远程 /embed 响应畸形: {str(data)[:120]}")
        return data

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        """重排序（POST /rerank）。"""
        data = cast("list[float]", self._post_json("/rerank", {"query": query, "texts": texts}))  # 同上
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

    # TTS 请求级超时: 节点首请求含自愈装依赖（幂等 ~20s）+ worker 冷启
    # (~10s) + 长文合成——推理默认超时不够，单独放宽
    TTS_TIMEOUT_SEC = 600.0

    def tts_synth(self, text: str, voice: str, speed: float,
                  instruct: str = "", seed: int = -1, mode: str = "",
                  no_cache: bool = False) -> bytes:
        """语音合成（POST /api/tts——WAV 二进制响应，不经 _post_json 的
        JSON 假设; gateway 对非 JSON 响应以原始 bytes 装入 ApiResp.body）。
        no_cache: 预热专用——节点侧跳过缓存读写（强制真合成）。"""
        payload: dict[str, object] = {"text": text, "voice": voice, "speed": speed,
                                      "instruct": instruct, "seed": seed, "mode": mode,
                                      "no_cache": no_cache}
        if self._p2p_cfg is not None:
            from services.remote_transport import TransportError
            transport = self._get_transport()
            try:
                resp = transport.request("POST", "/api/tts", payload, self._token,
                                         timeout=self.TTS_TIMEOUT_SEC)
            except TransportError as e:
                raise RemoteUnavailable(f"远程 P2P 调用失败: {e}") from e
            if resp.status != 200:
                raise RemoteUnavailable(
                    f"远程 /api/tts {resp.status}: {str(resp.body)[:400]}")
            if not isinstance(resp.body, (bytes, bytearray)):
                raise RemoteUnavailable("远程 /api/tts 响应非二进制（非 WAV）")
            return bytes(resp.body)
        url = f"{self._base}/api/tts"
        try:
            r = self._http.post(url, json=payload, headers=self._headers(),
                                timeout=max(self._infer_timeout, self.TTS_TIMEOUT_SEC))
        except httpx.HTTPError as e:
            raise RemoteUnavailable(f"连接远程失败: {e}") from e
        if r.status_code != 200:
            raise RemoteUnavailable(
                f"远程 /api/tts {r.status_code}: {r.text[:120]}")
        return r.content

    # ─── 健康探测 ─────────────────────────────────────────

    def probe_health(self) -> RemoteHealthInfo:
        """轻量健康探测（GET /api/remote/health，短超时）。

        供心跳周期调用——延迟纳入返回值（前端健康度展示）。
        P2P 模式: 先经 transport ping（快速失败），再走 api.resp。
        """
        t0 = time.monotonic()
        raw = self._get_json("/api/remote/health", timeout=self._probe_timeout)
        if not isinstance(raw, dict):
            raise RemoteUnavailable(
                f"远程 /api/remote/health 响应畸形: {str(raw)[:120]}")
        data = cast("_RemoteHealthJson", raw)
        latency = round((time.monotonic() - t0) * 1000, 1)
        models = [
            ModelFingerprint(
                repo_id=str(m.get("repo_id", "")),
                display=str(m.get("display", "")),
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
            code_fingerprint=str(data.get("code_fingerprint", "")),
        )

    # ─── 节点管理转发（主控代理调远程节点，routes/remote.py 用）───

    def get_node_config(self) -> "dict[str, str]":
        """读取远程节点的三项节点配置。"""
        return cast("dict[str, str]", self._get_json("/api/remote/node-config"))

    def put_node_config(self, updates: dict[str, str]) -> "dict[str, object]":
        """更新远程节点配置（PUT /api/remote/node-config，仅三 KEY）。

        载荷契约: {"configs": {...}}（NodeConfigUpdate pydantic 模型）。
        """
        return cast("dict[str, object]", self._put_json("/api/remote/node-config", {"configs": updates}))

    def get_autostart(self) -> "dict[str, object]":
        return cast("dict[str, object]", self._get_json("/api/remote/autostart"))

    def post_autostart(self, enable: bool) -> "dict[str, object]":
        return cast("dict[str, object]", self._post_json("/api/remote/autostart", {"enable": enable}))

    # ─── 生命周期 ─────────────────────────────────────────

    def close(self) -> None:
        self._http.close()
        if self._transport is not None:
            try:
                self._transport.stop()
            except Exception:  # noqa: BLE001 —— 关闭异常不阻断
                pass
            self._transport = None

