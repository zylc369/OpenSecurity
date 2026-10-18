"""routes/remote `/node-logs/query` 单测（local 本机分支 / remote 转发分支 / 错误映射）。

沙箱与 tests/test_remote_routes.py 同款（同路径——幂等，防互相覆盖）。
"""
# pyright: reportMissingParameterType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportAny=false, reportMissingTypeArgument=false
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("OPENSECURITY_HOME", "/tmp/control_test_routes")
_ROUTES_TEST_ROOT = Path("/tmp/control_test_routes_root")
_ROUTES_TEST_ROOT.mkdir(parents=True, exist_ok=True)
(_ROUTES_TEST_ROOT / ".ai_env").write_text("# routes 测试沙箱\n")
os.environ["OPENCODE_ROOT"] = str(_ROUTES_TEST_ROOT)

import routes.remote as rmod  # noqa: E402
from services.runtime_paths import RuntimePaths  # noqa: E402


class _FakeClient:
    """记录 `_post_json` 调用；可注入返回体或异常。"""

    def __init__(self, response: dict | None = None, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._response = response if response is not None else {"file": "x", "lines": [], "more": False}
        self._error = error

    def _post_json(self, path: str, payload: dict, timeout: float | None = None) -> dict:
        self.calls.append((path, payload))
        if self._error is not None:
            raise self._error
        return self._response


def _sandbox_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 RuntimePaths.LOGS_DIR 指到 tmp_path（local 分支的真实查询目录）。"""
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(RuntimePaths, "LOGS_DIR", str(logs))
    return logs


def _req(**kw):
    return rmod.NodeLogsQueryReq(**kw)


def test_local_branch_queries_local_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """node=local：走本机实现（与 services.log_query 直接调用一致）。"""
    logs = _sandbox_logs(tmp_path, monkeypatch)
    (logs / "node.log").write_text("boot\n[tts] warm\n[tts] done\n", encoding="utf-8")
    resp = asyncio.run(rmod.query_node_logs(_req(file="node.log", pattern=r"\[tts\]", limit=10), node="local"))
    body = json.loads(bytes(resp.body))
    assert body == {"file": "node.log", "lines": ["[tts] warm", "[tts] done"], "more": False}


def test_remote_branch_forwards_path_and_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """node=remote：经 client._post_json 转发到节点 /api/logs/query（payload 四字段）。"""
    fake = _FakeClient(response={"file": "remote-node.log", "lines": ["a", "b"], "more": True})
    monkeypatch.setattr(rmod, "_forward_or_local", lambda node: fake if node == "remote" else None)
    resp = asyncio.run(rmod.query_node_logs(
        _req(file="remote-node.log", pattern="\\[tts\\]|预热", is_regex=True, limit=50), node="remote"))
    assert fake.calls == [("/api/logs/query",
                           {"file": "remote-node.log", "pattern": "\\[tts\\]|预热",
                            "is_regex": True, "limit": 50})]
    assert json.loads(bytes(resp.body)) == {"file": "remote-node.log", "lines": ["a", "b"], "more": True}


def test_remote_branch_failure_502(monkeypatch: pytest.MonkeyPatch) -> None:
    """转发异常 → 502 转发失败。"""
    fake = _FakeClient(error=RuntimeError("节点不可达: boom"))
    monkeypatch.setattr(rmod, "_forward_or_local", lambda node: fake if node == "remote" else None)
    with pytest.raises(rmod.HTTPException) as ei:
        asyncio.run(rmod.query_node_logs(_req(file="x.log"), node="remote"))
    assert ei.value.status_code == 502
    assert "转发失败" in str(ei.value.detail)


def test_remote_not_configured_409() -> None:
    """未配置远程连接时 node=remote → 409（_forward_or_local 既有语义）。"""
    from services.config_manager import ConfigManager
    ConfigManager._reset_for_tests()
    try:
        with pytest.raises(rmod.HTTPException) as ei:
            asyncio.run(rmod.query_node_logs(_req(file="x.log"), node="remote"))
        assert ei.value.status_code == 409
    finally:
        ConfigManager._reset_for_tests()


def test_local_branch_error_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """local 分支异常映射：不存在 → 404；非法文件名/非法正则 → 422。"""
    logs = _sandbox_logs(tmp_path, monkeypatch)
    with pytest.raises(rmod.HTTPException) as e404:
        asyncio.run(rmod.query_node_logs(_req(file="nope.log"), node="local"))
    assert e404.value.status_code == 404
    with pytest.raises(rmod.HTTPException) as e422a:
        asyncio.run(rmod.query_node_logs(_req(file="../x"), node="local"))
    assert e422a.value.status_code == 422
    (logs / "a.log").write_text("x\n", encoding="utf-8")
    with pytest.raises(rmod.HTTPException) as e422b:
        asyncio.run(rmod.query_node_logs(_req(file="a.log", pattern="[", is_regex=True), node="local"))
    assert e422b.value.status_code == 422
