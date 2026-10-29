#!/usr/bin/env python3
"""Recover the Qfact Defender-quarantined HTA and decrypt the affected files.

The script never executes the recovered HTA. It treats Evidence.zip as immutable
input, decodes the Defender quarantine container, derives the ransomware keying
material from recovered evidence, and writes recovered artifacts under --output.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import struct
import sys
import zipfile
from pathlib import Path, PurePosixPath

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad


DEFENDER_QUARANTINE_RC4_KEY = bytes.fromhex(
    "1E87781B8DBAA844CE69702C0C78B786A3F623B738F5EDF9AF83530FB3FC54FA"
    "A21EB9CF1331FD0F0DA954F687CB9E18279697900E53FB317C9CBCE48E23D053"
    "71ECC15951B8F3649D7CA33ED68DC9047E82C9BAAD9799D0D458CB847CA9FFBE"
    "3C8A775233557DDE13A8B14087CC1BC8F10F6ECDD083A959CFF84A9D1D50755E"
    "3E191818AF23E2293558766D2C07E25712B2CA0B535ED8F6C56CE73D24BDD029"
    "1771861A54B4C285A9A3DB7ACA6D224AEACD621DB9F2A22ED1E9E11D75BED7DC"
    "0ECB0A8E68A2FF1263408DC808DFFD164B116774CD0B9B8D05411ED6262E429B"
    "A495676B8398DB2F35D3C1B9CED52636F2765E1A95CB7CA4C3DDABDDBFF38253"
)

FLAG_RE = re.compile(rb"(?:BHFlagY|flag|[A-Za-z]+CTF)\{[^}\r\n]{1,200}\}")
BASE64_RE = re.compile(rb"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{20,}={0,2}(?![A-Za-z0-9+/])")


class SolverError(RuntimeError):
    """Raised when the evidence does not satisfy an expected invariant."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_member_name(raw_name: str) -> str:
    """Normalize ZIP separators and reject absolute/traversal member names."""
    name = raw_name.replace("\\", "/")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise SolverError(f"unsafe ZIP member: {raw_name!r}")
    return path.as_posix()


def rc4_crypt(data: bytes) -> bytes:
    """Apply the fixed RC4 protection used by Microsoft Defender quarantine."""
    if len(DEFENDER_QUARANTINE_RC4_KEY) != 256:
        raise SolverError("invalid Defender RC4 key length")

    sbox = list(range(256))
    j = 0
    for i in range(256):
        j = (j + sbox[i] + DEFENDER_QUARANTINE_RC4_KEY[i]) & 0xFF
        sbox[i], sbox[j] = sbox[j], sbox[i]

    out = bytearray(len(data))
    i = j = 0
    for offset, value in enumerate(data):
        i = (i + 1) & 0xFF
        j = (j + sbox[i]) & 0xFF
        sbox[i], sbox[j] = sbox[j], sbox[i]
        out[offset] = value ^ sbox[(sbox[i] + sbox[j]) & 0xFF]
    return bytes(out)


def defender_streams(resource_data: bytes) -> list[tuple[int, str, bytes]]:
    """Parse a decrypted sequence of WIN32_STREAM_ID records."""
    clear = rc4_crypt(resource_data)
    streams: list[tuple[int, str, bytes]] = []
    offset = 0

    while offset < len(clear):
        if len(clear) - offset < 20:
            raise SolverError("truncated WIN32_STREAM_ID header")
        stream_id, _attributes, size, name_size = struct.unpack_from("<IIQI", clear, offset)
        offset += 20
        if name_size % 2 or offset + name_size + size > len(clear):
            raise SolverError("invalid Defender stream bounds")
        name_raw = clear[offset : offset + name_size]
        offset += name_size
        name = name_raw.decode("utf-16-le") if name_raw else ""
        payload = clear[offset : offset + size]
        offset += size
        streams.append((stream_id, name, payload))

    return streams


def carve_wide_ascii(data: bytes, minimum: int = 4) -> list[str]:
    pattern = rb"(?:[\x20-\x7e]\x00){" + str(minimum).encode() + rb",}"
    return [match.group().decode("utf-16-le") for match in re.finditer(pattern, data)]


