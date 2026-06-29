# CTF 密码学方向技术调研报告（2023–2026）

> 调研范围：CTFtime / CryptoHack / GitHub writeup 仓库 / eprint.iacr.org / 中文社区
> 产出目标：技术清单 + SageMath 模板代码 + 解题方法论 + 知识库沉淀建议
> 说明：链接抓取失败处标注「待核对」，不阻塞产出。

---

## 一、近三年密码学方向技术趋势概览

1. **格密码（Lattice）全面主导高难题**。CryptoHack 已把 Lattices 独立为「后量子」大类，CTFtime 2026 题目（Polynomial Drift / Sealed Signal 等）标题即指向多项式/格构造。HNP、CVP/SVP、Coppersmith 是出现频率最高的三大原语，几乎所有现代 RSA/ECC/格题最终都归约到这三个之一。
2. **后量子与新型原语进入比赛**：SIDH 被 Castryck-Decru 攻击（RCTF 2022 S2DH）后迅速成为模板题；Kyber/Dilithium（NIST PQC 标准化）的非标准参数开始出现；zk-SNARK 的 Fiat-Shamir 错误（frozen heart）成为 ZKP 类主流考法。
3. **「组合攻击」成为区分难度的方式**：纯 Wiener / 纯 Fermat 已是签到题；中高难题普遍是 `Coppersmith + LLL`、`truncated LCG + matrix LCG`、`ECDSA biased nonce → HNP → LLL`、`Singular curve → Pohlig-Hellman` 这类多原语串联（如 DiceCTF 2023 BBBB、RCTF 2022 IS_THIS_LCG）。
4. **工具链收敛到 SageMath + Python**：SageMath 内置的 `small_roots`、`LLL`、`discrete_log`、`factor`、`p-adic` 是事实标准；`gmpy2`/`pycryptodome` 做数据 IO；`z3` 处理逆向类约束。pcw109550 仓库中 Sage 代码占比 55%，印证这点。
5. **侧信道/故障/格的交叉**：RSA-CRT 故障攻击、AES 中间态伪造（CCE 2023 NZK-SIARK）、nonce 偏差被反复考，本质都是「泄漏少量信息 → 格/代数恢复」。

---

## 二、关键技术清单（按重要性 / 出现频率排序）

> 每个技术给：原理 / 数学条件 / SageMath 关键代码 / 适用场景 / 参考来源。
> 代码为可直接套用的模板骨架，参数需按题填入。

---

### 2.1 Coppersmith 方法（small_roots）—— 最高频原语

```
技术名称: Coppersmith 小根（单变量 small_roots / 多变量 Howgrave-Graham 扩展）
出现频率: 高（RSA 类几乎必考其一）
核心原理: 若多项式 f(x) 模 N 的某个因子有一个"小"根 x0（|x0| < N^(1/deg) 的某个界），
          则可在整数环上用 LLL 归约格基，把模方程根还原成实数根。
          关键定理：univariate 下若 |x0| < N^(1/d) (beta=1) 或更一般 < N^(beta^2/d)，
          即可求出。
数学条件:
  - 单变量 stereotyped: 已知 m 的高位/低位，未知部分 x0 满足 |x0| < N^(1/e)（e 较小）
  - 部分 p 泄漏: p 高位已知时，beta=0.5，界约 N^(0.25)
  - 多变量(二元 Howgrave-Graham/Herrmann-May): 需要手动构造 lattice，alpha(单调格)与模等参数
关键步骤:
  构造多项式环 Zmod(N)[x]，写 f，调 small_roots(X=根上界, beta=因子的相对大小, epsilon=精度)
适用场景:
  - RSA e 小 + 明文高位已知 (stereotyped message)
  - RSA 部分 p 高位泄漏 (partial key exposure)
  - 低 e 广播 (Håstad broadcast)
  - Short-pad / Franklin-Reiter 相关消息
参考来源:
  - DEF CON 2020 coooppersmith (二元 Coppersmith 因式分解 n) [pcw109550/write-up/2020/DEFCON/coooppersmith]
  - Pwn2Win 2020 Omni Crypto (partial p exposure) [pcw109550/write-up/2020/Pwn2Win/Omni_Crypto]
  - PlaidCTF 2020 dyrpto (short pad + Franklin-Reiter) [pcw109550/write-up/2020/PlaidCTF/dyrpto]
  - DiceCTF 2023 BBBB (LCG + Coppersmith) [pcw109550/write-up/2023/Dice/BBBB]
  - Coppersmith 1996, Eurocrypt（待核对 DOI）
```

