"""嵌入/重排序 HTTP 客户端。

duck-type 兼容 SentenceTransformer.encode() 和 CrossEncoder.predict()。
消费方（graphiti_config.py、reranker.py、knowledge/server.py）代码零改动。

embed_server 是硬依赖——不可用时直接抛异常，不降级到本地加载。
"""
import os
import time
from pathlib import Path

import httpx
import numpy as np

EMBED_MODEL = "BAAI/bge-m3"


def _read_port() -> int:
    """读取 embed_server 端口。优先级：环境变量 > 端口文件 > 默认 9776。"""
    # 1. 环境变量（由 TS Plugin shell.env hook 注入 bash 环境，或后续 spawn 的子进程继承）
    port = os.environ.get("EMBED_SERVER_PORT")
    if port:
        return int(port)
    # 2. 端口文件（首次请求时读，最多等 5 秒）
    data_dir = os.environ.get("DATA_DIR", str(Path.home() / "bw-security-analysis"))
    port_file = Path(data_dir) / ".embed_server_port"
    for _ in range(5):
        if port_file.exists():
            try:
                return int(port_file.read_text().strip().split("\n")[0])
            except (ValueError, IndexError):
                pass
        time.sleep(1)
    # 3. 默认值（最后手段）
    return 9776


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
        """延迟构建 base_url，首次访问时读端口。"""
        if self._base_url is None:
            port = _read_port()
            self._base_url = f"http://127.0.0.1:{port}"
        return self._base_url

    def _try_http(self, endpoint, payload):
        """发送 HTTP 请求。失败返回 None，由 encode/predict 层抛异常。"""
        client = self._client_first if self._first_request else self._client_normal
        try:
            resp = client.post(f"{self.base_url}{endpoint}", json=payload)
            resp.raise_for_status()
            self._first_request = False
            return resp.json()
        except Exception as e:
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
            raise RuntimeError("embed_server /embed 请求失败")
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
            raise RuntimeError("embed_server /rerank 请求失败")
        return np.array(data)
