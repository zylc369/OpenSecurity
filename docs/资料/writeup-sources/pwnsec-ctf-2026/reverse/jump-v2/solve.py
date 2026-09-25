#!/usr/bin/env python3
"""Reproduce the verified jump-v2 solution against the official binary."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BINARY = ROOT / "challenge" / "jump_v2"
EXPECTED_SHA256 = "ee8973d9a3a88c6a70e557d1c6cb1fb717b7f72ef41c7bea20e4c654c6e68008"
SOLUTION = b"hi_astra_i_believe_you_can_jump_4c6a05cc40f5d4cb"
FLAG_RE = re.compile(rb"pwnsec\{[^}\r\n]+\}")


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def run_binary() -> bytes:
    if not BINARY.is_file():
        fail(f"missing official binary: {BINARY}")
    digest = hashlib.sha256(BINARY.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA256:
        fail(f"unexpected jump_v2 SHA-256: {digest}")

    if os.name == "nt":
        converted = subprocess.run(
            ["wsl", "wslpath", "-a", str(BINARY)], check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout.strip()
        command = ["wsl", converted.decode("utf-8")]
    else:
        BINARY.chmod(BINARY.stat().st_mode | 0o100)
        command = [str(BINARY)]

    completed = subprocess.run(
        command, input=SOLUTION + b"\n", stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=30,
    )
    if completed.returncode != 0:
        fail("official binary rejected the recovered solution")
    match = FLAG_RE.search(completed.stdout)
    if match is None:
        fail("official binary did not emit a flag")
    return match.group(0)


if __name__ == "__main__":
    sys.stdout.buffer.write(run_binary())
