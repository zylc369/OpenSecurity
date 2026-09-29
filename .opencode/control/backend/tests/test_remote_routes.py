"""routes/remote 端点单元测试（TestClient 本机来源; remote_link/ConfigManager fake 注入）。

覆盖（需求文档 §3.1 步骤 15 验证点）:
  1. node-config 仅三 KEY 白名单（其他 key 422 拒绝）
  2. switch 成功/失败路径（校验失败不置位）
  3. status 字段完整
  4. /api/remote/health 返回三模型指纹

运行方式:
  cd .opencode/control/backend
  python tests/test_remote_routes.py
"""
# pyright: reportMissingParameterType=false
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("OPENSECURITY_HOME", "/tmp/control_test_routes")
# 根隔离: 本文件测试的路由直接写 .ai_env——OPENCODE_ROOT 重定向到临时目录，
# 防止测试值污染生产配置（config_store 的读写路径跟随 OPENCODE_ROOT）
_ROUTES_TEST_ROOT = Path("/tmp/control_test_routes_root")
_ROUTES_TEST_ROOT.mkdir(parents=True, exist_ok=True)
(_ROUTES_TEST_ROOT / ".ai_env").write_text("# routes 测试沙箱\n")
os.environ["OPENCODE_ROOT"] = str(_ROUTES_TEST_ROOT)

from tests.test_control import test, assert_eq, assert_true  # noqa: E402


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import remote
    app = FastAPI()
    app.include_router(remote.router)
    return TestClient(app)


def _fake_remote_link(ok_probe=True):
    """patch remote_link 单例的探测与配置读取。"""
    import services.remote_link as rl_module
    from services.remote_client import RemoteHealthInfo, ModelFingerprint

    rl_module.RemoteLinkService.get_instance()._read_config = lambda: ("http://fake:1", True, "tok12345")  # noqa: F811
    info = RemoteHealthInfo(
        service="opencode-control", version="t",
        models=[ModelFingerprint("BAAI/bge-m3", "snap-x", True),
                ModelFingerprint("BAAI/bge-reranker-v2-m3", "snap-y", False),
                ModelFingerprint("glm-ocr", "snap-z", True)],
        latency_ms=8.0)

    async def fake_probe():
        if ok_probe:
            return (True, "", info)
        return (False, "连接拒绝: boom", None)

    svc = rl_module.RemoteLinkService.get_instance()
    svc.reload_config()
    svc._probe_raw = fake_probe  # noqa: SLF001
    return svc


@test("routes/remote: status 字段完整")
def test_status_fields():
    svc = _fake_remote_link()
    # 先让状态机进 REMOTE（初始成功）
    asyncio.run(svc._probe_once())  # noqa: SLF001
    c = _client()
    r = c.get("/api/remote/status")
    assert_eq(r.status_code, 200)
    d = r.json()
    for field in ("enabled", "url", "token_configured", "token_prefix", "state",
                  "fail_streak", "recover_streak", "last_ok_at", "last_fail_reason",
                  "remote_health", "local_models", "unload_countdown_sec"):
        assert_true(field in d, f"缺字段 {field}")
    assert_eq(d["state"], "remote")
    assert_eq(d["url"], "http://fake:1")
    assert_true(d["token_configured"])
    assert_eq(d["token_prefix"], "tok123", "token 只回传前 6 位")
    assert_true(isinstance(d["local_models"], dict), "本地模型状态 dict")


@test("routes/remote: health 返回三模型指纹")
def test_health_fingerprints():
    _fake_remote_link()
    c = _client()
    r = c.get("/api/remote/health")
    assert_eq(r.status_code, 200)
    d = r.json()
    assert_eq(d["service"], "opencode-control")
    assert_eq(len(d["models"]), 3, "三模型指纹")
    repos = [m["repo_id"] for m in d["models"]]
    assert_true("BAAI/bge-m3" in repos and "glm-ocr" in repos, f"repo 列表: {repos}")
    for m in d["models"]:
        assert_true("snapshot" in m and "loaded" in m, "指纹字段完整")


