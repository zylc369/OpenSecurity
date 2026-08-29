# 自制分组密码结构攻击

> 触发场景：样本提供自制分组密码的**完整源码**（非标准 AES/DES/ChaCha）+ **大批量结构化 (明文, 密文) 记录** + 一个待开启的**认证加密盒**。路线：组件弱点分解 → 积分攻击恢复密钥 → 开盒。
>
> 与 `rsa-attacks.md` 等标准方案攻击库互补：那些针对标准算法的参数误用，本文件针对攻击者可读到全部实现的自制算法。

---

## 1. 前置识别：记录集的三件套结构

自制密码样本通常给三样东西，先逐一确认：

1. **源码**：能本地复现加密（必有 `encrypt`/`matrix` 等函数）——立即用自造密钥跑一遍，确认可复现。
2. **记录集**：`records.json`（结构描述）+ `records.bin`（密文块序列）。关键字段识别：
   - `"block_bytes": N` → 每块 N 字节，`len(bin) / N` = 总块数，与 sets 的 `count` 总和对账
   - 枚举描述 `"index m selects basis vector i when bit i of m is one"` → 明文空间 = `base ⊕ span{basis[i] | m 的第 i 位为 1}`，即 **d 维仿射子空间的 2^d 个点全部加密**——这是积分攻击的理想输入
   - `sets[].offset` 是块序列偏移，枚举顺序 = m 从 0 递增
3. **加密盒**：`{n: nonce, c: ct, t: tag}` 三字段 JSON → 认证加密结构（§5）。

**必做**：解析 records.json 后先重放第一个 set 的明文生成，与样本自带 `__main__` 输出对账，防字段误解。

## 2. 轮函数组件弱点清单

拿到源码后逐组件对表，每个组件暴露独立攻击面：

| 组件 | 特征识别（代码形态） | 暴露的攻击面 |
|------|---------------------|-------------|
| Feistel 半字节 S 盒 | `return r \| ((l ^ F(r)) << 4)` 型（低半 = f(高半)，高半直通或半交换） | 双射但跨半扩散弱；差分/积分性质易推导 |
| 全局位仿射置换 | `y \|= ((x>>i)&1) << ((a*i+b) % n)` | 纯线性，可编程求逆，非密码学混淆 |
| 逐字节独立最终层 | `for i: out[i] = M_i(S(x[i])) ^ c_i`，M_i 由 `key[i]` 索引公开表 | 字节间零混合 → 逐字节分离枚举 |
| 轮密钥只依赖主密钥子集 | `round_key = H(key[i] >> 8 材料拼接)` | 高位/低位分离：先攻高位（定轮密钥），再正向解低位 |
| 哈希派生公开表 | `matrix(idx) = sha256(D + idx ...)` 重试至满秩 | 所有"密表"本地可算 → 枚举空间就是 idx 值域 |

**分析要点**：找出"最终层之前的变换整体记为 F（依赖轮密钥）"与"最终层（仅依赖逐字节 key[i]）"的分界——攻击就打在这条分界线上。

## 3. 积分攻击完整流程

### 3.1 平衡性实验先行（禁止跳过）

自造随机密钥，取一个 d 维 set 的全部 2^d 明文，复刻源码中间态（3.5 轮输出，即最终层输入），计算每字节 XOR 和：

```python
def mid_state(block, key):  # 复刻源码：轮密钥 XOR → S 盒 → 置换，重复 R 次，最后再 XOR 一次轮密钥
    s = bytes(block)
    for r in range(R):
        k = round_key(key, r)
        s = bytes(S_box(a ^ b) for a, b in zip(s, k))
        s = permute(s)
    return bytes(a ^ b for a, b in zip(s, round_key(key, R)))

xs = [mid_state(plain_of(m), TESTKEY) for m in range(2**d)]
bal = [0]*N
for x in xs:
    for j in range(N): bal[j] ^= x[j]
# bal 全 0 → 中间态逐字节平衡，积分区分器成立
```

- **全 0** → 区分器成立，进入 3.2
- **非全 0** → 检查明文枚举是否错（bit 顺序/offset 对账）或轮数理解错；也可降维验证（单 basis 差分的扩散路径）

### 3.2 逐字节枚举过滤（numpy 模板）

攻击原理：最终层 `out[i] = M_{s_i}(q(x_i)) ^ c_i` 中 `M_{s_i}^{-1}`、`q^{-1}` 都可本地构造；对候选 `(s_i, c_i)` 反推 `x_i` 序列，检验每 set 的 XOR 和是否为 0（真密钥必满足 3.1 的平衡性）。

