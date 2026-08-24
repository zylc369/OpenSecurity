# PRNG 攻击与状态恢复

> 何时用：目标用弱/可观测 PRNG（Python random / PHP mt_rand / Java Random / V8 Math.random / C rand / 自制递推）生成 token、密钥、密钥流、验证码。核心思路：观测输出 → 恢复状态/种子 → 接管预测（含历史回溯）。

## 1. 识别与路由

| 特征 | 类型 | 去读 |
|------|------|------|
| Python `random.*` 输出可观测 | MT19937 | §2 |
| JavaScript `Math.random()` | V8 xs128p | §3 |
| Java `Random.nextInt()` | Java LCG (48-bit) | §4 |
| `s_{n+1}=a*s_n+c mod m` | LCG | §5 |
| 种子含 time()/可控值/外部服务 | 种子审计 | §6 |
| 自制递推（XOR/移位/CA/混沌） | 特殊 PRNG | §7 |
| 无显式对错反馈但有求解/校验耗时 | 求解时间侧信道 | §8 |

## 2. MT19937（Python random / PHP mt_rand）

- **untemper + 624 输出**: 624 个连续 32-bit 输出逐个 untemper 得完整状态，`setstate` 接管。现成: randcrack（submit 624×32bit）
- **63-bit randrange**: 每输出耗 2 个 MT 字 `(mt1<<31)|(mt2>>1)` 丢 1 bit → Z3 BitVec 符号化全部 624 状态
- **浮点输出**: random.random()=(a·2^27+b)/2^53（两 MT 字各 27/26 bit）。观测 int(f*256) 每个仅 8 bit → 需 3360+ 观测。工具 not_random（fx5）预计算 GF(2) magic 矩阵直接重建状态。场景: 一端点泄浮点 + 另一端点用 random 生成 token（全局单流共享）
- **种子恢复（仅 2 个输出值）**: mt[0] 与 mt[227]（twist wrap-around: mt[624] 依赖 mt[0]+mt[397]）足够 2^32 离线爆破 32-bit 种子。任何泄漏 2 个间隔输出的接口（解题回执）即可
- **部分位泄漏**: 每轮泄 24-120 bit → 状态字建候选集 + 沿递推（x 依赖 x-624/x-623/x-227）双向约束传播，~20 轮收敛
- **全局流毒化**: 进程级单流——任一端点泄 random 输出即毒化全部消费者。DSA k=randrange: randcrack 预测 k → `x=(s*k-h)*r⁻¹ mod q` 直接解私钥
- PHP mt_rand: 单输出即可 php_mt_seed 恢复种子（PHP 变体，见 web-crypto-attacks.md §4）

## 3. V8 XorShift128+（Math.random）

- 输出只用 state0: `(state0>>12 | 0x3FF0000000000000) - 1.0`；观测 `floor(CONST*rand)` 值约束 mantissa 区间（Decimal(val)/multiple 上下界），Z3 QF_BV 求解，5-10 个连续观测唯一解
- **LIFO cache**: Math.random 从 64 值缓存倒序取——观测序列 `tac` 反转后再喂 solver
- **逆向步进**（预测过去值，如他人已生成的 2FA）: 逆 `v^=v>>s` 三次迭代 `r=v^(r>>s)`；逆 `v^=v<<s` 同型。reverse_step 从 (s0,s1) 回推 (old_s0, old_s1)
- 工具: d0nutptr/v8_rand_buster。陷阱: 多 tab/worker 独立状态；跨 64 次 refill 边界不连续

## 4. Java Random

- 结构: `seed = (seed*25214903917 + 11) mod 2^48`，输出 `(seed*a+c) >> 16`（丢低 16 位）
- **部分模输出 MITM**: 只见 nextInt(62) 字符 → 低 18-bit 种子只影响输出 LSB → 2^18 低段（按奇偶过滤）× 2^30 高段两趟，替代 2^48
- **反向步进**: `prev = a⁻¹*(state-11) mod 2^48`，`pow(25214903917,-1,1<<48)`。任意 2^k 模 LCG 可逆；LCG/xorshift/MT 转移皆双射——历史状态无需从种子重模拟

## 5. LCG

参数恢复（差分 gcd）、截断 LCG（HNP 格）、部分输出暴力——见 symmetric-and-hash.md §6 与 lattice-attacks.md §4.2。本文件补充: ①LCG 派生 RSA 素数时，已知明文恢复密钥流（=LCG 输出）→ 恢复参数 → 重放素数生成序列重建 N ②周期检测免参数: LCG 周期 ≤ m，持续拉输出记录 seen 映射，出现重复即找到周期——此后未来值=历史循环回放，无需恢复参数（输出缓冲无限拉取的博弈型服务）。

## 6. 种子审计

逐项问种子组成项可控性:

