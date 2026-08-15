"""前端集成测试（API 层断言）。

E2E 渲染验证在 test_frontend_e2e.py（无头浏览器）。
control_server fixture 在 conftest.py（与 E2E 共享沙箱实例）。
"""
import re
import time

import httpx
import pytest


def test_root_returns_html(control_server):
    r = httpx.get(f"http://127.0.0.1:{control_server}/", timeout=5)
    assert r.status_code == 200
    assert "DOCTYPE html" in r.text
    assert 'id="root"' in r.text


def test_root_references_react_bundle(control_server):
    r = httpx.get(f"http://127.0.0.1:{control_server}/", timeout=5)
    assert "/assets/" in r.text, "发布态应引用构建产物"


def test_js_asset_200(control_server):
    html = httpx.get(f"http://127.0.0.1:{control_server}/", timeout=5).text
    import re
    m = re.search(r'/assets/[^"]+\.js', html)
    assert m, "HTML 中未找到 JS 资源引用"
    r = httpx.get(f"http://127.0.0.1:{control_server}{m.group(0)}", timeout=10)
    assert r.status_code == 200


def test_js_bundle_contains_antd(control_server):
    """AntD v5 是 CSS-in-JS（无独立 .css 产物，样式由 JS 运行时注入）——
    原 CSS 资源断言随技术栈迁移失效，等价验证：bundle 体积含 AntD + 可加载。"""
    html = httpx.get(f"http://127.0.0.1:{control_server}/", timeout=5).text
    import re
    m = re.search(r'/assets/[^"]+\.js', html)
    assert m, "HTML 中未找到 JS 资源引用"
    r = httpx.get(f"http://127.0.0.1:{control_server}{m.group(0)}", timeout=10)
    assert r.status_code == 200
    assert len(r.content) > 500_000, "bundle 应含 AntD（>500KB），实际过小疑似缺失依赖"


def test_api_health_coexists(control_server):
    """B 方案：模型加载期 503、就绪后 200——两者都证明 API 与前端共存正常。"""
    r = httpx.get(f"http://127.0.0.1:{control_server}/health", timeout=5)
    assert r.status_code in (200, 503)
    assert "status" in r.json()


def test_api_config_coexists(control_server):
    r = httpx.get(f"http://127.0.0.1:{control_server}/api/config", timeout=10)
    assert r.status_code == 200
    assert "DEEPSEEK_API_KEY" in r.json()


def test_api_scan_coexists(control_server):
    r = httpx.get(f"http://127.0.0.1:{control_server}/api/scan", timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert "agents" in d
    # python_packages 与外部工具分离（kind 标记）
    pkgs = d["global"]["python_packages"]
    assert isinstance(pkgs, list) and len(pkgs) > 10
    assert all(p["kind"] == "python" for p in pkgs)
    pip_names = {p["pip_name"] for p in pkgs}
    assert "sentence-transformers" in pip_names


def test_api_hardware_coexists(control_server):
    r = httpx.get(f"http://127.0.0.1:{control_server}/api/hardware", timeout=10)
    assert r.status_code == 200
    assert "cpu" in r.json()


def test_embed_works_after_model_load(control_server):
    """等模型加载完（503→200），/embed 仍可调（前端不影响 API）。"""
    for _ in range(40):
        try:
            if httpx.get(f"http://127.0.0.1:{control_server}/health", timeout=3).json().get("status") == "ok":
                break
        except Exception:
            pass
        time.sleep(1)
    r = httpx.post(
        f"http://127.0.0.1:{control_server}/embed",
        json={"inputs": "test"},
        timeout=60,
    )
    assert r.status_code == 200
    vecs = r.json()
    assert isinstance(vecs, list) and len(vecs[0]) == 1024


# ─── 前端重设计新增 API（2026-08-15）──────────────────────


def test_api_system(control_server):
    """GET /api/system：venv/HF 缓存/进程身份。"""
    r = httpx.get(f"http://127.0.0.1:{control_server}/api/system", timeout=5)
    assert r.status_code == 200
    d = r.json()
    assert ".venv" in d["venv_path"]
    assert "huggingface" in d["hf_cache_dir"]
    assert d["control_pid"] > 0
    assert isinstance(d["dev_mode"], bool)


def test_api_models(control_server):
    """GET /api/models：两个 BAAI 模型 + 硬件评估 + 下载状态。"""
    r = httpx.get(f"http://127.0.0.1:{control_server}/api/models", timeout=5)
    assert r.status_code == 200
    d = r.json()
    ids = {m["id"] for m in d["models"]}
    assert {"bge-m3", "bge-reranker-v2-m3"} <= ids
    for m in d["models"]:
        assert set(m["hardware"]) >= {"ok", "reasons", "notes", "available_gb"}
        assert set(m["download"]) >= {"status", "progress", "error"}
    assert d["hf_endpoint"].startswith("http")


def test_api_fs_check(control_server):
    """GET /api/fs/check：三态（存在目录/不存在/~ 展开）。"""
    base = f"http://127.0.0.1:{control_server}/api/fs/check"
    ok = httpx.get(base, params={"path": "/tmp"}, timeout=5).json()
    assert ok["exists"] is True and ok["is_dir"] is True
    miss = httpx.get(base, params={"path": "/no/such/__path__"}, timeout=5).json()
    assert miss["exists"] is False
    home = httpx.get(base, params={"path": "~"}, timeout=5).json()
    assert home["exists"] is True and "~" not in home["resolved"]


def test_api_config_meta(control_server):
    """GET /api/config/meta：必要键带 password/path 类型。"""
    r = httpx.get(f"http://127.0.0.1:{control_server}/api/config/meta", timeout=5)
    assert r.status_code == 200
    d = r.json()
    assert d["DEEPSEEK_API_KEY"]["type"] == "password"
    assert d["IDA_PRO_HOME"]["type"] == "path"
    assert d["DEEPSEEK_API_KEY"]["required"] is True


def test_api_pippable_list(control_server):
    """GET /api/install：白名单列表（前端行级安装按钮数据源）。"""
    r = httpx.get(f"http://127.0.0.1:{control_server}/api/install", timeout=5)
    assert r.status_code == 200
    pkgs = r.json()["packages"]
    assert isinstance(pkgs, list) and len(pkgs) > 0
    assert "frida" in pkgs