#### 模板 A：单变量 small_roots（部分 p 高位 / stereotyped）

```sage
# 场景：已知 p 的高位 p0，p = p0 + x0，x0 为未知低位
def partial_p(n, p_high_bits, unknown_bits):
    N = n
    P.<x> = PolynomialRing(Zmod(N))
    # p_high_bits 应已左移到与 N 同量级；p = p_high + x
    f = p_high_bits + x
    # beta=0.5 (p≈N^0.5), X=2^unknown_bits, epsilon 越小越慢越稳
    res = f.small_roots(X=2**unknown_bits, beta=0.5, epsilon=0.02)
    return [ZZ(r) + p_high_bits for r in res]

# 场景：RSA stereotyped，m = m0||x0, c = m^e mod n, e 小
def stereotyped(n, e, c, known_high_int, unknown_bits):
    P.<x> = PolynomialRing(Zmod(n))
    f = (known_high_int + x)^e - c
    roots = f.small_roots(X=2**unknown_bits, beta=1.0, epsilon=1/20)
    return [int(r) + known_high_int for r in roots]
```

#### 模板 B：二元 Coppersmith（Herrmann-May 简化，用于 short-pad / 分解 n）

```sage
# 场景：short pad attack，两条密文 m1 = 2^k * M + r1, m2 = 2^k * M + r2
# 构造 g1 = x^e - c1, g2 = (x+y)^e - c2，求二元小根 (x, y)
def short_pad_rsa(n, e, c1, c2):
    PR.<x, y> = PolynomialRing(Zmod(n))
    g1 = x^e - c1
    g2 = (x + y)^e - c2
    # 求 g1, g2 的结式(resultant)消元，退化为关于 y 的单变量，再 small_roots
    pg = g1.resultant(g2, x)
    # pg 关于 y，small_roots 求出 pad 差，再回代
    PY.<yy> = PolynomialRing(Zmod(n))
    pg_uni = PY(pg(y, yy)) if False else None  # 按 resultant 输出适配
    # 简化模板：实际常配合 Franklin-Reiter 直接求明文
    return pg
```

> 提示：CTF 中二元 Coppersmith 多用 `defund/coppersmith` 风格的 `small_roots` 多变量封装（社区流传版），核心是 Howgrave-Graham 的格构造 + LLL。由于 SageMath 官方 `small_roots` 仅稳定支持单变量，多变量通常需要自定义 lattice。

---

### 2.2 LLL / BKZ 格归约 —— 最高频底层工具

```
技术名称: LLL / BKZ 格基归约（CVP / SVP 近似解）
出现频率: 高
核心原理: 在一个格 L 中找"短向量"或"接近某目标"的向量。
          CVP(最近向量): 给目标 t，找 v∈L 使 ||v - t|| 最小 → 加 Babai 近平面/嵌入法
          SVP(最短向量): LLL 输出的首向量即近似最短向量
数学条件: 格的维度 d 不能太大（LLL 在 d≤200 内秒级；BKZ 更高 block_size 更慢更准）；
          目标向量要比格中其他向量"明显短"（gap），否则归约失败。
适用场景: HNP、ECDSA/DSA nonce 偏差、knapsack/subset-sum、truncated LCG、
          NTRU/LWE 参数弱、RSA-CRT dp 泄漏、common prime。
参考来源:
  - DEF CON 2019 tania (DSA LCG nonce → LLL) [pcw109550/write-up/2019/DEFCON/tania]
  - zer0pts 2022 Karen (Hidden Subset Sum, Nguyen-Stern) [pcw109550/write-up/2022/zer0pts/Karen]
  - X-MAS 2019 hide and seek (HNP + partial p) [pcw109550/write-up/2019/X-MAS/hide_and_seek]
```

