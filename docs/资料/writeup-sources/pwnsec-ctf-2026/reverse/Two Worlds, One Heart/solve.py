from __future__ import annotations

import re
import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BINARY = ROOT / "challenge" / "portal33.exe"


def ror(value: int, count: int, bits: int) -> int:
    mask = (1 << bits) - 1
    return ((value >> count) | (value << (bits - count))) & mask


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def read_u64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def rol(value: int, count: int, bits: int) -> int:
    mask = (1 << bits) - 1
    return ((value << count) | (value >> (bits - count))) & mask


def recover_flag(data: bytes) -> bytes:
    # RVA 0x1600 is file offset 0xa00 in portal33.exe's .text section.
    # Verify the opcode skeleton before treating embedded immediates as constants.
    signatures = {
        0xA09: b"\x35",       # xor eax, imm32
        0xA0E: b"\xc1\xc0\x0b",  # rol eax, 11
        0xA11: b"\x3d",       # cmp eax, imm32
        0xA5F: b"\x48\xb8",  # movabs rax, imm64 (64-bit interpretation)
        0xA69: b"\x48\x33\x46\x14",
        0xA6D: b"\x48\xc1\xc0\x13",  # rol rax, 19
        0xA71: b"\x49\xb8",  # movabs r8, imm64
        0xA80: b"\x48\x8b\x4e\x1c",
        0xA87: b"\x48\xc1\xc1\x1d",  # rol rcx, 29
        0xA8B: b"\x49\xb8",
        0xA9A: b"\x8b\x56\x24",
        0xA9F: b"\xc1\xc2\x0d",  # rol edx, 13
        0xAA2: b"\x81\xfa",
    }
    for offset, expected in signatures.items():
        if data[offset : offset + len(expected)] != expected:
            raise ValueError(f"unexpected verifier bytes at file offset 0x{offset:x}")

    key32 = read_u32(data, 0xA0A)
    expected32 = [
        read_u32(data, 0xA12),
        read_u32(data, 0xA22),
        read_u32(data, 0xA31),
        read_u32(data, 0xA41),
        read_u32(data, 0xA50),
    ]

    chunks: list[bytes] = []
    previous = key32
    for target in expected32:
        word = ror(target, 11, 32) ^ previous
        chunks.append(struct.pack("<I", word))
        previous = target

    key64 = read_u64(data, 0xA61)
    target64_0 = read_u64(data, 0xA73)
    target64_1 = read_u64(data, 0xA8D)
    target32_last = read_u32(data, 0xAA4)

    qword0 = ror(target64_0, 19, 64) ^ key64
    qword1 = ror(target64_1, 29, 64) ^ target64_0
    word_last = ror(target32_last, 13, 32) ^ (target64_1 & 0xFFFFFFFF)
    chunks.extend(
        [
            struct.pack("<Q", qword0),
            struct.pack("<Q", qword1),
            struct.pack("<I", word_last),
        ]
    )
    return b"".join(chunks)


def verify(flag: bytes, data: bytes) -> bool:
    if len(flag) != 40 or re.fullmatch(rb"pwnsec\{[^\r\n]+\}", flag) is None:
        return False

    key32 = read_u32(data, 0xA0A)
    targets32 = [
        read_u32(data, offset)
        for offset in (0xA12, 0xA22, 0xA31, 0xA41, 0xA50)
    ]
    previous = key32
    for index, target in enumerate(targets32):
        word = read_u32(flag, index * 4)
        if rol(word ^ previous, 11, 32) != target:
            return False
        previous = target

    qword0 = read_u64(flag, 20)
    qword1 = read_u64(flag, 28)
    word_last = read_u32(flag, 36)
    target64_0 = read_u64(data, 0xA73)
    target64_1 = read_u64(data, 0xA8D)
    return (
        rol(qword0 ^ read_u64(data, 0xA61), 19, 64) == target64_0
        and rol(qword1 ^ target64_0, 29, 64) == target64_1
        and rol(word_last ^ (target64_1 & 0xFFFFFFFF), 13, 32)
        == read_u32(data, 0xAA4)
    )


def main() -> int:
    try:
        data = BINARY.read_bytes()
        flag = recover_flag(data)
        if not verify(flag, data):
            raise ValueError("recovered bytes do not satisfy both verifier paths")
    except (OSError, ValueError, struct.error) as exc:
        print(f"solve failed: {exc}", file=sys.stderr)
        return 1

    sys.stdout.buffer.write(flag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