@test("routes/remote: switch 失败不置位 / 成功置位 ENABLED")
def test_switch_paths():
    import services.config_manager as cs
    written = {}
    _cmi = cs.ConfigManager.get_instance()
    orig_write = _cmi.set_one
    _cmi.set_one = lambda k, v: written.update({k: v}) or {}  # pyright: ignore[reportAttributeAccessIssue]  (测试动态 patch/fake 注入)
    try:
        # 失败路径
        _fake_remote_link(ok_probe=False)
        c = _client()
        r = c.post("/api/remote/switch", json={"target": "remote"})
        d = r.json()
        assert_true(not d["ok"], "校验失败 ok=False")
        assert_true("boom" in d.get("detail", ""), f"detail 含原因: {d.get('detail')}")
        assert_eq(written, {}, "失败不写 ENABLED")

        # 成功路径
        _fake_remote_link(ok_probe=True)
        r = c.post("/api/remote/switch", json={"target": "remote"})
        d = r.json()
        assert_true(d["ok"], f"成功 ok=True: {d}")
        assert_eq(written.get("REMOTE_CONSOLE_ENABLED"), "1", "置位 ENABLED=1")

        # 切本地
        r = c.post("/api/remote/switch", json={"target": "local"})
        d = r.json()
        assert_true(d["ok"])
        assert_eq(written.get("REMOTE_CONSOLE_ENABLED"), "0")

        # 非法 target
        r = c.post("/api/remote/switch", json={"target": "xxx"})
        assert_eq(r.status_code, 422, "非法 target 422")
    finally:
        _cmi.set_one = orig_write


@test("routes/remote: node-config 三 KEY 白名单 + API_KEY 脱敏")
def test_node_config_whitelist():
    _fake_remote_link()
    c = _client()
    # 非白名单 key 拒绝
    r = c.put("/api/remote/node-config", json={"configs": {"DEEPSEEK_API_KEY": "x"}})
    assert_eq(r.status_code, 422, "非白名单 key 422")
    d = r.json()
    assert_true("CONTROL_RESIDENT" in d["detail"], f"错误信息指明白名单: {d['detail']}")

    # 合法写入（本机）
    import services.config_manager as cs
    written = {}
    _cmi = cs.ConfigManager.get_instance()
    orig_write = _cmi.set
    _cmi.set = lambda updates: written.update(updates) or updates
    try:
        r = c.put("/api/remote/node-config",
                  json={"configs": {"CONTROL_RESIDENT": "1", "CONTROL_AUTOSTART": "0"}})
        assert_eq(r.status_code, 200)
        assert_eq(written.get("CONTROL_RESIDENT"), "1", "写入成功")
        assert_true(r.json()["reboot_required"] is False, "非 KEY 变更无需重启")
        r = c.put("/api/remote/node-config", json={"configs": {"CONTROL_API_KEY": "abc"}})
        assert_true(r.json()["reboot_required"], "API_KEY 变更提示重启")
    finally:
        _cmi.set = orig_write

    # 读取脱敏
    _cmi2 = cs.ConfigManager.get_instance()
    orig_read = _cmi2.get
    _cmi.get = lambda key: {"CONTROL_API_KEY": "secret123", "CONTROL_RESIDENT": "1"}.get(key)
    try:
        r = c.get("/api/remote/node-config")
        d = r.json()
        assert_eq(d.get("CONTROL_API_KEY"), "secret", "API_KEY 脱敏为前 6 位")
    finally:
        _cmi.get = orig_read


@test("routes/remote: /config 更新触发热重载")
def test_config_reload():
    import services.remote_link as rl_module
    import services.config_manager as cs
    calls = []
    svc = rl_module.RemoteLinkService.get_instance()
    orig = svc.reload_config
    # 隔离: patch config_store.write（路由层调 write 而非 write_one——
    # 不 patch 会把测试值写进真实 .ai_env，污染生产配置）
    _cmi = cs.ConfigManager.get_instance()
    orig_write = _cmi.set
    _cmi.set = lambda updates: dict(updates)  # noqa: E731
    try:
        _fake_remote_link()
        svc.reload_config = lambda: calls.append(1)
        c = _client()
        r = c.put("/api/remote/config", json={"url": "http://new:2", "token": "newtok"})
        assert_eq(r.status_code, 200)
        assert_eq(calls, [1], "reload_config 被调用")
        # 空更新 422
        r = c.put("/api/remote/config", json={"url": "", "token": ""})
        assert_eq(r.status_code, 422)
    finally:
        svc.reload_config = orig
        _cmi.set = orig_write


if __name__ == "__main__":
    _tests = [(n, f) for n, f in globals().items()
              if callable(f) and getattr(f, "_is_test", False)]
    print(f"routes/remote 测试: {len(_tests)} 个\n")
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