#### 模板 C：隐藏数问题 HNP（ECDSA/DSA nonce 已知高位 / nonce 偏小）

```sage
# HNP: 已知 t_i ≡ alpha * a_i (mod p) 的若干高位
# 设已知 t_i, a_i，未知 alpha，B = 2^(泄露后未知比特数)
# 构造格 (Boneh-Venkatesan)：
def hnp(p, A, T, B):
    # A, T: 已知点列表；B: 未知部分上界
    n = len(A)
    M = matrix(ZZ, n + 2, n + 2)
    for i in range(n):
        M[i, i] = p
    M[n] = A + [0] * 2          # 最后一行 a_i
    M[n + 1] = T + [B, 0]       # 目标偏移
    # 标准做法见下面完整矩阵写法（推荐用下面 HNP 完整版）
    return M.LLL()

# 推荐完整写法（DSA/ECDSA nonce bias）：
def recover_x_dsa(q, rs, hs, known_bits_of_k_or_bias):
    # s_i = k_i^-1 (h_i + r_i * x) mod q  =>  k_i = (h_i + r_i*x) * s_i^-1 mod q
    # 若 k_i 高位固定 / 上 n-k 位为 0，则 t_i = r_i * s_i^-1 mod q, u_i = h_i * s_i^-1 mod q
    # 关系: k_i = t_i * x + u_i (mod q)，x 未知小量 → 建 HNP 格
    m = len(rs)
    B = q >> known_bits_of_k_or_bias   # nonce 真实大小上界
    M = matrix(ZZ, m + 2, m + 2)
    for i in range(m):
        M[i, i] = q
        t = (rs[i] * inverse_mod(... , q)) % q   # 按题填 s_i
        u = 0
        M[m, i] = t
        M[m + 1, i] = (B // 2) * 0              # 中点偏移按需
    M[m, m] = 1
    M[m + 1, m + 1] = B
    L = M.LLL()
    for row in L:
        x_cand = row[m] % q
        if 0 < x_cand < q:
            yield x_cand
```

#### 模板 D：subset-sum / knapsack 低密度（Nguyen-Stern / CJLOSS）

```sage
# 已知 a_1..a_n, S, 求 b_i∈{0,1} 使 sum a_i b_i = S
def subset_sum(a, S):
    n = len(a)
    # CJLOSS 格：每行 [2*I | a_i]，目标含 S
    M = matrix(ZZ, n + 1, n + 1)
    for i in range(n):
        M[i, i] = 2
        M[i, n] = a[i]
    M[n, n] = -S
    L = M.LLL()
    for row in L:
        if set(row[:n]) <= {1, -1} and row[n] == 0:
            return [(x // 2 + 1) // 2 % 2 ... ]   # 解码 b_i
    return None
```

---

### 2.3 RSA 经典攻击矩阵（速查）

| 场景（看参数特征） | 攻击 | 关键条件 / SageMath |
|---|---|---|
| `e` 很小（3,5,7）+ 同明文多接收者 | Håstad broadcast | CRT 合并后开 e 次整数根 |
| `d` 很小（`e` 大） | Wiener | `d < N^0.25`，连分数逼近 `e/N` 的收敛子 |
| `d` 较小（`e` 大） | Boneh-Durfee | `d < N^0.292`，二元 Coppersmith |
| `p,q` 接近 | Fermat | 从 `ceil(sqrt(N))` 向上试 `a^2 - N` |
| 多个 `N_i` 共享一个素因子 | common prime / gcd | `gcd(N_i, N_j)` 两两求 |
| `e` 与 `N` 同量级，`d` 小 | Boneh-Durfee | 见上 |
| 已知 `dp=d mod (p-1)` 较小 | dp 泄漏 / Coppersmith | `e*dp ≡ 1 mod (p-1)` → 枚举 k 求 p |
| CRT 计算出错（一个签名故障） | RSA-CRT 故障攻击 | 正确 sig 与错误 sig 比 → `p = gcd(s - s', N)` |
| `N` 为多素数 (multiprime) | Pollard / Fermat | 子群变小，离散对数/分解更易 |
| `p-1` 光滑 | Pollard p-1 | `a^(M!) mod N` 求 gcd |

