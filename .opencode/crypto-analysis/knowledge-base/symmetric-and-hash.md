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
| GCM 同 nonce 重用 | forbidden attack（keystream XOR + GHASH H 恢复） | §7 |
| 定长头部恰占一个 CBC 块 | 头部块提升 IV 剥离 | §7 |
| CTR + CRC 组合完整性 | CTR bitflip + CRC 线性同时修 | §7 |
| 错误消息回显解密值 | 全零块读 intermediate 构造密文 | §7 |
| 自定义密码 S-box 非双射 | 碰撞差分 4097 查询 | §8 |
| 只有 XOR/rot 的自定义 hash | GF(2) 高斯消元直接求逆 | §8 |
| LFSR/移位寄存器/比特级递推 | LFSR 攻击族 | §13 |
| 代数混合（模加）自定义流密码 + 已知前缀 | Z3 约束求解 | §13 |
| sign(sha1(M)) 模式 | chosen-prefix 碰撞伪造 | §9 |
| hash 链认证 + 种子公开派生 | 正向预计算全链 | §9 |

## 2. AES-ECB 模式弱点

**特征**：相同明文块 → 相同密文块。无 IV，不隐藏模式。

**识别**：密文按 16 字节分块，找重复块。

```python
def find_ecb_repeat(ct, block=16):
    blocks = [ct[i:i+block] for i in range(0, len(ct), block)]
    return len(blocks) != len(set(blocks))   # True = 疑似 ECB
```

**利用**：逐字节注入（选择明文）：把未知字节对齐到块末，枚举前 15 字节已知 + 1 未知，比对密文块。

**cut-and-paste 块重组**（可控字段场景）: 构造输入使目标词+padding 恰好独占一块（如 email="foo@bar.coadmin\x0b×11" → 某块=纯 "admin"+padding），保存该密文块，再拼接到 role 字段所在块的位置——ECB 无链接，块序即明文序。

**未知前缀对齐**（prefix∥input∥secret 场景）: ①逐块对比 encrypt("") 与 encrypt("A"*i) 找首个变化块 = prefix 结束块 ②该块内 A/B 两字符对 i=1..16 对比，两输入同块相等时的 j 给出 prefix 尾偏移 → 补偿 padding 对齐后再做 byte-at-a-time。

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

**假阳性校验**（末字节 0x01 时）: padding \x02\x02 也会让末字节探测返回 valid——命中后再把倒数第二字节 ^1 翻转复验，仍 valid 才是真 \x01。

**CBC-R（用 padding oracle 加密任意明文）**: 随机选末密文块 → oracle 解出它的 intermediate → prev_ct = intermediate ⊕ 目标明文块（该块解密即目标）→ 以 prev_ct 为新末块迭代向前，首块即 IV。解密 oracle 与加密能力等价。HTTP 场景: 把上面 oracle 参数换成 requests 回调（发伪造密文→按响应状态码/长度差异判断 padding 是否合法），完整封装代码见 web-crypto-attacks.md §2.2。

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

**续算**需 `hashpumpy`（`pip install hashpumpy`）或手写 MD5 状态恢复（用 `pure-python-md5` 改造）；多算法 CLI 用 hash_extender，Python 库 hlextend：

**易感性速查**: MD5/SHA-1/SHA-256/SHA-512（Merkle-Damgård）可扩展; SHA-3/Keccak（海绵）、HMAC-*（双哈希）、BLAKE2、截断哈希（缺内部状态位）**不可**扩展。

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

**部分输出的暴力恢复**（参数已知时，格法的轻量替代）: 输出为 state mod N → `for c in range(output, M, N)` 用下一输出验证; 只见高位 → 暴力隐藏低位（≤2^32 可行），下一状态高位匹配验证。隐藏位更多走 HNP 格（lattice-attacks.md §4.2）。

### 反向：参数注入造循环（攻击者可控 a 时）

