"""audit_middleware 行为回归（消耗零容忍 + 脱敏边界——ASGI 层直测）。

固化两类不变量:
  1. 零消耗: 请求/响应消息流经 middleware 后逐字节不变（流式/二进制/分片/空）
  2. 脱敏: 敏感键值（含大小写/query 串）不落日志; 空值保持; 普通值不动
运行: cd backend && python -m pytest tests/test_audit_middleware.py -q
"""
from __future__ import annotations
# pyright: reportMissingParameterType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportAny=false, reportMissingTypeArgument=false, reportUnknownLambdaType=false

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from services.audit_middleware import AuditMiddleware, _mask_secrets  # noqa: E402


# ── ASGI 测试脚手架 ─────────────────────────────────────

def _make_scope(method: str = "POST", ctype: str = "application/json") -> dict:
    return {"type": "http", "method": method, "path": "/t", "query_string": b"",
            "headers": [(b"content-type", ctype.encode()), (b"content-length", b"0")]}


async def _drive(app, req_msgs, resp_chunks, scope=None):
    """驱动 ASGI 三方（client ↔ middleware ↔ app），返回 (下游收到的请求, 客户端收到的响应)。"""
    downstream_req: dict = {"body": b""}
    upstream_resp: dict = {"status": 0, "chunks": []}

    async def downstream(scope, receive, send):
        body, more = b"", True
        while more:
            msg = await receive()
            body += msg.get("body", b"")
            more = msg.get("more_body", False)
        downstream_req["body"] = body
        await send({"type": "http.response.start", "status": 200, "headers": []})
        for c in resp_chunks:
            await send({"type": "http.response.body", "body": c})
        await send({"type": "http.response.body", "body": b""})

    req_iter = iter(req_msgs or [{"type": "http.request", "body": b"", "more_body": False}])

    async def client_receive():
        return next(req_iter)

    async def client_send(message):
        if message["type"] == "http.response.start":
            upstream_resp["status"] = message["status"]
        elif message["type"] == "http.response.body" and message.get("body"):
            upstream_resp["chunks"].append(message["body"])

    wrapped = AuditMiddleware(downstream)
    await wrapped(scope or _make_scope(), client_receive, client_send)
    return downstream_req["body"], upstream_resp


# ── 1. 零消耗（消息流逐字节不变）──────────────────────

def test_entry_log_exists_for_binary(caplog=None):
    """二进制请求必须有 [入口] 行（防不可达分支回归——review 抓过的死代码）。"""
    import logging as _lg
    from typing import Any
    records: list[str] = []
    class _H(_lg.Handler):
        def emit(self, record: "_lg.LogRecord") -> None:
            records.append(record.getMessage())
    h: Any = _H()
    _audit = _lg.getLogger("api.audit")
    _audit.addHandler(h)
    _audit.setLevel(_lg.INFO)  # 测试进程 root 默认 WARNING——INFO 需显式放行
    try:
        async def _run():
            await _drive(None, [{"type": "http.request",
                                 "body": bytes(range(256)) * 10,
                                 "more_body": False}], [b"{}"],
                         _make_scope(ctype="application/octet-stream"))
        asyncio.run(_run())
    finally:
        _lg.getLogger("api.audit").removeHandler(h)
    entries = [r for r in records if r.startswith("[入口]")]
    assert entries, f"二进制请求无 [入口] 行: {records}"
    assert "2560 字节" in entries[0], entries[0]  # 256B×10——形态行（类型+长度）


def test_zero_consumption_matrix():
    """五场景: 大 body / 分片 / 二进制 / 流式二进制响应 / 空——两端完整性。"""
    async def run():
        big = b'{"d":"' + b"x" * 300_000 + b'"}'
        binary = bytes(range(256)) * 400  # 100KB 全字节值
        cases = [
            ("大 JSON", [big], [b'{"ok":1}']),
            ("分片请求", [b'{"a":', b'1}'], [b'{"ok":2}']),
            ("二进制请求", [binary], [b'{"ok":3}']),
            ("流式二进制响应", [b"{}"], [binary[i*51200:(i+1)*51200] for i in range(5)]),
            ("空请求空响应", [], [b""]),
        ]
        for name, reqs, resps in cases:
            scope = _make_scope(ctype=(
                "application/octet-stream" if "二进制请求" in name else "application/json"))
            got_req, got_resp = await _drive(None, [
                {"type": "http.request", "body": c,
                 "more_body": i < len(reqs) - 1} for i, c in enumerate(reqs)],
                resps, scope)
            assert got_req == b"".join(reqs), f"{name}: 下游请求体不完整"
            assert b"".join(got_resp["chunks"]) == b"".join(resps) and got_resp["status"] == 200, \
                f"{name}: 客户端响应不完整"
    asyncio.run(run())


# ── 2. 脱敏边界 ──────────────────────────────────────

def test_mask_secrets_matrix():
    """敏感值不落日志; 空值/普通值不动; 键名保留。"""
    assert _mask_secrets('{"DEEPSEEK_API_KEY":"sk-abc"}') == '{"DEEPSEEK_API_KEY":"***"}'
    assert _mask_secrets('{"deepseek_api_key":"sk-abc"}') == '{"deepseek_api_key":"***"}'
    assert _mask_secrets('{"RELAY_PSK":""}') == '{"RELAY_PSK":""}'  # 空值=未配置
    r = _mask_secrets("?token=sk-123&x=1")
    assert "sk-123" not in r and "x=1" in r
    assert _mask_secrets('{"name":"普通值"}') == '{"name":"普通值"}'
    # 嵌套 JSON
    r = _mask_secrets('{"a":{"GITHUB_TOKEN":"gh_x"}}')
    assert "gh_x" not in r


if __name__ == "__main__":
    test_zero_consumption_matrix()
    test_mask_secrets_matrix()
    print("audit_middleware 回归 ✓")
