# 对称密码与哈希攻击

> 何时用：题目用 AES/DES 分组密码（ECB/CBC/CTR/GCM）、有 padding 报错（padding oracle）、`mac=hash(key∥msg)`（长度扩展）、或弱随机数（LCG）。

## 1. 识别攻击

| 特征 | 攻击 | 去读 |
|------|------|------|
| ECB + 相同明文块 | ECB 模式重复块 | §2 |
| CBC + 已知明文结构 + 想改某字节 | CBC bit flip | §3 |
| 解密失败/成功反馈不同（报错差异） | padding oracle | §4 |
| `mac = hash(key ∥ msg)`，可构造新 msg | 哈希长度扩展 | §5 |
| `s_{n+1}=a*s_n+c mod m`，连续输出 | LCG 状态恢复 | §6 |
| IV 可控 + CBC | CBC IV 注入/bit flip | §3 |

## 2. AES-ECB 模式弱点

**特征**：相同明文块 → 相同密文块。无 IV，不隐藏模式。

**识别**：密文按 16 字节分块，找重复块。

```python
def find_ecb_repeat(ct, block=16):
    blocks = [ct[i:i+block] for i in range(0, len(ct), block)]
    return len(blocks) != len(set(blocks))   # True = 疑似 ECB
```

**利用**：逐字节注入（选择明文）：把未知字节对齐到块末，枚举前 15 字节已知 + 1 未知，比对密文块。

> AES 加解密需 `pycryptodome`（`from Crypto.Cipher import AES`）或 `cryptography` 库。本环境的攻击识别逻辑（上面）用标准库，实际加解密示例需装库。

## 3. CBC bit flip（无需破解密钥）

**原理**：CBC 解密 `P[i] = D(C[i]) XOR C[i-1]`（`C[-1]=IV`）。翻转 `C[i-1]` 的第 `j` 位 → `P[i]` 第 `j` 位翻转（代价：`P[i-1]` 被破坏成乱码）。

**何时用**：已知密文 + 已知明文结构，想改解密后明文的某位（如把 `is_admin=0` 改成 `1`）。

```python
def cbc_flip_bit(ciphertext, block_index, byte_offset, xor_mask, block=16):
    """
    翻转第 block_index 个明文块的 byte_offset 字节 (XOR xor_mask)。
    代价: 第 (block_index-1) 个密文块被破坏。
    block_index=0 时翻转 IV。
    """
    ct = bytearray(ciphertext)
    # CBC: P[idx] = D(C[idx]) ^ C[idx-1]; 改 C[idx-1] 即改 P[idx]
    target = (block_index - 1) * block + byte_offset   # block_index=0 → 改 IV
    ct[target] ^= xor_mask
    return bytes(ct)

# 示例: 明文 "role=user;admin=0..." 改 admin=0→1
# 已知 admin=0 在第 2 块第 7 字节, xor_mask = ord('0')^ord('1')
new_ct = cbc_flip_bit(ct, block_index=2, byte_offset=7, xor_mask=ord('0')^ord('1'))
```

**注意**：被破坏的块（`block_index-1`）需是不影响判断的部分（如 padding 块）。

## 4. Padding Oracle（PKCS7）

**原理**：解密后校验 PKCS7 padding，失败/成功反应不同（报错、状态码、时长）。利用 oracle 逐块逐字节恢复明文，无需密钥。

**PKCS7 规则**（可执行，标准库）：

```python
def pkcs7_pad(data, block=16):
    n = block - len(data) % block      # n∈[1,block], 全块时补一整块
    return data + bytes([n]) * n
def pkcs7_unpad(data):
    n = data[-1]
    if n < 1 or n > 16 or data[-n:] != bytes([n]) * n:
        raise ValueError('bad padding')
    return data[:-n]
```

**攻击流程**（每块 16 字节，从末位爆破）：

