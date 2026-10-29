#!/usr/bin/env python3
"""Reproduce the extended-license PRNG, Feistel, oracle, and AES path.

The accepted license and the final AES key are username-dependent. Supply the
same username (and, if used, bytes after the ``!`` delimiter) as the challenge
environment to recover the embedded flag.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import math
from pathlib import Path
import re
import struct
import sys
import tarfile
import tempfile
import zipfile
import zlib
from contextlib import contextmanager

from Crypto.Cipher import AES


CHALLENGE_SHA256 = "05cca43b4b9ef229e402fb6869f6613209a3d91542993af32e9984bb99d40563"
CIPHERTEXT_OFFSET = 0x2111850
CIPHERTEXT_SIZE = 80
LICENSE_PREFIX = b"BHLCNS_"
LICENSE_DELIMITER = b"!"
MAX_HASHED_LICENSE_SIZE = 120
EXPECTED_USERNAME_VALUE = 0xBF2B0FA2

FLAG_PATTERN = re.compile(rb"BHFlagY\{[^{}\r\n]+\}")
MASK32 = 0xFFFFFFFF
MASK64 = 0xFFFFFFFFFFFFFFFF
CLMUL_CONSTANT = 0x1D872B41F2A3C4D5
STATE_XOR = 0x9E3779B97F4A7C15


@contextmanager
def resolved_challenge(override: Path | None):
    if override is not None:
        yield override
        return
    root = Path(__file__).resolve().parent
    archive_path = root / "challenge" / "extended-license.tar.zip"
    with zipfile.ZipFile(archive_path) as outer:
        tar_data = outer.read("extended-license.tar.gz")
    with tarfile.open(fileobj=io.BytesIO(tar_data), mode="r:gz") as bundle:
        binary = bundle.extractfile("challenge")
        if binary is None:
            raise ValueError("challenge binary is missing from the supplied archive")
        binary_data = binary.read()
    with tempfile.TemporaryDirectory(prefix="extended-license-") as temp_dir:
        challenge_path = Path(temp_dir) / "challenge"
        challenge_path.write_bytes(binary_data)
        yield challenge_path

# Feeding an all-zero transformed payload to the extracted 30-instruction cBPF
# program exposes these selector bits. The userspace chain requires the
# opposite path (EPERM) for all 512 tests, so the real Feistel target is its
# bitwise complement.
ORACLE_ZERO_VALUE = bytes.fromhex(
    "a79a5194654c7c84d9e3efae2e44e119"
    "61a2651ba7f2bd0e27983582626dd61c"
    "704dc90fb1dfed76b0990690a8c1074f"
    "f13cf3148c774697b5c711bf73618afb"
)
FEISTEL_TARGET = bytes(value ^ 0xFF for value in ORACLE_ZERO_VALUE)


def float32(value: float) -> float:
    """Round a Python float exactly as an x86 single-precision operation."""

    return struct.unpack("<f", struct.pack("<f", value))[0]


def carryless_multiply_low64(left: int, right: int) -> int:
    """Return the low 64 bits of PCLMULQDQ-style carry-less multiplication."""

    result = 0
    while right:
        if right & 1:
            result ^= left
        left <<= 1
        right >>= 1
    return result & MASK64


def derive_seed(username: bytes) -> int:
    """Derive the shellcode's initial 64-bit state from the login name."""

    digest = hashlib.sha256(username[:20].ljust(20, b"\0")).digest()
    seed = 0
    for word in struct.unpack("<4Q", digest):
        seed ^= word
    return seed


def prng_step(state: int) -> tuple[int, int]:
    """Run one recovered CLMUL/float32 PRNG step."""

    state = carryless_multiply_low64(state, CLMUL_CONSTANT) ^ STATE_XOR
    unit = float32(float32(state & MASK32) * float32(2.0**-32))
    mapped = float32(
        float32(unit * float32(1.690000057220459))
        + float32(0.12345670163631439)
    )
    fraction = float32(mapped - float32(math.floor(mapped)))
    output = int(float32(fraction * float32(2.0**32))) & MASK32
    return state, output


def derive_round_keys(username: bytes) -> tuple[tuple[int, ...], ...]:
    """Generate four 32-bit keys for each of the eight Feistel blocks."""

    state = derive_seed(username)
    flat_keys: list[int] = []
    for _ in range(32):
        state, output = prng_step(state)
        flat_keys.append(output)
    return tuple(tuple(flat_keys[index : index + 4]) for index in range(0, 32, 4))


def round_function(value: int, key: int) -> int:
    mixed = (value + key) & MASK32
    return (mixed ^ ((mixed << 7) & MASK32) ^ (mixed >> 9)) & MASK32


def encrypt_block(block: bytes, keys: tuple[int, ...]) -> bytes:
    left = int.from_bytes(block[:4], "little")
    right = int.from_bytes(block[4:], "little")
    for key in keys:
        left, right = right, (left ^ round_function(right, key)) & MASK32
    return left.to_bytes(4, "little") + right.to_bytes(4, "little")


def decrypt_block(block: bytes, keys: tuple[int, ...]) -> bytes:
    left = int.from_bytes(block[:4], "little")
    right = int.from_bytes(block[4:], "little")
    for key in reversed(keys):
        old_right = left
        old_left = right ^ round_function(old_right, key)
        left, right = old_left & MASK32, old_right
    return left.to_bytes(4, "little") + right.to_bytes(4, "little")


