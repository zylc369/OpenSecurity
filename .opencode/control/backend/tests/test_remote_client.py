"""remote_client 单元测试（httpx.MockTransport，不发真网络请求）。

覆盖（需求文档 §3.1 步骤 7 验证点）:
  1. 正常 embed / rerank / ocr_extract / probe_health
  2. 连接失败 / 超时 / 401 / 5xx / 畸形响应 → RemoteUnavailable
  3. Bearer 头携带（有 token 时）

运行方式:
  cd .opencode/control/backend
  python tests/test_remote_client.py
"""
# pyright: reportMissingParameterType=false
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("OPENSECURITY_HOME", "/tmp/control_test_data")

from tests.test_control import test, assert_eq, assert_true  # noqa: E402


def _client_with(handler, token="secret-token-123"):
    """构造使用 MockTransport 的 RemoteConsoleClient。"""
    from services.remote_client import RemoteConsoleClient
    c = RemoteConsoleClient("http://remote.test:9999", token=token,
                            infer_timeout=2.0, probe_timeout=1.0)
    transport = httpx.MockTransport(handler)
    c._http = httpx.Client(transport=transport, timeout=2.0)  # noqa: SLF001
    return c


@test("remote_client: embed/rerank/ocr_extract 正常路径 + Bearer 头")
def test_normal_paths():
    seen_auth: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("Authorization"))
        if request.url.path == "/embed":
            return httpx.Response(200, json=[[0.1] * 1024, [0.2] * 1024])
        if request.url.path == "/rerank":
            return httpx.Response(200, json=[0.9, 0.1])
        if request.url.path == "/api/ocr/extract":
            return httpx.Response(200, json={"text": "识别结果"})
        return httpx.Response(404, json={})

    c = _client_with(handler)
    vecs = c.embed(["a", "b"])
    assert_eq((len(vecs), len(vecs[0])), (2, 1024), "embed 返回形状")
    scores = c.rerank("q", ["p1", "p2"])
    assert_eq(scores, [0.9, 0.1], "rerank 分数")
    text = c.ocr_extract("imgdata", "prompt")
    assert_eq(text, "识别结果", "ocr 文本")
    assert_eq(seen_auth, ["Bearer secret-token-123"] * 3, "每次请求都带 Bearer")
    c.close()


@test("remote_client: 无 token 时不发 Authorization 头")
def test_no_token_no_header():
    seen_auth: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("Authorization"))
        return httpx.Response(200, json=[[0.1] * 4])

    c = _client_with(handler, token="")
    c.embed(["a"])
    assert_eq(seen_auth, [None], "无 token 不带 Authorization")
    c.close()


@test("remote_client: 401 → RemoteUnavailable（令牌被拒）")
def test_401():
    from services.remote_client import RemoteUnavailable
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "bad token"})
    c = _client_with(handler)
    try:
        c.embed(["a"])
        raise AssertionError("401 应抛 RemoteUnavailable")
    except RemoteUnavailable as e:
        assert_true("401" in str(e), f"信息应含 401: {e}")
    c.close()


@test("remote_client: 5xx → RemoteUnavailable")
def test_5xx():
    from services.remote_client import RemoteUnavailable
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "loading"})
    c = _client_with(handler)
    try:
        c.embed(["a"])
        raise AssertionError("503 应抛 RemoteUnavailable")
    except RemoteUnavailable as e:
        assert_true("503" in str(e), f"信息应含 503: {e}")
    c.close()


@test("remote_client: 连接失败 → RemoteUnavailable")
def test_connect_error():
    from services.remote_client import RemoteUnavailable

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    c = _client_with(handler)
    try:
        c.embed(["a"])
        raise AssertionError("连接失败应抛 RemoteUnavailable")
    except RemoteUnavailable as e:
        assert_true("连接远程失败" in str(e), f"信息应含连接失败: {e}")
    c.close()


@test("remote_client: 畸形响应（非预期结构）→ RemoteUnavailable")
def test_malformed():
    from services.remote_client import RemoteUnavailable
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/embed":
            return httpx.Response(200, json={"unexpected": "dict"})
        if request.url.path == "/rerank":
            return httpx.Response(200, json="not-a-list")
        return httpx.Response(200, json={"no_text_field": 1})

    c = _client_with(handler)
    for call in (lambda: c.embed(["a"]), lambda: c.rerank("q", ["p"]),
                 lambda: c.ocr_extract("img", "")):
        try:
            call()
            raise AssertionError("畸形响应应抛 RemoteUnavailable")
        except RemoteUnavailable as e:
            assert_true("畸形" in str(e), f"信息应含畸形: {e}")
    c.close()


@test("remote_client: probe_health 解析指纹 + 延迟")
def test_probe_health():
    def handler(request: httpx.Request) -> httpx.Response:
        assert_eq(request.url.path, "/api/remote/health")
        return httpx.Response(200, json={
            "service": "opencode-control",
            "version": "test-1",
            "models": [
                {"repo_id": "BAAI/bge-m3", "snapshot": "abc123", "loaded": True},
                {"repo_id": "BAAI/bge-reranker-v2-m3", "snapshot": "def456", "loaded": False},
            ],
        })

    c = _client_with(handler)
    info = c.probe_health()
    assert_eq(info.service, "opencode-control")
    assert_eq(info.version, "test-1")
    assert_eq(len(info.models), 2)
    assert_eq(info.models[0].repo_id, "BAAI/bge-m3")
    assert_true(info.models[0].loaded, "embedder loaded=True")
    assert_true(info.models[1].snapshot == "def456", "reranker snapshot")
    assert_true(info.latency_ms >= 0, "延迟非负")
    c.close()


@test("remote_client: 节点管理转发方法")
def test_node_management():
    calls: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json
        body = _json.loads(request.content.decode()) if request.content else {}
        calls.append((request.method, request.url.path, body))
        if request.url.path == "/api/remote/node-config":
            if request.method == "GET":
                return httpx.Response(200, json={"CONTROL_RESIDENT": "1"})
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/api/remote/autostart":
            return httpx.Response(200, json={"installed": True})
        return httpx.Response(404)

    c = _client_with(handler)
    assert_eq(c.get_node_config(), {"CONTROL_RESIDENT": "1"})
    assert_eq(c.put_node_config({"CONTROL_RESIDENT": "0"}), {"ok": True})
    assert_eq(c.get_autostart(), {"installed": True})
    assert_eq(c.post_autostart(True), {"installed": True})
    # 方法 + 载荷契约（端点是 PUT-only + {"configs": ...} 包裹——B1 修复锚点）
    assert_eq(calls, [
        ("GET", "/api/remote/node-config", {}),
        ("PUT", "/api/remote/node-config", {"configs": {"CONTROL_RESIDENT": "0"}}),
        ("GET", "/api/remote/autostart", {}),
        ("POST", "/api/remote/autostart", {"enable": True}),
    ], "转发调用序列（方法+载荷）")
    c.close()


if __name__ == "__main__":
    _tests = [(n, f) for n, f in globals().items()
              if callable(f) and getattr(f, "_is_test", False)]
    print(f"remote_client 测试: {len(_tests)} 个\n")
    for _name, _fn in _tests:
        _fn()
    from tests.test_control import _results
    _passed = sum(1 for _, ok, _ in _results if ok)
    _failed = len(_results) - _passed
    print(f"\n通过 {_passed} / 失败 {_failed} / 总计 {len(_results)}")
    if _failed:
        for _n, ok, _msg in _results:
            if not ok:
                print(f"  ✗ {_n}: {_msg}")
        sys.exit(1)
