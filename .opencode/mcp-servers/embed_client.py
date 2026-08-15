"""嵌入/重排序 HTTP 客户端。

duck-type 兼容 SentenceTransformer.encode() 和 CrossEncoder.predict()。
消费方（graphiti_config.py、reranker.py、knowledge/server.py）代码零改动。

端口发现收口到 control_url.py（读端口文件，事实来源）。
控制台不可用时直接抛异常，不降级到本地加载。

控制台重启换端口的自愈机制：
  请求失败 → 清掉 base_url 缓存 → 下次请求重新走 control_url.resolve_control()
  （端口文件已被新控制台覆写，拿到新端口自动恢复，opencode 无需重启）
"""
import httpx
import numpy as np

from control_url import resolve_control

EMBED_MODEL = "BAAI/bge-m3"


class HttpEmbedClient:
    """适配 SentenceTransformer.encode() + CrossEncoder.predict() 的 HTTP 客户端。

    首次请求用 60s 超时（可能触发模型加载），后续请求用 10s 超时（推理 <1s）。
    """

    def __init__(self, model_name=EMBED_MODEL):
        self._base_url = None
        self._model_name = model_name
        self._first_request = True
        self._client_first = httpx.Client(timeout=60.0)
        self._client_normal = httpx.Client(timeout=10.0)

    @property
    def base_url(self) -> str:
        """延迟构建 base_url；失败清缓存后可重新解析（换端口自愈）。"""
        if self._base_url is None:
            addr = resolve_control()
            if addr is None:
                raise RuntimeError("控制台地址未知（无环境变量、端口文件不存在）")
            self._base_url = addr.url
        return self._base_url

    def _try_http(self, endpoint, payload):
        """发送 HTTP 请求。失败返回 None 并清 base_url 缓存（供下次重解析）。"""
        # 先在 try 外解析 base_url——端口未知时直接抛"端口未知"，
        # 不进入下面的 except 被吞成误导性的"请求失败"。
        base = self.base_url
        client = self._client_first if self._first_request else self._client_normal
        try:
            resp = client.post(f"{base}{endpoint}", json=payload)
            resp.raise_for_status()
            self._first_request = False
            return resp.json()
        except Exception:
            # 清缓存：下次请求重新解析端口。
            # 覆盖控制台重启换端口场景（旧地址连不上 → 端口文件已是新端口）。
            self._base_url = None
            return None

    def encode(self, inputs, convert_to_numpy=True, **kwargs):
        """适配 SentenceTransformer.encode()。

        签名兼容：接受 str 或 list[str]，返回 np.ndarray。
        - 输入 str → 返回 1D (dim,)（与 SentenceTransformer 一致）
        - 输入 list[str] → 返回 2D (N, dim)
        **kwargs 吃掉 convert_to_numpy、batch_size 等参数（HTTP 不需要）。
        """
        is_single = isinstance(inputs, str)
        if is_single:
            inputs = [inputs]
        data = self._try_http("/embed", {"inputs": inputs})
        if data is None:
            raise RuntimeError("控制台 /embed 请求失败")
        arr = np.array(data)
        return arr[0] if is_single else arr

    def predict(self, pairs, **kwargs):
        """适配 CrossEncoder.predict()。

        签名兼容：接受 list[(query, passage)]，返回 np.ndarray。
        **kwargs 吃掉 batch_size、activation_fn 等参数。
        """
        if not pairs:
            return np.array([])
        query = pairs[0][0]
        texts = [p[1] for p in pairs]
        data = self._try_http("/rerank", {"query": query, "texts": texts})
        if data is None:
            raise RuntimeError("控制台 /rerank 请求失败")
        return np.array(data)
