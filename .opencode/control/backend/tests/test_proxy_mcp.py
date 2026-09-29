"""proxy MCP 协议级测试：工具清单/描述含判定 SOP/真实调用形态（REVIEW 补齐项 8）。"""
# pyright: reportMissingParameterType=false
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
SERVER = BACKEND_DIR.parent.parent / "mcp-servers" / "proxy" / "server.py"  # backend→control→.opencode(两次 parent)

EXPECTED_TOOLS = ["proxy_status", "proxy_rotate", "proxy_mode", "proxy_get_entry"]
SOP_KEYWORDS = ["判定SOP", "预期挑战", "bad_ip"]


def _spawn():
    import os
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SERVER.parent.parent) + os.pathsep + env.get("PYTHONPATH", "")  # control_url 等薄壳共享模块（自持，不依赖外部注入）
    # v2 薄壳须由启动方注入 IPC 地址（生产=插件 mcp-manager）；测试语义=直连本机生产控制台。
    # 不用进程 env 推导（pool/routes 测试会 monkeypatch OPENSECURITY_HOME 致其漂移）
    env.setdefault(
        "OPENSECURITY_CONTROL_IPC",
        str(Path.home() / "bw-security-analysis" / "opensecurity-control.sock"),
    )
    return subprocess.Popen(
        [sys.executable, str(SERVER)],
        env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True)  # cwd 无关：脚本经绝对路径+内部 sys.path 自理


def _rpc(proc, msg: dict, read: bool = True) -> dict | None:
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    if not read:
        return None
    line = proc.stdout.readline()
    return json.loads(line) if line.strip() else None


def test_mcp_tools_and_sop_description():
    proc = _spawn()
    try:
        init = _rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                      "clientInfo": {"name": "t", "version": "0"}}})
        assert init and "result" in init
        _rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"}, read=False)
        tools = _rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert tools is not None
        names = [t["name"] for t in tools["result"]["tools"]]
        assert names == EXPECTED_TOOLS, names
        desc = next(t for t in tools["result"]["tools"]
                    if t["name"] == "proxy_status")["description"]
        for kw in SOP_KEYWORDS:                      # 判定 SOP 必须内嵌（铁律一引导物）
            assert kw in desc, f"SOP 关键词缺失: {kw}"
        # 描述不越界：无调用方代码示例/无供应商名
        all_desc = " ".join(t["description"] for t in tools["result"]["tools"])
        for banned in ("requests", "Playwright", "巨量"):
            assert banned not in all_desc, f"描述越界残留: {banned}"
    finally:
        proc.kill()
        proc.wait()


def test_mcp_status_call_shape():
    """真实调用：控制台在跑→JSON 状态；未跑→明确错误（两种形态都合法，不得崩）。"""
    proc = _spawn()
    try:
        _rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "t", "version": "0"}}})
        _rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"}, read=False)
        r = _rpc(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "proxy_status", "arguments": {}}})
        assert r is not None
        text = r["result"]["content"][0]["text"]
        if "错误" in text:
            return  # 控制台未运行/不可发现：错误路径明确 ✓（错误文本非 JSON，先判分支再 parse）
        parsed = json.loads(text)
        assert "rotate_history" in parsed and "credentials_configured" in parsed
    finally:
        proc.kill()
        proc.wait()
