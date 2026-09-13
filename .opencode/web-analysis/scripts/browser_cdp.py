#!/usr/bin/env python3
"""browser_cdp.py — 跨平台启动可被 CDP 接管的独立 Chrome 进程。

浏览器进程通过 start_new_session (POSIX) / DETACHED_PROCESS (Windows)
脱离当前 shell 会话，父会话中止不会连坐杀掉浏览器。

用法:
    python browser_cdp.py start [--url URL] [--port 9222] [--profile DIR] [--browser PATH]
    python browser_cdp.py probe [--port 9222]

start 成功时 stdout 末行输出机器可读 JSON: {"pid": N, "port": P, "profile": DIR, "reused": bool}
退出码: 0 成功/复用 | 2 找不到 Chrome | 3 进程启动即退 | 4 CDP 端口就绪超时
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"


@dataclass
class ChromeTarget:
    """探测到的 Chrome 可执行文件。"""
    path: str
    source: str  # "explicit" | "system" | "playwright-cache"


def _first_existing(paths: list[str]) -> str | None:
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return None


def _system_candidates() -> str | None:
    if IS_MAC:
        return _first_existing([
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ])
    if IS_WIN:
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        return _first_existing([
            os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(local, "Google", "Chrome", "Application", "chrome.exe") if local else "",
        ])
    # linux
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        w = shutil.which(name)
        if w:
            return w
    return None


def _playwright_cache_candidates() -> str | None:
    """Playwright 缓存目录 glob（不依赖 playwright API 版本）。

    注意 glob 模式用 "chromium-*" 而非 "chromium*"，避免误匹配
    chromium_headless_shell-*（headless shell 不适合用户交互场景）。
    """
    if IS_MAC:
        base = os.path.expanduser("~/Library/Caches/ms-playwright")
        pats = [f"{base}/chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/*"]
    elif IS_WIN:
        base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright")
        pats = [f"{base}\\chromium-*\\chrome-win*\\chrome.exe"]
    else:
        base = os.path.expanduser("~/.cache/ms-playwright")
        pats = [f"{base}/chromium-*/chrome-linux/chrome"]
    hits: list[str] = []
    for pat in pats:
        hits.extend(glob.glob(pat))
    if not hits:
        return None
    # 目录名含版本号，按降序取最新
    hits.sort(reverse=True)
    for h in hits:
        if os.path.isfile(h) and os.access(h, os.X_OK):
            return h
    return None


def find_chrome(explicit: str | None) -> ChromeTarget | None:
    """三级探测链: 显式指定 → 平台路径 → Playwright 缓存。"""
    for cand in (explicit, os.environ.get("BROWSER_CDP_CHROME")):
        if cand:
            if os.path.isfile(cand):
                return ChromeTarget(cand, "explicit")
            print(f"[warn] 指定的浏览器不存在: {cand}", file=sys.stderr)
    sysp = _system_candidates()
    if sysp:
        return ChromeTarget(sysp, "system")
    pwp = _playwright_cache_candidates()
    if pwp:
        return ChromeTarget(pwp, "playwright-cache")
    return None


def cdp_info(port: int, timeout: float = 1.5) -> dict | None:
    """GET /json/version，200 且含 Browser 字段则返回解析结果。"""
    url = f"http://127.0.0.1:{port}/json/version"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        if isinstance(data, dict) and "Browser" in data:
            return data
    except Exception:
        pass
    return None


def default_profile() -> str:
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, ".browser-profiles")
    return os.path.abspath(os.path.join(root, time.strftime("%Y%m%d-%H%M%S")))


def cmd_probe(args: argparse.Namespace) -> int:
    info = cdp_info(args.port)
    print(json.dumps({
        "reachable": info is not None,
        "browser": info.get("Browser") if info else None,
    }))
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    # 判定 1: 端口已有 CDP 实例 → 复用，不开新进程
    info = cdp_info(args.port)
    if info:
        print(f"[reuse] CDP 实例已在运行: {info.get('Browser')} @ 127.0.0.1:{args.port}")
        print(json.dumps({"pid": None, "port": args.port, "profile": None, "reused": True}))
        return 0

    target = find_chrome(args.browser)
    if not target:
        print("[error] 未找到任何 Chrome/Chromium（探测链: --browser/env BROWSER_CDP_CHROME → "
              "系统安装路径 → Playwright 缓存）", file=sys.stderr)
        print("安装其一: 系统 Chrome，或 python -m playwright install chromium", file=sys.stderr)
        return 2

    profile = os.path.abspath(args.profile) if args.profile else default_profile()
    os.makedirs(profile, exist_ok=True)
    # stderr 落盘（不用 DEVNULL），进程即死时可回读报错
    err_path = os.path.join(profile, "browser_stderr.log")
    err_f = open(err_path, "w")

    cmd = [
        target.path,
        f"--remote-debugging-port={args.port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if args.url:
        cmd.append(args.url)

    popen_kwargs: dict = {"stdout": err_f, "stderr": err_f, "close_fds": True}
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True  # 脱离进程组，父会话中止不连坐
    else:
        popen_kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )

    print(f"[start] {target.source}: {target.path}")
    print(f"[start] profile: {profile}")
    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
    except OSError as e:
        err_f.close()
        print(f"[error] 启动失败（路径无效或无执行权限）: {e}", file=sys.stderr)
        return 3

    # 判定 2: 进程启动即退
    time.sleep(1.5)
    if proc.poll() is not None:
        err_f.close()
        with open(err_path) as f:
            err = f.read()[:800]
        print(f"[error] 浏览器进程立即退出 (code={proc.returncode}): {err}", file=sys.stderr)
        return 3

    # 判定 3: 轮询 CDP 就绪
    deadline = time.time() + 15
    while time.time() < deadline:
        info = cdp_info(args.port)
        if info:
            err_f.close()
            print(f"[ok] CDP 就绪: {info.get('Browser')}")
            print(f"[ok] 接管: playwright chromium.connect_over_cdp('http://127.0.0.1:{args.port}')")
            print(f"[ok] 浏览器退出码查看/清理: kill {proc.pid}")
            print(json.dumps({"pid": proc.pid, "port": args.port, "profile": profile, "reused": False}))
            return 0
        if proc.poll() is not None:
            err_f.close()
            with open(err_path) as f:
                err = f.read()[:800]
            print(f"[error] 浏览器进程中途退出 (code={proc.returncode}): {err}", file=sys.stderr)
            return 3
        time.sleep(0.5)

    # 判定 4: 进程活但端口不通
    err_f.close()
    print(f"[error] CDP 端口 {args.port} 15s 内未就绪（进程仍在运行 pid={proc.pid}）",
          file=sys.stderr)
    print("常见原因: user-data-dir 与已运行的 Chrome 实例冲突（新进程把 URL 转发给旧实例后"
          "不开调试端口）→ 换独立 --profile 或 kill 冲突进程", file=sys.stderr)
    return 4


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("start", help="启动独立 Chrome 并等待 CDP 就绪")
    sp.add_argument("--url", default=None, help="启动后打开的 URL")
    sp.add_argument("--port", type=int, default=9222)
    sp.add_argument("--profile", default=None, help="user-data-dir（默认独立时间戳目录; "
                     "传固定目录可跨次复用登录态）")
    sp.add_argument("--browser", default=None, help="Chrome 可执行文件路径（覆盖探测链）")
    sp.set_defaults(func=cmd_start)

    pp = sub.add_parser("probe", help="探测 CDP 端口是否可用")
    pp.add_argument("--port", type=int, default=9222)
    pp.set_defaults(func=cmd_probe)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