当题目让攻击者选乘数 `a`（如"设计一个通过校验的 RNG"），选 `a` 为 `x^k - 1` 的非 1 单位根使种子周期循环:
```python
R.<x> = PolynomialRing(Zmod(p))
eq = x^5 - 1
for root, _ in eq.roots():
    if root == 1: continue
    a = root  # a^5 ≡ 1 mod p → s_{i+5} = s_i（周期 5 循环）
    # 检验: 5 个 seed 成循环，满足 RNG 校验
```

## 7. 模式滥用与组合攻击速查

- **GCM nonce 重用（forbidden attack）**: ①C1^C2=P1^P2 恢复明文 ②tag 差多项式在 GF(2^128) 因式分解恢复 GHASH 认证密钥 H → 伪造任意 tag。工具 nonce-disrespect。短 nonce（1-4 字节）+ 已知 key 直接暴力。派生链常见 nonce=wrapped^SHA256(secret), key=SHA256(secret+nonce)——MAC check failed 先查上游 secret 端序
- **CBC 头部块剥离**: 任意连续密文切片是合法 CBC 密文（前块提升为 IV）。nonce/magic 恰占一块时 new_iv=ct[:16], new_ct=ct[16:] 剥掉头部
- **CTR + CRC**: CRC(A^B)=CRC(A)^CRC(B)^CRC(0)——XOR 改数据段同时修 CRC 段; CRC32(msg||secret) 可用 crchack 追 4 字节伪造任意目标 CRC。流密码+CRC=完整性灾难
- **错误消息泄漏解密值**: 全零块读 intermediate（D(C)），目标明文 XOR intermediate = 正确密文块，从最后一块向前迭代构造任意明文密文（可携盲注 payload）
- **CTR 常量计数器**: counter=lambda:secret 不递增 → 16 字节重复 XOR; 文件头引导 crib-dragging 迭代扩展密钥流（工具 otp_pwn）
- **CFB-8 静态 IV**: 16 已知字节后移位寄存器状态完全确定，可接管伪造后续密文
- **OFB-MAC 伪造**: 密钥流与明文无关，new_sig = known_sig^P1块^P2块（含 padding）; CBC-MAC 无此弱点
- **Bleichenbacher v1.5（ROBOT）**: 00 02 前缀 oracle，B=2^(8(k-2))，s 从 ceil(n/3B) 搜起区间收缩，RSA-2048 ~10K 查询。工具 robot-detect/TLS-Attacker。与 Manger（OAEP 首字节）互补
- **AES 密钥槽索引溢出清零**: index*SIZE 回绕 → 选择性清零密钥字节 → 单字节 256 暴力 ×16 = 4096 次恢复
- **生日/MITM**: n-bit 碰撞 ~2^(n/2)（32bit→65K）; 双重加密 MITM O(2^(2k))→O(2^k) 时空

## 8. 自定义密码分析

- **非置换 S-box**: len(set(sbox))<256 即有碰撞对; 差 delta 明文对 ct 相等 → 每字节 2-way，2^16 合并，~4097 查询。接近标准的改动 S-box（仅 3 元素交换）→ C(256,3)×2≈5.5M 直接可爆
- **GF(2) 线性 hash/密码**: 只含 XOR+rot（无 S-box/模加）→ 构造变换矩阵高斯消元直接求逆恢复原像（numpy 实现，O(n³) 纯 XOR）。适用自定义 hash 求逆/CRC 状态/LFSR/线性 MAC
- **SPN 列独立暴力**: 末层列对齐 XOR 密钥逐字节独立暴力（逆 pbox/sbox 后所有块须可打印 ASCII，多块取交集）; 种子共享 sbox/pbox 时部分密钥约束种子跨列传播
- **S-box 质量评估（DDT/LAT）**: ddt[dx][dy] 统计 sbox[x]^sbox[x^dx]，非零 dx 行最大值=最大差分概率（8-bit 最优 4/256）; LAT 最大线性偏差。自定义 S-box 显著高于最优 → 截断差分/回旋镖可行。另查不动点/对合/代数次数
- **减轮差分（Ascon/GIFT 类）**: 精确复现轮函数 → GF(2) 建线性层逆矩阵 → 逐位注入 diff 采样输出偏差 → (k0[i],k1[i]) 四类质心聚类分类密钥位（符号模式掩码处理位相关）→ 验证+低置信位补采样
- **DES DFA**: 倒数第二轮单比特故障 → 末轮 S-box 差分约束 K16（每 box 6-bit 猜测多故障对取交集）→ 48-bit 子密钥 + 8 校验位暴力 → 回推主密钥

