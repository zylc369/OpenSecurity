# 异型/外来代数结构密码攻击（Exotic Crypto）

> 何时用：方案不用标准 RSA/ECC/AES，而是 exotic 代数结构（辫群、热带半环、矩阵群、小对称群、量子模拟）或冷门公钥方案（Paillier/GM/Rabin/OSS/Cayley-Purser）。核心思路：找方案代数结构里的**数学缺陷**（乘法性不变量、无消去律、交换等价对象、小空间）而非爆破。

## 1. 识别与路由

| 特征 | 方案 | 去读 |
|------|------|------|
| braids/knots/winding/Reidemeister/topological | 辫群 DH | §2 |
| tropical/min-plus、矩阵乘用 min+ | 热带半环 DH | §3 |
| c = g^m·r^n mod n²（加法同态） | Paillier | §4 |
| 逐 bit 加密（QR/非 QR mod n） | Goldwasser-Micali | §5 |
| x²+ky²≡m (mod n) 验证方程 | OSS 签名 | §6 |
| 2×2 矩阵公钥 α/β/γ=α^r·β·α^-r | Cayley-Purser | §7 |
| 高精度小数输出+部分位遮蔽 | 单调函数编码 | §8 |
| FPE/Feistel+密钥分组件 | 格式保持加密 | §9 |
| 多面体/对称群/小字母表+oracle | 小群编码 | §10 |
| qubit/basis 模拟 BB-84 | QKD 模拟 | §11 |
| Laplace/Gaussian 加噪接口 | 差分隐私 | §12 |
| 份额带模数 (s_i, p_i) | Asmuth-Bloom 分享 | §13 |
| Hamming+矩阵交织 | 纠错码交织 | §14 |

## 2. 辫群 DH——Alexander 多项式乘法性

Δ(β₁·β₂)=Δ(β₁)×Δ(β₂)——共享秘密的"单向函数"实为乘法性不变量: calc_alice_priv = calc_alice / calc_pub（精确除法），shared = calc_alice_priv × calc_bob 纯公开值算出。搅乱（Reidemeister）无效——多项式是不变量。工程: ①符号行列式先清分母（元素乘 t^k 变多项式矩阵，det 后除回 t^(k·n)）②合法 Alexander 多项式系数回文作 sanity check。**DH 型方案要求单向函数无乘法不变量**——任何拓扑/代数不变量做共享秘密同理可破。

## 3. 热带半环（min-plus）DH——residuation

加法=min、乘法=+，(A·B)[i,j]=min_k(A[i,k]+B[k,j])。无消去律 → 残差直接算: `b*[j]=max_i(Mb[i]-M[i][j])`，共享秘密 `aMb=min_j(aM[j]+b*[j])`——任何矩阵尺寸通用。半环选择审计: 无消去律/有 residuation 的代数做 DH 不安全。

## 4. Paillier 攻击族

- **基础解密**: λ=lcm(p-1,q-1)、L(x)=(x-1)//n、μ=L(g^λ mod n²)⁻¹ mod n、m=L(c^λ mod n²)·μ mod n。n 未知: sqrt(max(c,o,h)) 下界逼近 + 邻域爆破，h=(c·o) mod n² 验证
- **LSB oracle（同态倍增二分）**: ct² mod n² 明文倍增，回绕改变奇偶——log2(n) 次二分（同构 RSA LSB oracle）
- **尺寸限制绕过（同态减法二分）**: E(flag-mid)=ct·(n+1)^(n-mid) mod n²，oracle 判"小/大（回绕）"即方向——O(log n)
- 通则: 加法同态 + 解密值范围/奇偶可观测 = 二分 oracle

## 5. Goldwasser-Micali 复制隔离

每密文独立编 1 bit（0=QR、1=非 QR）。协议"逐 bit 加密密钥 + 重组后做可观测操作"时: 同一密文行复制 128 次 → 重组密钥全 0x00/全 0xFF 两候选，预计算双 hash 比对 oracle 响应定 bit。128 线性查询替代 2^128。同族: 同态 oracle 低 bit 用 +1 递增观测 2^k 溢出; 高 bit 同态减到偶后反复除 2 观 LSB。防御: 密文绑位置/MAC。

