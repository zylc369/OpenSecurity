# 需求：FHE 攻击方法论（crypto-analysis 补充）

> 创建: 2026-07-02
> 状态: ✅ 已完成（Phase 2-6 全通过，2026-07-02）
> 来源: 批次2；R3CTF TinySEAL（BFV+galois）暴露的 gap
> 前置: 2026-07-02-gap-definition-clarity.md（批次1）

## §1 背景与目标

**痛点**: R3CTF 2024 Crypto/TinySEAL（BFV + galois keys 旋转）这类全同态加密（FHE）题，crypto 知识库仅在 `crypto-methodology.md` L20 类型识别表提了一句"加密/评估 oracle（SEAL/CKKS/BFV）→ FHE → 格归约恢复密钥"，**无任何攻击方法论**。AI 遇到只能从零学 SEAL/TenSEAL API + FHE 理论。

**素材现状**: FHE 在公开 writeup 仓库（rkm0959/pcw109550）无专门解题（极罕见）；本批次素材 = R3CTF TinySEAL 源码（BFV+galois 场景）+ FHE 通用理论。

**目标**: 新建 `crypto-analysis/knowledge-base/fhe-attacks.md`，覆盖 FHE 题的方案识别 + 攻击向量决策树 + 主要向量（密钥恢复/噪声/galois滥用/CKKS精度/oracle）的检查与利用方法。

**准确性边界**: galois 滥用部分写原理（已知向量），TinySEAL 作"方案识别案例"而非"完整解"（无 writeup 验证，不编造）。

## §2 技术方案

### 改动性质
- 新增知识库文件 `crypto-analysis/knowledge-base/fhe-attacks.md`（约 130 行）
- 修改 `crypto-analysis/knowledge-base/crypto-methodology.md` L20：类型识别表 FHE 行加索引指向新文件
- 无脚本、无架构变更
- 风险：低（知识库文档，验证靠 writing-guide 四项检查 + 自包含性）

### 文件结构（fhe-attacks.md）
```
# FHE（全同态加密）CTF 攻击方法论
> 一句话定位
## 1. 方案与库识别（看什么判定 BFV/CKKS/库）
## 2. 攻击向量决策树（参数/oracle/galois/精度 → 选哪条路；含噪声预算约束判断）
## 3. 密钥恢复（LWE/RLWE 格归约）
## 4. galois keys / 旋转密钥滥用
## 5. CKKS 近似精度攻击
## 6. 评估/加密 oracle 滥用
## 7. 常见参数与工具速查（SEAL/TenSEAL API）
```

## §3 实现规范

### 改动范围表
| 文件 | 类型 | 行数 |
|------|------|------|
| `crypto-analysis/knowledge-base/fhe-attacks.md` | 新增 | ~130 |
| `crypto-analysis/knowledge-base/crypto-methodology.md` L20 | 改（加索引） | +1 行 |

### §3.1 实施步骤拆分

**步骤 1. 写 fhe-attacks.md**
- 文件: `crypto-analysis/knowledge-base/fhe-attacks.md`
- 预估: ~130 行（≤200）
- 验证点: writing-guide 四项检查（准确/完整/一致/可操作）+ 自包含（不依赖外部文件）
- 依赖: 无

**步骤 2. crypto-methodology.md L20 加索引**
- 文件: `crypto-analysis/knowledge-base/crypto-methodology.md`
- 预估: 改 1 行（+索引指向 fhe-attacks.md）
- 验证点: 索引路径用 `$AGENT_DIR` 变量；grep 确认 fhe-attacks.md 被引用
- 依赖: 步骤 1

**步骤 3. 自检（规则11 + writing-guide）**
- 验证点: 逐条回答规则11七问；代码示例（TenSEAL API）对照 TinySEAL 源码确认可执行

## §4 验收标准

### 功能验收
- [ ] 方案识别：看库/参数能判定 BFV vs CKKS
- [ ] 攻击向量决策树：覆盖 4 条攻击向量（密钥恢复/galois/CKKS精度/oracle）+ 噪声预算约束判断
- [ ] 各向量有"识别+检查+利用"（非骨架）
- [ ] galois 滥用写原理，不编造 TinySEAL 完整解

### 质量验收（writing-guide）
- [ ] 准确性：TenSEAL/SEAL API 与 TinySEAL 源码一致
- [ ] 完整性：读者能据此开始分析 FHE 题
- [ ] 一致性：术语与 crypto 现有库一致，引用用 `$AGENT_DIR`
- [ ] 可操作性：有具体参数值、检查步骤

### 回归验收
- [ ] 不与 lattice-attacks.md 重复（密钥恢复引用 lattice，不重写）
- [ ] crypto-methodology 索引更新

## §5 与现有需求文档的关系
- 互补 `2026-06-28-crypto-knowledge-completion.md`（crypto 知识完善）：后者补 RSA/ECC/lattice 等，本文档补 FHE 这个唯一空白子领域
- 与批次1（gap 定义）衔接：批次1 让 agent 能识别 FHE 是技术点级 gap，本文档填补该 gap
