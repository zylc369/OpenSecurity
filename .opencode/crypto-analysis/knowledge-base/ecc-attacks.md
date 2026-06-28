# 椭圆曲线攻击（ECC）

> 何时用：题目有曲线方程 `y²=x³+ax+b (mod p)`、点运算、基点 `G`、公钥 `Q=kG`，求私钥 `k`（离散对数）。必用 sage 的 `EllipticCurve`。

## 1. 识别 ECC 攻击方向

拿到 ECC 题先检查"曲线有没有弱点"：

| 观察 | 弱点 | 攻击 | 去读 |
|------|------|------|------|
| 曲线阶 `#E = p`（与素域同） | anomalous | Smart（多项式时间） | §2 |
| embedding degree 小（`p^k-1` 含 `#E` 因子，`k` 小） | MOV 可行 | MOV（Weil pairing） | §3 |
| 曲线阶 `#E` 光滑（因子都小） | 阶光滑 | Pohlig-Hellman | §4 |
| 没检查点是否在曲线上 | invalid curve | invalid curve 攻击 | §5 |
| 判别式 `4a³+27b² ≡ 0 (mod p)` | 奇异曲线 | 退化映射 | §6 |
| 都不满足 | 通用离散对数 | BSGS / Pollard rho | §7 |

**先算**：`E.order()`（sage）、`(4*a**3+27*b**2) % p`（判奇异，注意 `%` 优先级高于 `+`，必须加括号）、`#E` 是否光滑。

## 2. Smart 攻击（anomalous 曲线）

**何时用**：曲线阶 `#E(Fp) == p`（anomalous）。此时可用 p-adic 提升多项式时间解出 `k`。

```sage
def smart_attack(P, Q, p):
    E = P.curve()
    Eqp = EllipticCurve(Qp(p, 2), [ZZ(t) + randint(0,p)*p for t in E.a_invariants()])
    # 提升 P, Q 到 Qp: lift_x 返回 ±y 两个候选, 选 y 约化(mod p)等于原点的
    # 判据: 候选 y 与原 y 之差的 p-adic 赋值 > 0 (即差是 p 的倍数)
    def lift(pt):
        cands = Eqp.lift_x(ZZ(pt.xy()[0]), all=True)
        return next(c for c in cands if (c.xy()[1] - pt.xy()[1]).valuation() > 0)
    P_qp = lift(P)
    Q_qp = lift(Q)
    # p-adic 形式对数之比 = k (注: .log() 依 sage 版本可能需改用 formal_group().log)
    return ZZ((-Q_qp.log() / P_qp.log()) % p)

# 用法: k = smart_attack(G, Q, p); assert k*G == Q
```

## 3. MOV 攻击（小 embedding degree）

**何时用**：embedding degree `k` 小（即 `p^k - 1` 被 `#E` 整除，且 `k` 较小，如 `k ≤ 6`）。把 `E(Fp)` 的离散对数搬到 `Fp^k` 的乘法群（那里有次指数算法）。

```sage
def mov_attack(P, Q, p, order, ed):
    # ed = embedding degree (最小 k 使 p^k ≡ 1 mod order)
    E = P.curve()
    Fpk = GF(p^ed, 'a')
    Ek = E.change_ring(Fpk)
    Pk = Ek(P); Qk = Ek(Q)
    # 找一个随机点 R 使 Weil pairing 非退化
    while True:
        R = Ek.random_point()
        if R.order() == order:
            break
    alpha = Pk.weil_pairing(R, order)
    beta  = Qk.weil_pairing(R, order)
    # 解 beta = alpha^dlog in Fpk*
    dlog = discrete_log(beta, alpha, ord=order)
    return dlog
```

> `k`（embedding degree）需先确定：找最小的 `k` 使 `p^k ≡ 1 (mod order)`。

## 4. Pohlig-Hellman（阶光滑）

**何时用**：曲线阶 `#E` 分解后因子都较小（每个 < 2^40 左右）。sage 的 `discrete_log` **自动用** Pohlig-Hellman + BSGS，无需手写。

```sage
E = EllipticCurve(GF(p), [a, b])
G = E(Gx, Gy); Q = E(Qx, Qy)
order = E.order()
print(factor(order))   # 检查是否光滑
k = discrete_log(Q, G, ord=order, operation='+')   # 椭圆曲线是加法群
assert k*G == Q
```

**注意**：若 `order` 有大素因子（> 2^60），Pohlig-Hellman 退化，需 Pollard rho（sage 的 `discrete_log` 也会自动用，但慢）。

## 5. Invalid Curve 攻击

**何时用**：服务端**不验证输入点是否在曲线上**。可送入"同 a、不同 b"的曲线上的点，那里阶可能小/光滑，用少量交互恢复 `k mod (小因子)`，CRT 拼 `k`。

```sage
# 找同 a、b' 使 E': y²=x³+a*x+b' 阶光滑 (所有素因子 < 阈值)
THRESH = 2^40
for b_test in range(p):
    try:
        Et = EllipticCurve(GF(p), [a, b_test])
        if all(f < THRESH for f, _ in factor(Et.order())):
            print("找到 invalid curve b' =", b_test, "阶 =", factor(Et.order()))
            break
    except ArithmeticError:
        continue
# 用 Et 上的点 P' 与服务端交互得 Q'=k*P', 在 Et 上解离散对数
```

> sage 整数无 `.is_smooth()` 内置方法，用 `all(f < 阈值 for f,_ in factor(n))` 判断阶是否光滑。

## 6. 奇异曲线（singular）

**何时用**：判别式 `4a³+27b² ≡ 0 (mod p)`——曲线退化有奇点，可映射到加法/乘法群，离散对数变易。

```sage
# 判奇异
if (4*a^3 + 27*b^2) % p == 0:
    print("奇异曲线!")
# 奇点 x0 = 求导 3x²+a=0 的根
# node (两切线): 映射到 Fp* 的离散对数
# cusp (尖点):   映射到 Fp 的加法 (k = (m_Q)/(m_P) mod p)
```

**node 映射**：奇点 `(x0,0)`，令 `t=(y)/(x-x0)`，则点映射到 `t`，离散对数在 `Fp*`。

## 7. 通用离散对数（无弱点时）

曲线无以上弱点时，只能用通用算法：

```sage
# BSGS (Baby-step Giant-step), 复杂度 O(sqrt(order))
k = discrete_log(Q, G, ord=order, operation='+')
# sage 内部: order 光滑用 Pohlig-Hellman, 否则 BSGS/Pollard rho
```

`order > 2^80` 时通用算法不可行——说明题目必有 §2-§6 的弱点，重新检查。

## 决策

```
检查曲线弱点:
├─ #E == p? → Smart (§2)
├─ 4a³+27b² ≡ 0? → 奇异曲线 (§6)
├─ #E 光滑? → Pohlig-Hellman (§4, sage 自动)
├─ embedding degree 小? → MOV (§3)
├─ 服务端不验点? → invalid curve (§5)
└─ 都不满足 → 通用 BSGS (§7), order>2^80 则重查弱点
```

## 注意

- **先算 `E.order()` 和判别式**：ECC 题的弱点全在这两个量上
- sage 的 `discrete_log` 对加法群要传 `operation='+'`
- **验证**：求出 `k` 后必须 `k*G == Q` 确认
- 点坐标给的是 `(x,y)` 还是压缩格式要注意；sage 构造点 `E(x,y)`
- 求出 `k`（私钥/明文）后转 flag：`k.to_bytes((k.bit_length()+7)//8,'big')`（标准库，无需 pycryptodome）