```
参考来源（含题目对应）:
  - ISITDTU 2019 Easy_RSA_1: Boneh-Durfee [pcw109550/write-up/2019/ISITDTU/Easy_RSA_1]
  - ISITDTU 2019 Easy_RSA_2: 多素数 Fermat [pcw109550/write-up/2019/ISITDTU/Easy_RSA_2]
  - KAPO 2019 ROCA: Weak-Strong [pcw109550/write-up/2019/KAPO/Weak-Strong]
  - KAPO 2019 LLL: dp 泄漏 Coppersmith [pcw109550/write-up/2019/KAPO/Lenstra-Lenstra-Lovasz]
  - KAPO 2020 Child Beubmi: multiprime Coppersmith [pcw109550/write-up/2020/KAPO/Child_Beubmi]
  - CSAW 2019 Fault Box: RSA-CRT 故障 [pcw109550/write-up/2019/CSAW/Fault_Box]
```

#### 模板 E：Wiener（连分数）

```sage
def wiener(e, n):
    cf = continued_fraction(e / n)
    for k in cf.convergents():
        k_, d_ = k.numerator(), k.denominator()
        if k_ == 0: continue
        phi = (e * d_ - 1) // k_
        # 检验 n = p*q
        s = n - phi + 1
        disc = s*s - 4*n
        if disc >= 0 and is_square(disc):
            return d_
    return None
```

#### 模板 F：Pollard p-1

```sage
def pollard_pm1(n, B=2**16):
    a = 2
    for j in range(2, B):
        a = pow(a, j, n)
    d = gcd(a - 1, n)
    if 1 < d < n: return d
    return None
```

---

### 2.4 椭圆曲线攻击

```
技术名称: ECC 攻击家族
出现频率: 高（ECC 是 CryptoHack 大类）
核心分类:
  (a) Smart's attack     : anomalous curve, #E(F_p) = p → 提升到 Q_p 用 p-adic 离散对数，秒解
  (b) Pohlig-Hellman     : 群阶光滑 → 把 DLP 拆到小素数子群，逐个 CRT
  (c) MOV                : 嵌入度小 → Weil pairing 把 DLP 映到 F_{p^k} 上做
  (d) Singular curve     : 判别式=0 → 退化到 加法群/乘法群，DLP 变平凡
  (e) Invalid curve      : 点不在曲线上（输入未校验 a,b）→ 在弱曲线上算 DLP
  (f) Twist attack       : 用 twist 上的低阶点
  (g) 复合环上的曲线      : E over Z_n (n 合数) → 算 DLP 时顺带分解 n
数学条件:
  - Smart: trace t = p+1-#E == 1，即 #E == p
  - Pohlig-Hellman: ord(G) 的因子都小
  - MOV: 嵌入度 k = order(G) | p^k - 1 的最小 k 很小
  - Singular: a 或 b 使 4a^3+27b^2 == 0 (Weierstrass 下)
适用场景: 题目给自定义曲线参数；flag 是 DLP g^x 的 x
参考来源:
  - TSG 2023 Delta Force: DLP over singular curve over composite ring [pcw109550/write-up/2023/TSG/Delta-Force]
  - Facebook 2019 storagespace: 阶小，discrete_log() [pcw109550/write-up/2019/Facebook/storagespace]
  - angstromCTF 2022 logloglog: 素数幂阶 Pohlig-Hellman [pcw109550/write-up/2022/angstromCTF/logloglog]
  - CSAW 2019 SuperCurve: 小阶 ECDLP [pcw109550/write-up/2019/CSAW/SuperCurve]
  - Harekaze 2019 show_me_your_private_key: E over Zmod(n) [pcw109550/write-up/2019/Harekaze/show_me_your_private_key]
```

