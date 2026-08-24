# RSA 攻击

> 何时用：题目有 `n=p*q`、公钥指数 `e`、密文 `c=pow(m,e,n)`，或给出 p/q 的 hint。开始时先读本文件定位攻击方向。

## 0. 通用约定

bytes↔int 转换用 Python 标准库：

```python
def i2b(n):  # int -> bytes (大端)
    return n.to_bytes((n.bit_length()+7)//8 or 1, 'big')
def b2i(b):  # bytes -> int (大端)
    return int.from_bytes(b, 'big')
```

> **后续各节代码片段默认已定义 `i2b`/`b2i`**（见本节）。复制单段运行时需先包含本节定义。

## 1. 先做的事：参数体检

拿到 RSA 题先列参数，找"异常点"（异常 = 攻击方向）：

| 观察 | 异常点 | 指向攻击 |
|------|--------|---------|
| `e` 很小（3/5/7/17） | 小指数 | §2 直接开方 / §3 Hastad |
| `e` 很大（接近 n） | d 很小 | §4 Wiener / §5 Boneh-Durfee |
| 多组 `(c_i, n_i)` 同 `e` | 广播 | §3 Hastad |
| 两组同 `n` 不同 `e` | 共模 | §6 共模 |
| `n` 可分解 | factordb/特殊形 | §7 分解 |
| 给了 p/q 的高位或低位 | partial | §8 Coppersmith（引 lattice-attacks.md） |
| 已知 `p`、`q` 或 `phi` | 直接解 | §9 |

## 2. 小 e + 明文小：直接开方

**何时用**：`e` 很小（如 3）且 `m**e < n`（明文未填充或填充很短），则 `c = m**e`（没模掉）。

```python
import gmpy2
m, exact = gmpy2.iroot(c, e)   # e 次整数开方
if exact:
    print(i2b(int(m)))
```

失败（`exact=False`）→ 明文 `m**e ≥ n`，转 §3 Hastad 或加 padding 的 Coppersmith。

## 3. Hastad 广播攻击（同 e 多组密文）

**何时用**：同一明文 `m` 用**相同小 `e`** 加密到 `e` 个不同模数 `n_i`，得 `c_i`。

**原理**：CRT 合并 `c_i mod n_i` 得 `C = m**e mod (Π n_i)`，因 `m**e < Π n_i`，直接开 `e` 次方。

```python
from sympy.ntheory.modular import crt
import gmpy2
# ns=[n0,n1,n2], cs=[c0,c1,c2], e=3
C, _ = crt(ns, cs)              # CRT 合并
m, exact = gmpy2.iroot(C, e)
assert exact
print(i2b(int(m)))
```

## 4. Wiener 攻击（d 小，e 大）

**何时用**：`e` 很大（接近 `n`）→ 私钥 `d` 很小（`d < n^0.25 / 3`）。用 `d` 的连分数逼近。

```sage
# solve.sage
def wiener(e, n):
    cf = continued_fraction(e/n)
    for k, d in cf.convergents():
        if k == 0: continue
        phi = (e*d - 1) // k
        # 判二次方程 x^2 - (n-phi+1)x + n = 0 有整数根
        s = n - phi + 1
        disc = s*s - 4*n
        if disc >= 0 and is_square(disc):
            return d
    return None
d = wiener(e, n)
m = pow(c, d, n)
print(bytes.fromhex(hex(m)[2:]))
# 运行: sage solve.sage
```

无 sage 时用 `owiener` 库：`pip install owiener; d = owiener.attack(e, n)`。

## 5. Boneh-Durfee（d 较小但超 Wiener 界限）

**何时用**：`d < n^0.292`（比 Wiener 的 0.25 界限大）。用 Coppersmith 求小根。

```sage
# 思路: 由 e*d ≡ 1 (mod phi), e*d = k*phi + 1
#   => k*e ≡ k (mod n-...) 实际解  e*d - 1 = k*(n - p - q + 1) + ...
# 用 defund/coppersmith 的 small_roots 或现成 boneh_durfee.py
# github: mimoo/RSA-and-LLL-attacks 或 cr-thead/boneh_durfee
```

建议直接用社区现成 `boneh_durfee.sage`（参数调 `delta=0.292`、`m`、`t`）。

## 6. 共模攻击（同 n 不同 e）

