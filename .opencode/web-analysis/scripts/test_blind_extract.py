#!/usr/bin/env python3
"""blind_extract.py 回归测试（本地 mock oracle，零外网）。

覆盖: match 模式 check/length/char_at/extract、stop_chars、单特征模式、重试、
timing 模式、POST form / POST JSON、header/cookie 透传、拒绝路径（OracleError）、
JSON 控制字符转义、配置校验（ValueError）、CLI smoke（含 --verify-cond / --output）。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blind_extract import BlindOracle, OracleConfig, OracleError

SECRET = "Sp4ceDb{}"
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blind_extract.py")

LEN_RE = re.compile(r"^length\('([^']*)'\)>=(\d+)$")
ASC_RE = re.compile(r"^ascii\(substr\('([^']*)',(\d+),1\)\)>(\d+)$")


def evaluate(cond):
    m = LEN_RE.match(cond)
    if m:
        return len(m.group(1)) >= int(m.group(2))
    m = ASC_RE.match(cond)
    if m:
        s, pos, mid = m.group(1), int(m.group(2)), int(m.group(3))
        code = ord(s[pos - 1]) if 1 <= pos <= len(s) else 0
        return code > mid
    return None


class Handler(BaseHTTPRequestHandler):
    flaky_left = 1

    def log_message(self, *args):
        pass

    def _reply(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        cond = parse_qs(u.query).get("cond", [""])[0]
        self._handle(u.path, cond)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", "replace")
        ct = self.headers.get("Content-Type", "")
        if "json" in ct:
            cond = json.loads(body).get("cond", "")
        else:
            cond = parse_qs(body).get("cond", [""])[0]
        self._handle(urlparse(self.path).path, cond)

    def _handle(self, path, cond):
        if path == "/guarded":
            if self.headers.get("X-Test") != "1" or "sid=abc" not in (self.headers.get("Cookie") or ""):
                self._reply(403, b"denied")
                return
        if path == "/flaky" and Handler.flaky_left > 0:
            Handler.flaky_left -= 1
            self._reply(500, b"boom")
            return
        r = evaluate(cond)
        if r is None:
            self._reply(400, b"unknown")
            return
        if path == "/slow" and r:
            time.sleep(0.25)
        self._reply(200, b"ok" if r else b"no")


ok = fail = 0


def check(name, cond):
    global ok, fail
    print(("PASS " if cond else "FAIL ") + name)
    ok += 1 if cond else 0
    fail += 0 if cond else 1


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def oracle(path="/probe", **kw):
        cfg = OracleConfig(url_template=f"{base}{path}?cond={{payload}}",
                           payload_template="{cond}", true_match="ok", false_match="no", **kw)
        return BlindOracle(cfg, workers=8)

    # ── 核心（S6a）──
    o = oracle()
    check("T1 check true", o.check(f"length('{SECRET}')>=1") is True)
    check("T2 check false", o.check(f"length('{SECRET}')>=99") is False)
    check("T3 length probe", o.length(f"'{SECRET}'") == len(SECRET))
    check("T4 char_at pos1", o.char_at(f"'{SECRET}'", 1) == ord("S"))
    check("T5 char_at pos8", o.char_at(f"'{SECRET}'", 8) == ord("{"))
    check("T6 extract full", o.extract(f"'{SECRET}'") == SECRET)
    check("T7 stop '}' 含尾字符", o.extract(f"'{SECRET}'", stop_chars="}") == SECRET)
    check("T8 stop '{' 截断含该字符", o.extract(f"'{SECRET}'", stop_chars="{") == SECRET[:8])
    check("T9 越界位置=0（终止）", o.char_at(f"'{SECRET}'", 99) == 0)
    o_single = BlindOracle(OracleConfig(url_template=f"{base}/probe?cond={{payload}}",
                                        payload_template="{cond}", true_match="ok"), workers=4)
    check("T10 单特征模式（无 false 特征）", o_single.check(f"length('{SECRET}')>=99") is False)
    o_flaky = oracle(path="/flaky")
    r = o_flaky.check(f"length('{SECRET}')>=1")
    check("T11 首请求故障重试", r is True and o_flaky.requests_made >= 2)
    o_timing = oracle(path="/slow", mode="timing", timing_threshold_s=0.15)
    check("T12 timing 模式 true", o_timing.check(f"length('{SECRET}')>=1") is True)
    check("T13 timing 模式 false", o_timing.check(f"length('{SECRET}')>=99") is False)

    # ── CLI（S6b）──
    tmpdir = tempfile.mkdtemp()
    out_path = os.path.join(tmpdir, "out.json")
    cmd = [sys.executable, SCRIPT,
           "--url", f"{base}/probe?cond={{payload}}", "--payload-template", "{cond}",
           "--true", "ok", "--false", "no", "--expr", f"'{SECRET}'", "--stop", "}",
           "--verify-cond", f"length('{SECRET}')>=1", "--output", out_path]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    check("T14 CLI smoke 成功且结果正确", p.returncode == 0 and repr(SECRET) in p.stdout)
    data = json.load(open(out_path, encoding="utf-8")) if os.path.exists(out_path) else {}
    check("T15 CLI --output JSON 字段", data.get("result") == SECRET
          and data.get("requests", 0) > 0 and "elapsed_s" in data)
    p2 = subprocess.run([sys.executable, SCRIPT,
                         "--url", f"{base}/probe?cond={{payload}}", "--payload-template", "{cond}",
                         "--true", "ok", "--false", "no", "--expr", f"'{SECRET}'",
                         "--verify-cond", f"length('{SECRET}')>=99"],
                        capture_output=True, text=True, timeout=60)
    check("T16 verify-cond 未通过 → rc=2", p2.returncode == 2)

    # ── 请求形态与凭证（补测：POST / header / cookie / 拒绝路径）──
    o_form = BlindOracle(OracleConfig(url_template=f"{base}/probe", payload_template="{cond}",
                                      data_template="cond={payload}", method="POST",
                                      true_match="ok", false_match="no"), workers=4)
    check("T17 POST form 模式提取", o_form.extract(f"'{SECRET}'") == SECRET)
    o_json = BlindOracle(OracleConfig(url_template=f"{base}/probe", payload_template="{cond}",
                                      json_template='{"cond": "{payload}"}', method="POST",
                                      true_match="ok", false_match="no"), workers=4)
    check("T18 POST JSON 模式提取", o_json.extract(f"'{SECRET}'") == SECRET)
    o_guard = BlindOracle(OracleConfig(url_template=f"{base}/guarded?cond={{payload}}",
                                       payload_template="{cond}", true_match="ok", false_match="no",
                                       headers={"X-Test": "1"}, cookies={"sid": "abc"}), workers=4)
    check("T19 header/cookie 透传", o_guard.extract(f"'{SECRET}'") == SECRET)
    o_bad = BlindOracle(OracleConfig(url_template=f"{base}/guarded?cond={{payload}}",
                                     payload_template="{cond}", true_match="ok", false_match="no",
                                     retries=1), workers=1)
    try:
        o_bad.check(f"length('{SECRET}')>=1")
        check("T20 无凭证被拒 → OracleError", False)
    except OracleError:
        check("T20 无凭证被拒 → OracleError", True)

    # ── 转义与配置校验（外部评审补测）──
    tricky = "Sp4\tce\n{}"
    o_json2 = BlindOracle(OracleConfig(url_template=f"{base}/probe", payload_template="{cond}",
                                       json_template='{"cond": "{payload}"}', method="POST",
                                       true_match="ok", false_match="no"), workers=4)
    check("T21 JSON 模式控制字符转义", o_json2.extract(f"'{tricky}'") == tricky)
    try:
        BlindOracle(OracleConfig(url_template=f"{base}/probe", payload_template="no-placeholder",
                                 true_match="ok", false_match="no"), workers=1)
        check("T22 缺 {cond} 占位符 → ValueError", False)
    except ValueError:
        check("T22 缺 {cond} 占位符 → ValueError", True)
    try:
        BlindOracle(OracleConfig(url_template=f"{base}/probe?c={{payload}}", payload_template="{cond}"),
                    workers=1)
        check("T23 match 模式缺特征串 → ValueError", False)
    except ValueError:
        check("T23 match 模式缺特征串 → ValueError", True)

    srv.shutdown()
    shutil.rmtree(tmpdir, ignore_errors=True)
    print(f"\n=== {ok} pass / {fail} fail ===")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
