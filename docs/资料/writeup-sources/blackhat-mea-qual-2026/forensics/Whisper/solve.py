#!/usr/bin/env python3
"""Recover the exfiltrated CSV bundle and print the Whisper flag."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tarfile
import tempfile
import zipfile

try:
    import pyzipper
except ImportError:
    print("error: install dependencies with 'python -m pip install -r requirements.txt'", file=sys.stderr)
    raise SystemExit(2)


TAR_HISTORY = "whisper_evidence/home/dwright/.ollama/history"
TAR_SCRIPT = "whisper_evidence/home/dwright/.local/share/Trash/files/cache_mgr.py"
TAR_SESSION_ZIP = "whisper_evidence/home/dwright/.cache/fontconfig/session.zip"
FLAG_PATTERN = re.compile(r"BHFlagY\{[^{}\r\n]+\}\Z")


def fail(message: str) -> "NoReturn":
    raise RuntimeError(message)


def read_tar_member(tf: tarfile.TarFile, name: str) -> bytes:
    try:
        member = tf.getmember(name)
    except KeyError as exc:
        fail(f"missing tar member: {name}")
        raise AssertionError from exc
    if not member.isfile():
        fail(f"tar member is not a regular file: {name}")
    stream = tf.extractfile(member)
    if stream is None:
        fail(f"cannot read tar member: {name}")
    return stream.read()


def recover_bundle(evidence_zip: Path) -> tuple[dict[str, bytes], str]:
    with zipfile.ZipFile(evidence_zip) as outer:
        candidates = [
            item
            for item in outer.infolist()
            if not item.is_dir() and item.filename.endswith(".tar.gz")
        ]
        if len(candidates) != 1:
            fail(f"expected one .tar.gz member, found {len(candidates)}")

        with tempfile.TemporaryDirectory(prefix="whisper-solve-") as temp_dir:
            tar_path = Path(temp_dir) / "evidence.tar.gz"
            with outer.open(candidates[0]) as source, tar_path.open("wb") as target:
                shutil.copyfileobj(source, target)

            with tarfile.open(tar_path, "r:gz") as tf:
                history = read_tar_member(tf, TAR_HISTORY).decode("utf-8")
                deleted_script = read_tar_member(tf, TAR_SCRIPT).decode("utf-8")
                session_zip = read_tar_member(tf, TAR_SESSION_ZIP)

    password_match = re.search(r"^use the password (\S+)\s*$", history, re.MULTILINE)
    if password_match is None:
        fail("Ollama history does not contain the archive passphrase")
    raw_passphrase = password_match.group(1)

    required_markers = ("hashlib.blake2b", "digest_size=32", ".hexdigest()[:20]")
    if not all(marker in deleted_script for marker in required_markers):
        fail("deleted script does not contain the expected key derivation")
    archive_password = hashlib.blake2b(
        raw_passphrase.encode("utf-8"), digest_size=32
    ).hexdigest()[:20]

    recovered: dict[str, bytes] = {}
    with pyzipper.AESZipFile(io.BytesIO(session_zip)) as encrypted:
        encrypted.setpassword(archive_password.encode("ascii"))
        for info in encrypted.infolist():
            member_path = PurePosixPath(info.filename)
            if info.is_dir():
                continue
            if member_path.is_absolute() or ".." in member_path.parts:
                fail(f"unsafe encrypted ZIP member: {info.filename}")
            recovered[info.filename] = encrypted.read(info)

    return recovered, archive_password


def write_recovered_files(files: dict[str, bytes], output_dir: Path) -> None:
    root = output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        target = (root / PurePosixPath(name)).resolve()
        if os.path.commonpath((str(root), str(target))) != str(root):
            fail(f"unsafe recovery target: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != data:
            fail(f"refusing to overwrite a different file: {target}")
        target.write_bytes(data)


def extract_flag(internal_keys: bytes) -> str:
    rows = csv.DictReader(io.StringIO(internal_keys.decode("utf-8"), newline=""))
    matches = [row for row in rows if row.get("service") == "master_vault"]
    if len(matches) != 1:
        fail(f"expected one master_vault row, found {len(matches)}")
    encoded = matches[0].get("key_b64", "")
    try:
        flag = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        fail(f"invalid master_vault Base64 value: {exc}")
    if FLAG_PATTERN.fullmatch(flag) is None:
        fail(f"decoded value does not match the flag format: {flag!r}")
    return flag


def parse_args() -> argparse.Namespace:
    default_evidence = (
        Path(__file__).resolve().parent / "challenge" / "whisper_evidence.tar.zip"
    )
    parser = argparse.ArgumentParser(
        description="Recover Whisper's AES ZIP from the Linux triage archive."
    )
    parser.add_argument(
        "evidence",
        nargs="?",
        type=Path,
        default=default_evidence,
        help=f"path to whisper_evidence.tar.zip (default: {default_evidence})",
    )
    parser.add_argument(
        "--recover-dir",
        type=Path,
        help="optional directory in which to recover all five CSV files",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if not args.evidence.is_file():
            fail(f"evidence archive not found: {args.evidence}")
        recovered, _archive_password = recover_bundle(args.evidence)
        internal_keys = recovered.get("internal_api_keys.csv")
        if internal_keys is None:
            fail("internal_api_keys.csv is missing from the encrypted ZIP")
        if args.recover_dir is not None:
            write_recovered_files(recovered, args.recover_dir)
        sys.stdout.buffer.write(extract_flag(internal_keys).encode("ascii"))
        return 0
    except (OSError, RuntimeError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