#### 模板 G：Smart's attack（anomalous curve）

```sage
def smart_attack(P, Q, p):
    E = P.curve()
    Eqp = EllipticCurve(Qp(p, 2), [ZZ(t) + randint(0,p)*p for t in [E.a4(), E.a6()]])
    P_qp = Eqp.lift_x(ZZ(P.xy()[0]), all=True)
    # 选正确的 lift（y 接近 P）
    P_qp = P_qp[0]
    Q_qp = Eqp.lift_x(ZZ(Q.xy()[0]), all=True)
    Q_qp = Q_qp[0]
    p_P = -P_qp[0] / P_qp[1]          # p-adic formal log
    p_Q = -Q_qp[0] / Q_qp[1]
    x_Q = ZZ(p_Q / p_P)
    return x_Q % p
```

#### 模板 H：Singular curve 退化

```sage
# 若 4a^3+27b^2 == 0，曲线奇异。节点(node)→乘法群 DLP；尖点(cusp)→加法群 DLP
# 尖点 (cusp, a2=0 重根): 映射 (x,y) -> x/y，DLP 变 y = m*x 加法
def singular_cusp_dlog(P, Q):
    # 适用于 y^2 = x^3 形（平移后）
    tP = P.xy()[0] / P.xy()[1]
    tQ = Q.xy()[0] / Q.xy()[1]
    return ZZ(tQ / tP)
```

#### 模板 I：Pohlig-Hellman（SageMath 一行）

```sage
# 直接用 SageMath：E.order() 光滑时 discrete_log 自动用 Pohlig-Hellman
n = E.order()
x = discrete_log(Q, P, ord=n, operation='+')   # 或 Q.discrete_log(P)
```

---

### 2.5 签名 / ZKP

```
技术名称: ECDSA/DSA nonce 重用与偏差 / ZKP Fiat-Shamir
出现频率: 高（nonce 类）/ 中（ZKP，2023+ 上升）
核心原理:
  - nonce 重用: 同一 k 两次签名 → k = (h1-h2)/(s1-s2) mod q，进而 x
  - nonce 偏差: k 的高位固定/低位小 → HNP → LLL（见 2.2 模板 C）
  - LCG 产生 nonce: tania (DEF CON 2019) → LLL 恢复 LCG 状态再推 nonce
  - ZKP frozen heart: Fiat-Shamir 的挑战由攻击者可控（未绑定 transcript）→ 伪造证明
数学条件:
  - nonce 重用: 直接代数，无条件
  - nonce 偏差: 需足够多签名（约 2*未知比特数 / 泄漏比特数 条）使 HNP 可解
适用场景: 给一堆签名 + 部分信息；ZK 系统交互式或 transcript 可控
参考来源:
  - DEF CON 2019 tania: DSA LCG nonce → LLL [pcw109550/write-up/2019/DEFCON/tania]
  - LINE CTF 2022 Baby crypto revisited: 归约到 ECDSA biased nonce [pcw109550/write-up/2022/LINE/Baby_crypto_revisited]
  - CODEGATE 2022 Final Look It Up: Plonkup frozen heart [pcw109550/write-up/2022/CODEGATE/Final/Look_It_Up]
```

#### 模板 J：ECDSA nonce 重用

```sage
# 已知 r, s1, h1, s2, h2（同一 k）
q = ...  # 曲线阶
k = ((h1 - h2) * inverse_mod(s1 - s2, q)) % q
x = (k * s1 - h1) * inverse_mod(r, q) % q
```

---

### 2.6 对称密码 / 哈希

