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
| PRNG、随机数、状态恢复 | 伪随机 | `prng-attacks.md`（MT/V8/Java/LCG/种子审计/自制递推）；LCG 参数恢复另见 `symmetric-and-hash.md` §6 |
| 构造满足整除/模运算/位运算约束的输入（非给密文求明文） | 数论构造题 | `number-theory-construction.md` |
| circom/snarkjs/halo2 电路、Σ 协议、`c=H(transcript)` Fiat-Shamir | ZKP（零知识证明） | §5 ZQP 攻击速查（Fiat-Shamir 伪造/欠约束电路/Castryck-Decru SIDH） |
| 加密/评估 oracle（SEAL/CKKS/BFV）、LWE 参数、噪声预算 | FHE（全同态加密） | `fhe-attacks.md`（方案识别/密钥恢复/galois/CKKS精度/oracle）；密钥恢复见 `lattice-attacks.md` |
| Kyber/ML-KEM、Dilithium、LWE/RLWE 公式、SIDH 辅助点映像 | PQC（后量子） | LWE→`lattice-attacks.md`（§5h PQC 实现泄漏）；SIDH→§5 ZQP 攻击速查（Castryck-Decru） |
| 辫群/热带半环/Paillier/GM/OSS/Cayley-Purser/BB-84 模拟等冷门方案 | 异型代数结构 | `exotic-algebra-attacks.md`（不变量/残差/复制隔离/小群查表） |
| `.sol`/Foundry(`foundry.toml`)/Hardhat、`pragma solidity`、`isSolved()`、RPC 端点 | 智能合约（blockchain） | `blockchain-attacks.md`（delegatecall/重入/access control/整数/签名/随机数/flash loan） |

**判断不清时**：把题目所有参数列出来，看"哪个参数异常"（e 太小/太大、hint 数量、比特长度关系）——异常点就是攻击方向。

## 2. 通用求解流程

```
1. 提取全部已知量（n, e, c, hint, 曲线参数……）写进脚本常量
2. 识别攻击模式（见各攻击库的"什么时候用"）
3. 用 SageMath 构造求解（格 → matrix.LLL()；多项式小根 → small_roots()；离散对数 → discrete_log）
4. 求出 p/q/明文 → i2b → 验证 flag 格式
5. 失败 → 回溯：换攻击 / 检查参数识别 / 调格构造参数
```

**执行纪律（顺序规则，来自实战教训）**：

- **廉价实验优先**：存在秒级可跑、自带结果验证器的候选攻击（如连分数收敛子 + 判别式校验）时，先跑再推导——禁止先做"最坏情况界分析"论证可行性。秒级实验的期望成本比长推演低几个数量级，且实验结果能直接裁剪理论方向。长篇纯推演还有耗尽输出预算、导致整个回合报废的风险。
- **生成器自测先行**：题目脚本含完整生成器（可本地复现实例）时，打线上前必须先本地自造实例端到端自测整条求解管线（攻击 → 解密 → flag 格式转换）。nc 类服务每次连接生成新实例，线上失败即丢失已破解状态；本地自测可同时拦截笔误级 bug 与数学级陷阱（如环 RSA 的 λ 陷阱，见 `rsa-attacks.md` §4a）两类问题。

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

