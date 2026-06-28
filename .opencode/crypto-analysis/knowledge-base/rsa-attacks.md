# RSA 攻击

> 何时用：题目有 `n=p*q`、公钥指数 `e`、密文 `c=pow(m,e,n)`，或给出 p/q 的 hint。开始时先读本文件定位攻击方向。

## 0. 通用约定

bytes↔int 转换用标准库（无需 pycryptodome）：

```python
def i2b(n):  # int -> bytes (大端), 等价于 pycryptodome 的 long_to_bytes
    return n.to_bytes((n.bit_length()+7)//8 or 1, 'big')
def b2i(b):  # bytes -> int (大端), 等价于 bytes_to_long
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
| `p`、`q` 接近（差小） | Fermat 分解：从 `√n` 往上试 `a`，`b²=a²-n` |
| 多素数 / 有小因子 | `sympy.factorint` / ECM（`yafu`） |
| 已在 factordb | 直接查 factordb.com |

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

## 决策

```
e 很小?
├─ 单组 + m**e<n → 直接开方 (§2)
└─ 多组同 e → Hastad (§3)
e 很大? → Wiener(§4) → 失败试 Boneh-Durfee(§5)
同 n 多 e (gcd=1)? → 共模 (§6)
n 特殊? → 分解 (§7)
给了 p/q 的部分位? → Coppersmith (§8, 转 lattice)
已知 p,q/phi? → 直接解 (§9)
```

## 注意

- **先验证**：求出 `m` 必须 `i2b` 看是否像 flag，不能只算出数
- `pow(c, s, n)` 中 `s` 为负时，Python 3.8+ 自动用模逆，旧版本需手动 `pow(c, -1, n)`
- Coppersmith 的 bound 要满足 `unknown < N^(beta²/delta)`，调 `beta`/`epsilon`
- 解出 `m` 后若 `pow(m, e, n) != c`，说明 `m` 错或攻击选错