```
技术名称: CBC padding oracle / GCM nonce reuse / 流密码 / 长度扩展 / 哈希碰撞
出现频率: 中
核心原理:
  - CBC padding oracle: 解密失败信息区分 → 逐字节恢复明文（PKCS#7）
  - GCM nonce reuse: 同 nonce 两次 → C1 xor C2 = P1 xor P2，且可伪造 GHASH → 恢复 H
  - 流密码(LFSR/truncated LCG): 输出序列 → Berlekamp-Massey 求特征多项式 / LLL
  - 长度扩展: H(secret||msg) 可在不 知道 secret 下算 H(secret||msg||pad||ext)
  - MD5/SHA1 碰撞: hashclash / hashcat；CTF 多给"前缀可控+附加固定"
适用场景: 有交互 oracle 的题；明显 nonce 重复；自实现哈希/PRNG
参考来源:
  - Pragyan 2020 AskTheOracle: padding oracle [pcw109550/write-up/2020/Pragyan/AskTheOracle]
  - TAMUctf 2020 ETERNAL_GAME: hash 长度扩展 [pcw109550/write-up/2020/TAMUctf/ETERNAL_GAME]
  - CCE 2023 NZK-SIARK: AES 中间态伪造 [pcw109550/write-up/2023/CCE/NZK-SIARK]
  - PlaidCTF 2022 choreography: Feistel slide attack [pcw109550/write-up/2022/PlaidCTF/choreography]
```

#### 模板 K：CBC padding oracle（逐字节）

```python
def padding_oracle_byte(oracle, prev_block, target_block, bs=16):
    plain = [0]*bs
    for i in range(bs-1, -1, -1):
        for guess in range(256):
            forged = bytearray(bs)
            for j in range(i+1, bs):
                forged[j] = plain[j] ^ (bs - i)
            forged[i] = guess
            if oracle(bytes(forged), target_block):  # 返回 padding 合法
                plain[i] = guess ^ (bs - i)
                break
    return bytes(a ^ b for a,b in zip(plain, prev_block))
```

#### 模板 L：hash 长度扩展

```python
import struct
def md5_pad(msg_len):
    pad = b'\x80'
    pad += b'\x00' * ((56 - (msg_len+1) % 64) % 64)
    pad += struct.pack('<Q', msg_len*8)
    return pad
# 用已知 H(secret||msg) 的内部状态作初始值，继续 update(append)
# pycryptodome/HashPumpy（HashPumpy 库封装最方便）
```

---

### 2.7 后量子 / 同源 / 其他新兴

```
技术名称: SIDH Castryck-Decru / Kyber / LWE / NTRU / FHE
出现频率: 中（SIDH 已模板化，Kyber 上升）
核心原理:
  - SIDH: 2022 Castryck-Decru 在几秒内破 SIDH（利用 torsion point 图结构）→ CTF 模板题
  - LWE: A*s + e = b，错误 e 小 → LLL/primal 恢复 s（参数弱时）
  - NTRU: h = f^-1 * g，f,g 短 → 格归约恢复
  - Kyber: 标准化但弱参数 / 实现错误（decryption failure 泄漏）
适用场景: 题目明确是后量子原语或自实现有缺陷
参考来源:
  - RCTF 2022 S2DH: SIDH Castryck-Decru [pcw109550/write-up/2022/RCTF/S2DH]
  - zer0pts 2022 Karen: Hidden Subset Sum Nguyen-Stern [pcw109550/write-up/2022/zer0pts/Karen]
```

---

## 三、工具链现状

### 3.1 SageMath 最佳实践（事实标准，CTF crypto 必装）
- **核心内置**：`small_roots`(Coppersmith)、`LLL()`、`BKZ()`、`discrete_log`(自动 Pohlig-Hellman+BSGS)、`factor()`(ECM/Pollard)、`EllipticCurve`、`Qp`(p-adic)、`continued_fraction`、`Matrix.LLL()`、`resultant`。
- **精度坑**：`small_roots` 的 `epsilon` 越小越稳但越慢（默认 1/8，常需调到 1/20~1/32）；`beta` 必须匹配因子占 N 的比例（p 是 N^0.5 → beta=0.5）。
- **多变量 Coppersmith**：官方 `small_roots` 只稳支持单变量；二元/多元需自定义 lattice（社区流传 `defund/coppersmith` 封装最常用，待核对仓库现址）。
- **p-adic 精度**：Smart's attack 需 `Qp(p, 2)`，精度不够会得到错解。

