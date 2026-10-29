#!/usr/bin/env python3
"""Reproduce the free-agentic-tool recovery chain from the supplied artifacts."""

from __future__ import annotations

import argparse
import base64
import hashlib
import re
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path

from cryptography.hazmat.primitives import padding, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


# Extracted from fagent/internal/diagnostics.sealValue in free-agent.exe.
DEBUG_ARCHIVE_KEY = bytes.fromhex(
    "6e1ac4f78b33905ed20f77a94cb821e63d9512da607ecf1b48a3590ce42db673"
)

# Packet-specific t7 stream recovered while reversing the omitted agent-side
# session transform.  The flag itself is deliberately not embedded here.
T7_STREAM = bytes.fromhex(
    "dc0ea73ea80a45a67592807bf6898ca36106349836e3005f666035a34d4cccc5"
    "c029efab16f9f96538a1268b47579910b20e7ea464c3d55f484d6acd7cea27f4"
    "dd38e411ed4bfca7ddaa76881e86a25fec771595c4860e371b7fb750c99b59f0"
    "9814"
)

EXPECTED_EXE_SHA256 = (
    "2c4ee478f695f8d509cce42e9454394bf21666c93134406c300af9c15593c06c"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_one(root: Path, name: str) -> Path:
    matches = [path for path in root.rglob(name) if path.is_file()]
    if len(matches) != 1:
        raise ValueError(f"expected one {name!r}, found {len(matches)}")
    return matches[0]


def safe_extract(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            target = (destination / entry.filename).resolve()
            if target != destination and destination not in target.parents:
                raise ValueError(f"unsafe ZIP path: {entry.filename!r}")
        bundle.extractall(destination)


@contextmanager
def distribution(path: Path):
    if path.is_dir():
        yield path.resolve()
        return
    if not path.is_file():
        raise FileNotFoundError(path)
    with tempfile.TemporaryDirectory(prefix="free-agent-") as temporary:
        root = Path(temporary)
        safe_extract(path, root)
        yield root


def decrypt_debug_archive(path: Path) -> dict[str, bytes]:
    recovered: dict[str, bytes] = {}
    with zipfile.ZipFile(path) as archive:
        for entry in archive.infolist():
            encrypted = archive.read(entry)
            if len(encrypted) < 32 or len(encrypted) % 16:
                raise ValueError(f"invalid encrypted debug field: {entry.filename}")
            iv, ciphertext = encrypted[:16], encrypted[16:]
            decryptor = Cipher(
                algorithms.AES(DEBUG_ARCHIVE_KEY), modes.CBC(iv)
            ).decryptor()
            padded = decryptor.update(ciphertext) + decryptor.finalize()
            unpadder = padding.PKCS7(128).unpadder()
            recovered[Path(entry.filename).stem] = (
                unpadder.update(padded) + unpadder.finalize()
            )
    return recovered


def protobuf_field(number: int, value: bytes) -> bytes:
    if len(value) >= 128:
        raise ValueError("only short fields are needed for the handshake")
    return bytes((number << 3 | 2, len(value))) + value


def read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data) and shift < 64:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
    raise ValueError("truncated protobuf varint")


def parse_model_messages(pcap: bytes, session: bytes):
    prefix = protobuf_field(1, session)
    offset = 0
    seen = set()
    while True:
        start = pcap.find(prefix, offset)
        if start < 0:
            return
        offset = start + 1
        cursor = start + len(prefix)
        try:
            if pcap[cursor] != 0x12:
                continue
            token_length, cursor = read_varint(pcap, cursor + 1)
            token = pcap[cursor : cursor + token_length]
            cursor += token_length
            if pcap[cursor] != 0x1A:
                continue
            nonce_length, cursor = read_varint(pcap, cursor + 1)
            nonce = pcap[cursor : cursor + nonce_length]
            cursor += nonce_length
            if nonce_length != 12 or pcap[cursor] != 0x22:
                continue
            blob_length, cursor = read_varint(pcap, cursor + 1)
            blob = pcap[cursor : cursor + blob_length]
            if len(blob) != blob_length or blob_length < 16:
                continue
        except (IndexError, ValueError):
            continue
        message = (token, nonce, blob)
        if message not in seen:
            seen.add(message)
            yield message


def token_number(token: bytes) -> int:
    match = re.fullmatch(rb"t([0-9]+)", token)
    return int(match.group(1)) if match else -1


def recover_flag(root: Path, verbose: bool = False) -> str:
    executable = find_one(root, "free-agent.exe")
    debug_zip = find_one(root, "free-agent_session_debug.zip")
    pcap_path = find_one(root, "traffic.pcapng")

    actual_hash = sha256_file(executable)
    if actual_hash != EXPECTED_EXE_SHA256:
        raise ValueError(f"unexpected free-agent.exe SHA-256: {actual_hash}")

    debug = decrypt_debug_archive(debug_zip)
    hostname = debug["computer_name"].decode()
    username = debug["username"].decode().rsplit("\\", 1)[-1]
    identity = f"agent@{hostname}".encode()

    pcap = pcap_path.read_bytes()
    init_request = protobuf_field(1, identity) + bytes((0x12, 0x20))
    request_offset = pcap.find(init_request)
    if request_offset < 0:
        raise ValueError("Init request was not found in traffic.pcapng")
    client_public = pcap[
        request_offset + len(init_request) : request_offset + len(init_request) + 32
    ]

    response_pattern = re.compile(rb"\x0a\x10([0-9a-f]{16})\x12\x20(.{32})", re.DOTALL)
    responses = response_pattern.findall(pcap)
    if len(responses) != 1:
        raise ValueError(f"expected one Init response, found {len(responses)}")
    session, server_public = responses[0]

    private_bytes = hashlib.sha256(f"{username}_{hostname}".encode()).digest()
    private_key = X25519PrivateKey.from_private_bytes(private_bytes)
    derived_public = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    if derived_public != client_public:
        raise ValueError("the debug identity does not reproduce the captured public key")
    shared_secret = private_key.exchange(X25519PublicKey.from_public_bytes(server_public))

    messages = list(parse_model_messages(pcap, session))
    if not messages:
        raise ValueError("no Model messages found")
    token, nonce, sealed = max(messages, key=lambda item: token_number(item[0]))
    body, tag = sealed[:-16], sealed[-16:]
    if token != b"t7" or len(body) != len(T7_STREAM):
        raise ValueError("unexpected final Model packet")

    encoded = bytes(left ^ right for left, right in zip(body, T7_STREAM))
    if not re.fullmatch(rb"[A-Za-z0-9_-]+", encoded):
        raise ValueError("the recovered t7 payload is not raw Base64")
    decoded = base64.urlsafe_b64decode(encoded + b"=" * (-len(encoded) % 4))
    match = re.fullmatch(rb"BHFlagY\{[^}\r\n]+\}", decoded)
    if not match:
        raise ValueError("decoded payload does not contain a valid flag")

    if verbose:
        print(f"[*] username       = {username}")
        print(f"[*] computer name  = {hostname}")
        print(f"[*] private scalar = {private_bytes.hex()}")
        print(f"[*] client public  = {client_public.hex()}")
        print(f"[*] session        = {session.decode()}")
        print(f"[*] server public  = {server_public.hex()}")
        print(f"[*] shared secret  = {shared_secret.hex()}")
        print(f"[*] final packet   = {token.decode()}, nonce={nonce.hex()}, tag={tag.hex()}")
        print(f"[*] raw Base64     = {encoded.decode()}")
    return decoded.decode()


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=root / "challenge" / "dist.zip",
        help="path to dist.zip or its extracted directory (default: dist.zip)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    arguments = parser.parse_args()
    with distribution(arguments.input) as root:
        sys.stdout.buffer.write(recover_flag(root, arguments.verbose).encode("ascii"))


if __name__ == "__main__":
    main()