```python
def padding_oracle_block(oracle, prev_block, cipher_block, block=16):
    """oracle(prev||cipher) -> bool (padding 是否合法). 返回恢复的明文块."""
    plain = bytearray(block)
    inter = bytearray(block)      # intermediate = D(cipher_block)
    for pad_len in range(1, block+1):       # 从最后 1 字节往前
        pad_byte = pad_len
        for guess in range(256):
            forged = bytearray(block)
            forged[-pad_len:] = bytes(inter[i] ^ pad_byte for i in range(block-pad_len, block))
            forged[-pad_len] = guess ^ pad_byte   # 试当前位
            if oracle(bytes(forged), cipher_block):
                inter[-pad_len] = guess ^ pad_byte
                plain[-pad_len] = inter[-pad_len] ^ prev_block[-pad_len]
                break
        else:
            raise RuntimeError(f"oracle 无解 (pad_len={pad_len})")
    return bytes(plain)
```

`oracle` 函数需按题目封装（HTTP 请求/本地函数）。每块需最多 `16*256` 次查询。

## 5. 哈希长度扩展攻击

**何时用**：`mac = H(secret ∥ msg)`（secret 前置，无 HMAC），已知 `mac`、`len(secret)`、`msg`，无需 secret 可算出 `H(secret ∥ msg ∥ padding ∥ append)`。

**原理**：MD5/SHA1 内部状态 = 最终输出。把已知 `mac` 还原为内部状态，继续处理 `append`，即得扩展哈希。

**padding 构造**（标准库可算，可执行）：

```python
import struct
def md5_padding(msg_len, block=64):
    """MD5 的 padding: 0x80 + 0x00*... + 64位长度(小端). 使总长为 block 倍数."""
    pad = b'\x80'
    zeros = (-(msg_len + 1) - 8) % block   # 使 msg+0x80+zeros 恰好占满到 (block-8) 字节
    pad += b'\x00' * zeros
    pad += struct.pack('<Q', msg_len * 8)  # MD5 长度小端 (bit)
    return pad
# glue_padding = md5_padding(len(secret) + len(msg))
# 伪造: 新msg = msg + glue_padding + append; 新mac = 续算结果
```

**续算**需 `hashpumpy`（`pip install hashpumpy`）或手写 MD5 状态恢复（用 `pure-python-md5` 改造）：

```python
# hashpumpy 用法 (标注依赖)
import hashpumpy
new_mac, new_msg = hashpumpy.hashpump(original_mac, original_msg, append, original_key_length)
```

## 6. 弱随机：LCG 状态恢复

**何时用**：`s_{n+1} = (a*s_n + c) mod m`，给了连续输出。参数 `a,c,m` 可能全给/部分给/全隐藏。

```python
def recover_lcg(s):
    """已知连续 ≥4 个输出, 恢复 a, c, m (当 m 未知).
    原理: 一阶差分 T_i=s_{i+1}-s_i 满足 T_{i+1}≡a*T_i (mod m),
          故 T_i*T_{i+2}-T_{i+1}^2 ≡ 0 (mod m), 取 gcd 得 m."""
    from math import gcd
    T = [s[i+1]-s[i] for i in range(len(s)-1)]        # 一阶差分
    U = [T[i]*T[i+2] - T[i+1]**2 for i in range(len(T)-2)]
    m = 0
    for u in U: m = gcd(m, abs(u))
    a = (T[1] * pow(T[0], -1, m)) % m                  # T_1 ≡ a*T_0 (mod m)
    c = (s[1] - a*s[0]) % m
    return a, c, m

# 验证: all((a*s[i]+c)%m == s[i+1] for i in range(len(s)-1))
```

若 `m` 已知：直接 `a = (s2-s1) * inverse(s1-s0, m) % m`，`c = (s1 - a*s0) % m`。

## 决策

```
ECB? → 找重复块 (§2)
CBC + 想改明文位? → bit flip (§3)
解密有 padding 合法/非法反馈? → padding oracle (§4)
mac=hash(key∥msg)? → 长度扩展 (§5)
连续随机数? → LCG 恢复 (§6)
```

## 注意

- **padding oracle 的 oracle 要可靠**：反馈差异必须可区分（报错 vs 正常、不同状态码、甚至时延）
- **CBC bit flip 破坏相邻块**：确保被破坏块不影响判断（如放在 padding 区）
- **长度扩展只对 secret 前置有效**：`H(msg∥secret)` 不可扩展；HMAC 不可扩展
- **AES 实操需 pycryptodome/cryptography**：本环境的攻击识别（重复块、padding、LCG、哈希扩展 padding 构造）用标准库；实际 AES 加解密需装库
- 求出明文后验证符合 flag 格式