### 3.2 必备模板代码清单（应沉淀为独立 .sage 文件）
| 模板 | 用途 | 对应章节 |
|---|---|---|
| `coppersmith_univariate.sage` | stereotyped / partial p / 低 e | 2.1-A |
| `coppersmith_bivariate.sage` | short-pad / 分解 n | 2.1-B |
| `hnp_ecdsa.sage` | nonce bias / 部分已知 | 2.2-C |
| `subset_sum_lll.sage` | knapsack / hidden subset sum | 2.2-D |
| `rsa_wiener.sage` / `rsa_boneh_durfee.sage` | 小 d | 2.3-E |
| `rsa_dp_leak.sage` | dp 泄漏 | 2.3 |
| `ecc_smart.sage` | anomalous | 2.4-G |
| `ecc_singular.sage` | 奇异曲线 | 2.4-H |
| `ecdsa_reuse.sage` | nonce 重用 | 2.5-J |
| `cbc_padding_oracle.py` | CBC oracle | 2.6-K |
| `hash_length_ext.py` | 长度扩展 | 2.6-L |

### 3.3 辅助工具
- **gmpy2**：大整数快速运算、`invert`、`is_prime`、`gmpy2.iroot`（精确整数开根，开 Håstad 用）。
- **pycryptodome**：AES/RSA/CBC/ELGamal 实现 + 数据 IO；`Crypto.Util.number`。
- **sympy**：`discrete_log`、`nthroot_mod`、`sqrt_mod`（轻量替代）。
- **z3 / cvc5**：逆向类约束求解（如 InCTF 2021 find_plut0 用 z3）。
- **yafu / msieve / CADO-NFS**：分解中等规模 N（数域筛）。
- **factordb.com / alpertron**：在线查 N 是否已分解。
- **HashPumpy**：长度扩展攻击封装。
- **pwntools**：远程交互 oracle。
- **openssl / RsaCtfTool**：快速 RSA 体检（自动跑常见攻击）。

---

## 四、解题方法论

### 4.1 标准解题流程（现代 crypto 题通用）
1. **分类**：看给出的是 RSA(n,e,c) / ECC(E,P,Q) / 对称(ciphertext+oracle) / 签名(一组 sig) / 后量子(A,s,b) / ZKP(transcript)。
2. **提取参数特征**（见 4.2 表），据此定攻击。
3. **判定信息泄漏量**：泄漏的明文/nonce 比特数够不够支撑格攻击（HNP 需 `泄露比特数 * 样本数 ≥ q 比特数` 量级）。
4. **套模板 → 调参**：先用题目参数跑标准模板；失败时调 `epsilon/beta`、增加 lattice 维度、换 block_size。
5. **多原语串联**：单原语不通时，看能否归约到下一个（如 `truncated LCG → matrix LCG → LLL`；`biased nonce → HNP → LLL`）。

### 4.2 参数特征 → 攻击 速查表
| 观察到的特征 | 第一选择 |
|---|---|
| `e` 极小 (3,5,17) | Håstad / stereotyped Coppersmith |
| `e` 大且与 N 同量级 | Wiener → Boneh-Durfee |
| 多个 `N` | 两两 `gcd`（common prime） |
| `N = p*q`, `p≈q` | Fermat |
| `dp/dq` 泄漏 | dp leak Coppersmith |
| 签名 nonce 有规律 / 偏小 | HNP + LLL |
| 同 nonce | 直接代数 |
| 自定义曲线 `a,b` | 查 `4a^3+27b^2==0`(singular)、`#E==p`(Smart)、阶光滑(PH)、嵌入度(MOV) |
| 点未校验输入 | Invalid curve |
| AES + 解密失败区分 | CBC padding oracle |
| 同 nonce 两次 GCM | xor 明文 + GHASH 恢复 |
| 输出序列(流密码) | Berlekamp-Massey / LLL |
| LWE/NTRU 弱参数 | LLL primal/dual |

