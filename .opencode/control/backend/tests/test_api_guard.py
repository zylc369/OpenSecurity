"""api_guard 鉴权中间件单元测试（TestClient + scope client 伪造非本机来源）。

覆盖（需求文档 §3.1 步骤 12 验证点）:
  1. 本机放行（默认 testclient 来源）
  2. 局域网 + 白名单路径 + 正确 token → 放行
  3. 局域网 + 错误 token → 401
  4. 局域网 + 非白名单路径 → 403
  5. 未配置 CONTROL_API_KEY → 局域网全 403

非本机来源伪造方式: httpx TestClient 支持 transport 层自定义 scope?
用 starlette TestClient 的 app 直接构建 + ASGI 手动调用太重——此处用
monkeypatch _is_local 间接控制（单元级验证 dispatch 逻辑分支）。
"""
# pyright: reportMissingParameterType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportAny=false, reportMissingTypeArgument=false
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("OPENSECURITY_HOME", "/tmp/control_test_guard")

from tests.test_control import test, assert_eq, assert_true  # noqa: E402


def _mk_app():
    """最小 FastAPI app + guard 中间件 + 白名单/管理面各一个端点。"""
    from fastapi import FastAPI
    from services.api_guard import ApiGuardMiddleware

    app = FastAPI()
    app.add_middleware(ApiGuardMiddleware)

    @app.post("/embed")
    async def embed_ep():
        return {"ok": "embed"}

    @app.get("/api/remote/health")
    async def health_ep():
        return {"service": "opencode-control"}

    @app.get("/api/config")
    async def config_ep():
        return {"secret": "管理面"}

    return app


def _client(app, token: str = ""):
    from fastapi.testclient import TestClient
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return TestClient(app, headers=headers)


@test("api_guard: 本机来源全放行（无需 token）")
def test_local_allows_all():
    app = _mk_app()
    c = _client(app)
    assert_eq(c.post("/embed").status_code, 200, "白名单端点")
    assert_eq(c.get("/api/config").status_code, 200, "管理面端点也放行（本机信任）")


@test("api_guard: 局域网 + 白名单 + 正确 token → 放行; 错误 token → 401")
def test_lan_whitelist_token():
    import services.api_guard as guard
    import services.config_manager as cs
    app = _mk_app()
    c_ok = _client(app, token="right-key-123")
    c_bad = _client(app, token="wrong-key")
    _cmi = cs.ConfigManager.get_instance()
    orig_read, orig_local = _cmi.get, guard.ApiGuardMiddleware.__dict__['_is_local']
    _cmi.get = lambda key: "right-key-123" if key == "CONTROL_API_KEY" else None
    guard.ApiGuardMiddleware._is_local = classmethod(lambda cls, host: False)  # 伪造非本机  # pyright: ignore[reportAttributeAccessIssue]  (测试动态 patch/fake 注入)
    try:
        assert_eq(c_ok.post("/embed").status_code, 200, "正确 token 白名单放行")
        assert_eq(c_ok.get("/api/remote/health").status_code, 200, "health 放行")
        assert_eq(c_bad.post("/embed").status_code, 401, "错误 token 401")
        assert_eq(c_ok.get("/api/remote/health/").status_code, 200, "尾斜杠容忍")
    finally:
        _cmi.get = orig_read
        guard.ApiGuardMiddleware._is_local = orig_local


@test("api_guard: 局域网 + 非白名单路径 → 403（管理面不暴露）")
def test_lan_admin_forbidden():
    import services.api_guard as guard
    import services.config_manager as cs
    app = _mk_app()
    c = _client(app, token="right-key-123")
    _cmi = cs.ConfigManager.get_instance()
    orig_read, orig_local = _cmi.get, guard.ApiGuardMiddleware.__dict__['_is_local']
    _cmi.get = lambda key: "right-key-123" if key == "CONTROL_API_KEY" else None
    guard.ApiGuardMiddleware._is_local = classmethod(lambda cls, host: False)  # pyright: ignore[reportAttributeAccessIssue]  (测试动态 patch/fake 注入)
    try:
        assert_eq(c.get("/api/config").status_code, 403, "管理面 403")
        assert_eq(c.get("/api/docs").status_code, 403, "docs 403")
        assert_eq(c.get("/").status_code, 403, "前端页面 403")
        # 相似路径不误放行（精确匹配）
        assert_eq(c.post("/embedding").status_code, 403, "/embedding 不在白名单")
    finally:
        _cmi.get = orig_read
        guard.ApiGuardMiddleware._is_local = orig_local


@test("api_guard: 未配置 CONTROL_API_KEY → 局域网全 403")
def test_lan_no_key_all_forbidden():
    import services.api_guard as guard
    import services.config_manager as cs
    app = _mk_app()
    c = _client(app, token="whatever")
    _cmi = cs.ConfigManager.get_instance()
    orig_read, orig_local = _cmi.get, guard.ApiGuardMiddleware.__dict__['_is_local']
    _cmi.get = lambda key: None
    guard.ApiGuardMiddleware._is_local = classmethod(lambda cls, host: False)  # pyright: ignore[reportAttributeAccessIssue]  (测试动态 patch/fake 注入)
    try:
        assert_eq(c.post("/embed").status_code, 403, "无 key 白名单也 403")
        assert_eq(c.get("/api/config").status_code, 403, "无 key 管理面 403")
    finally:
        _cmi.get = orig_read
        guard.ApiGuardMiddleware._is_local = orig_local


if __name__ == "__main__":
    _tests = [(n, f) for n, f in globals().items()
              if callable(f) and getattr(f, "_is_test", False)]
    print(f"api_guard 测试: {len(_tests)} 个\n")
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
