"""remote-p2p 加密基元（wire protocol 权威规范: services/remote_relayd/protocol.md）。

分段交付:
- P2: NoiseHandshake（Noise NNpsk2 握手状态机，X25519 + ChaChaPoly + SHA-256）
- P3: SessionCrypto（会话计数器加解密）+ FrameCodec（TCP/UDP 帧）
- P4: Fragmenter/Reassembler（UDP 分片重组）

三端对齐判据: protocol.md 附录 B vectors.json（本模块生成，Kotlin 单测消费）。
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import cast

import msgpack
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

PROTOCOL_NAME = b"Noise_NNpsk2_25519_ChaChaPoly_SHA256"
NOISE_TAG_LEN = 16  # ChaCha20-Poly1305 AEAD tag
PSK_LEN = 32
TCP_FRAME_MAX = 8 << 20  # 8 MiB 防御上限（TTS 音频/OCR 图片量级; protocol.md §9）


class CryptoError(RuntimeError):
    """加解密/防重放/帧格式错误统一面。"""


class ReplayError(CryptoError):
    """UDP 计数器重复/过旧（防重放拦截）。"""


class FrameError(CryptoError):
    """帧格式非法（长度越界/截断）。"""


def _nonce(counter: int) -> bytes:
    """ChaCha20-Poly1305 nonce: 计数器 8B 小端 + 4B 零填充。"""
    return counter.to_bytes(8, "little") + b"\x00" * 4


class NoiseCipherSuite:
    """Noise 原语套件（SHA-256 / HMAC / HKDF / ChaCha20-Poly1305）。

    无状态但成组演化的密码原语收口为一等对象——握手/会话/向量生成
    共享同一实例（依赖注入点=单测替换假原语; 模块级散函数不可审计）。
    """

    @staticmethod
    def sha256(data: bytes) -> bytes:
        return hashlib.sha256(data).digest()

    @staticmethod
    def hmac_sha256(key: bytes, data: bytes) -> bytes:
        return hmac.new(key, data, hashlib.sha256).digest()

    def hkdf(self, chaining_key: bytes, ikm: bytes, n: int) -> list[bytes]:
        """Noise HKDF（标准 expand，无 info）: temp=HMAC(ck,ikm); out_i=HMAC(temp,out_{i-1}||i)。"""
        temp = self.hmac_sha256(chaining_key, ikm)
        outputs: list[bytes] = []
        prev = b""
        for i in range(1, n + 1):
            prev = self.hmac_sha256(temp, prev + bytes([i]))
            outputs.append(prev)
        return outputs


#: 模块共享原语套件（三端一致的单一实例; gen_vectors/测试经此对齐）
CIPHER = NoiseCipherSuite()


class NoiseHandshake:
    """Noise NNpsk2 握手状态机（协议: NNpsk2 = -> e / <- e, ee, psk）。

    用法:
        init = NoiseHandshake(initiator=True, psk=psk)
        resp = NoiseHandshake(initiator=False, psk=psk)
        msg1 = init.write_message()          # -> e（32B 临时公钥 + 可选明文 payload）
        resp.read_message(msg1)
        msg2 = resp.write_message()          # <- e, ee, psk（32B 公钥 + AEAD 密文 16B tag）
        init.read_message(msg2)
        send_k, recv_k = init.split()        # 与 responder 的 (recv, send) 互为镜像
    """

    def __init__(self, initiator: bool, psk: bytes,
                 e_priv: X25519PrivateKey | None = None,
                 cipher: NoiseCipherSuite | None = None) -> None:
        if len(psk) != PSK_LEN:
            raise ValueError(f"PSK 必须为 {PSK_LEN} 字节")
        self._cipher = cipher or CIPHER
        if len(PROTOCOL_NAME) <= 32:
            self._h: bytes = PROTOCOL_NAME + b"\x00" * (32 - len(PROTOCOL_NAME))
        else:
            self._h = self._cipher.sha256(PROTOCOL_NAME)
        self._ck: bytes = self._h
        self._k: bytes | None = None
        self._nonce = 0  # 握手内 AEAD 计数器（独立于会话计数器）
        self._psk = psk
        self._initiator = initiator
        self._e: X25519PrivateKey = e_priv if e_priv is not None \
            else X25519PrivateKey.generate()
        self._e_remote: X25519PublicKey | None = None
        self._step = 0  # NNpsk2 两消息: initiator=write+read / responder=read+write
        self._done = False
        # 交替守卫: initiator=write→read / responder=read→write
        self._expect = "write" if initiator else "read"

    # ── 状态机原语 ─────────────────────────────────────

    def _mix_hash(self, data: bytes) -> None:
        self._h = self._cipher.sha256(self._h + data)

    def _mix_key(self, ikm: bytes) -> None:
        o1, o2 = self._cipher.hkdf(self._ck, ikm, 2)
        self._ck, self._k = o1, o2

    def _mix_key_and_hash(self, ikm: bytes) -> None:
        o1, o2, o3 = self._cipher.hkdf(self._ck, ikm, 3)
        self._ck, self._k = o1, o3
        self._mix_hash(o2)

    def _encrypt_and_hash(self, plaintext: bytes) -> bytes:
        if self._k is None:
            ct = plaintext  # 无密钥: 明文附加（nonce 不递增——规范仅在实际 AEAD 时计数）
        else:
            ct = ChaCha20Poly1305(self._k).encrypt(
                self._nonce.to_bytes(12, "little"), plaintext, self._h)
            self._nonce += 1
        self._mix_hash(ct)
        return ct

    def _decrypt_and_hash(self, ciphertext: bytes) -> bytes:
        if self._k is None:
            pt = ciphertext
        else:
            pt = ChaCha20Poly1305(self._k).decrypt(
                self._nonce.to_bytes(12, "little"), ciphertext, self._h)
            self._nonce += 1
        self._mix_hash(ciphertext)
        return pt

    def _dh(self) -> bytes:
        assert self._e_remote is not None
        return self._e.exchange(self._e_remote)

    # ── 消息读写 ───────────────────────────────────────

    @property
    def handshake_hash(self) -> bytes:
        """握手哈希（会话绑定/channel binding 用）。"""
        return self._h

    def _advance(self) -> None:
        self._step += 1
        self._done = self._step >= 2
        self._expect = "read" if self._expect == "write" else "write"

    def _check_op(self, op: str) -> None:
        if self._done or op != self._expect:
            raise RuntimeError("握手已完成或操作次序错误")

    def write_message(self, payload: bytes = b"") -> bytes:
        self._check_op("write")
        if self._initiator:
            # msg1: -> e
            ep = self._e.public_key().public_bytes_raw()
            self._mix_hash(ep)
            body = self._encrypt_and_hash(payload)  # k=None → 明文附加 + MixHash
            self._advance()
            return ep + body
        # msg2: <- e, ee, psk
        ep = self._e.public_key().public_bytes_raw()
        self._mix_hash(ep)
        self._mix_key(self._dh())          # ee
        self._mix_key_and_hash(self._psk)  # psk（token 位置 2）
        body = self._encrypt_and_hash(payload)
        self._advance()
        return ep + body

    def read_message(self, message: bytes) -> bytes:
        """返回对端附带的 payload。"""
        self._check_op("read")
        if self._initiator:
            # msg2: <- e, ee, psk
            if len(message) < 32 + NOISE_TAG_LEN:
                raise ValueError("msg2 长度不足")
            self._e_remote = X25519PublicKey.from_public_bytes(message[:32])
            self._mix_hash(message[:32])
            self._mix_key(self._dh())
            self._mix_key_and_hash(self._psk)
            payload = self._decrypt_and_hash(message[32:])
            self._advance()
            return payload
        # msg1: -> e
        if len(message) < 32:
            raise ValueError("msg1 长度不足")
        self._e_remote = X25519PublicKey.from_public_bytes(message[:32])
        self._mix_hash(message[:32])
        payload = self._decrypt_and_hash(message[32:])
        self._advance()
        return payload

    def split(self) -> tuple[bytes, bytes]:
        """握手完成后派生 (send_key, recv_key)——按角色定向。

        initiator: send=k1 recv=k2; responder: send=k2 recv=k1。
        """
        if not self._done:
            raise RuntimeError("握手未完成")
        k1, k2 = self._cipher.hkdf(self._ck, b"", 2)
        return (k1, k2) if self._initiator else (k2, k1)


class SessionCrypto:
    """会话加解密（protocol.md §3.3）。

    两套 API 按承载二选一（同一实例禁止混用）:
    - TCP（字节流严格有序）: encrypt_seq/decrypt_seq 隐式计数器，乱序即 CryptoError
    - UDP（数据报可乱序）: encrypt/decrypt 显式计数器 + 防重放窗口
    """

    _WINDOW = 64        # 已见集合超限时保留的滑动窗口
    _SET_LIMIT = 1024   # 已见集合条目上限（超限退化为窗口模式）

    def __init__(self, send_key: bytes, recv_key: bytes) -> None:
        self._send = ChaCha20Poly1305(send_key)
        self._recv = ChaCha20Poly1305(recv_key)
        self._send_ctr = 0
        self._recv_ctr = 0          # TCP 隐式接收计数
        self._udp_seen: set[int] = set()
        self._udp_max = -1
        self._udp_floor = -1        # 剪枝水位：低于此值一律拒绝（防重放不依赖 set 大小）

    # ── UDP 显式计数器 ────────────────────────────────

    def encrypt(self, plaintext: bytes) -> tuple[bytes, int]:
        """返回 (密文, 计数器)——封 UDP 帧时显式携带计数器。"""
        ctr = self._send_ctr
        self._send_ctr += 1
        return self._send.encrypt(_nonce(ctr), plaintext, b""), ctr

    def decrypt(self, ciphertext: bytes, ctr: int) -> bytes:
        """UDP 显式计数器解密; 重复/低于水位抛 ReplayError（protocol.md §3.3）。

        防重放三重判定: ①已见集合 ②低于剪枝水位（水位=max-WINDOW，剪枝时抬升）
        ③窗口内但早已见过。水位独立于 set 大小——长会话剪枝后依然拒绝旧帧。
        """
        if ctr in self._udp_seen or (self._udp_floor >= 0 and ctr <= self._udp_floor):
            raise ReplayError(f"UDP 计数器重复或过旧: {ctr}")
        try:
            plaintext = self._recv.decrypt(_nonce(ctr), ciphertext, b"")
        except InvalidTag as e:
            raise CryptoError("会话解密失败(InvalidTag)") from e
        self._udp_seen.add(ctr)
        if ctr > self._udp_max:
            self._udp_max = ctr
        if len(self._udp_seen) > self._SET_LIMIT:
            floor = self._udp_max - self._WINDOW
            self._udp_seen = {c for c in self._udp_seen if c > floor}
            self._udp_floor = max(self._udp_floor, floor)
        return plaintext

    # ── TCP 隐式计数器 ────────────────────────────────

    def encrypt_seq(self, plaintext: bytes) -> bytes:
        """TCP: 计数器隐式（严格递增，不传输）。"""
        ctr = self._send_ctr
        self._send_ctr += 1
        return self._send.encrypt(_nonce(ctr), plaintext, b"")

    def decrypt_seq(self, ciphertext: bytes) -> bytes:
        """TCP: 接收计数器必须连续，乱序/跳跃即 CryptoError。"""
        ctr = self._recv_ctr
        try:
            plaintext = self._recv.decrypt(_nonce(ctr), ciphertext, b"")
        except InvalidTag as e:
            raise CryptoError(f"会话解密失败/序错乱(InvalidTag, 期望计数器 {ctr})") from e
        self._recv_ctr += 1
        return plaintext


class FrameCodec:
    """统一帧封装（protocol.md §3）——对 payload 透明（握手消息或密文均可承载）。

    实例化使用（codec = FrameCodec()）; 消费方（relayd/gateway/transport/
    测试）各自持有实例——帧语义演化时改一处类，无模块级散函数。
    """

    def pack_tcp(self, payload: bytes) -> bytes:
        if len(payload) > TCP_FRAME_MAX:
            raise FrameError(f"TCP 帧超限: {len(payload)}")
        return len(payload).to_bytes(4, "big") + payload

    def pack_udp(self, counter: int, ciphertext: bytes) -> bytes:
        """UDP 帧: [8B 小端计数器][密文]。"""
        return counter.to_bytes(8, "little") + ciphertext

    def unpack_udp(self, datagram: bytes) -> tuple[int, bytes]:
        if len(datagram) < 8:
            raise FrameError("UDP 帧过短")
        return int.from_bytes(datagram[:8], "little"), datagram[8:]


class TcpFrameReader:
    """TCP 流式帧解析器（缓冲 + 定界，protocol.md §3.1）。

    feed() 追加字节流，弹出已完整帧的 payload 列表。
    """

    __slots__ = ("_buf",)

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self._buf.extend(data)
        out: list[bytes] = []
        while len(self._buf) >= 4:
            n = int.from_bytes(self._buf[:4], "big")
            if n > TCP_FRAME_MAX:
                raise FrameError(f"TCP 帧长度超限: {n}")
            if len(self._buf) < 4 + n:
                break
            out.append(bytes(self._buf[4:4 + n]))
            del self._buf[:4 + n]
        return out


# ── 消息编解码 + 打洞 MAC（protocol.md §4/§4.4）────────


class MsgCodec:
    """消息编解码（msgpack; 库类型存根缺失——Unknown 收口在 encode/decode 两处）。

    dict ↔ bytes 的唯一通道; 解码失败/非 dict 统一 CryptoError。
    """

    def encode(self, obj: dict[str, object]) -> bytes:
        return msgpack.packb(obj, use_bin_type=True)  # type: ignore[no-any-return,call-overload]

    def decode(self, data: bytes) -> dict[str, object]:
        try:
            obj = msgpack.unpackb(data, raw=False)  # type: ignore[no-any-return,call-overload]
        except (ValueError, msgpack.exceptions.ExtraData) as e:
            raise CryptoError(f"消息解码失败: {e}") from e
        typed = cast("object", obj)
        if not isinstance(typed, dict):
            raise CryptoError(f"消息必须为 dict: {type(typed).__name__}")
        return cast("dict[str, object]", typed)

    @staticmethod
    def as_int(value: object, name: str) -> int:
        """object → int 收口（bool 排除）; 非法即 CryptoError。"""
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        raise CryptoError(f"字段 {name} 必须为 int: {value!r}")


#: 模块共享消息编解码器（与 CIPHER 同模式——单一实例对齐三端）
MSG = MsgCodec()


def encode_msg(obj: dict[str, object]) -> bytes:
    """消息序列化（共享 MsgCodec 委托——兼容期接口; 新代码经实例）。"""
    return MSG.encode(obj)


def decode_msg(data: bytes) -> dict[str, object]:
    """消息反序列化（共享 MsgCodec 委托——兼容期接口）。"""
    return MSG.decode(data)


class PunchAuth:
    """打洞认证（punch MAC + 一次性 sid 生成——protocol.md §4.4）。

    收口为对象: MAC 计算与 sid 生成的演化（如改算法/长度）只改此处;
    三端（relayd 协调/gateway 应答/client 发起）共享同一语义。
    """

    def __init__(self, psk: bytes) -> None:
        self._psk = psk

    def mac(self, sid: str) -> str:
        """hmac_sha256(psk, "punch:"+sid).hex()[:16]。"""
        return hmac.new(self._psk, f"punch:{sid}".encode(),
                        hashlib.sha256).hexdigest()[:16]

    def verify(self, sid: str, mac: str) -> bool:
        return hmac.compare_digest(self.mac(sid), mac)

    @staticmethod
    def gen_sid() -> str:
        """一次性会话号: 16B 随机 hex（32 字符）。"""
        import secrets
        return secrets.token_bytes(16).hex()


# ── UDP 分片（protocol.md §5）───────────────────────────

FRAG_LIMIT = 900        # 单帧明文上限（超过即分片）
FRAG_TOTAL_MAX = 4096   # 分片数上限（≈3.7MB 明文——TTS WAV/OCR 图片量级）
REASM_WINDOW_S = 0.100  # 重组窗口
NACK_ROUNDS = 3         # 分片补片轮次上限


class Fragmenter:
    """发送端分片（有状态: msg_id 单调分配收口到实例——调用方不再自管）。

    明文 bytes → 分片消息列表（每片独立加密为一个 UDP 帧）。
    """

    def __init__(self) -> None:
        self._next_id = 1

    @staticmethod
    def need_split(plaintext: bytes) -> bool:
        return len(plaintext) > FRAG_LIMIT

    def split(self, plaintext: bytes, msg_id: int | None = None) -> list[dict[str, object]]:
        """分片（msg_id 省略时实例自增分配; 显式传入=向量生成等确定性场景）。"""
        total = (len(plaintext) + FRAG_LIMIT - 1) // FRAG_LIMIT
        if total > FRAG_TOTAL_MAX:
            raise CryptoError(f"消息过大: 需 {total} 片 > 上限 {FRAG_TOTAL_MAX}")
        if msg_id is None:
            msg_id = self._next_id
            self._next_id += 1
        return [
            {"t": "_frag", "id": msg_id, "seq": i, "total": total,
             "data": plaintext[i * FRAG_LIMIT:(i + 1) * FRAG_LIMIT]}
            for i in range(total)
        ]


class Reassembler:
    """接收端重组（单消息实例）。

    feed() 喂分片（含 NACK 补片重发，同 id 幂等）; due_nack() 由调用方在
    feed 后/定时循环中调用——窗口到期未集齐生成 _frag_nack; NACK_ROUNDS
    轮后标记 dead（上层超时兜底）。clock 注入点=单测。
    """

    def __init__(self, first_frag: dict[str, object],
                 clock: "object | None" = None) -> None:
        self._clock = clock or time.monotonic
        self._id = MsgCodec.as_int(first_frag["id"], "id")
        self._total = MsgCodec.as_int(first_frag["total"], "total")
        if not (0 < self._total <= FRAG_TOTAL_MAX):
            raise CryptoError(f"分片 total 非法: {self._total}")
        self._parts: dict[int, bytes] = {}
        self._first_at = self._clock()  # type: ignore[operator]
        self._nack_rounds = 0
        self.dead = False
        self.feed(first_frag)

    @property
    def msg_id(self) -> int:
        return self._id

    def feed(self, frag: dict[str, object]) -> "bytes | None":
        """喂入分片; 集齐返回完整明文，否则 None。"""
        if self.dead:
            return None
        if MsgCodec.as_int(frag.get("id", -1), "id") != self._id \
                or MsgCodec.as_int(frag.get("total", -1), "total") != self._total:
            raise CryptoError("分片 id/total 不匹配")
        seq = MsgCodec.as_int(frag["seq"], "seq")
        data = frag.get("data")
        if not isinstance(data, (bytes, bytearray)) or not (0 <= seq < self._total):
            raise CryptoError(f"分片 seq/data 非法: {seq}")
        self._parts[seq] = bytes(data)
        if len(self._parts) == self._total:
            return b"".join(self._parts[i] for i in range(self._total))
        return None

    def due_nack(self) -> "dict[str, object] | None":
        """窗口到期未集齐 → 生成 _frag_nack; 轮次耗尽标记 dead。"""
        if self.dead or len(self._parts) == self._total:
            return None
        if self._clock() - self._first_at < REASM_WINDOW_S * (self._nack_rounds + 1):  # type: ignore[operator]
            return None
        self._nack_rounds += 1
        if self._nack_rounds > NACK_ROUNDS:
            self.dead = True
            return None
        missing = [i for i in range(self._total) if i not in self._parts]
        return {"t": "_frag_nack", "id": self._id, "missing": missing}
