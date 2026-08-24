# 格攻击（Lattice）

> 何时用：题目有线性关系的 hint（如 `a*p+b*q`、截断的比特、近似值）、HNP（隐藏数问题）、多维 Coppersmith 小根。格攻击的核心是**把问题构造为格，用 LLL/BKZ 找短向量**。必用 sage。

## 1. 识别格题

| 特征 | 类型 | 去读 |
|------|------|------|
| 多个 `a_i*p + b_i*q = c_i` 形 hint | 线性关系求 p,q | §3 |
| 给了 LCG 输出的高位/低位（截断） | 截断 LCG / HNP | §4 |
| 给了 `x` 的近似值 `x_approx`，求小误差 `e` | HNP / Coppersmith | §4/§5 |
| RSA 已知 p 的高位/低位 | Coppersmith 一元小根 | §5 |
| 多个变量的小根联立 | 多维 Coppersmith | §5 |

**判断**：只要能写成"`小未知数` 满足 `模方程`"→ 考虑格/Coppersmith。

**分诊第一问——"什么是小的？"**：秘密本身 / 误差向量 / nonce 差 / 子集指示向量 {0,1}^n / 模回绕修正项。那个"小东西"就是格要暴露的目标。措辞指纹："high bits of k are known"、"error is small"、"coefficients in {-1,0,1}"、"recover seed from truncated outputs"、"noisy linear equations mod q"。

**工具梯度**：LLL 先手（快，CTF 参数常够）→ 差一点 BKZ(block_size=20..35) → 有目标向量用 Babai 最近平面（fpylll `CVP.babai`，先规约再 Babai）。SVP vs CVP：只知"某关系必短"→ SVP/embedding；已有目标点求最近格点 → CVP/Babai。

## 2. LLL 基础（必读）

LLL 在格 `{Σ a_i·b_i : a_i∈Z}`（`b_i` 为格基行向量）中找"短"向量。构造格的关键：**把已知量放对角线、未知小量放某行使 LLL 后该行变短**。

```sage
# sage 格规约模板
M = matrix(ZZ, [
    [大缩放_1,  0,    ..., 已知量_1],
    [0,    大缩放_2, ..., 已知量_2],
    ...
])
L = M.LLL()      # 或 M.BKZ(block_size=20)
# L 的某一行即为所求小向量
```

**缩放原则**：不同行的"量纲"差很大时（如一行是 bit、一行是 256 位素数），用缩放因子把各行量纲拉到同一数量级，否则 LLL 会偏向大数值行。

## 3. `a*p+b*q` 提示求 p,q

**何时用**：给了多组 `(a_i, b_i, c_i)` 满足 `a_i*p + b_i*q = c_i`（p、q 是 RSA 的素因子）。

**原理**：把 `c_i - a_i*p - b_i*q = 0` 的"小解"用格找。至少 2 组线性无关的 hint 可定 p、q。

```sage
# 给两组 hint: a1*p+b1*q=c1, a2*p+b2*q=c2 (p,q 约 N^0.5)
# 直接解线性方程最简单; hint 多于2组或有噪声时用 LLL
# 噪声型: c_i = a_i*p + b_i*q + e_i (e_i 小) => HNP 风格格
def solve_apbq(hints, N):
    # hints = [(a1,b1,c1), (a2,b2,c2), ...]
    M = matrix(ZZ, [[h[0], h[1], h[2]] for h in hints] + [[1,0,0],[0,1,0]])
    # 构造使 p,q 为短向量的格 (具体构造依题)
    ...
```

> 2 组精确 hint 直接用 sympy 解线性方程 `solve([a1*p+b1*q-c1, a2*p+b2*q-c2], [p,q])`；格用于"多于方程数"或"有噪声"的情形。

## 4. HNP（隐藏数问题）/ 截断 LCG

**何时用**：已知 `t_i` 和 `a_i` 满足 `|a_i - t_i·x (mod p)| < B`（x 是隐藏值），或 LCG 输出被截断了高位/低位。

**截断 LCG 模型**：`s_{i+1} = a·s_i + b (mod m)`，只看到 `s_i` 的高 `k` 位（低 `l` 位未知）。构造格恢复未知低位。

```sage
# HNP 经典格构造 (Boneh-Venkatesan)
# 已知 t_i, a_i, 求 x 使 a_i ≈ t_i*x (mod p), 误差 < B
def hnp_lattice(t_list, a_list, p, B):
    n = len(t_list)
    M = matrix(ZZ, n+2, n+2)
    for i in range(n):
        M[i,i] = p
        M[n,i] = t_list[i]
        M[n+1,i] = a_list[i]
    M[n,n] = B            # 缩放
    M[n+1,n+1] = B
    # LLL 后含 (x, ...) 的短向量
    return M.LLL()
```

**常见陷阱**：`B`（误差界）选错 → LLL 找不到短向量。`B` 应略大于真实误差上界。

### 4.1 ECDSA 部分泄漏 nonce 的标准变换