## 6. OSS 签名 Pollard 伪造

x²+k·y²≡m (mod n) 型验证方程——Brahmagupta 恒等式使型乘法复合: X=(x1x2+k·y1y2)、Y=(x1y2-x2y1) 是 m1·m2 的合法签名。目标 m: 取已签 m1 构造 m2=m_target·m1⁻¹。二次型/范数型签名检查乘法封闭性。

## 7. Cayley-Purser——交换矩阵等价密钥

解密只需任何与 γ 交换的 H，不需要 r 本身。Cayley-Hamilton: H=c1·I+c2·γ 自动交换，c1 由 α⁻¹γ 与 γβ 逐元素比较读出——公开值直接构造。审计: "私钥"是否只是生成满足某关系对象的手段，该关系可否由公开值构造的等价对象满足（交换/共轭/中心化子）。

## 8. 单调函数部分输出反演

①f(flag_min) vs f(flag_max) 相同的位直接定（固定位）②剩余未知按位权降序逐个: 候选 0-9 → mpmath.findroot 反演 → 校验 ASCII/前后缀。10×未知位（线性）。精度: SageMath RealField(N)=N-bit MPFR，mpmath 用 mp.prec=N（二进制）不是 mp.dps。导数预算: 每步导数≈1 时精度保持（67 已知位→67 输入位）。

## 9. FPE/Feistel 分层剥离

总密钥大但分层（16-bit 轮密钥 s + GF(2) 混合矩阵 M + 偏移 b）: ①多组明密文对 ②爆破 s（<2^32）——正确 s 下剩余变换是 GF(2) 仿射 ③超定线性系统高斯消元解 M、b。规则: 可爆破层先爆破，线性层转方程。<32-bit 密钥分量都是短板。

## 10. 小群/小集合编码查表

编码基于小群（阶 ≤ 几千，如二十面体群 120）+ 加密 oracle——单位探测（0..k-1 单值加密）建全查找表即解。部分可见（6/12 面等）先实测碰撞率。

## 11. BB-84 模拟 MITM

QKD 安全性依赖认证经典信道——无认证: 对 Alice 固定 Z 基测量截获 key，对 Bob 固定发 Z 基 1（其 key 全知），节流 Bob 猜对数与 Alice 匹配避统计异常。

## 12. 差分隐私零均值噪声平均消除

Laplace/Gaussian 加噪 → 同位置 N 次查询取均值（标准误 ∝1/√N），round 恢复精确值（λ=1、1000 次误差 ±0.1）。无速率限制的 DP 接口 ε 约束随查询数坍缩。

## 13. Asmuth-Bloom 秘密分享

份额 (s_i, p_i)=（S mod p_i, 互素素数）——区别于 Shamir 的 (x,y) 无模数份额。阈值数量直接 `crt(moduli, residues)` 恢复。审计: S < min p_i 才唯一、模数互素公开性。Mignotte 序列是互素非素变体。

## 14. Hamming 纠错码 + 空间交织

交织（螺旋/对角/分块置换）参数未知时: 爆破矩阵维度 (w,h) → 按交织序读 bit → **零伴随式（H·codeword≡0）当维度判据**。起始未知试 8 种 bit 偏移。合法流再做 Hamming 纠错（伴随式定位错位）。

## 决策

```
方案不用标准构件? → 先找代数结构缺陷（本文件）
├─ DH 型 exotic 代数 → 查乘法不变量(§2)/消去律(§3)/交换等价(§7)
├─ 冷门公钥(Paillier/GM/Rabin/OSS) → §4-§6（Rabin 见 rsa-attacks §9b）
├─ 编码型（小群/单调函数/纠错交织） → §8/§10/§14
├─ 协议型（QKD 模拟/DP 接口） → §11/§12
└─ 密钥分层结构 → §9 逐层剥离
```

## 注意

- exotic 方案的数学缺陷是常态——先推导方案不变量/同态/封闭性再谈爆破
- oracle 探测前先算"可探测空间大小"（小群查表/部分位二分都是空间坍缩的结果）
- Rabin 四根解密见 rsa-attacks.md §9b；BIP39 助记词爆破见 blockchain-attacks.md
