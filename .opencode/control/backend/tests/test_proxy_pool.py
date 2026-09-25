"""proxy_pool 单元测试（需求 §8 步骤 1 验证点）。

覆盖：归一化全表逐行（§5.1 十形态含拒绝分支）、签名官方自测、
mock 代理IP供应商 API 的缓存/过期/黑名单/冷却/history/持久化往返、凭证缺失行为。
"""
from __future__ import annotations

import asyncio

import sys
import time
from pathlib import Path

import pytest

# 自包含导入（同 test_control.py 模式）
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from services import proxy_pool as pp


# ─── 归一化全表（需求 §5.1）────────────────────────────────


@pytest.mark.parametrize("raw,expected", [
    ("https://Target.COM/path?x=1#frag", "target.com"),
    ("HTTP://target.com:8443/a", "target.com"),
    ("http://user:pass@target.com/x", "target.com"),
    ("ws://target.com", "target.com"),
    ("wss://target.com/v2", "target.com"),
    ("target.com", "target.com"),                       # 无 scheme
    ("target.com:443", "target.com"),                   # 无 scheme 带端口
    ("target.com.", "target.com"),                      # trailing dot
    ("https://target.com..", "target.com"),             # 多 trailing dot
    ("127.0.0.1:9776", "127.0.0.1"),                    # IP host
    ("localhost", "localhost"),
    ("https://目标站.com/", "xn--iwvq54a91c.com"),    # IDN→punycode（目标站.com 实测值）
])
def test_normalize_domain_ok(raw, expected):
    assert pp.normalize_domain(raw) == expected


@pytest.mark.parametrize("raw", [
    "",                 # 空
    "   ",              # 空白
    "not a url",        # 无 host
    "/a/b",             # 纯路径
    "https://",         # scheme 后无 host
    "http:///onlypath", # 空 host
])
def test_normalize_domain_reject(raw):
    with pytest.raises(ValueError):
        pp.normalize_domain(raw)


# ─── 签名自测（官方文档 §1.2 演示数据）──────────────────────


def test_sign_selftest_official():
    assert pp.selftest_sign() is True


# ─── 状态机（mock 代理IP供应商 API）────────────────────────────────


class FakeJuliang:
    """构造替身函数替换类属性 _fetch_from_julang（async def 函数作为类属性
    会绑定 self，签名首个参数接 pool 实例）。按序返回预置 IP，记录提取次数。"""

    def __init__(self, pool: pp.ProxyPool, ips: list[str]):
        self.calls = 0
        pool_ref, ip_list, calls = pool, list(ips), self

        async def fake_fetch(_self):
            calls.calls += 1
            if not ip_list:
                raise pp.JuliangError("mock exhausted")
            ip = ip_list.pop(0)
            now = time.time()
            info = pp.ProxyInfo(
                ip=ip, fetched_at=now,
                expire_at=now + pp.JULIANG_IP_TTL_SEC - pp.JULIANG_TTL_MARGIN_SEC)
            pool_ref._state.current = info
            pool_ref._state.surplus = 9000 - calls.calls
            pool_ref._state.total_fetched += 1
            return info, 300

        self.fn = fake_fetch


@pytest.fixture
def pool(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import importlib, config
    importlib.reload(config)
    importlib.reload(pp)
    p = pp.ProxyPool(state_path=tmp_path / "proxy_state.json")
    return p


def test_pool_lifecycle(pool):
    fake = FakeJuliang(pool, ["1.1.1.1:1", "2.2.2.2:2", "3.3.3.3:3"])
    original = pp.ProxyPool._fetch_from_julang
    pp.ProxyPool._fetch_from_julang = fake.fn  # 替身：async def（绑定 self 形态）
    try:
        # 缓存：两次 get 只提取一次
        a = asyncio.run(pool.get())
        b = asyncio.run(pool.get())
        assert a.ip == b.ip == "1.1.1.1:1" and fake.calls == 1

        # rotate(bad_ip)：旧 IP 进黑名单 + 新 IP + history 记录
        c = asyncio.run(pool.rotate("bad_ip"))
        st = pool.status()
        assert c.ip == "2.2.2.2:2"
        assert "1.1.1.1:1" in pool._state.bad_ips
        assert st["rotate_history"][-1]["reason"] == "bad_ip"
        assert st["rotate_history"][-1]["old"] == "1.1.1.1:1"
        assert st["rotate_history"][-1]["new"] == "2.2.2.2:2"

        # 过期：current 到期后 get 提取新
        pool._state.current.expire_at = time.time() - 1
        d = asyncio.run(pool.get())
        assert d.ip == "3.3.3.3:3" and fake.calls == 3

        # 持久化往返：重建实例读同一状态文件
        pp.ProxyPool._fetch_from_julang = original
        pool2 = pp.ProxyPool(state_path=pool._path)
        assert pool2._state.current.ip == "3.3.3.3:3"
        assert pool2._state.bad_ips == ["1.1.1.1:1"]
        assert pool2._state.total_fetched == 3
    finally:
        pp.ProxyPool._fetch_from_julang = original


def test_domain_cool_and_cooled(pool):
    assert pool.domain_cool("https://Target.COM/p?a=1") == "target.com"   # 归一化入键
    assert pool.domain_cooled("http://target.com:9999") is True           # 不同写法同键命中
    assert pool.domain_cooled("other.com") is False
    pool._state.domain_limited["target.com"] = time.time() - 1            # 过期
    assert pool.domain_cooled("target.com") is False


def test_mode_validation_and_history(pool):
    with pytest.raises(ValueError):
        pool.set_mode("turbo")
    pool.set_mode("proxy")
    st = pool.status()
    assert st["mode"] == "proxy"
    assert st["rotate_history"][-1]["reason"] == "mode_direct_to_proxy"


def test_credentials_missing_no_crash(pool, monkeypatch):
    """铁律二：凭证缺失时 status 正常返回未配置标记，提取抛 JuliangError（带指引）。"""
    monkeypatch.setattr(pool, "credentials_configured", lambda: False)
    st = pool.status()
    assert st["credentials_configured"] is False and st["mode"] == "direct"
    with pytest.raises(pp.JuliangError, match="未配置"):
        asyncio.run(pool.get(force_new=True))


def test_history_limit(pool, tmp_path):
    for i in range(pp.ROTATE_HISTORY_LIMIT + 10):
        pool._record("agent_rotate", f"old{i}", f"new{i}")
    assert len(pool._state.rotate_history) == pp.ROTATE_HISTORY_LIMIT
    assert pool._state.rotate_history[-1].new == f"new{pp.ROTATE_HISTORY_LIMIT + 9}"


def test_state_file_corruption_reset(pool, tmp_path):
    pool._persist()
    pool._path.write_text("{broken json!!")
    pool3 = pp.ProxyPool(state_path=pool._path)
    assert pool3._state.mode == "direct" and pool3._state.current is None
