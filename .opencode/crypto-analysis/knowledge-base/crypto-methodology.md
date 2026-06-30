# 密码学分析方法论

> 总入口：识别题目类型 → 路由到对应攻击库 → 用 SageMath 求解。开始分析时先读本文件。

## 1. 类型识别（最先做）

拿到题目先判断属于哪类，再读对应攻击库。按特征匹配：

| 看到的特征 | 类型 | 去读 |
|------------|------|------|
| `n=p*q`、`e`、`c=pow(m,e,n)`；或给了 p/q 的 hint | RSA | `rsa-attacks.md` |
| 多个 `a*p+b*q`、截断比特、近似值、HNP | 格（lattice） | `lattice-attacks.md` |
| 椭圆曲线方程 `y²=x³+ax+b (mod p)`、点加法/标量乘、离散对数 `Q=kG` | ECC | `ecc-attacks.md` |
| 凯撒/维吉尼亚/单表替换/无密钥、字母频率 | 古典 | `classical-crypto.md` |
| AES/DES、CBC/ECB/CTR/GCM、padding 报错、IV 可控 | 对称 | `symmetric-and-hash.md` |
| MD5/SHA、`mac=hash(key∥msg)`、长度扩展 | 哈希 | `symmetric-and-hash.md` |
| PRNG、随机数、状态恢复 | 伪随机 | 按子类（LCG/LFSR/Mersenne Twister）查通用资料；LCG 恢复见 `symmetric-and-hash.md` §6 |
| 构造满足整除/模运算/位运算约束的输入（非给密文求明文） | 数论构造题 | `number-theory-construction.md` |
| circom/snarkjs/halo2 电路、Σ 协议、`c=H(transcript)` Fiat-Shamir | ZKP（零知识证明） | §5 ZQP 攻击速查（Fiat-Shamir 伪造/欠约束电路/Castryck-Decru SIDH） |
| 加密/评估 oracle（SEAL/CKKS/BFV）、LWE 参数、噪声预算 | FHE（全同态加密） | §5 速查（噪声/oracle 滥用 → LWE 格归约恢复密钥） |
| Kyber/ML-KEM、Dilithium、LWE/RLWE 公式、SIDH 辅助点映像 | PQC（后量子） | LWE→`lattice-attacks.md`；SIDH→§5 ZQP 攻击速查（Castryck-Decru） |

**判断不清时**：把题目所有参数列出来，看"哪个参数异常"（e 太小/太大、hint 数量、比特长度关系）——异常点就是攻击方向。

## 2. 通用求解流程

```
1. 提取全部已知量（n, e, c, hint, 曲线参数……）写进脚本常量
2. 识别攻击模式（见各攻击库的"什么时候用"）
3. 用 SageMath 构造求解（格 → matrix.LLL()；多项式小根 → small_roots()；离散对数 → discrete_log）
4. 求出 p/q/明文 → i2b → 验证 flag 格式
5. 失败 → 回溯：换攻击 / 检查参数识别 / 调格构造参数
```

## 3. SageMath 使用基础

### 3.1 何时用 sage（优先于手写）

- **格规约 LLL/BKZ**：`matrix.LLL()`、`matrix.BKZ()`——手写极易出错，必用 sage。
- **多项式小根（Coppersmith）**：`f.small_roots(X=, beta=, epsilon=)`。
- **离散对数**：`discrete_log(Q, G)`、Pohlig-Hellman 自动用。
- **椭圆曲线运算**：`EllipticCurve(...)`、点运算 `+`、`*`。
- **数论**：`factor(n)`、`nth_root`、`GF(p)`、`Zmod(n)`。

### 3.2 调用方式

```bash
# .sage 文件（含 sage 语法）
sage solve.sage

# 或 sage 跑 python
sage -python solve.py
```

### 3.3 sage 缺失时

detect_env 会检测。若缺失：
- 格攻击/Coppersmith/ECC 离散对数 → **必须先装 sage**（detect_env 会给命令：`conda install -p ~/bw-security-analysis/.venv sage`）。
- 简单 RSA（已知 p/q 直接解）、古典、对称 → 用 `gmpy2` + `sympy` 手写可行。