Python ≥ 3.11 解析超过 4300 位的十进制字符串会报 `ValueError: Exceeds the limit`（CTF 的 N/e 必超），脚本开头加：
```python
import sys; sys.set_int_max_str_digits(1000000)
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
| 曲线判别式 Δ=0（奇异） | singular curve | cusp: y²=x³ → 映射到加法群(阶 p)；node: y²=x²(x+α) → α 为 QR 映到 GF(p)* (阶 p-1)；α 非 QR 映到范数 1 群 (阶 p+1) |
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
| 交互式 Σ 协议 + 可控 verifier challenge | **HVZKP 恶意验证者** | Two-Prime-Divisor: 发 `ρ=r² mod N`，prover 返回 `σ`，`gcd(N,σ-r)` 出因子；Short Factoring: `e=A` 反解 `φ(N)=N-y//e`（精确，因 e=A=r 上界时 r<e） |
| circom/halo2 电路有 `<--` 无 `<==` | **Under-constrained circuit** | 找未约束信号，构造满足等式但取非预期值的 witness |
| SIDH 公开辅助扭基点映像 | **Castryck-Decru 攻击** | 构造积曲面 + Richelot (2,2)-isogeny 分裂逐位恢复私钥（SageMath 脚本搜索：Castryck-Decru-SageMath）|
| challenge 可被操纵为常量（calldata/transcript 可控） | **Frozen Heart** | 固定 β,γ → 令某因子=0（如 f[0]=-γ）使 grand-product 方程恒成立。Plonkup 经 assembly calldatacopy offset 操纵把真值挪出 hash 区 → β,γ 固定已知 |
| ZKP 挑战通用清单 | **协议缺陷扫描** | ①证明不可能实例（如 K4 3-染色）= 必须作弊（承诺碰撞/揭示换值）②commit=H(salt∥值) 且 salt 已知 → 小域枚举 ③salt 由可恢复 PRNG 生成 ④networkx greedy_color 判可染色性 |
| 混淆电路 free XOR | **δ 恢复/密钥泄漏** | 真值表三行 XOR 消去 AES 项得 δ（W0⊕W1=δ）; 固定密钥跨会话 + 可提交自定义电路 → δ 本地评估 key schedule + S-box 逐字节（256）爆破重构 AES 密钥 |
| Shamir 系数缺陷 | **门限失效** | ①系数全部由秘密派生 → 单份额=单变量方程，gcd(x^p-x, h(x)) Frobenius 提根 ②系数跨字符重用 → 同求值点份额相减消随机项，已知首字符逐位恢复 |
| 门限签名（FROST 类）挑战可控 | **区间交攻击** | 承诺选择固定 c → z=λ·u+noise(mod q)，不同签名者子集给多尺度 λ，区间交迭代收敛份额 |
| DV-SNARG + verifier oracle | **可靠性崩塌** | 未约束 pair 提取验证者随机 v; CRS 条目线性组合代数相消伪造（ePrint 2024/1138） |
| KZG 点集 shuffle | **配对 oracle 排序** | e(P_i,ψ(P_j)) 暴露指数加法关系（distortion map ζ³=1）→ 链式比较恢复 α^i 排序 → 解 A(x)=0 提取 toxic waste α |

**SIDH/Castryck-Decru 工程化要点**:
- 素数形式: `p = 2^a · 3^b - 1`
- j=1728 曲线（E:y²=x³+x）需提取 two_i 自同构: `phi=EllipticCurveIsogeny(E,x)` → 遍历 codomain automorphisms 找 `iota(iota(P))==-P`
- 共享密钥用 j 不变量恢复: `shared = Ea.isogeny(phiPb+recovered*phiQb, algorithm='factored').codomain().j_invariant()`
- Fp² → int 密钥: `key = (int(shared[1])<<84) + int(shared[0])`（shared[0]=实部, shared[1]=i 系数）
- 性能: `proof.arithmetic(False)` + monkey patch `vector_space`/`dimension`；Oudompheng 改进（直接同源）SIKEp434: 10min→22s

### FHE（全同态加密）参数

> 详见 `$AGENT_DIR/knowledge-base/fhe-attacks.md`（方案识别/攻击向量决策树/galois滥用/CKKS精度/oracle）

| 参数特征 | 攻击方向 |
|---------|---------|
| SEAL/TenSEAL/PALISADE + BFV/CKKS 参数 | FHE 题 → 按交互选路（密钥恢复/galois/CKKS精度/oracle） |
| 参数弱（N≤1024、q 小）+ 多密文 | RLWE 格归约恢复密钥（见 lattice-attacks.md） |
| 题目给 galois elements 选择权 | galois 滥用：旋转系数提取/聚合 |
| CKKS + 精度/解码差异 | 精度泄露/枚举 |
| 提供加密/评估/解密 oracle | oracle 滥用（选择明文/评估/解密逼近） |

先算噪声预算：BFV 初始 ≈ log2(q/t) bit，`decryptor.invariant_noise_budget(ct)` 查剩余（>0 才能解密）。

## 6. Coppersmith 变种速查

> Coppersmith 方法 = 在模 n（或 n 的因子）下求多项式小根。是 RSA 题的核心武器。

| 变种 | 场景 | sage 模板 |
|------|------|---------|
| **small_roots** | f(x) 在 mod n 下有小根 | `P.<x>=PolynomialRing(Zmod(n)); f.small_roots(X=上界, beta=1)` |
| **partial key exposure (d)** | 已知 d 的高/低 k 位 | 构造 `f(x) = e*x - 1` 在 mod phi(n) 下 |
| **partial factor (p)** | 已知 p 的高/低 k 位 | `f(x) = x + p_high`，`beta=0.5`，在 mod n 下 |
| **stereotyped message** | 已知明文前缀 | `f(x) = (prefix + x)^e - c` |
| **related message** | m2 = a*m1 + b | `f1 = m1^e - c1`, `f2 = (a*m1+b)^e - c2`，resultant 消元 |
| **short pad** | 同消息两次短随机 padding（m·2^k+r1, m·2^k+r2） | `g1=x^e-c1, g2=(x+y)^e-c2`，`resultant(g1,g2,x)` 消 x 得 y 的单变量式，small_roots(X=2^pad_bits) 得 r1-r2 再解 m |
| **broadcast** | 同明文 e 组 (c_i, n_i) | CRT 合并 → `m^e mod (n1*n2*...)` → 开 e 次方。**超界退路**: 若 `m^e ≥ Πn_i`（明文有未知段），CRT 后用 Coppersmith: `g=sum(ts[i]*((shift*x+r_i+C)^e-c_i))` 在 `mod Πn_i` 上 `small_roots(X=未知段上界)` |
| **多元（defund）** | 多变量多项式小根 | 用 `defund/coppersmith` 封装（GitHub） |