def decode_windows_text(data: bytes) -> str:
    """Decode common Windows text encodings without lossy fallback."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    return data.decode("utf-8-sig")


def parse_identity(note: bytes, defender_log: bytes) -> tuple[str, str]:
    note_text = decode_windows_text(note)
    match = re.search(
        r"Unique ID:\s*LOCK-(?P<machine>.+)-(?P<initials>[A-Z]{2})-\d{8}-[A-Z0-9]+",
        note_text,
    )
    if not match:
        raise SolverError("could not recover machine name from ransom note")

    machine = match.group("machine")
    initials = match.group("initials")
    # EVTX BinXML value strings are carved as one contiguous UTF-16 run. The
    # username is followed by the next field (file:_...) or the AV version.
    identity_re = re.compile(
        re.escape(machine) + r"\\([A-Za-z0-9_.-]+?)(?=file:_|AV:)", re.IGNORECASE
    )
    usernames: set[str] = set()
    for carved in carve_wide_ascii(defender_log):
        usernames.update(identity_re.findall(carved))
    usernames = {name for name in usernames if name[:2].upper() == initials}
    if len(usernames) != 1:
        raise SolverError(f"expected one matching username, got {sorted(usernames)!r}")
    return machine, usernames.pop()


def parse_ransomware_secret(hta: bytes) -> str:
    text = decode_windows_text(hta)
    key_block = re.search(r"Dim k(?P<body>.*?)Dim ps", text, flags=re.DOTALL | re.IGNORECASE)
    if not key_block:
        raise SolverError("could not locate the HTA key-construction block")
    codepoints = [int(value) for value in re.findall(r"Chr\((\d+)\)", key_block.group("body"))]
    if not codepoints or any(value > 0x7F for value in codepoints):
        raise SolverError("invalid HTA Chr() key construction")
    return "".join(map(chr, codepoints))


def decrypt_file(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    if not ciphertext or len(ciphertext) % AES.block_size:
        raise SolverError("encrypted file is not a non-empty AES block sequence")
    padded = AES.new(key, AES.MODE_CBC, iv).decrypt(ciphertext)
    try:
        return unpad(padded, AES.block_size, style="pkcs7")
    except ValueError as exc:
        raise SolverError("AES-CBC padding validation failed") from exc


def find_flags(data: bytes) -> set[bytes]:
    """Find plaintext flags and flags wrapped once in standard Base64."""
    found = set(FLAG_RE.findall(data))
    for candidate in BASE64_RE.findall(data):
        try:
            decoded = base64.b64decode(candidate, validate=True)
        except (ValueError, base64.binascii.Error):
            continue
        found.update(FLAG_RE.findall(decoded))
    return found


def solve(evidence_path: Path, output_dir: Path) -> list[str]:
    if not evidence_path.is_file():
        raise SolverError(f"evidence file not found: {evidence_path}")
    archive_bytes = evidence_path.read_bytes()

    with zipfile.ZipFile(evidence_path) as archive:
        if archive.testzip() is not None:
            raise SolverError("ZIP CRC validation failed")
        members = {safe_member_name(info.filename): info for info in archive.infolist()}

        note_info = members.get("READ_ME.txt")
        defender_info = members.get("EventLogs/Defender-Operational.evtx")
        if note_info is None or defender_info is None:
            raise SolverError("required note or Defender event log is missing")
        note = archive.read(note_info)
        defender_log = archive.read(defender_info)

        hta_candidates: list[bytes] = []
        for name, info in members.items():
            if not name.startswith("Quarantine/ResourceData/") or name.endswith("/"):
                continue
            for stream_id, _stream_name, payload in defender_streams(archive.read(info)):
                if stream_id == 1 and b"<html>" in payload.lower() and b"VBScript" in payload:
                    hta_candidates.append(payload)
        if len(hta_candidates) != 1:
            raise SolverError(f"expected one quarantined HTA, got {len(hta_candidates)}")
        hta = hta_candidates[0]

        passphrase = parse_ransomware_secret(hta)
        machine, username = parse_identity(note, defender_log)
        key = passphrase.ljust(32)[:32].encode("utf-8")
        if len(key) != 32:
            raise SolverError("derived AES key is not 32 bytes")
        iv = hashlib.md5((machine + username).encode("utf-8")).digest()

        recovered_root = output_dir / "recovered"
        recovered_root.mkdir(parents=True, exist_ok=True)
        hta_path = recovered_root / "Q3_Financial_Review.hta.txt"
        hta_path.write_bytes(hta)

        recovered: list[dict[str, object]] = []
        flags: set[bytes] = set()
        encrypted_names = sorted(
            name for name in members if name.startswith("EncryptedFiles/") and name.endswith(".enc")
        )
        if not encrypted_names:
            raise SolverError("no encrypted files found")

        for name in encrypted_names:
            ciphertext = archive.read(members[name])
            plaintext = decrypt_file(ciphertext, key, iv)
            relative = PurePosixPath(name.removeprefix("EncryptedFiles/").removesuffix(".enc"))
            destination = recovered_root.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(plaintext)
            flags.update(find_flags(plaintext))
            recovered.append(
                {
                    "path": destination.relative_to(output_dir).as_posix(),
                    "size": len(plaintext),
                    "sha256": sha256(plaintext),
                }
            )

    decoded_flags = sorted(flag.decode("ascii") for flag in flags)
    if len(decoded_flags) != 1:
        raise SolverError(f"expected one unique flag, got {decoded_flags!r}")

    manifest = {
        "evidence": {
            "path": str(evidence_path.resolve()),
            "size": len(archive_bytes),
            "sha256": sha256(archive_bytes),
        },
        "identity": {"computer": machine, "username": username},
        "recovered_hta": {
            "path": hta_path.relative_to(output_dir).as_posix(),
            "size": len(hta),
            "sha256": sha256(hta),
        },
        "decrypted_files": recovered,
        "flag_count": len(decoded_flags),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    return decoded_flags


def main() -> int:
    challenge_dir = Path(__file__).resolve().parent
    default_evidence = challenge_dir / "challenge" / "Evidence.zip"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", nargs="?", type=Path, default=default_evidence)
    parser.add_argument("--output", type=Path, default=challenge_dir / "output")
    args = parser.parse_args()

    try:
        flags = solve(args.evidence.resolve(), args.output.resolve())
    except (OSError, zipfile.BadZipFile, SolverError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(flags[0].encode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
