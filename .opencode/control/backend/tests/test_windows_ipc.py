"""Windows 命名管道 IPC 验证（CI 专用，windows-latest 运行）。

验证链：
  1. 最小 FastAPI + uvicorn TCP（CONTROL_TCP_PORT=9776，CI 独占机器无冲突）
  2. ipc_listener.start_windows_listener() 管道监听（FIRST_INSTANCE 互斥）
  3. Python 客户端：mcp-servers/control_url.py 的本地代理 + httpx 往返
  4. 互斥：第二个监听实例应失败（返回 None）
  5. Bun 客户端：node:http socketPath 管道往返（CI裁决 Bun 兼容性）

非 Windows 平台直接跳过（exit 0）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR.parent.parent / "mcp-servers"))

if os.name != "nt":
    print("(非 Windows 平台，跳过)")
    sys.exit(0)

import httpx
import uvicorn
from fastapi import FastAPI

FAILURES: list[str] = []


def check(name: str, fn) -> None:
    try:
        fn()
        print(f"  ✓ {name}")
    except Exception as e:
        FAILURES.append(f"{name}: {type(e).__name__}: {e}")
        print(f"  ✗ {name}: {type(e).__name__}: {e}")


def main() -> int:
    print("=== Windows 管道 IPC 验证 ===")

    app = FastAPI()

    @app.get("/health")
    def _h():
        return {"ok": True, "via": "pipe"}

    # 1. uvicorn TCP 9776 + 注册进 FrontendPortRegistry（桥经注册中心找 upstream）
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=9776, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(40):
        if server.started:
            break
        time.sleep(0.25)
    assert server.started, "uvicorn 未启动"
    from services.frontend_port import frontend_ports
    assert frontend_ports.register_tcp(9776), "上游端口注册（9776 应有监听）"

    # 2. 管道监听
    from services.ipc_listener import IpcListener
    listener = IpcListener()
    name = listener.start() and "pipe-ok"
    check("管道监听启动", lambda: (_ for _ in ()).throw(AssertionError("None")) if name is None else None)

    # 3. Python 客户端（control_url 本地代理 + httpx）
    def py_client():
        from control_url import make_control_client, resolve_control
        addr = resolve_control()
        assert addr is not None, "resolve_control 返回 None"
        import asyncio
        async def _run():
            async with make_control_client(timeout=10) as c:
                return await c.get(f"{addr.url}/health")
        r = asyncio.run(_run())
        assert r.status_code == 200, f"HTTP {r.status_code}"
        assert r.json().get("ok") is True
    check("Python httpx 经管道往返", py_client)

    # 4. 互斥（并发等待语义：活实例在 → 第二个 start 返回 False 复用，不报错）
    def mutex():
        from services.ipc_listener import IpcListener
        second = IpcListener().start()
        assert second is False, f"活实例在时第二 start 应返回 False（复用），实际 {second}"
    check("管道互斥（第二实例复用退出）", mutex)

    # 5. Bun 客户端（node:http socketPath）
    def bun_client():
        probe = BACKEND_DIR.parent.parent / "plugins" / "tests" / "win-pipe-probe.ts"
        r = subprocess.run(
            ["bun", "run", str(probe)],
            capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 0, f"bun probe 退出码 {r.returncode}: {r.stdout} {r.stderr}"
    check("Bun node:http socketPath 管道往返", bun_client)

    print("=" * 50)
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项")
        for f in FAILURES:
            print(f"  ✗ {f}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
