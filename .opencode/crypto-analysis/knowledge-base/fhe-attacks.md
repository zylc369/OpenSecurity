# FHE（全同态加密）CTF 攻击方法论

> 遇到 SEAL/TenSEAL/PALISADE/OpenFHE 或 BFV/CKKS 参数的密码学题时读取。覆盖方案识别、攻击向量选择与利用。不依赖主 prompt 上下文。

---

## 1. 方案与库识别

**识别信号（看到任一即 FHE）**：
- `import tenseal.sealapi` / `from seal import ...` → Microsoft SEAL（C++）/ TenSEAL（Python 绑定）
- `PALISADE` / `OpenFHE` → 同构库族
- `Concrete` / `Zama` → TFHE 系
- 参数 `SCHEME_TYPE.BFV` / `BGV` → 整数同态
- 参数 `SCHEME_TYPE.CKKS` + `scale` → 近似（实数）同态

**关键参数**：
- `poly_modulus_degree`（N）：2 的幂，常见 1024/2048/4096/8192/16384。N 越大越安全越慢
- `plain_modulus`（t，BFV 专用）：明文模数，明文在 Z_t 上
- `coeff_modulus`（q）：密文模数，决定噪声预算

**BFV vs CKKS**：
- BFV：明文是 Z_t[x]/(x^N+1) 的整数多项式，**精确**算术
- CKKS：明文是实数（缩放 `scale`，如 2^40），**近似**算术，有精度损失

---

## 2. 攻击向量决策树

按题目给的交互/数据选路（先做噪声预算判断，它是运算可行性的约束）：

| 场景 | 选拓 | 详见 |
|------|------|------|
| 只有密文+公钥+参数，参数弱（N 小/q 小） | 密钥恢复（格归约） | §3 |
| 让你选 galois elements / 给旋转密钥生成权限 | galois 滥用 | §4 |
| CKKS + 涉及精度/解码差异 | CKKS 精度攻击 | §5 |
| 提供加密/评估/解密 oracle | oracle 滥用 | §6 |

**噪声预算（约束，必先算）**：BFV 初始预算 ≈ log2(q/t) bit；每次乘法消耗大量预算，加法消耗少。预算 ≤0 则解密失败。
- 检查：SEAL `decryptor.invariant_noise_budget(ciphertext)` 返回剩余 bit（>0 才能正确解密；这是 SEAL C++ API，tenseal 绑定方法名遇题时确认）
- 若题目要求你做运算但预算紧张 → 必须在预算深度内完成（常需重排运算、减少乘法深度）

---

## 3. 密钥恢复（LWE/RLWE 格归约）

**场景**：参数弱，或泄露多个密文可作为 LWE 样本。

BFV/CKKS 密文是 RLWE 样本：`(a, b = a·s + e)`，s 是密钥多项式（小系数），e 是小噪声。
- 若 N 小（如 ≤1024）、q 不大、e 的范围已知 → 多个密文堆成矩阵，用 LLL/BKZ 归约恢复 s
- 具体方法（构造格、归约、提取小向量）详见 `$AGENT_DIR/knowledge-base/lattice-attacks.md` 的 LWE/RLWE 攻击章节，本文不重写

**检查**：N 与 q 的 bit 长度、可用密文数量、噪声分布与范围。

---

## 4. galois keys / 旋转密钥滥用

**场景**：题目让你选择 galois elements（旋转步长），服务端据此生成 galois keys 返回，你再提交一个"计算"密文通过验证（典型：R3CTF TinySEAL 模式——给密文、限选若干 galois 元素、提交计算结果使解密==target）。

**原理**：
- BFV 明文在 Z_t[x]/(x^N+1)，galois 自同构 σ_j: x → x^j（j 为 mod 2N 的奇数）
- 对密文应用 σ_j → 明文变为 a(x^j)，即系数按 `(i·j mod 2N)` 重排（含 x^N ≡ -1 引入的符号）
- 通过选择多个 j + 密文的同态加法/标量乘，可**聚合或提取特定系数**