## 9. 哈希协议缺陷

- **sign(sha1(M)) 模式**: chosen-prefix 碰撞（cpc/shattered 工具）造 OCR/转换差异双文档同 digest，签名 A 重放 B。协议签 hash 不签原文 + 哈希可碰撞 = 伪造
- **hash 链种子重建**: hash^N(seed) 认证中种子公开派生（md5(username) 等）→ 从链头正向预计算全链应答。种子必须当密钥
- **MD5 多碰撞**: fastcol（hashclash）分钟级一对，Merkle-Damgård 组合性质（H(A||X)==H(A||Y) ⟹ 追加 Z 仍等）链式 k 轮产 2^k 同哈希文件; CRC32 碰撞可 PNG IEND 后追加 + 4 字节调整。同族: UniColl（单块近碰撞，两消息仅 1 字节差同哈希，适合 PDF/PE 双构造）; chosen-prefix（cpc）用于证书伪造/二进制替换
- **PBKDF2 长密码预哈希**: HMAC 密钥超块大小（SHA-1/256 为 64B）先 H(K)——用 SHA1(password) 直接登录等价（规范行为）。SHA-512 族阈值 128B
- **hash 时间反转**: 迭代截断 hash 作时间函数——Brent 圈检测找圈长 L（64-bit 截断 MD5 期望 ~2^32），回退 N 步 = 前进 (L-N)%L 步
- **长度扩展 + 已知密钥组合伪造**: 签名 H(secret||decrypt(ct)) 且 AES key 可泄时——hashpumpy 扩展明文 + 已知 key 重加密，使 CBC 解密结果与扩展后签名一致（后字段覆盖前字段）
- **素数模 GHASH**: tag = c + Σb_i·H^(i+1) mod n（n 素数非 GF(2^128)）→ 同 nonce 两 tag 相减消 c，`H=(t1-t2)*inverse(m1-m2,n)` 单模逆恢复; 2 字节随机 nonce 生日 ~256 查询必碰

## 10. 协议与实现陷阱

- **SRP 绕过**: 只校验 A≠0/A≠N 不够——发 A=2N（或 kN）强制共享密钥 S=0，K=SHA256(0) 伪造证明（见 auth-attacks.md SRP 条目同族）
- **三轮 XOR 协议密钥自消去**: c1=m^Kc、c2=c1^Ks、c3=c2^Kc → c1^c2^c3=m（密钥应用偶数次即消去，被动 pcap 可解）
- **Blum-Goldwasser 位扩展**: 密文 c<<1 扩一位 + y=y² 推进平方序列，oracle LSB 每查询泄 1 bit 明文
- **OFB 可逆 RNG 反向解密**: 任一块已知明文（零 padding/文件头/结尾 NUL）泄漏状态; 转移函数双射时从尾向头反演全部状态解密
- **弱密钥派生**: AES key = SHA256(公钥 DER) XOR 硬编码 seed——派生只含公开信息 = 零安全，公钥+密文无私钥场景先查派生链
- **HMAC-CRC**: CRC 线性 → HMAC-CRC 整体 GF(2) 线性，单组 (msg,MAC) 多项式运算直接解 key
- **XOR+加法混用逐位泄密**: sha256((key^msg)+msg) 型——msg=0 得 sha256(key)，msg=2^i 哈希相同 ⟺ key 第 i 位为 1（XOR 清位加法还原）
- **DES 弱密钥 OFB**: 4 个弱密钥（0x00..00/0xFF..FF/E1E1E1E1F0F0F0F0/1E1E1E1E0F0F0F0F）自逆 → 密钥流周期 2，等价 16 字节重复 XOR
- **LSB 奇偶 oracle 基础版**: 密文乘 pow(2,e,N)（Rabin 乘 4）明文翻倍，模回绕改变奇偶——log2(N) 次二分精确恢复; 噪声版走众数投票（rsa-attacks.md §11）
- **Square 攻击（4 轮 AES）**: λ 集（256 明文一字节遍历）3 轮后 XOR 和为 0; 逐字节猜末轮密钥部分解密验证和为 0，~4096 次替代 2^128
- **密钥槽索引溢出清零**: index*SIZE 回绕 → 选择性清零密钥字节 → 单字节 256 暴力 ×16 次恢复
- **SPN S-box 交集法**: 每 S-box 位置独立攻击，多明密文对的子密钥候选取交集唯一化（108-bit → 6 个独立 12-bit 搜索）