**何时用**：同一 `n`，两组 `(e1, c1)`、`(e2, c2)`，且 `gcd(e1, e2) == 1`。

**原理**：由扩展欧几里得找 `s, t` 使 `s*e1 + t*e2 == 1`，则 `m = c1^s * c2^t mod n`。

```python
import gmpy2
g, s, t = gmpy2.gcdext(e1, e2)
assert g == 1
m = (pow(c1, s, n) * pow(c2, t, n)) % n   # 负指数 pow 自动处理 (Python3.8+)
print(i2b(m))
```

## 7. 分解 n

**何时用**：`n` 特殊（可分解）。

| 形式 | 方法 |
|------|------|
| 小 `n`（< 60 位十进制） | `sympy.factorint(n)` 或 factordb.com |
| `p`、`q` 接近（差小） | Fermat 分解：从 `√n` 往上试 `a`，`b²=a²-n`；q=next_prime(p) 时直接 `p = prevprime(isqrt(n)+1)` 递减试除更快 |
| 多素数 / 有小因子 | `sympy.factorint` / ECM（`yafu`） |
| 已在 factordb | 直接查 factordb.com |
| p-1 光滑（B-smooth） | Pollard p-1：`a=pow(a,j,n)` 累计到 B!，`gcd(a-1,n)=p`；不够大递增 B 重试；p+1 光滑试 Williams 变体 |
| 有 phi 的倍数（e\*d-1 等） | Miller-Rabin 平方根技术分解：M=2^s*d，随机 a 走平方链找非平凡平方根，`gcd(prev-1,n)` 出因子，单次成功率 ≥1/2 |
| Infineon 结构化素数（TPM/YubiKey 4） | ROCA（CVE-2017-15361）：`roca-detect` 检测，512-bit 用 neca 分钟级分解 |
| 素数 = 小系数×大基数+小余量（p=kp\*B+tp） | 混合基分解：A=n//B²=kp*kq，D=n%B=tp*tq，暴力 2^12 级 kp |
| q 由 p 经公开关系派生（q=e⁻¹ mod p 等） | 关系写成 f_k(p)=0 参数化多项式，sage `.roots()` 枚举小 k |
| q ≈ k\*p（k 已知） | Coppersmith：q_approx = k\*isqrt(N//k) + 2^(bitlen/2) 上界边距，f=q_approx-x，small_roots(X, beta=0.5)（Fermat 的已知比例推广） |
| 素数数字集受限（如只含 6/7） | LSB 起逐位恢复+剪枝：q mod 10^k = n\*p⁻¹ mod 10^k，两位数字都须在集合内；十进制结构 p=base+10^k\*x 用 f = x + base\*inv(10^k,N) |
| 多模数共享素数 | batch GCD（product tree，数千密钥 O(n log n)）；三模数两两共素（N1=p1p2,N2=p1p3,N3=p2p3）三次 gcd 封闭解；生成器用 next_prime(2^k+small) 时 delta 落同间隙即收敛共素 |
| p+q 近似已知（和的高位） | 二维格 [[2^bits, -offset],[0, n+1]] LLL 短向量给 p+q，x²-sx+n=0 求根；Fermat 是 offset≈2√n 特例 |
| 两组密钥 d1≈d2（共模） | d2-d1 ≡ (e1e2)⁻¹(e1-e2) (mod p)，f=r-x small_roots(X=差值上界, beta=0.5)，与 Wiener（d 本身小）互补 |
| 四元数/高维代数 RSA | 幂运算下向量方向不变 → 密文分量比 c1:c2:c3 = a1:a2:a3 → 消 m 得 A·p+B·q≡0 → gcd(A,n),gcd(B,n) 分解; 解密阶用 p²-1（Wedderburn，F_p 上 ≅ M₂(F_p)） |
| 多个 p/q 多项式组合 | 构造两个都含目标素数的表达式取 gcd，试除小素剥离 |

```python
# Fermat (p,q 接近)
import gmpy2
a = gmpy2.isqrt(n) + 1
while not gmpy2.is_square(a*a - n):
    a += 1
b = gmpy2.isqrt(a*a - n)
p, q = int(a+b), int(a-b)
```

## 8. 已知 p/q 的高位或低位 → Coppersmith

**何时用**：给了 `p` 的高 `k` 位或低 `k` 位（未知位 < `n^0.5 / 2` 量级）。**详见 `$AGENT_DIR/knowledge-base/lattice-attacks.md`**（Coppersmith 的格构造原理）。

```sage
# 已知 p 高位 p0 (低 unknown_bits 位未知)
P.<x> = PolynomialRing(Zmod(n))
f = p0 + x
roots = f.small_roots(X=2^unknown_bits, beta=0.5)
# roots[0] 即 p 的未知低位
```

## 9. 已知 p、q 或 phi：直接解

```python
import gmpy2
phi = (p-1)*(q-1)
d = gmpy2.invert(e, phi)
m = pow(c, d, n)
print(i2b(int(m)))
```

`phi` 直接给（非 p/q）：同样 `d = gmpy2.invert(e, phi)`。注意 `phi` 与 `n` 的关系验算 `n - phi + 1 == p + q`。

多素数模数 phi：`phi = Π (p_i-1) * p_i^(e_i-1)`（含素数幂；square-free 时 Π(p_i-1)）。多小素数时逐素数幂 `d_pk = pow(e,-1,(p-1)*p^(k-1))` 解密再 CRT 合并。

## 9a. gcd(e, phi) > 1（d 不存在）

- **指数约减**：e'=e/g，d'=e'⁻¹ mod phi，`pow(c,d',n)` = m^g，`iroot(m^g, g)` 开根；不过界时遍历 `iroot(m^g + k*n, g)` 小 k
- **逐素数开根 + CRT 枚举**：每素因子 p≡1 (mod e) 时 `nthroot_mod(c%p, e, p, all_roots=True)` 有 e 个根，`itertools.product` 枚举组合（3^13≈160 万可行），CRT 合并后按可打印过滤

## 9b. 非标准模数结构

- **n = p²q（Schmidt-Samoa）**：phi = p*(p-1)*(q-1)（不是 (p-1)²(q-1)）。gcd(e,phi)≠1 时约化到 q 子域：`enc=pow(enc, inverse_mod(q,phi), n) % q`，再 `pow(enc, inverse_mod(p*p,q-1), q)`。识别：iroot(n,3) 近整数
- **p=q 校验绕过**：服务端用 (p-1)² 验证 phi(p²)=p*(p-1) 的错误值 → 校验过但测试解密失败泄漏密文。phi(p^k)=p^(k-1)(p-1)
- **e=1 + 构造模数**：验证方接受用户 (n,e) 无约束时，设 n = sig - PKCS1_pad(msg) 使 pow(sig,1,n) 通过
- **Rabin（e=2）四根解密**：p,q≡3 (mod 4) 时闭式根 mp=c^((p+1)/4) mod p、mq 同理（无需 Tonelli-Shanks），Bezout 系数组合四候选 ±(yp·p·mq ± yq·q·mp)，按可读 ASCII/magic bytes/前缀筛唯一明文。素数由小变量多项式派生（p=r²+3、q=r²+7 类）→ N 展开是 r 的多项式，`iroot(N - 常数, 4)` 直接恢复 r

## 10. 乘法同态滥用族（无 padding RSA）

- **签名黑名单绕过**：S(a)*S(b)=S(a*b)。目标 m 分解成 x*y（小因子试除，两者都过黑名单），签名相乘。hash 是 CRC 类可碰撞函数时用 crchack 逐因子构造 CRC=f_i 的消息连乘伪造（要求因子全 < 2^32 落入 CRC32 值域）
- **解密黑名单盲化**：dec(c * pow(r,e,n) % n) * inverse(r,n) % n = m。变体：奇 e 时乘 pow(-1,e,n)=n-1 翻转明文符号绕过明文黑名单
- **隐藏模数恢复**：加密 oracle 用 `gcd(m1^e-enc(m1), m2^e-enc(m2))`；解密 oracle 发 c 与 c*2^e，wraparound 差 `2*m - (2m mod N) = N`
- 防御视角：PKCS#1 padding 存在的意义——带 padding 消息无法分解成其他合法带 padding 消息

## 11. Oracle/侧信道攻击

- **Manger（OAEP 首字节阈值 oracle）**：B=2^(8(k-1))，oracle 判 m < B。三步：倍增 f1 至过界 → (n+B)//B*f1//2 起 +f1//2 步进找 f2 → 二分收缩（1024-bit 约 1024 查询）。比 Bleichenbacher（v1.5，~10K 查询）收敛快
- **Python or 短路时延 oracle**：昂贵 KDF 排在条件链后位被短路 → 快=Y≠0 / 慢=Y==0。校准（known-fast/known-slow 各 5 采样定阈值）+ 模糊区间重试
- **LSB oracle 噪声版**：随机出错不收敛 → 跑 N 轮逐字节取众数（`Counter.most_common`）；或恢复后按字符集定位错误位翻转重算
- **Montgomery 规约时序（Kocher）**：额外条件减法次数泄漏 → MSB 起 逐位猜 0/1 预测减法数与观测取 corrcoef。768-bit 需 ~20 万签名
- **RSA-CRT 故障**：单比特翻转 d 时 `ratio = s_bad * s_good⁻¹ mod n == 2^(±2^k) mod n` 逐位恢复 d；输出前不自验的 CRT 实现一次故障即泄因子 gcd(s^e-m, n)
- **CRT 字段解析缺陷**：无边界 fgets 读 d_p 发 33+ 空字节 → d_p=0 → m_2=0^0=1 → gcd(sig-1, N)=p；`buf[strlen-1]=0` 剥换行遇空输入回写覆盖相邻模数末字节（N' 与真 N 差 ≤255，delta 暴力）

## 12. 部分密钥泄漏

dp/dq/qinv 任一泄漏即全恢复：`for k in range(3, e): p = (dp*e-1)//k + 1; is_prime(p)` 命中即 p（O(e) 瞬时）。原理 e*dp-1 = k*(p-1)，k < e。PEM 只泄底部 CRT 区照样沦陷。

