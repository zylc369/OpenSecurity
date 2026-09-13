#!/usr/bin/env python3
"""browser_cdp.py 异常路径与 edge case 全套测试。"""
import json, os, subprocess, sys, tempfile, time, urllib.request

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser_cdp.py")
TMP = tempfile.mkdtemp(prefix="bcdp-test-")
results = []

def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), name, detail)

def run(args, timeout=40):
    p = subprocess.run([sys.executable, SCRIPT] + args, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr

# ---------- T1: 退出码 3a —— Popen OSError（非执行文件）----------
notexec = os.path.join(TMP, "notexec.txt")
open(notexec, "w").write("i am not a binary")
code, out, err = run(["start", "--port", "9299", "--browser", notexec, "--profile", f"{TMP}/p1"])
check("T1 非执行文件 → exit 3 + 优雅报错", code == 3 and "启动失败" in err, f"code={code}")

# ---------- T2: 退出码 3b —— 进程启动即退（假 chrome 秒退）----------
fake_die = os.path.join(TMP, "fake_die.sh")
open(fake_die, "w").write("#!/bin/sh\necho 'fake chrome died' >&2\nexit 1\n")
os.chmod(fake_die, 0o755)
code, out, err = run(["start", "--port", "9298", "--browser", fake_die, "--profile", f"{TMP}/p2"])
check("T2 假 chrome 即退 → exit 3 + stderr 回显", code == 3 and "fake chrome died" in (out + err), f"code={code}")

# ---------- T3: 退出码 4 —— 进程活着但 CDP 不开端口（假 chrome 挂起）----------
fake_hang = os.path.join(TMP, "fake_hang.sh")
open(fake_hang, "w").write("#!/bin/sh\nsleep 60\n")
os.chmod(fake_hang, 0o755)
t0 = time.time()
code, out, err = run(["start", "--port", "9297", "--browser", fake_hang, "--profile", f"{TMP}/p3"], timeout=40)
dt = time.time() - t0
check("T3 挂起假 chrome → exit 4 + 冲突诊断提示", code == 4 and "user-data-dir" in err, f"code={code} dt={dt:.0f}s")
subprocess.run(["pkill", "-f", fake_hang], capture_output=True)

# ---------- T4: 退出码 2 —— 探测链全空 ----------
probe_test = f"""
import sys, types
sys.path.insert(0, "{os.path.dirname(SCRIPT)}")
import browser_cdp as bc
bc._system_candidates = lambda: None
bc._playwright_cache_candidates = lambda: None
assert bc.find_chrome(None) is None, "should be None"
code = bc.cmd_start(types.SimpleNamespace(port=9296, browser=None, profile=None, url=None))
assert code == 2, f"expect 2 got {{code}}"
print("OK")
"""
p = subprocess.run([sys.executable, "-c", probe_test], capture_output=True, text=True)
check("T4 探测链全空 → find_chrome None + exit 2", "OK" in p.stdout, p.stderr[-200:] if p.returncode else "")

# ---------- T5: probe false 分支 ----------
code, out, err = run(["probe", "--port", "9295"])
try:
    data = json.loads(out.strip())
except Exception:
    data = {}
check("T5 probe 未占用端口 → reachable:false JSON", code == 0 and data.get("reachable") is False and data.get("browser") is None, out.strip())

# ---------- T6: --url 实际打开页面 ----------
code, out, err = run(["start", "--port", "9294", "--url", "https://example.com"])
last = [l for l in out.strip().splitlines() if l.startswith("{")][-1] if "{" in out else "{}"
info = json.loads(last)
pid, port, my_profile = info.get("pid"), info.get("port"), info.get("profile")
check("T6a start JSON 含 profile 字段", isinstance(my_profile, str) and ".browser-profiles" in my_profile, str(my_profile))
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as r:
        pages = json.loads(r.read().decode())
    urls = [pg.get("url", "") for pg in pages if pg.get("type") == "page"]
    check("T6b start --url 页面真实打开", code == 0 and pid and any("example.com" in u for u in urls), f"urls={urls}")
finally:
    if pid:
        subprocess.run(["kill", str(pid)], capture_output=True)
        time.sleep(1.5)  # 等 Chrome 及其 helper 进程退出释放 profile 文件句柄
    if my_profile and os.path.isdir(my_profile):  # 精确清理本次 profile
        subprocess.run(["rm", "-rf", my_profile], capture_output=True)

subprocess.run(["rm", "-rf", TMP], capture_output=True)
fails = [r for r in results if not r[1]]
print(f"\n===== {len(results) - len(fails)}/{len(results)} PASS =====")
sys.exit(1 if fails else 0)