| 组成项 | 攻击面 |
|---|---|
| time()/时钟 | 窗口爆破（±60s 起，容器时钟漂移更大）；文件 mtime/响应 Date 头即种子（id 详见 web-crypto §4） |
| 用户可控输入 XOR | 控制输入（如 NTP 返回 0）直接消出内部状态 |
| 用户可控偏移（+bet） | 内存写原语定种后完全离线预测 |
| 外部服务取值（NTP/API） | 中间人替换 |
| 可打印 ASCII 之和/短数字 | 熵坍缩 10^6~10^9 离线枚举 + 已知明文判据 |

规则: 种子熵 = 实际输入空间 log2，与算法强度无关。C 的 srand: Python random ≠ C rand，须 ctypes CDLL 加载**同一 libc**（题目自带 libc.so.6 优先）调 srand/rand；远端 +1/+2s 偏移重试；对齐中间多余 rand() 调用。

**PoW 预计算（games-and-vms）**: 服务 alarm 超时 + 每轮 scrypt/hashcash PoW 且挑战由 `srand(time(NULL)>>4)` 生成时——种子空间仅 ~1024（16s 粒度×窗口），连接前离线预计算全部 seed→挑战→解，线上查表秒答; 瓶颈在 PoW 速度而非游戏逻辑时优先此路。

## 7. 特殊/自制 PRNG

- **GF(2) 线性族**: 只含 XOR/移位/旋转 → 输出=矩阵×种子 (mod 2)，单位向量逐列建矩阵 + 高斯消元（见 symmetric-and-hash.md §8）。输出字节折叠不破坏线性——ASCII top bit=0 是免费奇偶方程，字符集约束转 GF(2) 方程组零暴力解状态
- **混沌 logistic map**: x_{n+1}=r·x(1-x)，r≈4 混沌但确定。种子 0-1 小数枚举（6-11 位精度 × 有意义基数），struct.pack("<f") 打包变体（4B/8B/[-2:]）。指纹: chaos/logistic/butterfly
- **元胞自动机（Rule N）**: 规则号=真值表 → Bool 变量 + DNF 编码 + 符号推进 N 轮 + 输出约束，Z3 反演初始态（CA 非单射，多 preimage 用 push/pop 枚举）
- **middle-square/弱种子**: 平方取中 6 位种子 + time 取模 → 10^6 离线爆破，1 组已知明文足够
- **秘密做种子**: flag 字节串 seed random.Random 驱动确定性渲染 → 已知前缀锚 + 逐字节爬山（每候选渲染评分取最优；前缀对则评分单调升）
- **密钥复杂派生函数**: Ghidra 模拟器直接执行派生函数读输出（零转写误差），优于静态重实现；Unicorn/qiling 同理

## 8. Oracle/侧信道形态

- **Z3 求解时间**: 服务端内部跑 solver 验证输入——错猜平凡 SAT 秒回、对猜 UNSAT-hard 显著慢。紧 timeout(500ms) + 慢解晋升，逐字符爆破。用已知对/错样本先校准方向
- **随机模式挡板消除法**: 目标藏在 N 种随机模式/IV 之一 + 可提交探测——先 ~50 probe 探可达性（密文前缀同模式），不可达重连；可达连接中字节不匹配=永久排除候选（排除跨连接持久）。消除法优于确认法
- **并行连接中继**: 确定性序列（同时连接→同种子）+错误即断连的服务——开 N+1 连接 threading.Barrier 按轮同步，每轮牺牲一个连接穷举答案，其余连接吃中继答案; 判定适用: 惩罚是断连非全局重置（若惩罚为全局重置则本路失效，改用 cookie 存档回滚逐轮爆破）

## 9. 工具速查

| 工具 | 用途 |
|---|---|
| randcrack | Python MT 接管（624×32bit submit 后 predict） |
| not_random (fx5) | random.random() 浮点恢复 MT 状态 |
| v8_rand_buster (d0nutptr) | V8 xs128p 状态恢复/预测 |
| php_mt_seed | PHP mt_rand 单输出恢复种子 |
| ctypes CDLL | C rand/srand 序列同步（同 libc） |
| crypto-attacks (jvdsn) | LCG 参数恢复等套件 |

## 决策

```
输出可观测 + 全宽 32bit? → untemper/randcrack 接管 (§2)
输出被截断/取模/部分? → 约束传播 / MITM 分割 / HNP 格 (§2/§4/lattice)
Math.random? → xs128p + tac 反转 (§3)
只见历史值? → 反向步进 (§3/§4)
种子含 time/可控值? → 种子审计表 (§6)
自制递推? → 先判线性 (GF2 矩阵) → 混沌/CA 枚举 → Z3 (§7)
无对错反馈? → 求解时间侧信道 (§8)
恢复后必须: 预测值与后续观测比对验证再利用
```

## 注意

- 观测与目标操作共享同一流是接管前提（多流/多 worker 各自独立）
- 浮点/截断输出每次丢 bit，先算"每观测净信息量 × 观测数 ≥ 状态熵"再开工
- 种子爆破判据（解密成功/格式匹配/预测命中）先行确定，否则枚举无法收敛