**基本调用**：
```python
# 单变量 Coppersmith
P.<x> = PolynomialRing(Zmod(n))
f = (known_prefix * (256^k) + x)^e - c
roots = f.small_roots(X=256^unknown_bytes, beta=1, epsilon=0.05)
```

**参数调优**：`epsilon` 越小越能找到根但越慢（默认 1/e）；`X` 是根的上界（要准确估计）。

## 6a. 数学方程求解工具（高级）

- **Hensel 提升（模 p^k 根）**: P(x)≡0 (mod p^k)、p 小可枚举、k 大——枚举 mod p 根后牛顿迭代 `r' = r - P(r)·inv(P'(r), p) mod p^(i+1)` 逐级提升。**每步必须 mod p^(i+1)** 否则中间整数指数膨胀卡死。N=Πp_i^k_i 时各素幂独立提升再 CRT。前提 P'(root)≡0 (mod p) 不成立（单根）
- **Pell 方程 x²-D·y²=1**: 连分数 √D 逐收敛项验证得基本解 (x1,y1); 解成乘法群 (x1+y1√D)^n——群内二进制幂快速算大指标解，按附加约束枚举 n（解指数增长 n 范围小），剩余量配 Coppersmith 收尾
- **矩阵群 DLP（Jordan 形）**: GL(n,F_p) 求 G^k=H——可对角化时对每对特征值解标量 discrete_log 再 CRT 合并; 不可对角化（重根）时 Jordan 块 J=λI+N 的幂零部分 N 给 k 的附加线性方程，必须走此路线否则丢解。另查 |GL(n,p)|=Π(p^n-p^i) 光滑可整体 Pohlig-Hellman
- **Vandermonde 系数恢复**: 隐藏 n 次多项式求值 oracle——n+1 点建 A[i][k]=x_i^k 解线性系统得全部系数（sage solve_right 支持大次数）。秘密多项式/Shamir 阈值内插值/"拟合曲线"题通用，本质线性代数
- **Z3 适用面与 BPF/seccomp 重建**: XOR/移位→BitVec、模加/比较→Int、有限域方程→Int+mod。BPF flag 校验器: `seccomp-tools dump` 导出 → flag 按 4 字节小端字建模 BitVec32 + 每字节可打印约束 + 逐条 BPF if/alu 重建约束 → check/model 读出。声明式约束用 Z3，指令式混淆逻辑用 Ghidra 模拟器（prng-attacks.md §7）
- **De Bruijn 序列子串覆盖**: 输入需包含任意 n 位 k 进制码作子串且长度受限——B(k,n) 循环长 k^n 全覆盖，尾接首 n-1 字符线性化（k^n+n-1）; 每轮同一输入必中
- **Benford 分布合规生成**: 服务校验首位数字频率（P(d)=log10(1+1/d)，约 30/18/12/10/8/7/6/5/5%）时按比例构造数字串+shuffle——容差常 ±5% 近似即可，随机数过不了
- **15-puzzle 可解性当 bit 编码**: 可解 ⟺ 逆序数+空行自底行数偶——每实例 1 bit; 多 puzzle 且数量为 8 倍数即编码信号
- **线性递推大 N**: `a_{n+1}=f(a_n,...)` 经典形（Fibonacci/Tribonacci/青蛙跳步数=step{1..k} 组合计数）N 达 10^12 时写 2×2/3×3 矩阵更新+二进制矩阵幂 O(log N)（mod 下）; "下一个数是什么"类序列题先 OEIS 一发 HTTP（oeis.org/search?q=1,1,2,5,14 解析 pre 取下一项），瓶颈在包装层（captcha/PoW）不在数学

## 7. 注意

- **先验证再下结论**：求出候选明文必须 `i2b` 看是否像 flag，不能只算出数就说"解了"。
- **参数即线索**：e=3、n=2*p、hint=3 个、bits 不对称……每个异常都指向特定攻击。
- **不盲目爆破**：先模式匹配；爆破只在搜索空间极小（如古典密码位移）时。