泄漏 k_i 高位时（k_i = leaked_i·2^t + delta_i，delta 小），由 s_i·k_i - h_i ≡ r_i·d (mod q) 代入消 k：
`r_i·d - s_i·delta_i ≡ s_i·leaked_i·2^t - h_i (mod q)` —— 未知量 = d + 一组小 delta_i。
```python
M = Matrix(ZZ, n+2, n+2)
for i in range(n): M[i,i] = q
for i in range(n):
    M[n, i]   = ss[i]
    M[n+1, i] = (hs[i] - ss[i]*leaked[i]*(1<<t)) % q
M[n, n] = 1; M[n+1, n+1] = q // (1<<t)
```
LLL 后验签确认，差几位暴力收尾。适用多签名+单一长期密钥；Schnorr 有偏 nonce 同型。

签名数需求经验表: MSB 恒 0（1 bit）~100 条; 错误长度生成的 k ~50 条; 时延侧信道（1-4 bit）20-100 条; 不安全 PRNG 少量; nonce 完全复用 2 条直接代数恢复（无需格）。判据: n ≥ q_bits / 泄漏 bits。

### 4.2 截断 LCG 递推变换（标准化）

只见 y_i = x_i >> t 时写 x_i = y_i·2^t + z_i（z 小）代入 x_{i+1}=a·x_i+b：
`z_{i+1} - a·z_i ≡ a·y_i·2^t + b - y_{i+1}·2^t (mod m)` —— 未知量全是小 z_i。
```python
M = Matrix(ZZ, n+1, n+1)
for i in range(n): M[i,i] = m
for i in range(n):
    M[n, i] = (a*ys[i]*(1<<t) + b - ys[i+1]*(1<<t)) % m
M[n, n] = 1 << t
```
恢复 z_i → x_i → 递推验证。截断状态恢复本质是 HNP 换装。

## 5. Coppersmith（小根）

**何时用**：多项式模方程 `f(x) ≡ 0 (mod N)` 有小根 `x < X`，且 `X < N^(1/deg(f))`（一元）或满足多维界（多元）。

### 5.1 一元小根（RSA 已知 p 高位/低位）

```sage
# 已知 p 的高位 p0, 未知低 unknown_bits 位
P.<x> = PolynomialRing(Zmod(n))
f = p0 + x            # f(x) = p (mod p), 其中 p|n
roots = f.small_roots(X=2^unknown_bits, beta=0.5)
# beta: p 相对 n 的规模, p≈n^0.5 => beta=0.5
# roots[0] 即 p 的未知低位, p = p0 + roots[0]
```

### 5.2 多元小根（多变量联立）

```sage
# 例: 求 x,y 使 f(x,y) ≡ 0 (mod n), x<X, y<Y
P.<x,y> = PolynomialRing(Zmod(n))
f = x*y - c           # 或更复杂的关系
# 多元 Coppersmith 需调 m (Howgrave-Graham 参数) 和 t
# 用 defund/coppersmith 的 multivariate small_roots:
# https://github.com/defund/coppersmith
roots = small_roots(f, [X_bound, Y_bound], m=3, d=2)
```

> 多元 Coppersmith 无标准库一键函数，常用 `defund/coppersmith` 的 `small_roots` 实现。调参（`m`、`d`）是经验活，失败时增 `m`。

## 5a. LWE（embedding + Babai）

形态 `b = A·s + e (mod q)`（s 小/稀疏、e 小）。先查：s ∈ {-1,0,1}？e ≪ q？行多列少？整数上解几乎成立只差模回绕？
```python
top    = block_matrix([[q*identity_matrix(m), zero_matrix(ZZ, m, n)]])
bottom = block_matrix([[A.transpose(),          identity_matrix(n)]])
L = block_matrix([[top], [bottom]])   # 规约后 + Babai/CVP
```
三元/稀疏秘密后处理：近零映回 {-1,0,1}；**两种端序、行/列两种约定都试**（服务端描述与实际编码不符是常见坑）。CTF 的 LWE 几乎都在硬度线以下——发现 s/e 够小 LLL+Babai 即解。

## 5b. Ring-LWE / Module-LWE：先摊平再攻

识别：mod x^n±1 多项式、循环/负循环卷积、(a(x), b(x)=a(x)s(x)+e(x)) 样本。意图捷径：①系数小到直接整数提升 ②环解耦成标量 ③泄漏求值点摊平 plain LWE ④表示 bug（NTT 用错/符号/端序/未中心化 [-q/2,q/2]）。

摊平：a(x) 展开为负循环旋转矩阵（j≤i 取 coeffs[i-j]，否则 -coeffs[n+i-j]），按 plain LWE 处理。正交攻击变体：增广格 [A | I_m | 0; b^T | 0 | q] LLL 后末分量 0 的行给 (s,e)；关键参数 q/σ。

## 5c. 正交格恢复隐藏子集/子空间（HSSP）

已知 h = α·A (mod M)、A 是 0/1 矩阵：最短向量不是答案而是门道——格 [M·I_k | 0; H^T | I_n] 规约 → 右下短行是正交关系 → 取核 → 再规约暴露隐藏二元基。

## 5d. 子集和/背包