## 4. 大整数与编码

```python
# bytes↔int 用 Python 标准库
def i2b(n):  # int -> bytes (大端)
    return n.to_bytes((n.bit_length()+7)//8 or 1, 'big')
def b2i(b):  # bytes -> int (大端)
    return int.from_bytes(b, 'big')
# 明文整数 → bytes（flag）
flag = i2b(m)
# 检查
assert flag.startswith(b'flag') or flag.startswith(b'SEKAI')
```

`gmpy2` 基本运算：
```python
import gmpy2
d = gmpy2.invert(e, (p-1)*(q-1))   # RSA 私钥
m = pow(c, d, n)
phi = (p-1)*(q-1)
```

## 5. 参数特征→攻击速查表（详见各攻击库）

### RSA 参数异常

| 参数特征 | 攻击 | 条件/说明 |
|---------|------|----------|
| 同 n 不同 e | 共模攻击（common modulus） | `gcd(e1,e2)=1`，用扩展欧几里得合并 |
| e 很小（3/5/7）+ m 小 | 直接开方 / Coppersmith | m < n^(1/e) 直接开 e 次方；否则 small_roots |
| e 很小 + 多组 (c_i, n_i) 同明文 | Håstad broadcast | 需要 ≥ e 组 |
| d 小（e 大，接近 n） | Wiener（d < n^0.25）/ Boneh-Durfee（d < n^0.292） | Wiener 用连分数；BD 用格 |
| n1, n2 共因子 | `gcd(n1, n2)` | 多个 n 时两两 GCD |
| 已知 p 的高/低 k 位 | Coppersmith partial factor | 已知 > n^0.25 位即可 |
| 已知 d 的高/低 k 位 | partial key exposure | 已知 d 的 n^0.25 位即可 |
| 已知 p+q 或 p-q | 转化 → 一元二次 → 求根 | `(p+q)^2 - 4n = (p-q)^2` |
| 给了 dp/dq（CRT 密钥） | CRT 攻击 | dp 满足 `e*dp ≡ 1 mod (p-1)` |
| 两次加密有线性关系 m1=a*m2+b | Franklin-Reiter / Coppersmith related | e=3 最有效 |
| 给了多个 a*p+b*q 形式的 hint | LLL 格规约 | 见 lattice-attacks.md |

### ECC 参数异常

| 参数特征 | 攻击 | 条件 |
|---------|------|------|
| 曲线判别式 Δ=0（奇异） | singular curve | cusp: y²=x³ → 映射到加法群；node: y²=x²(x+a) → 映射到 GF(p) 乘法 |
| 曲线阶 = p（anomalous） | Smart's attack | `p == E.order()`，把 ECDLP 降到 GF(p) 加法 |
| 阶光滑（小因子分解） | Pohlig-Hellman | `order` 的因子全小，sage `discrete_log` 自动用 |
| 超奇异（#E = p+1） | MOV / Supersingular | embedding degree 小，映射到有限域 |
| 点不在曲线上（invalid curve） | invalid curve attack | 换曲线阶分解离散对数 |
| twist 攻击 | twist attack | 未验证点 ∈ E，用 twist 的低阶子群 |

### 格/Lattice 参数异常

| 参数特征 | 攻击 | 条件 |
|---------|------|------|
| 多组 hint 含 p,q 线性组合 | LLL 格规约 | 见 lattice-attacks.md |
| 截断的 LCG 输出 / 截断比特 | HNP（Hidden Number Problem） | 构造 CVP，LLL 求解 |
| LWE（带噪声线性方程） | 格规约 / BKZ | 噪声小时 LLL 可解 |
| NTRU 结构 | 格规约 | 私钥 = 短向量 |
| 多变量多项式小根 | Coppersmith 多元（defund 封装） | 见 Coppersmith 小节 |

### 对称/哈希 参数异常

