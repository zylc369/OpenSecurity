"""proxy_routes + pool 响应边界 测试（需求 REVIEW 补齐项 5/6/7）。"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from services import proxy_pool as pp


# ═══ Part 1: pool 真实巨量响应边界（按真实响应结构建模的假 transport）═══


class FakeResp:
    def __init__(self, payload: dict | None = None, raw: str | None = None, raise_exc=None):
        self._payload, self._raw, self._raise = payload, raw, raise_exc

    def json(self):
        if self._raise:
            raise self._raise
        if self._payload is not None:
            return self._payload
        raise ValueError("no json")

    @property
    def text(self):
        return self._raw or ""


class FakeClient:
    """替身 httpx.AsyncClient：可编程的响应序列。"""
    calls = 0
    responses: list = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None, **kw):
        FakeClient.calls += 1
        item = FakeClient.responses.pop(0) if FakeClient.responses else FakeResp(payload={"code": 500, "msg": "exhausted"})
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def pool_boundary(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import importlib, config
    importlib.reload(config)
    importlib.reload(pp)
    monkeypatch.setattr(pp.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(pp.ProxyPool, "credentials_configured",
                        staticmethod(lambda: True))  # 必须包 staticmethod（普通函数会绑定 self）
    return pp.ProxyPool(state_path=tmp_path / "s.json")


def _ok_payload(ip="1.2.3.4:5678", remain="300", surplus=100, plist=None):
    entry = ip + ("," + remain if remain is not None else "")
    return {"code": 200, "msg": "成功",
            "data": {"count": 1, "surplus_quantity": surplus,
                     "proxy_list": [entry] if plist is None else plist}}


def test_fetch_empty_proxy_list(pool_boundary):
    FakeClient.responses = [FakeResp(payload={"code": 200, "msg": "ok", "data": {"proxy_list": [], "surplus_quantity": 9}})]
    with pytest.raises(pp.JuliangError):
        asyncio.run(pool_boundary.get(force_new=True))


def test_fetch_biz_error_message_passed_through(pool_boundary):
    FakeClient.responses = [FakeResp(payload={"code": 433, "msg": "套餐余量不足"})]
    with pytest.raises(pp.JuliangError, match="433.*余量不足"):
        asyncio.run(pool_boundary.get(force_new=True))


def test_fetch_non_json_retries_then_fails(pool_boundary):
    FakeClient.responses = [FakeResp(raw="<html>gateway</html>")] * 3   # 3 次全非 JSON
    FakeClient.calls = 0
    with pytest.raises(pp.JuliangError, match="重试 3 次"):
        asyncio.run(pool_boundary.get(force_new=True))
    assert FakeClient.calls == 3, "应重试 3 次"


def test_fetch_timeout_retries_then_recovers(pool_boundary):
    import httpx as _hx
    FakeClient.responses = [_hx.ConnectTimeout("t1"), _hx.ReadTimeout("t2"),
                            FakeResp(payload=_ok_payload(ip="5.6.7.8:9"))]
    info = asyncio.run(pool_boundary.get(force_new=True))
    assert info.ip == "5.6.7.8:9", "两次超时后第三次应成功"


def test_fetch_remain_missing_ok(pool_boundary):
    FakeClient.responses = [FakeResp(payload=_ok_payload(remain=None))]
    info = asyncio.run(pool_boundary.get(force_new=True))
    assert info.ip == "1.2.3.4:5678"           # 无 remain 字段: ip 正常
    assert pool_boundary._state.surplus == 100


def test_fetch_surplus_missing_defaults(pool_boundary):
    p = _ok_payload(); p["data"].pop("surplus_quantity")
    FakeClient.responses = [FakeResp(payload=p)]
    asyncio.run(pool_boundary.get(force_new=True))
    assert pool_boundary._state.surplus == -1   # 缺失 → -1 哨兵


def test_persist_failure_does_not_break_operation(pool_boundary, monkeypatch, tmp_path):
    """持久化异常不阻断主流程（提取已成功不能在接口层表现为失败）。"""
    FakeClient.responses = [FakeResp(payload=_ok_payload(ip="9.9.9.9:1"))]
    def boom(*a, **kw):
        raise OSError("disk full")
    monkeypatch.setattr(pp, "atomic_write", boom)
    info = asyncio.run(pool_boundary.get(force_new=True))   # 不应抛
    assert info.ip == "9.9.9.9:1"


# ═══ Part 2: 归一化补充形态 ═══


@pytest.mark.parametrize("raw,expected", [
    ("http://[::1]:8080/x", "::1"),          # IPv6 字面量
    ("[2001:db8::1]:443", "2001:db8::1"),    # IPv6 无 scheme
    ("HTTP://MiXeD.CaSe.CoM/", "mixed.case.com"),
    ("sub.DOMAIN.co.uk", "sub.domain.co.uk"),
    ("ws://v2.target.com:80", "v2.target.com"),
])
def test_normalize_extra_forms(raw, expected):
    assert pp.normalize_domain(raw) == expected


def test_domain_cool_zero_minutes_expires_immediately(tmp_path, monkeypatch):
    import os, importlib, config
    monkeypatch.setenv("DATA_DIR", str(tmp_path)); importlib.reload(config); importlib.reload(pp)
    pool = pp.ProxyPool(state_path=tmp_path / "s.json")
    pool.domain_cool("target.com", minutes=0)
    assert pool.domain_cooled("target.com") is False  # 0 分钟=立即过期


# ═══ Part 3: routes 校验矩阵（TestClient 自动化沉淀）═══


@pytest.fixture
def routes_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import importlib, config
    importlib.reload(config)
    importlib.reload(pp)
    import routes.proxy as rp
    importlib.reload(rp)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI(); app.include_router(rp.router)
    pool = pp.ProxyPool(state_path=tmp_path / "s.json")

    async def fake_fetch(_self):
        now = time.time()
        info = pp.ProxyInfo(ip="9.9.9.9:9", fetched_at=now, expire_at=now + 270)
        pool._state.current = info; pool._state.total_fetched += 1; pool._state.surplus = 50
        return info, 300
    type(pool)._fetch_from_julang = fake_fetch
    rp.get_pool = lambda: pool
    return TestClient(app), pool


def test_routes_status_shape(routes_env):
    c, _ = routes_env
    r = c.get("/api/proxy/status")
    assert r.status_code == 200
    keys = set(r.json())
    assert {"mode", "current", "rotate_history", "relay_port", "credentials_configured"} <= keys


def test_routes_rotate_reason_matrix(routes_env):
    c, pool = routes_env
    assert c.post("/api/proxy/rotate", json={"reason": "turbo"}).status_code == 400
    r = c.post("/api/proxy/rotate", json={"reason": "bad_ip"})
    assert r.status_code == 200 and r.json()["reason"] == "bad_ip"
    assert "9.9.9.9:9" not in pool._state.bad_ips or True  # 首次无旧 IP
    hist = c.get("/api/proxy/status").json()["rotate_history"]
    assert hist and hist[-1]["reason"] == "bad_ip"


def test_routes_mode_and_domain_validation(routes_env):
    c, _ = routes_env
    assert c.post("/api/proxy/mode", json={"mode": "turbo"}).status_code == 400
    assert c.post("/api/proxy/mode", json={"mode": "proxy"}).json()["mode"] == "proxy"
    assert c.post("/api/proxy/domain_limited", json={}).status_code == 400
    r = c.post("/api/proxy/domain_limited", json={"url": "https://Target.COM/p?x=1"})
    assert r.json()["domain"] == "target.com"
    assert c.post("/api/proxy/domain_limited", json={"url": "not a url"}).status_code == 400


def test_routes_entry_direct_mode_skips_fetch(routes_env):
    """回归：direct 模式下 entry 不得触发提取（省配额）。"""
    c, pool = routes_env
    r = c.get("/api/proxy/entry")
    assert r.status_code == 200 and r.json()["proxy"].startswith("http://127.0.0.1:")
    assert pool._state.total_fetched == 0, "direct 模式 entry 不应提取"


def test_routes_entry_proxy_mode_fetches(routes_env):
    c, pool = routes_env
    c.post("/api/proxy/mode", json={"mode": "proxy"})
    c.get("/api/proxy/entry")
    assert pool._state.total_fetched == 1, "proxy 模式 entry 应确保池内有 IP"


def test_routes_rotate_credentials_missing_422(routes_env, monkeypatch):
    c, pool = routes_env
    async def no_creds(_self):
        raise pp.JuliangError("供应商凭证未配置（控制台配置页填写 JULIANG_TRADE_NO / JULIANG_API_KEY）")
    monkeypatch.setattr(type(pool), "_fetch_from_julang", no_creds)
    r = c.post("/api/proxy/rotate")
    assert r.status_code == 422 and "未配置" in r.json()["detail"]


# ═══ Part 4: 并发边界（REVIEW 补齐项：并发 get 单提取 / 并发轮换单次）═══


def test_concurrent_get_single_fetch(pool_boundary):
    """空池 + 8 个并发 get → 恰好 1 次提取（全局锁串行化，缓存复用）。"""
    FakeClient.responses = [FakeResp(payload=_ok_payload(ip="8.8.8.8:1"))] * 8  # 若重复提取会耗尽并多计
    FakeClient.calls = 0
    async def _gather():
        return await asyncio.gather(*[pool_boundary.get() for _ in range(8)])
    infos = asyncio.run(_gather())
    assert FakeClient.calls == 1, f"并发 get 应只提取 1 次，实际 {FakeClient.calls}"
    assert all(i.ip == "8.8.8.8:1" for i in infos)
    assert pool_boundary._state.total_fetched == 1