## 11. Oracle 条件族与侧信道扩展

- **oracle 不止 padding**: UTF-8 有效性（UnicodeDecodeError）、base64 可解码、JSON 可解析、ASCII-only——任何服务端可区分的明文合法性响应都构成解密 oracle，bit-flip 逐字节爆破同理
- **逐字符校验时延**: early-exit + 每正确字符重哈希（如 9999 次迭代 ≈0.66s/字符）→ 逐位置爆破测时延差（比 baseline 不比绝对值）。防御用 `hmac.compare_digest`（恒定时间比较）
- **Python or 短路时延**: 昂贵 KDF 排条件链后位被短路 → 快/慢分支即 oracle; 校准（known-fast/known-slow 采样定阈值）+ 模糊区间重试（见 rsa-attacks.md §11 Manger-OAEP）
- **CBC 块 2 与 IV 无关**: 块 ≥2 明密文对是 IV 无关的密钥恢复素材; 密钥定后 IV = AES_dec(ct[0],K) ^ pt[0]
- **错误消息泄漏解密值**: 全零块读 intermediate，目标明文 XOR intermediate 构造密文块，从尾向前迭代（可携盲注 payload）
- **CFB IV 时间种子恢复**: PRNG 种子 int(time()) 时文件 mtime = 精确种子; 注意 Python2/3 random 序列不同、cp/mv 重置 mtime
- **压缩 oracle（CRIME 类）**: 压缩后加密，密文长度变化泄明文——选择明文使 n-gram 匹配 SALT 时密文更短，逐字符恢复

## 12. XOR/线性聚合与多碰撞

- **SHA-256 基攻击**: XOR(sha256(f_i)) 聚合校验——~256 个随机哈希张成 GF(2)^256，solve_left 找子集使聚合不变，替换/注入文件维持校验（非碰撞，利用聚合线性性）
- **密钥流周期性消去伪造**: MAC 内部 keystream 每 N 块重复 → 三查询安排 filler 同位对消（mac1^mac2^mac3 = 目标 MAC）
- **GF(2) 线性 hash 求逆**: 只含 XOR/rot 的构造建变换矩阵高斯消元直接恢复原像（numpy O(n³) 纯 XOR）
- **自定义 hash 中间态泄漏**: 逆状态更新方程（如 hash=s(i)^ROL(s(i+1),7)）把全局原像分解为逐块小空间暴力
- **ZIP CRC32 小载荷暴力**: 加密 ZIP 头部 CRC 不加密，≤6 字节可打印暴力（C 快 100x，多碰撞上下文消歧）
- **海绵 rate<state MITM**: 不受控状态字节是天然分界，正向 2^24 表 + 反向查找，2^48→2^24
- **长度扩展过 ASCII 过滤**: 0x80 padding 字节替换为多字节 UTF-8（\x80→\xc2\x80），SHA 按字节相同、字符过滤器放行
- **GF(2)[x] 多项式 CRT**: 服务端给 r=flag mod f（f 随机 32-bit GF(2) 多项式）→ 收 ~20 对，多项式 gcd 滤互素，迭代 CRT 合并（模数乘积 ≥ flag 比特即唯一）。原语: 加法=XOR、无进位乘 poly_mul、bit_length 辗转 divmod
- **CRC 自反不动点**: CRC 线性 → CRC(x)=x 约束即 (CRC-I)x=0 线性系统，逐 bit 翻转求响应列，高斯消元 + 自由变量凑可打印 ASCII。与 crchack（改尾凑 CRC）互补

