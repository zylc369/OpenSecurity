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

## 6. 调参与排错

| 失败现象 | 排查方向 |
|---------|---------|
| LLL 输出无目标向量 | 缩放因子不对；增大格维度；检查格构造（未知量是否在某行） |
| Coppersmith `small_roots` 返回空 | bound `X` 太大（超理论界）；调大 `m`/调小 `epsilon`；检查 `beta` |
| 解出来但 `pow` 验证不过 | 求错了；检查模数/方程构造；可能需要换攻击 |

**调参梯度**：`m`（Howgrave-Graham 层数）从 3 起递增到 7；`epsilon` 从 0.05 调到更小；`beta` 按因子的规模设（`p≈n^k` 则 `beta=k`）。

## 决策

```
能写成 "小未知数 满足 模方程"?
├─ 单变量 + 小根 < N^(1/deg) → 一元 Coppersmith (§5.1)
├─ 多变量 → 多元 Coppersmith (§5.2, defund 库)
├─ 线性 hint 求 p,q → §3 (2组直接解, 多组/噪声用格)
├─ 截断 LCG / 近似值 → HNP 格 (§4)
└─ 纯找短向量 → LLL/BKZ (§2)
```

## 注意

- **必用 sage**：`matrix.LLL()`、`small_roots` 手写极易错，sage 是标配
- **缩放是关键**：格的各行量纲不一致时 LLL 失效，用缩放因子拉平
- **bound 必须满足理论界**：Coppersmith 的 `X < N^(beta²/delta)` 不满足时数学上无解
- **验证**：求出 p/q 后必须 `pow(c,d,n)` 解密验证，不能只靠 LLL 输出
- 详细 sage 用法见 `$AGENT_DIR/knowledge-base/crypto-methodology.md` §3