## 13. 实现细节补遗

- **Franklin-Reiter GCD 形态**（e=3 已知两 padding 差）：`f1=(X+pad1)^3-c1, f2=(X+pad2)^3-c2`，`m = -gcd(f1,f2).coefficients()[0]`（Zmod(n) 上）
- **立方根回绕**：m^e > n 时 `iroot(c + k*n, e)` 遍历小 k；CTR/流密码辅助密文保长提示 k 范围；已知倍数位移先乘模逆消位移
- **签名指数错用**：签名端用 e 代替 d（sign=m^e mod n）→ m^e<n 时任何人 integer_nthroot(m,e) 本地伪造签名; 根治靠验证 padding 结构而非裸 m
- **密钥影响字节受限**：密钥 ≤512 bit 只影响前 ~64 字节 → 前缀解密 + 参考文件拼尾部（PNG IEND/ZIP EOCD 等标准块）
- **多项式 hash 平凡根**：g(0)=0 → 签名恒 0；构造 msg ≡ 0 (mod P)：req = -prefix*256^len mod P，随机 high 凑 low 可打印
- 工具：RsaCtfTool（自动套件 `RsaCtfTool.py -n <n> -e <e> --uncipher <c>`）、`openssl rsa -pubin -text -noout`、rsatool.py 生成 PEM