def transform_payload(payload: bytes, username: bytes) -> bytes:
    if len(payload) != 64:
        raise ValueError("payload must be exactly 64 bytes")
    round_keys = derive_round_keys(username)
    return b"".join(
        encrypt_block(payload[offset : offset + 8], keys)
        for offset, keys in zip(range(0, 64, 8), round_keys, strict=True)
    )


def recover_payload(username: bytes) -> bytes:
    """Invert all eight Feistel blocks against the statically emulated oracle."""

    round_keys = derive_round_keys(username)
    payload = b"".join(
        decrypt_block(FEISTEL_TARGET[offset : offset + 8], keys)
        for offset, keys in zip(range(0, 64, 8), round_keys, strict=True)
    )
    if transform_payload(payload, username) != FEISTEL_TARGET:
        raise AssertionError("Feistel inversion failed")
    return payload


def build_license(username: bytes, extension: bytes = b"") -> bytes:
    """Create ``BHLCNS_ || payload || ! || extension`` for a username."""

    payload = recover_payload(username)
    if LICENSE_DELIMITER in payload:
        raise ValueError("recovered payload contains the parser delimiter 0x21")
    license_data = LICENSE_PREFIX + payload + LICENSE_DELIMITER + extension
    if len(license_data) > MAX_HASHED_LICENSE_SIZE:
        raise ValueError("license plus extension exceeds the 120-byte hashed window")
    return license_data


def username_validator(username: bytes, tsc_high: int = 0) -> int:
    """Model the recovered validator, including its leaked RDTSC high word."""

    return (zlib.crc32(username) ^ 0x14 ^ tsc_high) & MASK32


def extract_ciphertext(challenge_path: Path, *, verify_hash: bool = True) -> bytes:
    challenge = challenge_path.read_bytes()
    digest = hashlib.sha256(challenge).hexdigest()
    if verify_hash and digest != CHALLENGE_SHA256:
        raise ValueError(f"unexpected challenge SHA-256: {digest}")
    ciphertext = challenge[CIPHERTEXT_OFFSET : CIPHERTEXT_OFFSET + CIPHERTEXT_SIZE]
    if len(ciphertext) != CIPHERTEXT_SIZE:
        raise ValueError("challenge is too short for the embedded ciphertext")
    return ciphertext


def derive_aes_key(username: bytes, license_data: bytes) -> bytes:
    return hashlib.sha256(license_data[:MAX_HASHED_LICENSE_SIZE] + username).digest()


def decrypt_embedded_flag(
    username: bytes, license_data: bytes, challenge_path: Path
) -> tuple[bytes, bytes]:
    key = derive_aes_key(username, license_data)
    ciphertext = extract_ciphertext(challenge_path)
    plaintext = AES.new(key, AES.MODE_ECB).decrypt(ciphertext)
    return key, plaintext


def self_test(challenge_path: Path) -> None:
    """Check the recovered code against a native-tested regression vector."""

    username = b"zuackk"
    expected_payload = bytes.fromhex(
        "91e148cd4c446fb2b86c51d0342207f6"
        "fba29a5e719e434a4ab7a1dd8e523b3b"
        "1ea4ac12426eda084c8f309ab99ce07c"
        "d3033974dcb39814842684d4acaec0e4"
    )
    payload = recover_payload(username)
    assert payload == expected_payload
    assert transform_payload(payload, username) == FEISTEL_TARGET
    assert username_validator(username, 0) == 0xBF2B0F0C
    assert len(extract_ciphertext(challenge_path)) == CIPHERTEXT_SIZE
    print("self-test: PASS")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", help="login name used by the challenge")
    parser.add_argument(
        "--extension-hex",
        default="",
        help="optional bytes after the ! delimiter, encoded as hexadecimal",
    )
    parser.add_argument(
        "--output", type=Path, help="write the generated binary license to this path"
    )
    parser.add_argument(
        "--challenge",
        type=Path,
        help="path to the original ELF (defaults to the supplied archive)",
    )
    parser.add_argument(
        "--tsc-high",
        type=lambda value: int(value, 0),
        default=0,
        help="high 32 bits of the internal RDTSC value (default: 0)",
    )
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--require-flag",
        action="store_true",
        help="exit nonzero unless decrypted data contains BHFlagY{...}",
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> int:
    if args.self_test:
        self_test(args.challenge)
        if args.username is None:
            return 0
    if args.username is None:
        print("error: --username is required unless only --self-test is used", file=sys.stderr)
        return 2

    try:
        extension = bytes.fromhex(args.extension_hex)
    except ValueError as exc:
        print(f"error: invalid --extension-hex: {exc}", file=sys.stderr)
        return 2

    username = args.username.encode("utf-8")
    try:
        license_data = build_license(username, extension)
        key, plaintext = decrypt_embedded_flag(username, license_data, args.challenge)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(license_data)

    username_validator(username, args.tsc_high)

    match = FLAG_PATTERN.search(plaintext)
    if match:
        sys.stdout.buffer.write(match.group())
        return 0
    return 1 if args.require_flag else 0


def main() -> int:
    args = parse_args()
    try:
        with resolved_challenge(args.challenge) as challenge_path:
            args.challenge = challenge_path
            return run(args)
    except (OSError, tarfile.TarError, zipfile.BadZipFile, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