**利用思路**：
1. 分析 target（要构造的明文）与已知密文明文（系数向量 a）的关系——通常 target 是 a 的某个子集/线性组合（如只要常数项 a[0]）
2. 选 galois elements 使旋转后系数能线性组合出 target（消去不需要的项）
3. 选 j 使其生成的循环子群能覆盖所需的系数位置（j 对 2N 的阶决定覆盖范围，具体值依 N 选定并验证其阶）；利用 x^N=-1 的配对性质做系数抵消

**边界**：galois elements 数量受限（TinySEAL 限 12 个），需在限制内构造计算；超出数量限制则无法覆盖全部系数，需找代数捷径（如利用系数对称性、trace 性质）。

**检查**：是否给 galois 生成权限、元素数量上限、target 与密文明文的代数关系。

> 注：具体每道题的 galois 元素构造依赖该题明文结构，需结合 target 推导；本节给出识别与思路框架，不套用万能公式。

---

## 5. CKKS 近似精度攻击

**场景**：CKKS 解密近似，低有效位不准确。

**原理**：CKKS 编码实数时缩放 `scale`，运算后截断/重缩放，低位丢失。

**利用**：
- 若 flag/秘密编码在明文高位，精度损失可能直接泄露或可枚举剩余位
- 同一值多次评估的结果微小差异 → 推断内部噪声/密钥状态
- CKKS bootstrapping（密钥切换刷新噪声）本身有精度问题，可被利用

**检查**：是否 CKKS、scale 大小、解码结果是否带小数误差、flag 编码在明文的哪一位。

---

## 6. 评估/加密 oracle 滥用

**场景**：题目提供 oracle（你提交，它加密/评估/解密并返回）。

**利用**：
- **加密 oracle**：选择明文加密，对比密文推断编码方式或参数（选择明文攻击）
- **评估 oracle**：提交特定密文让其计算 f，结果泄露 f 的结构或密钥信息
- **解密 oracle**：若能解密任意密文（除 flag 密文），构造密文逐步逼近 flag 密文

**检查**：oracle 允许的操作类型、调用次数限制、输入输出格式、是否有黑名单（如禁止解密 flag 密文）。

---

## 7. 常见参数与工具速查（TenSEAL/SEAL API）

基于 `tenseal.sealapi`（与 C++ SEAL API 一致）：

```python
import tenseal.sealapi as sealapi

# BFV 参数设置
parms = sealapi.EncryptionParameters(sealapi.SCHEME_TYPE.BFV)
parms.set_poly_modulus_degree(4096)                              # N
parms.set_plain_modulus(163841)                                  # t
coeff = sealapi.CoeffModulus.BFVDefault(4096, sealapi.SEC_LEVEL_TYPE.TC128)
parms.set_coeff_modulus(coeff)
ctx = sealapi.SEALContext(parms, True, sealapi.SEC_LEVEL_TYPE.TC128)

# 密钥与加解密对象
keygen = sealapi.KeyGenerator(ctx)
pub = sealapi.PublicKey(); keygen.create_public_key(pub)
sec = keygen.secret_key()
enc = sealapi.Encryptor(ctx, pub)
dec = sealapi.Decryptor(ctx, sec)

# 加密/解密
ct = sealapi.Ciphertext()
enc.encrypt(sealapi.Plaintext("a[0] + a[1]x + ..."), ct)         # 明文为系数字符串
pt = sealapi.Plaintext(); dec.decrypt(ct, pt)

# 噪声预算（BFV 必查；SEAL C++ API，tenseal 绑定名遇题确认）
budget = dec.invariant_noise_budget(ct)                          # 返回剩余 bit，>0 可解密

# galois keys（旋转密钥，§4 滥用场景）
gk = sealapi.GaloisKeys()
keygen.create_galois_keys([3, 9, 27], gk)                        # 传 galois 元素列表
```

**参数选择经验**：
- N=1024 通常弱（格攻击可破）；N≥4096 较安全
- plain_modulus（t）选质数；t 过大压缩噪声预算
- CKKS 的 scale 通常 = 2^40 或 2^60
