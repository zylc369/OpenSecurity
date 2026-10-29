"""remote_crypto 单元测试（P2: Noise NNpsk2; P3/P4 增补会话/帧/分片用例）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from services.remote_crypto import (
    CryptoError,
    FRAG_LIMIT,
    FRAG_TOTAL_MAX,
    FrameCodec,
    FrameError,
    Fragmenter,
    NoiseHandshake,
    PSK_LEN,
    PunchAuth,
    ReplayError,
    Reassembler,
    SessionCrypto,
    TcpFrameReader,
    TCP_FRAME_MAX,
    decode_msg,
    encode_msg,
)

def _load_vectors() -> "dict[str, list[dict[str, object]]]":
    """加载测试向量（json.loads Any 在此单点 cast 收口）。"""
    from typing import cast
    return cast(
        "dict[str, list[dict[str, object]]]",
        json.loads(
            (Path(__file__).parent.parent / "services" / "remote_relayd" / "vectors.json"
             ).read_text()))


VECTORS = _load_vectors()


def _psk() -> bytes:
    return bytes(range(PSK_LEN))


def test_noise_deterministic_vector() -> None:
    """确定性向量回放: 固定 PSK/私钥 → 消息与密钥逐字节复现。"""
    v = VECTORS["noise_nnposk2"][0]
    psk_hex = str(v["psk_hex"])
    init = NoiseHandshake(
        initiator=True, psk=bytes.fromhex(psk_hex),
        e_priv=X25519PrivateKey.from_private_bytes(bytes.fromhex(str(v["init_e_priv_hex"]))))
    resp = NoiseHandshake(
        initiator=False, psk=bytes.fromhex(psk_hex),
        e_priv=X25519PrivateKey.from_private_bytes(bytes.fromhex(str(v["resp_e_priv_hex"]))))
    msg1 = init.write_message()
    resp.read_message(msg1)
    msg2 = resp.write_message()
    init.read_message(msg2)
    assert msg1.hex() == str(v["msg1_hex"])
    assert msg2.hex() == str(v["msg2_hex"])
    assert init.handshake_hash.hex() == str(v["handshake_hash_hex"])
    i_send, i_recv = init.split()
    r_send, r_recv = resp.split()
    assert i_send.hex() == str(v["init_send_key_hex"])
    assert i_recv.hex() == str(v["init_recv_key_hex"])
    assert r_send.hex() == str(v["resp_send_key_hex"])
    assert r_recv.hex() == str(v["resp_recv_key_hex"])


def test_noise_roundtrip_random_keys() -> None:
    psk = _psk()
    init = NoiseHandshake(initiator=True, psk=psk)
    resp = NoiseHandshake(initiator=False, psk=psk)
    msg1 = init.write_message()
    resp.read_message(msg1)
    msg2 = resp.write_message()
    init.read_message(msg2)
    i_send, i_recv = init.split()
    r_send, r_recv = resp.split()
    assert i_send == r_recv and i_recv == r_send
    assert i_send != i_recv


def test_noise_with_payloads() -> None:
    psk = _psk()
    init = NoiseHandshake(initiator=True, psk=psk)
    resp = NoiseHandshake(initiator=False, psk=psk)
    msg1 = init.write_message(b"hello")
    assert resp.read_message(msg1) == b"hello"
    msg2 = resp.write_message(b"world")
    assert init.read_message(msg2) == b"world"


def test_noise_wrong_psk_rejected() -> None:
    init = NoiseHandshake(initiator=True, psk=_psk())
    resp = NoiseHandshake(initiator=False, psk=_psk()[:31] + b"\xff")
    msg1 = init.write_message()
    resp.read_message(msg1)
    msg2 = resp.write_message()
    with pytest.raises(InvalidTag):
        init.read_message(msg2)


def test_noise_message_tamper_rejected() -> None:
    psk = _psk()
    init = NoiseHandshake(initiator=True, psk=psk)
    resp = NoiseHandshake(initiator=False, psk=psk)
    msg1 = init.write_message()
    resp.read_message(msg1)
    msg2 = bytearray(resp.write_message())
    msg2[-1] ^= 0x01
    with pytest.raises(InvalidTag):
        init.read_message(bytes(msg2))


def test_noise_state_guards() -> None:
    hs = NoiseHandshake(initiator=True, psk=_psk())
    with pytest.raises(RuntimeError):
        hs.split()  # 握手未完成
    hs.write_message()
    with pytest.raises(RuntimeError):
        hs.write_message()  # 已完成本方操作
    hs2 = NoiseHandshake(initiator=False, psk=_psk())
    with pytest.raises(ValueError):
        hs2.read_message(b"\x01\x02")  # msg1 长度不足
    with pytest.raises(ValueError):
        NoiseHandshake(initiator=True, psk=b"short")  # PSK 长度非法


# ── P3: SessionCrypto / FrameCodec ─────────────────────


def _session_pair() -> tuple[SessionCrypto, SessionCrypto]:
    """从真实握手派生镜像会话密钥对。"""
    psk = _psk()
    init = NoiseHandshake(initiator=True, psk=psk)
    resp = NoiseHandshake(initiator=False, psk=psk)
    resp.read_message(init.write_message())
    init.read_message(resp.write_message())
    i_send, i_recv = init.split()
    r_send, r_recv = resp.split()
    return SessionCrypto(i_send, i_recv), SessionCrypto(r_send, r_recv)


def test_session_udp_roundtrip() -> None:
    a, b = _session_pair()
    codec = FrameCodec()
    ct, ctr = a.encrypt(b"hello p2p")
    wire = codec.pack_udp(ctr, ct)
    got_ctr, got_ct = codec.unpack_udp(wire)
    assert got_ctr == ctr and got_ct == ct
    assert b.decrypt(got_ct, got_ctr) == b"hello p2p"


def test_session_udp_replay_rejected() -> None:
    a, b = _session_pair()
    ct, ctr = a.encrypt(b"once")
    b.decrypt(ct, ctr)
    with pytest.raises(ReplayError):
        b.decrypt(ct, ctr)  # 重放同一计数器


def test_session_udp_out_of_order_accepted() -> None:
    a, b = _session_pair()
    ct1, c1 = a.encrypt(b"m1")
    ct2, c2 = a.encrypt(b"m2")
    assert b.decrypt(ct2, c2) == b"m2"  # 乱序先到可解
    assert b.decrypt(ct1, c1) == b"m1"


def test_session_tcp_seq_roundtrip_and_disorder() -> None:
    a, b = _session_pair()
    f1 = a.encrypt_seq(b"one")
    f2 = a.encrypt_seq(b"two")
    assert b.decrypt_seq(f1) == b"one"
    assert b.decrypt_seq(f2) == b"two"
    with pytest.raises(CryptoError):
        b.decrypt_seq(f2)  # 重复投递（计数器已过）→ 解密失败


def test_session_tamper_rejected() -> None:
    a, b = _session_pair()
    ct, ctr = a.encrypt(b"authentic")
    bad = ct[:-1] + bytes([ct[-1] ^ 0x01])
    with pytest.raises(CryptoError):
        b.decrypt(bad, ctr)


def test_frame_tcp_roundtrip_and_split_stream() -> None:
    p1, p2 = b"\x00\x01hello", b"world" * 100
    codec = FrameCodec()
    wire = codec.pack_tcp(p1) + codec.pack_tcp(p2)
    reader = TcpFrameReader()
    assert reader.feed(wire[:3]) == []          # 半个长度头
    assert reader.feed(wire[3:10]) == []        # 帧1（11B）还差 1 字节
    frames = reader.feed(wire[10:])
    assert frames == [p1, p2]


def test_frame_tcp_oversize_rejected() -> None:
    with pytest.raises(FrameError):
        FrameCodec().pack_tcp(b"x" * (TCP_FRAME_MAX + 1))
    reader = TcpFrameReader()
    with pytest.raises(FrameError):
        reader.feed((TCP_FRAME_MAX + 1).to_bytes(4, "big"))


def test_frame_udp_short_rejected() -> None:
    with pytest.raises(FrameError):
        FrameCodec().unpack_udp(b"\x01\x02")


# ── P4: 消息编解码 / punch_mac / 分片重组 ───────────────


def test_msg_codec_roundtrip_and_reject() -> None:
    msg: dict[str, object] = {"t": "api.req", "id": 7, "body": {"k": [1, 2.5, "s", b"\x01\x02"]}}
    data = encode_msg(msg)
    assert decode_msg(data) == msg
    with pytest.raises(CryptoError):
        decode_msg(b"\xd4\x01")          # 非 dict msgpack
    with pytest.raises(CryptoError):
        decode_msg(b"\xff\xff garbage")  # 非法字节


def test_punch_mac_vector() -> None:
    v = VECTORS["punch_mac"][0]
    auth = PunchAuth(bytes.fromhex(str(v["psk_hex"])))
    assert auth.mac(str(v["sid"])) == str(v["mac_hex"])
    assert auth.verify(str(v["sid"]), str(v["mac_hex"]))
    assert len(str(v["mac_hex"])) == 16


def test_frag_split_reassemble_in_order() -> None:
    big = bytes((i * 11 + 5) & 0xFF for i in range(FRAG_LIMIT * 2 + 77))
    frags = Fragmenter().split(big, msg_id=9)
    assert len(frags) == 3 and not Fragmenter.need_split(b"short")
    reasm: Reassembler | None = None
    out: bytes | None = None
    for f in frags:
        if reasm is None:
            reasm = Reassembler(f)
            if reasm.msg_id != 9:
                raise AssertionError
        else:
            out = reasm.feed(f)
    assert out == big


def test_frag_out_of_order_and_duplicate() -> None:
    big = b"x" * (FRAG_LIMIT + 10)
    frags = Fragmenter().split(big, msg_id=1)
    r = Reassembler(frags[1])            # 后片先到
    assert r.feed(frags[0]) == big       # 集齐即出
    assert r.due_nack() is None          # 已齐不再 NACK


def test_frag_nack_and_dead() -> None:
    from services.remote_crypto import Fragmenter, Reassembler
    now = {"t": 0.0}

    def clock() -> float:
        return now["t"]

    big = b"y" * (FRAG_LIMIT * 2)
    frags = Fragmenter().split(big, msg_id=3)
    r = Reassembler(frags[0], clock=clock)
    now["t"] = 0.05
    assert r.due_nack() is None          # 窗口未到
    now["t"] = 0.11
    nack = r.due_nack()
    assert nack is not None and nack["missing"] == [1]  # type: ignore[index]
    now["t"] = 0.21
    nack2 = r.due_nack()
    assert nack2 is not None and nack2["missing"]  # type: ignore[index]
    now["t"] = 0.31
    nack3 = r.due_nack()
    assert nack3 is not None
    now["t"] = 0.41
    assert r.due_nack() is None and r.dead  # 3 轮耗尽 → dead
    assert r.feed(frags[1]) is None     # dead 后分片不再受理


def test_frag_oversize_rejected() -> None:
    huge = b"z" * (FRAG_LIMIT * FRAG_TOTAL_MAX + 1)
    with pytest.raises(CryptoError):
        Fragmenter().split(huge, msg_id=1)


def test_udp_replay_after_prune_rejected() -> None:
    """剪枝后重放窗口仍拒绝（review #3 回归——水位不依赖 set 大小）。"""
    a, b = _session_pair()
    # 交换 >SET_LIMIT 帧触发剪枝，随后重放早期帧
    replay_ct, replay_ctr = None, -1
    for i in range(1200):
        ct, ctr = a.encrypt(f"msg-{i}".encode())
        if i == 500:
            replay_ct, replay_ctr = ct, ctr
        b.decrypt(ct, ctr)
    assert replay_ct is not None
    with pytest.raises(ReplayError):
        b.decrypt(replay_ct, replay_ctr)