| 参数特征 | 攻击 | 条件 |
|---------|------|------|
| CBC + padding 报错反馈 | Padding Oracle | 逐字节解密，`l = len(block)` |
| GCM nonce reuse | GF(2^128) 求解 XOR | 两密文 XOR 去掉认证 |
| ECB 模式 | cut-paste / 字典 | 相同明文块→相同密文块 |
| mac = hash(key ∥ msg) | 长度扩展 | MD5/SHA1 可扩展 |
| 自定义 ARX（ChaCha/Salsa 变种） | 差分分析（简化版） | 轮数不足时 |
| LFSR 已知输出 | B-M 算法 / 格 | Berlekamp-Massey 求特征多项式 |

### DSA/ECDSA 参数异常

| 参数特征 | 攻击 | 条件 |
|---------|------|------|
| 两次签名 nonce k 相同 | 直接解出 k → 私钥 | `k = (m1-m2)/(s1-s2) mod n` |
| nonce k 有偏（HNP） | 格规约 | k 的高/低位固定 |

### ZKP / Fiat-Shamir 攻击速查

| 参数特征 | 攻击 | 关键步骤 |
|---------|------|---------|
| Fiat-Shamir 哈希输入缺公开量（如公钥 h） | **伪造证明** | 任取 u、随机 z → `c=H(g,q,u)` → 反推 `h=(g^z/u)^{1/c}` → 提交 `(u,c,z)` 双校验通过 |
| 交互式 Σ 协议 + 可控 verifier challenge | **HVZKP 恶意验证者** | Two-Prime-Divisor: 发 `ρ=r² mod N`，prover 返回 `σ`，`gcd(N,σ-r)` 出因子；Short Factoring: `e=A` 反解 `φ(N)≈N-y//e` |
| circom/halo2 电路有 `<--` 无 `<==` | **Under-constrained circuit** | 找未约束信号，构造满足等式但取非预期值的 witness |
| SIDH 公开辅助扭基点映像 | **Castryck-Decru 攻击** | 构造积曲面 + Richelot (2,2)-isogeny 分裂逐位恢复私钥（SageMath 脚本搜索：Castryck-Decru-SageMath）|

## 6. Coppersmith 变种速查

> Coppersmith 方法 = 在模 n（或 n 的因子）下求多项式小根。是 RSA 题的核心武器。

| 变种 | 场景 | sage 模板 |
|------|------|---------|
| **small_roots** | f(x) 在 mod n 下有小根 | `P.<x>=PolynomialRing(Zmod(n)); f.small_roots(X=上界, beta=1)` |
| **partial key exposure (d)** | 已知 d 的高/低 k 位 | 构造 `f(x) = e*x - 1` 在 mod phi(n) 下 |
| **partial factor (p)** | 已知 p 的高/低 k 位 | `f(x) = x + p_high`，`beta=0.5`，在 mod n 下 |
| **stereotyped message** | 已知明文前缀 | `f(x) = (prefix + x)^e - c` |
| **related message** | m2 = a*m1 + b | `f1 = m1^e - c1`, `f2 = (a*m1+b)^e - c2`，resultant 消元 |
| **broadcast** | 同明文 e 组 (c_i, n_i) | CRT 合并 → `m^e mod (n1*n2*...)` → 开 e 次方 |
| **多元（defund）** | 多变量多项式小根 | 用 `defund/coppersmith` 封装（GitHub） |

**基本调用**：
```python
# 单变量 Coppersmith
P.<x> = PolynomialRing(Zmod(n))
f = (known_prefix * (256^k) + x)^e - c
roots = f.small_roots(X=256^unknown_bytes, beta=1, epsilon=0.05)
```

**参数调优**：`epsilon` 越小越能找到根但越慢（默认 1/e）；`X` 是根的上界（要准确估计）。

## 7. 注意

- **先验证再下结论**：求出候选明文必须 `i2b` 看是否像 flag，不能只算出数就说"解了"。
- **参数即线索**：e=3、n=2*p、hint=3 个、bits 不对称……每个异常都指向特定攻击。
- **不盲目爆破**：先模式匹配；爆破只在搜索空间极小（如古典密码位移）时。