```python
M = Matrix(ZZ, n+1, n+1)
for i in range(n):
    M[i,i] = 1; M[i,n] = weights[i]
M[n,n] = -target
```
LLL 后找**末坐标 0 的行**，其余坐标应 ∈ {0,1} 或 {-1,0,1}。对角放 2 可强化 0/1 区分。

**密度判据**: d = n / max(log₂ a_i) < 0.9408（Lagarias-Odlyzko 界）→ 格攻击可行; 高密度基本无望; 超递增序列直接贪心免格。CJLOSS embedding（末行加 1 的 n+2 列增强版）比朴素构造成功率更高。

## 5e. NTRU 与 Mersenne 汉明重判决

h = g·f⁻¹ mod p，私钥 (f,g) 小系数。2n×2n 格（单位阵 | h 列 | q 对角）LLL 短行出 (f,g)。Mersenne 素数模（2^k-1）特化：中间值 c·g mod p 的**汉明重**区分明文位（~200 低位=0、~400 位=1，阈值 hw<300 判 0），逐轮逐位恢复。

## 5g. 近似 GCD（带噪声素数提示）

h_i = f·p_i + n_i（f 秘密、p_i 小素数、n_i 小噪声）: 格 [[1,0,0,h1],[0,1,0,h2],[0,0,1,h3],[0,0,0,-1]] LLL 短向量给 (p1,p2,p3)，f=(h1-n1)/p1。缩放行按噪声/素数量级调; 噪声大于素数时失败。适用一切 "秘密×小参数+小噪声" 多组泄漏（AGCD 家族）。

## 5h. PQC 实现泄漏（Dilithium/MAYO 样本）

Dilithium 类签名 z = y + c·s1，s1 系数 ∈ [-η,η] 小范围。实现缺陷（打包/解包 bug 如 poly_unpack）泄部分 s1 → y 有结构因子（如整除 49）时在 F7/(x^N+1) 小域上解方程组恢复，伪造签名。MAYO 故障注入版: 签名过程 s=v+O·x 构造前的受控 bit 翻转每次给一个 GF(16) 线性方程（GF(16)=GF(2)[x]/(x⁴+x+1) 查表消元），64 次故障逐行恢复秘密矩阵 O，重建等价签名者。规则: ①PQC 先 diff 参考实现的打包/采样器 ②小系数域使故障/泄漏成线性方程，几十次即解 ③数学结构难破、实现 bug 现实得多。

## 6. 调参与排错

| 失败现象 | 排查方向 |
|---------|---------|
| LLL 输出无目标向量 | 缩放因子不对；增大格维度；检查格构造（未知量是否在某行） |
| Coppersmith `small_roots` 返回空 | bound `X` 太大（超理论界）；调大 `m`/调小 `epsilon`；检查 `beta` |
| 解出来但 `pow` 验证不过 | 求错了；检查模数/方程构造；可能需要换攻击 |

**调参梯度**：`m`（Howgrave-Graham 层数）从 3 起递增到 7；`epsilon` 从 0.05 调到更小；`beta` 按因子的规模设（`p≈n^k` 则 `beta=k`）。

## 5f. 失败模式排查清单

| 症状 | 排查 |
|---|---|
| LLL 无目标向量 | 缩放错（一坐标支配基底）——拉平量纲 |
| 短向量在但值不对 | 未中心化到 [-q/2, q/2] |
| 结构总差一点 | 行/列约定交换 |
| 解不出 | 样本太少 |
| LLL 差一点 | 升 BKZ / 改缩放 / 换 embedding |
| 全败 | 问题类型误判（实为线性代数/CRT/编码 bug）|
| 结果几乎对 | 忘暴力收尾（末几位比特/符号小爆）|

novel/自创方案先试线性代数直解（sage `A.solve_right(b)`）；格方案先查参数结构（2 的幂模数、复合模数、NTT 环参数错误均可破坏健全性）。

## 决策

```
能写成 "小未知数 满足 模方程"?
├─ 单变量 + 小根 < N^(1/deg) → 一元 Coppersmith (§5.1)
├─ 多变量 → 多元 Coppersmith (§5.2, defund 库)
├─ 线性 hint 求 p,q → §3 (2组直接解, 多组/噪声用格)
├─ 截断 LCG / ECDSA 部分 nonce → HNP 格 (§4.1-4.2)
├─ LWE 形 (b=As+e) → §5a embedding+Babai
├─ 多项式环样本 → §5b 先摊平
├─ h=αA 隐藏子集 → §5c 正交格两段式
├─ 子集和/背包 → §5d
└─ 纯找短向量 → LLL/BKZ (§2)
```

## 注意

- **必用 sage**：`matrix.LLL()`、`small_roots` 手写极易错，sage 是标配
- **缩放是关键**：格的各行量纲不一致时 LLL 失效，用缩放因子拉平
- **bound 必须满足理论界**：Coppersmith 的 `X < N^(beta²/delta)` 不满足时数学上无解
- **验证**：求出 p/q 后必须 `pow(c,d,n)` 解密验证，不能只靠 LLL 输出
- 详细 sage 用法见 `$AGENT_DIR/knowledge-base/crypto-methodology.md` §3
