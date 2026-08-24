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
| 点满足 x²+y²=1（时钟群/单位圆） | clock group | 群阶 = **p+1**（不是 p-1），法则 (x1y2+y1x2, y1y2-x1x2)；p 隐藏时 gcd(x²+y²-1) 恢复 | §8 |

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

### 部分低位恢复（order = q·2^k，q 大素数时）

当 `order` 有大素因子 q 但目标只需光滑因子部分（如 flag 低位在 mod 2^k 内），投影到 2^k 阶子群手动恢复:
```python
# order = q * 2^e
g_ = pow(g, q, p)   # 2^e 阶元
a_ = pow(a, q, p)
gamma = pow(g_, 2**(e-1), p)  # 2 阶元（即 -1）
xs = [0]
for k in range(e):
    d = 1 if pow(pow(g_, -xs[k], p) * a_ % p, 2**(e-1-k), p) == gamma else 0
    xs.append(xs[k] + 2**k * d)
d_low = xs[e]  # = d mod 2^e
```
复杂度 O(e·√2)。q 不可破也能拿 flag 低位。

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

**何时用**：判别式 Δ ≡ 0 (mod p)——曲线退化有奇点，可映射到加法/乘法群，离散对数变易。

### 6.1 判别式与奇点

短 Weierstrass（y²=x³+ax+b）: Δ = -16(4a³+27b²)。
一般 Weierstrass（y²+a₁xy+a₃y=x³+a₂x²+a₄x+a₆）:
```python
b2 = a1**2 + 4*a2
b4 = 2*a4 + a1*a3
b6 = a3**2 + 4*a6
b8 = a1**2*a6 + 4*a2*a6 - a1*a3*a4 + a2*a3**2 - a4**2
Delta = -(b2**2)*b8 - 8*b4**3 - 27*b6**2 + 9*b2*b4*b6
```
奇点求解: 令 `A=6, B=4*a2+a1², C=2*a4+a1*a3`，解二次 `A*x²+B*x+C=0`，`y=(-a1*x-a3)*pow(2,-1,p)`。

### 6.2 cusp（尖点）: 映射到加法群（阶 p）

标准化后 `f = x³ - y²`。同态 `φ(x,y) = x/y, O→0`。

```python
twoinv = pow(2, -1, p)
# 1. 平移到奇点 (0,0)
f = f.subs(x=x+xp, y=y+yp)
# 2. 消去 xy 交叉项
xy_coeff = f.coefficient(x*y)
f = f.subs(y=y+xy_coeff*twoinv*x)
assert f == x**3 - y**2  # 确认 cusp
# 3. 点也做同样平移
Pxp = Px - xp;  Pyp = Py - yp - xy_coeff*twoinv*Pxp
Qxp = Qx - xp;  Qyp = Qy - yp - xy_coeff*twoinv*Qxp
# 4. 映射到 GF(p) 加法群: DLP 就是除法
dp = (Qxp * pow(int(Qyp),-1,p)) * pow(int(Pxp * pow(int(Pyp),-1,p)),-1,p) % p
```

### 6.3 node（结点）: split / nonsplit

标准化后 `f = x³ + α*x² - y²`（即 `y² = x²(x+α)`）。

```python
if kronecker(alpha, p) == 1:   pass  # split: 映到 GF(p)*, 阶 p-1
else:                          pass  # nonsplit: 映到范数1群, 阶 p+1
```
- **split**（α 是 QR）: `φ(x,y) = (y+√α·x)/(y-√α·x)`，√α ∈ GF(p)，映到 GF(p)*，阶 **p-1**
- **nonsplit**（α 非 QR）: `φ(x,y) = (y+√α·x)/(y-√α·x)`，√α ∈ GF(p²)\GF(p)，映到范数 1 子群 `{u+v√α | u²-αv²=1}`，阶 **p+1**

> ⚠ nonsplit 阶 = p+1（不是 p-1），检查光滑性/选攻击时查 **p+1** 的因子分解。

### 6.4 自定义 EC 实现的离散对数（operation="other"）

题目用自实现 EC（非 sage EllipticCurve），但群阶光滑时，用 `discrete_log(operation="other")` 复用 sage 的 Pohlig-Hellman:

```python
class ECPoint:  # 包装自定义点类型
    def __init__(self, point): self.point = point
    def is_zero(self): return self.point == ec.O
    def __eq__(self, other): return self.point == other.point
    def __hash__(self): return hash(self.point)

add = lambda x,y: ECPoint(ec.add(x.point, y.point))
inv = lambda x: ECPoint(ec.negate(x.point))
dq = discrete_log(ECPoint(Q), ECPoint(P), ord=order,
                  operation="other", identity=ECPoint(ec.O), inverse=inv, op=add)
```

### 6.5 复合环 Z_N（N=pq）上 EC 分解

EC 定义在 Z_N（非 GF(p)）上时，标量乘可能因逆不存在而报错 → 从异常提取因子:

```python
FF = IntegerModRing(N)
ec = EC(FF, (a1, a2, a3, a4, a6))
try:
    ec.scalar(N, P)
except Exception as e:
    # 异常: "inverse of Mod(t, ...) does not exist"
    t, _ = map(int, str(e).lstrip("inverse of Mod(").rstrip(") does not exist").split(", "))
    p = gcd(t, N);  q = N // p
```
> 原理: 若 EC(GF(p)) 是 cusp 则 ord=p，N·P 在 EC(N) 上模 p 侧需逆元 → 失败暴露 t，gcd(t,N)=p。与 Pollard/Fermat 并列的独立分解法。

