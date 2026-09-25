#!/usr/bin/env python3
"""End-to-end solver for Flagyard's Reduce, Reuse, Recycle challenge."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from Crypto.Cipher import AES


HERE = Path(__file__).resolve().parent
SUPPORT = HERE / "output" / "support"
sys.path.insert(0, str(SUPPORT))

import enumerate_key_candidates as key_equations  # noqa: E402
import experimental_sat_solver as crypto  # noqa: E402
import full_live as transport  # noqa: E402
import recover_live_nonce as nonce_solver  # noqa: E402
import sparse_exception_solver as sparse_solver  # noqa: E402


FLAG_RE = re.compile(rb"BHFlagY\{[^}\r\n]+\}")
def solve_session(host: str, port: int) -> dict[str, object]:
    """Exploit one live server process and return reproducibility evidence."""
    crypto.HOST = host
    crypto.PORT = port
    remote, backend = transport.connect_any()
    try:
        # connect_any() has already consumed the first prompt.
        remote.send_line(crypto.PROBE.encode())
        high = crypto.parse_tag_lines(remote.read_until(b"keys[0]> "), b"keys[0]> ")

        h = crypto.recover_h(high)
        columns, target = key_equations.projected_system(high, h)
        solution, kernel = crypto.linear_preimage(columns, target)
        if len(kernel) != 48:
            raise ValueError(f"unexpected key-system nullity {len(kernel)}")
        key, key_stats = sparse_solver.recover_from_reduced(
            solution, kernel, h.to_bytes(16, "big")
        )
        remote.send_line(key.hex().encode())

        remote.read_until(b"> ")
        remote.send_line(crypto.PROBE.encode())
        low = crypto.parse_tag_lines(remote.read_until(b"keys[1]> "), b"keys[1]> ")
        tags = [crypto.combine_nibbles(a, b) for a, b in zip(high, low)]

        nonce, j0, e4_byte_1 = nonce_solver.recover_nonce(key, h, tags)
        remote.send_line(nonce.hex().encode())

        final = remote.read_until(b"}")
        match = FLAG_RE.search(final)
        if not match:
            raise ValueError(f"flag missing from final response: {final!r}")
        flag = match.group(0).decode()
        return {
            "endpoint": f"{host}:{port}",
            "backend": backend,
            "probe_utf8": crypto.PROBE.encode().hex(),
            "high": high,
            "low": low,
            "full": [tag.hex() for tag in tags],
            "H": f"{h:032x}",
            "key0": key.hex(),
            "key1": nonce.hex(),
            "J0": j0.hex(),
            "E4_byte1": e4_byte_1,
            "key_stats": key_stats,
            "flag": flag,
        }
    finally:
        remote.close()


def self_test() -> None:
    """Exercise H, AES-key, and 16-byte nonce recovery without the server."""
    # This key has no 8/9 hex positions, keeping the exhaustive check quick.
    key = bytes.fromhex("01234567abcdef01234567abcdef0123")
    nonce = bytes.fromhex("fedcba98765432100123456789abcdef")
    tags = []
    for char in crypto.PROBE_CHARS:
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        cipher.encrypt(char.encode() + crypto.FIXED + key.hex().encode())
        tags.append(cipher.digest())

    high = [crypto.high_nibble_text(tag) for tag in tags]
    h = crypto.recover_h(high)
    expected_h = AES.new(key, AES.MODE_ECB).encrypt(bytes(16))
    if h.to_bytes(16, "big") != expected_h:
        raise AssertionError("GHASH subkey recovery failed")

    columns, target = key_equations.projected_system(high, h)
    solution, kernel = crypto.linear_preimage(columns, target)
    recovered_key, stats = sparse_solver.recover_from_reduced(
        solution, kernel, expected_h, progress=False
    )
    if recovered_key != key:
        raise AssertionError("AES key recovery failed")

    recovered_nonce, j0, _ = nonce_solver.recover_nonce(recovered_key, h, tags)
    if recovered_nonce != nonce:
        raise AssertionError("GCM nonce recovery failed")

    print(
        json.dumps(
            {
                "self_test": "passed",
                "H": f"{h:032x}",
                "key0": recovered_key.hex(),
                "key1": recovered_nonce.hex(),
                "J0": j0.hex(),
                "key_stats": stats,
            },
            indent=2,
        )
    )


def main() -> int:
    instance = json.loads((HERE / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in instance["endpoints"] if item["name"] == "main")
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--self-test", action="store_true")
    modes.add_argument("--remote", action="store_true")
    parser.add_argument("--host", default=endpoint["host"])
    parser.add_argument("--port", type=int, default=endpoint["port"])
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--delay", type=float, default=10.0)
    parser.add_argument("--evidence", type=Path, default=HERE / "output" / "evidence.json")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    last_error: Exception | None = None
    for attempt in range(1, args.attempts + 1):
        try:
            evidence = solve_session(args.host, args.port)
            args.evidence.parent.mkdir(parents=True, exist_ok=True)
            args.evidence.write_text(json.dumps(evidence, indent=2) + "\n", encoding="ascii")
            sys.stdout.buffer.write(str(evidence["flag"]).encode("ascii"))
            return 0
        except Exception as exc:
            last_error = exc
            if attempt < args.attempts:
                time.sleep(args.delay)
    assert last_error is not None
    raise last_error


if __name__ == "__main__":
    raise SystemExit(main())
