#!/usr/bin/env python3
"""web_helpers.py build_gopher_url 回归测试（gopher SSRF 构造契约）。"""
import sys, os, inspect, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from web_helpers import (
    build_gopher_url, _encode_selector,
    create_session, get_csrf, register_and_login,
    extract_flag_from_webhook, create_webhook,
)
from urllib.parse import unquote_to_bytes, unquote

ok = fail = 0

def check(name, cond):
    global ok, fail
    print(("PASS " if cond else "FAIL ") + name)
    ok += 1 if cond else 0
    fail += 0 if cond else 1

def wire(url):
    """gopher URL → libcurl 线上实际发送字节"""
    return unquote_to_bytes(url.split("/_", 1)[1])

# ---------- T1: CL 公式证据（str 版 unquote 禁用依据）----------
check("T1a unquote('%FF') 重编码=3B（str 版虚大）", len(unquote("%FF").encode("utf-8")) == 3)
check("T1b unquote_to_bytes('%FF')=1B（正确公式）", len(unquote_to_bytes("%FF")) == 1)

# ---------- T2: 头部 % 所见即所得（escape_percent 契约）----------
u = build_gopher_url("h", 80, "GET /a%20b HTTP/1.1\r\nHost: h\r\n\r\n")
check("T2a 头部 %20 线上保留", wire(u).startswith(b"GET /a%20b HTTP/1.1\r\n"))
u2 = build_gopher_url("h", 80, "GET /file%3Fq=1 HTTP/1.1\r\nHost: h\r\nX-T: abc%41\r\n\r\n")
check("T2b 请求行 %3F + 头 %41 线上保留", wire(u2).startswith(b"GET /file%3Fq=1 HTTP/1.1\r\nHost: h\r\nX-T: abc%41\r\n\r\n"))

# ---------- T3: 重复 Content-Length 去重 ----------
u3 = build_gopher_url("h", 80, "POST /x HTTP/1.1\r\nHost: h\r\nContent-Length: 99\r\nContent-Length: 88\r\n\r\nhi")
w3 = wire(u3)
check("T3a 重复 CL 去重为 1 个", w3.count(b"Content-Length:") == 1)
check("T3b CL 重算=解码后字节数", re.search(rb"Content-Length: (\d+)", w3).group(1) == b"2")

# ---------- T4: 二进制 %XX body 的 CL 逐字节还原 ----------
u4 = build_gopher_url("h", 80, "POST /x HTTP/1.1\r\nHost: h\r\n\r\n%FF%80%C3")
w4 = wire(u4)
check("T4a 二进制 body CL=3", re.search(rb"Content-Length: (\d+)", w4).group(1) == b"3")
check("T4b 二进制 body 线上字节还原", w4[-3:] == b"\xff\x80\xc3")

# ---------- T5: body %25XX 保留路径 ----------
u5 = build_gopher_url("h", 80, "POST /x HTTP/1.1\r\nHost: h\r\n\r\na=%253C")
w5 = wire(u5)
check("T5 body %253C 线上=%3C 且 CL=5", w5.endswith(b"a=%3C") and re.search(rb"Content-Length: (\d+)", w5).group(1) == b"5")

# ---------- T6: 核心 CL 修正回归（urlencoded body 解码语义）----------
u6 = build_gopher_url("127.0.0.1", 8000,
    "POST /report HTTP/1.1\r\nHost: 127.0.0.1:8000\r\nContent-Length: 40\r\n\r\ncontent=%3Ch1%3Ex%3C%2Fh1%3E")
w6 = wire(u6)
check("T6a CL=18（解码后）", re.search(rb"Content-Length: (\d+)", w6).group(1) == b"18")
check("T6b 线上 body=<h1>x</h1>", w6.endswith(b"content=<h1>x</h1>"))

# ---------- T7: 边界 ----------
u7 = build_gopher_url("127.0.0.1", 8000, "GET /h HTTP/1.1\r\nHost: x\r\n\r\n")
check("T7a 无 body 不加 CL", b"Content-Length" not in wire(u7))
u8 = build_gopher_url("h", 80, "POST /x HTTP/1.1\r\nHost: h\r\n\r\na=1#f?g")
check("T7b body #/? 编码且线上还原", wire(u8).endswith(b"a=1#f?g"))
u9 = build_gopher_url("h", 80, "POST /x HTTP/1.1\r\nHost: h\r\nContent-Length: 40\r\n\r\ncontent=%3Ca%3E", fix_content_length=False)
check("T7c fix=False 保留原 CL", re.search(rb"Content-Length: (\d+)", wire(u9)).group(1) == b"40")
u10 = build_gopher_url("h", 80, "POST /x HTTP/1.1\r\nHost: h\r\n\r\ncontent=中文")
check("T7d 中文 CL 按 UTF-8 字节数", re.search(rb"Content-Length: (\d+)", wire(u10)).group(1) == b"14")
try:
    build_gopher_url("h", 80, "garbage")
    check("T7e 非法输入抛 ValueError", False)
except ValueError:
    check("T7e 非法输入抛 ValueError", True)

# ---------- T8: 既有函数签名回归 ----------
EXPECTED_SIGS = {
    "create_session": ["base_url", "timeout=10", "retries=3", "backoff_factor=0.5"],
    "get_csrf": ["session", "url", "field_name='csrf_token'"],
    "register_and_login": ["session", "base_url", "username", "password", "register_path='/register'", "login_path='/login'"],
    "extract_flag_from_webhook": ["uuid", "keyword='SK-CERT'", "api_base='https://webhook.site'"],
    "create_webhook": ["api_base='https://webhook.site'"],
    "build_gopher_url": ["host", "port", "raw_request", "fix_content_length=True"],
}
for fn in [create_session, get_csrf, register_and_login, extract_flag_from_webhook, create_webhook, build_gopher_url]:
    sig = inspect.signature(fn)
    got = [p.name + (("=" + repr(p.default)) if p.default is not inspect.Parameter.empty else "") for p in sig.parameters.values()]
    check(f"T8 sig-{fn.__name__}", got == EXPECTED_SIGS[fn.__name__])

# ---------- T9: 加固边界（二次评审发现 4）----------
try:
    build_gopher_url("h", 80, "GET /x HTTP/1.1\r\nHost: h")
    check("T9a 头块无空行终止 → ValueError", False)
except ValueError:
    check("T9a 头块无空行终止 → ValueError", True)
u11 = build_gopher_url("h", 80, "POST /x HTTP/1.1\r\nHost: h\r\nContent-Length: 40\r\n\r\n")
check("T9b 空 body 遗留 CL 被移除", b"Content-Length" not in wire(u11))
u12 = build_gopher_url("h", 80, "POST /x HTTP/1.1\r\nHost: h\r\nContent-Length : 40\r\n\r\nhi")
w12 = wire(u12)
check("T9c 畸形 CL(冒号前空格)归一为单个正确 CL", w12.count(b"Content-Length") == 1 and re.search(rb"Content-Length: (\d+)", w12).group(1) == b"2")

print(f"\n=== {ok} pass / {fail} fail ===")
sys.exit(1 if fail else 0)