## 7. 通用离散对数（无弱点时）

曲线无以上弱点时，只能用通用算法：

```sage
# BSGS (Baby-step Giant-step), 复杂度 O(sqrt(order))
k = discrete_log(Q, G, ord=order, operation='+')
# sage 内部: order 光滑用 Pohlig-Hellman, 否则 BSGS/Pollard rho
```

`order > 2^80` 时通用算法不可行——说明题目必有 §2-§6 的弱点，重新检查。

**稀疏指数 MITM（低汉明重）**: 已知 x 至多 k 位为 1（如 128-bit 中 11 位）→ 指数劈半 x=x1·2^64+x2，baby 表存 C(64,5) 个 g^(x1·2^64)，giant 枚举 C(64,6) 个 x2 查 a·g^(-x2)。复杂度 C(n,k/2) 级，远优于 2^k 穷举和 2^(n/2) 标准 BSGS。指纹: "at most k bits set"、指数=若干 2^i 之和的生成逻辑。

## 8. 时钟群（单位圆）DLP

群法则（复数乘法模 p 实虚部）: `(x1,y1)*(x2,y2) = (x1y2+y1x2, y1y2-x1x2)`；单位元 (0,1)。**群阶 = p+1**，同构 GF(p²)* 范数 1 子群。

p 隐藏恢复：每点满足 x²+y²≡1 (mod p) → `p = reduce(gcd, [x²+y²-1 for points])`（剥离小因子）。攻击：分解 **p+1**，光滑则 Pohlig-Hellman + CRT。识别：clock/circle 措辞、DH 在 x²+y²=1 上。

## 9. Ed25519 torsion 侧信道与 nonce 缺陷扩展

**torsion 侧信道**（cofactor 8 泄漏标量位）: 密钥派生 key = MASTER*uid mod l 时，标量绕 l 使结果偏移 torsion 元（8 点之一）。对 t=0..254 查 uid=2^t 与 2^(t+1) 的签名点，`point_double(S_t).y != S_{t+1}.y` = 发生绕 l = 该位 1。位序列重建 MASTER ≈ l·(0.b0b1...)₂，8 个 torsion 修正逐一验证。ecpy 类 mod l 规约库受影响。

**nonce 缺陷三变体**（同 r 复用恢复公式之外）:
1. Ed25519 跨密钥 same-nonce（标量跨 rekey 存活）: `a = (S1-S2) * inverse(h1-h2) mod L`
2. k = MD5(prefix+counter) 派生: fastcoll 制造前缀碰撞 → 不同 counter 同 k → 退化标准复用
3. k 取值空间受限（如 1024 种）: 暴力 (k1,k2) 对解线性系统 `x = (s2k2h1 - s1k1h2)/(s1k1r2 - s2k2r1) mod q`，`pow(g,k1,p)%q==r1` 验证

**素数生成过滤缺陷**: 生成器带模过滤（如只取 p%3==2）→ 密钥空间坍缩 → 多公钥两两 gcd 高概率共享素数（ECC 的 p 与 RSA 的 n 同理）。

## 10. 同源图（isogeny）遍历

同源密码题本质常是**图寻路**:
- 节点 = j-invariant（同构类）；2-isogeny 连接成近树形图，每节点 ~3 邻居（2 子+1 父）
- 邻居求法: 解模多项式 Φ₂(j, Y)=0 的根——比算真实 isogeny 快得多
- 寻路: 随机游走估高度（多轮取最小深度到叶）→ 两端上行找 LCA → 拼接路径
- CM 判别式 D=f²·D_K，conductor f 决定树深; class number 1 判别式 -163/-67/-43 常是题眼

与 SIDH 密钥恢复（Castryck-Decru，crypto-methodology §5）互补: 那是辅助点泄漏的多项式时间攻击，本节是无可利用泄漏时的图结构攻击面。

### 跨曲线 DDH 判定（Tate 配对）

两条不同基域曲线判 z 是否 = x·y: embedding degree k 存在时点映射到 E1(F_{p^k})，比较 `tate_pairing(zP, Q, n, k) == tate_pairing(xP, yQ, n, k)`（双线性把乘法翻译成相等性; 曲线需满足度 4 twist 关系）。**先做意外检查**: 曲线阶含小因子（如 500）→ Pohlig-Hellman 直接子群解出 x,y,z mod 小因子验证 z≡xy。

## 决策

```
检查曲线弱点:
├─ #E == p? → Smart (§2)
├─ 4a³+27b² ≡ 0? → 奇异曲线 (§6)
├─ #E 光滑? → Pohlig-Hellman (§4, sage 自动)
├─ embedding degree 小? → MOV (§3)
├─ 服务端不验点? → invalid curve (§5)
├─ 点在 x²+y²=1 上? → 时钟群 (§8, 查 p+1 光滑)
├─ Ed25519 + key=master*uid? → torsion 侧信道 (§9)
└─ 都不满足 → 通用 BSGS (§7), order>2^80 则重查弱点
```

## 注意

- **先算 `E.order()` 和判别式**：ECC 题的弱点全在这两个量上
- sage 的 `discrete_log` 对加法群要传 `operation='+'`
- **验证**：求出 `k` 后必须 `k*G == Q` 确认
- 点坐标给的是 `(x,y)` 还是压缩格式要注意；sage 构造点 `E(x,y)`
- 求出 `k`（私钥/明文）后转 flag：`k.to_bytes((k.bit_length()+7)//8,'big')`（Python 标准库）