```python
import numpy as np
QINV = np.array([q_inverse(y) for y in range(256)], dtype=np.uint8)   # S盒逆查表
C256 = np.arange(256, dtype=np.uint8)
MINV = np.zeros((4096, 256), dtype=np.uint8)  # MINV[idx][y] = M_idx^{-1}(y)；矩阵用样本源码 matrix(idx) 生成，求逆用 §4.1 的 mat_inverse

def attack_byte(cols):
    """cols: 各 set 的该字节密文列 [np.array(2**d,)]，返回存活的 (s, c) 集合"""
    cands = None
    for col in cols:
        live = set()
        for s in range(4096):
            A = MINV[s][col[:, None] ^ C256[None, :]]     # (2**d, 256)
            acc = np.bitwise_xor.reduce(QINV[A], axis=0)  # 每个 c 的平衡值
            for c in np.nonzero(acc == 0)[0]:
                live.add((s, int(c)))
        cands = live if cands is None else cands & live
        if not cands: return []
    return sorted(cands)
```

- 实测性能：4096 矩阵 × 12 字节 × 3 组 512 块记录 ≈ 13 秒（M 系列 CPU）
- 典型结果：每个 `(s, c)` 中 `c` 可能全存活（最终层常数在 XOR 求和中成对消去），**`s`（矩阵索引）通常唯一**——这就是全部高位密钥

### 3.3 正向回推低位

`s` 全体唯一 → 轮密钥完全已知（轮密钥只依赖高位材料）：

```python
x0 = mid_state(p0, [s_i << 8 for s_i in s_vals])      # 任取一条已知 (p0, c0) 记录
c_i = c0[i] ^ apply(matrix(s_vals[i]), q(x0[i]))       # 直接解出每字节低位
KEY = [s_vals[i] << 8 | c_i for i in range(N)]
```

验证：随机抽 50 条记录加密比对，全过即密钥正确。

### 3.4 消歧与收尾

- 某字节 `s` 剩多候选 → 加一个 set 的列再过滤（一次一个，成本线性）
- 全部通过后立即开盒（§5），不要停留在"密钥已恢复"

## 4. 工程坑

### 4.1 GF(2) 矩阵求逆：增广单位阵位序

8×8 GF(2) 矩阵求逆时，增广单位阵必须放在**高位区**（`rows[i] | (1 << (8+i))`）。放 `1 << i` 会与系数区重叠，症状是"源码 rank 校验通过（满秩）但求逆返回失败/结果错"：

```python
def mat_inverse(rows):
    a = [rows[i] | (1 << (8 + i)) for i in range(8)]   # 关键：单位部分放 bit 8-15
    piv = {}; r = 0
    for c in range(8):
        p = next((i for i in range(r, 8) if (a[i] >> c) & 1), None)
        if p is None: return None
        a[r], a[p] = a[p], a[r]
        for i in range(8):
            if i != r and ((a[i] >> c) & 1): a[i] ^= a[r]
        piv[c] = r; r += 1
    if r != 8: return None
    return [(a[rw] >> 8) & 255 for c, rw in sorted(piv.items())]
```

验证：`apply(inv, apply(rows, x)) == x` 对全部 x ∈ [0,256) 成立。

### 4.2 攻击管线先自测再上真实数据

完整攻击（求逆 → 枚举过滤 → 回推）必须先在自造密钥上端到端跑通并命中已知密钥，再对真实记录执行。真实数据失败时能区分"攻击原理错"与"数据解析错"。

### 4.3 常数在求和中消去的陷阱

积分检验中每 set 有 2^d 条记录（偶数），最终层常数 `c_i` 被成对消去——**这不是过滤 c 的手段**，c 靠 3.3 正向回推获得；误把"c 全存活"当攻击失败是常见误判。

## 5. 认证加密盒开启

典型结构（样本源码含 `open` 函数时直接调用）：

```python
root = sha256(D + b'/seal/' + key_material)      # 密钥派生根
ek   = sha256(D + b'/enc/'  + root)              # 加密密钥 → HMAC-CTR 密钥流
mk   = sha256(D + b'/mac/'  + root)              # MAC 密钥
tag  = HMAC(mk, D + nonce + ct)[:16]             # 先验 tag，再解密
stream = HMAC(ek, nonce + counter_le64) 循环拼接 # 与 ct 等长后 XOR
```

密钥恢复后 `open_sealed(sealed, KEY)` 返回明文。明文形态预判：长度 32 字节且 hex 表示为 64 字符的目标数据（校验和自验证型目标的标准形态：64 hex + `sha256(64hex)[:16]` 拼接）。