### 4.3 常见「卡住」点及突破
- **Coppersmith `small_roots` 返回空**：`epsilon` 调小（1/20→1/30）、`X` 上界重新估算（是否过大）、确认 `beta` 与因子占比匹配。
- **LLL 没出目标向量**：维度不够（加更多样本/行）、目标向量 gap 不够（归一化、加权列）、换 Babai nearest plane、上 BKZ 提高 block_size。
- **discrete_log 太慢**：检查阶是否光滑（应自动 PH）；若不光滑考虑 MOV/Smart/Singular 是否适用。
- **结果乱码**：检查字节序、padding、是否 RSA-CRT 故障需用正确签名对照。
- **远程 oracle 题慢**：用 pwntools 批量、二分/并行减少交互次数。

---

## 五、知识库缺失识别（沉淀建议）

### 应沉淀（通用可复用原语）
- **算法级模板**：Coppersmith 单/多变量、LLL/HNP、subset-sum、Wiener、Boneh-Durfee、dp-leak、Smart、Singular、Pohlig-Hellman、ECDSA reuse/bias、CBC padding oracle、长度扩展、Berlekamp-Massey。这些是「换题即用」的原子能力，独立成 `.sage`/`.py` 模板。
- **判定决策树**：4.2 的「参数特征→攻击」表，作为自动分析引擎的规则集。
- **调参经验**：epsilon/beta/维度选择的经验值（来自实战复盘）。

### 不沉淀（特定题目 trick）
- 具体 flag 求解脚本、特定赛事的逆向壳（如 dodge 求解器、minesweeper 求解器）。
- 纯逆向/取证细节（QR 恢复、JPEG marker 等）——属于 misc/reverse，非密码原语。
- Solidity/EVM 细节（pcw109550 仓库中 blockchain 部分）——单独成域。

### 2023–2026 新增应关注的沉淀方向（建议补充进知识库）
1. **SIDH Castryck-Decru 模板**（已模板化但多数库缺）。
2. **ZKP frozen heart / Fiat-Shamir 攻击**（plonk/groth16 类，2023+ 上升）。
3. **Kyber/Dilithium 弱参数与实现错误**（PQC 标准化后必考）。
4. **多变量 Coppersmith 的可复用 lattice 构造库**（官方不支持，社区实现分散）。

---

## 参考来源索引（验证状态）

| 来源 | 状态 | 链接 |
|---|---|---|
| CryptoHack（分类结构，含 Lattices/ZKP/Isogenies 新类） | 已验证 | https://cryptohack.org/ |
| pcw109550/write-up（220★，技术-题目映射到 2023） | 已验证 | https://github.com/pcw109550/write-up |
| rkm0959/CTFWriteups（82★，到 2023） | 已验证 | https://github.com/rkm0959/CTFWriteups |
| CTFtime 2026 crypto 题（Polynomial Drift / Sealed Signal / Hextrap / China Crack） | 已验证题名 | https://ctftime.org/writeups |
| Anti-Slop CTF 2026 crypto writeup | 待核对 | https://cybersecurityelite.com/ctf-writeups/anti-slopctf-2026-crypto-writeup/ |
| Coppersmith 1996 Eurocrypt 原始论文 | 待核对（eprint 403） | 10.1007/3-540-68339-9_14 |
| defund/coppersmith 多变量封装 | 待核对（仓库现址需确认） | — |
| eprint.iacr.org 各年 | 待核对（直抓 403，需逐篇） | https://eprint.iacr.org/ |
| xz.aliyun.com 中文 writeup | 待核对 | https://xz.aliyun.com/ |
