#!/usr/bin/env python3
"""Recover the 16-byte GCM nonce from captured 48/49/50-byte tags."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from Crypto.Cipher import AES

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import experimental_sat_solver as rrr


def inc32(block: bytes, amount: int) -> bytes:
    return block[:12] + ((int.from_bytes(block[12:], "big") + amount) & 0xFFFFFFFF).to_bytes(4, "big")


def recover_nonce(key: bytes, h: int, tags: list[bytes]) -> tuple[bytes, bytes, int]:
    plaintexts = [char.encode() + rrr.FIXED + key.hex().encode() for char in rrr.PROBE_CHARS]
    if [len(plaintexts[i]) for i in (3, 4, 5)] != [48, 49, 50]:
        raise AssertionError("probe lengths changed")
    y48, y49, y50 = [
        int.from_bytes(tags[i], "big") ^ rrr.ghash_ciphertext_shape(plaintexts[i], h)
        for i in (3, 4, 5)
    ]
    h2 = rrr.gf_mul(h, h)
    inverse_h2 = rrr.gf_pow(h2, (1 << 128) - 2)

    # The 49->50 transition reveals byte 1 of the fourth CTR block.
    second_block = rrr.gf_mul(y49 ^ y50, inverse_h2).to_bytes(16, "big")
    if second_block[:1] != b"\0" or second_block[2:] != bytes(14):
        raise ValueError(f"unexpected 49/50 stream delta shape: {second_block.hex()}")
    fourth_byte_1 = second_block[1]

    # Y48 = M + E1*H^4 + E2*H^3 + E3*H^2
    # Y49 = M + E1*H^5 + E2*H^4 + E3*H^3 + trunc1(E4)*H^2
    # Hence Y49 + H*Y48 = (1+H)M + trunc1(E4)*H^2.
    z = y49 ^ rrr.gf_mul(y48, h)
    denominator = rrr.FIELD_ONE ^ h
    if denominator == 0:
        raise ValueError("degenerate H=1 instance")
    inverse_denominator = rrr.gf_pow(denominator, (1 << 128) - 2)
    aes = AES.new(key, AES.MODE_ECB)
    matches = []
    for fourth_byte_0 in range(256):
        partial_e4 = int.from_bytes(bytes([fourth_byte_0]) + bytes(15), "big")
        mask = rrr.gf_mul(z ^ rrr.gf_mul(partial_e4, h2), inverse_denominator)
        j0 = aes.decrypt(mask.to_bytes(16, "big"))
        e4 = aes.encrypt(inc32(j0, 4))
        if e4[0] == fourth_byte_0 and e4[1] == fourth_byte_1:
            matches.append((j0, mask.to_bytes(16, "big")))
    if len(matches) != 1:
        raise ValueError(f"expected one J0 candidate, got {len(matches)}")
    j0, mask = matches[0]

    nonce_length_block = (128).to_bytes(16, "big")
    nonce_value = rrr.gf_mul(
        int.from_bytes(j0, "big") ^ rrr.gf_mul(int.from_bytes(nonce_length_block, "big"), h),
        inverse_h2,
    )
    nonce = nonce_value.to_bytes(16, "big")
    for plaintext, wanted in zip(plaintexts, tags):
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        cipher.encrypt(plaintext)
        if cipher.digest() != wanted:
            raise ValueError("recovered nonce fails full local tag verification")
    return nonce, j0, fourth_byte_1


def main() -> None:
    data = json.loads((HERE / "live-session.json").read_text())
    key = bytes.fromhex(data["key0"])
    h = int(data["H"], 16)
    tags = [bytes.fromhex(item) for item in data["full"]]
    nonce, j0, byte1 = recover_nonce(key, h, tags)
    print(json.dumps({"key1": nonce.hex(), "J0": j0.hex(), "E4_byte1": byte1}, indent=2))


if __name__ == "__main__":
    main()