## 决策

```
e 很小?
├─ 单组 + m**e<n → 直接开方 (§2)
├─ m**e≥n → iroot(c+k*n, e) 遍历回绕 (§13) → 多组同 e → Hastad (§3)
e 很大? → Wiener(§4) → 失败试 Boneh-Durfee(§5)
同 n 多 e (gcd=1)? → 共模 (§6)
gcd(e,phi)>1? → 指数约减/CRT 枚举 (§9a)
n 特殊? → 分解 (§7 查表: 光滑/共享/结构化/受限数字/关系派生)
给了 p/q 的部分位? → Coppersmith (§8, 转 lattice)
已知 p,q/phi/phi倍数? → 直接解 (§9) / Miller-Rabin 分解 (§7)
泄了 dp/dq? → §12 O(e) 恢复
有解密/签名 oracle? → §10 同态滥用 / §11 oracle 族
验证方接受自定义 (n,e)? → §9b e=1 构造模数
```

## 注意

- **先验证**：求出 `m` 必须 `i2b` 看是否像 flag，不能只算出数
- `pow(c, s, n)` 中 `s` 为负时，Python 3.8+ 自动用模逆，旧版本需手动 `pow(c, -1, n)`
- Coppersmith 的 bound 要满足 `unknown < N^(beta²/delta)`，调 `beta`/`epsilon`
- 解出 `m` 后若 `pow(m, e, n) != c`，说明 `m` 错或攻击选错
