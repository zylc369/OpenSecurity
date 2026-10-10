"""生成 protocol.md 附录 B 的 vectors.json（确定性: 固定 PSK/私钥）。

用法: cd backend && python3 -m services.remote_relayd.gen_vectors
输出: services/remote_relayd/vectors.json（Kotlin 单测消费同一文件）
"""
from __future__ import annotations

import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from typing import cast

from services.remote_crypto import (
    FRAG_LIMIT,
    FrameCodec,
    Fragmenter,
    NoiseHandshake,
    PSK_LEN,
    PunchAuth,
    SessionCrypto,
    encode_msg,
)

OUT = Path(__file__).parent / "vectors.json"


def _seq(f: dict[str, object]) -> int:
    return cast("int", f["seq"])


def noise_vector() -> dict[str, str]:
    psk = bytes(range(PSK_LEN))
    e_init = X25519PrivateKey.from_private_bytes(b"\x01" * 32)
    e_resp = X25519PrivateKey.from_private_bytes(b"\x02" * 32)
    init = NoiseHandshake(initiator=True, psk=psk, e_priv=e_init)
    resp = NoiseHandshake(initiator=False, psk=psk, e_priv=e_resp)
    msg1 = init.write_message()
    resp.read_message(msg1)
    msg2 = resp.write_message()
    init.read_message(msg2)
    i_send, i_recv = init.split()
    r_send, r_recv = resp.split()
    assert i_send == r_recv and i_recv == r_send
    return {
        "psk_hex": psk.hex(),
        "init_e_priv_hex": (b"\x01" * 32).hex(),
        "resp_e_priv_hex": (b"\x02" * 32).hex(),
        "msg1_hex": msg1.hex(),
        "msg2_hex": msg2.hex(),
        "handshake_hash_hex": init.handshake_hash.hex(),
        "init_send_key_hex": i_send.hex(),
        "init_recv_key_hex": i_recv.hex(),
        "resp_send_key_hex": r_send.hex(),
        "resp_recv_key_hex": r_recv.hex(),
    }


def session_and_frame_vectors(noise: dict[str, str]) -> dict[str, list[dict[str, object]]]:
    """会话加密 + 帧封装 + 分片 + punch_mac 向量（基于 noise 向量的确定性密钥）。"""
    codec = FrameCodec()
    key_send = bytes.fromhex(noise["init_send_key_hex"])
    key_recv = bytes.fromhex(noise["resp_send_key_hex"])

    session: list[dict[str, object]] = []
    s = SessionCrypto(key_send, key_recv)
    pt = b'{"t":"ping"}'
    ct, ctr = s.encrypt(pt)
    session.append({"key_hex": key_send.hex(), "counter": ctr, "plaintext_hex": pt.hex(),
                    "ciphertext_hex": ct.hex()})

    udp_wire: list[dict[str, object]] = []
    for v in session:
        wire = codec.pack_udp(cast("int", v["counter"]),
                                   bytes.fromhex(str(v["ciphertext_hex"])))
        udp_wire.append({"key_hex": v["key_hex"], "counter": v["counter"],
                         "plaintext_hex": v["plaintext_hex"], "wire_hex": wire.hex()})

    tcp_frame: list[dict[str, object]] = []
    for payload in (b"\x00\x01hi", encode_msg({"t": "pong", "ts": 1.5})):
        tcp_frame.append({"payload_hex": payload.hex(),
                          "wire_hex": codec.pack_tcp(payload).hex()})

    big = bytes((i * 7 + 3) & 0xFF for i in range(FRAG_LIMIT * 2 + 123))
    codec = FrameCodec()
    frags = Fragmenter().split(big, msg_id=42)
    frag: dict[str, object] = {
        "plaintext_hex": big.hex(), "id": 42,
        "frags": [{"seq": _seq(f), "msg_hex": encode_msg(f).hex()} for f in frags]}

    punch: list[dict[str, object]] = [{"psk_hex": noise["psk_hex"], "sid": "ab" * 16,
              "mac_hex": PunchAuth(bytes.fromhex(noise["psk_hex"])).mac("ab" * 16)}]
    return {"session_roundtrip": session, "tcp_frame": tcp_frame,
            "udp_frame": udp_wire, "frag": [frag], "punch_mac": punch}


def main() -> None:
    noise = noise_vector()
    data: dict[str, object] = {"noise_nnposk2": [noise], **session_and_frame_vectors(noise)}
    OUT.write_text(json.dumps(data, indent=2) + "\n")
    print(f"written: {OUT}")


if __name__ == "__main__":
    main()