## 13. 流密码与 LFSR 攻击

- **Berlekamp-Massey 恢复 LFSR**: 已知 ≥2L 连续密钥流位（已知明文 XOR 密文）→ BM 求极小线性递推（Fibonacci 形式），初始状态=前 L 位，可前向后向预测全程。sage `berlekamp_massey(seq)`。等价路线: GF(2) 线性系统直接解（§8 高斯消元）
- **相关攻击（组合生成器）**: 多 LFSR 非线性组合时，组合函数对某 LFSR 输出有偏差（P>0.5）→ 独立爆破该 LFSR 全部 2^L 初始状态，匹配率显著>0.5 者胜。先算组合函数真值表找最大偏差输入
- **Galois 右移 LFSR tap 直接恢复**: `state>>=1; if lsb: state^=tap` 实现中，LSB=1 的转移对给 `tap = (state>>1) ^ next`；LSB=0 转移（next=state>>1）做校验。长度未知按候选 n 切状态窗对掩码投票，mismatches=0 即正确长度。已知文件头（PNG 16B→128bit）恢复密钥流。比 BM 直接（BM 假设 Fibonacci 形式，Galois 多项式=Fibonacci 倒数多项式）
- **常用本原多项式**: 16 位 x^16+x^14+x^13+x^11+1；32 位 x^32+x^22+x^2+x+1；64 位 x^64+x^4+x^3+x+1。周期 2^L-1。实现者常直接抄表，未知 LFSR 先试标准多项式
- **滤波零化子**: LFSR+非线性滤波 f 的密钥流，f 有低次零化子 g（g∘f=0）→ 每字节一个状态线性方程 → 高斯消元（right_kernel+可打印过滤）。滤波强度=代数免疫度，低免疫度退化为线性
- **RC4 第二字节偏差区分器**: P(第2字节=0)=1/128（随机 1/256）——~2048 样本数零个数 N/128 vs N/256 区分 RC4 与随机。其他偏差: 首字节 P(K[0]=0)≈2/256; FMS 弱 IV（IV 前拼 key 的 WEP 型密钥调度）; NOMORE 长期偏差 2^24-2^26 密文统计恢复明文
- **Z3 解代数混合流密码**: 递推只含模加/取模（如 enc[i]=(msg[i]+key[i%k]+enc[i-1])%128）→ 每步一个 Int 约束 + 可打印域 + 已知前缀锚，solver 同时恢复 key+明文，免结构分析
- **位置参数化密钥流 oracle 化**: 密钥流=数学函数(seed+pos) 且 seed 在查询输入中可控 → 平移 seed 使服务端变任意位置解密 oracle，O(n·256) 恢复
- **XOR 相邻字节自消去**: 输出=ct[i]^ct[i+1] 型 → 两密文差分消密钥流，一条已知明文恢复另一条全部明文
- **多对一后处理泄密钥流**: 解密后经 RLE 解码/归一化/小写化再哈希比对 → RLE 同游程多合法编码使不同密文同哈希 → 相等响应泄 keystream[i]^k[j]，逐对差分+单字节定标重建全密钥流
- **网络侧信道泄密钥**: hostname（gethostbyaddr 反查）/Host 头/TLS SNI 等协议字段明文携带程序取用的"机密"——先 pcap 抓运行期流量再静态逆向，密钥可能不在二进制内

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
