# 需求: 完善 crypto-analysis 知识库（数论构造题 + 补齐 4 篇攻击库）

## §1 背景与目标

**来源痛点**: 2026-06-28 做 SekaiCTF `oneline6ryp7o`（数论构造题）时发现两个体系缺口：

1. **类型识别盲区**: crypto-methodology.md 与 agent prompt 的"阶段 A 类型识别表"只覆盖 RSA/ECC/格/古典/对称/哈希 6 类。本题特征是"Python 一行 assert + 数论/位运算/模运算约束 + 构造满足约束的输入"，不落进任何一类。严格按框架走的 AI 会在"阶段 A：识别类型"卡住。这类题（math puzzle / golf / one-liner）在 CTF 是常见赛道。

2. **核心数学洞察未沉淀**: 本题核心解法——梅森数 `2^p-1` 模运算的"二进制位构造法"（`2^p ≡ 1 (mod M)`，字节流按位折叠，单位增量的二进制表示直接给解），知识库中完全没有。该技巧可把看似需爆破的 2^p 组合问题降为 O(p) 直接构造，同类题反复出现。

3. **攻击知识库未补齐**: 需求 `2026-06-27-crypto-analysis-agent.md` 计划 6 篇知识库，目前只完成 2 篇（crypto-methodology.md、classical-crypto.md），rsa-attacks.md / lattice-attacks.md / ecc-attacks.md / symmetric-and-hash.md 仍未建。agent prompt 的知识库索引已引用这 4 个文件，但文件不存在 → AI 按索引去读会落空。

**预期收益**:
- 数论构造题纳入类型识别，同类题不再卡壳（省 2-3 轮试错）
- 梅森数构造法沉淀，下次直接套用（避免从零推导）
- 补齐 4 篇攻击库，使 agent 知识库索引全部可用（RSA/格/ECC/对称题有完整方法论支撑）

**用户决策**: 方案 A（数论构造题）+ 方案 B（补齐 4 篇攻击库）一起做。

## §2 技术方案

### 2.1 新建知识库文件（5 篇，全部位于 `crypto-analysis/knowledge-base/`）

| 文件 | 定位 | 覆盖内容 |
|------|------|---------|
| `number-theory-construction.md` | 专题深度 | 数论/位运算构造题：类型识别 + 梅森数 `2^p-1` 二进制位构造法 + Python 优先级陷阱 + 用原 assert 验证 |
| `rsa-attacks.md` | 漏洞模式 | RSA：共模/小 e 开方/Wiener/Boneh-Durfee/低解密指数/广播/partial key/已知 p,q 直接解 |
| `lattice-attacks.md` | 漏洞模式 | 格攻击：LLL 基础/HNP/截断 LCG/`a*p+b*q` 提示/多维 Coppersmith；含 sage 格构造模板 |
| `ecc-attacks.md` | 漏洞模式 | 椭圆曲线：Smart(anomalous)/MOV/Pohlig-Hellman/invalid curve/奇异曲线 |
| `symmetric-and-hash.md` | 漏洞模式 | 对称+哈希：AES ECB/CBC、CBC bit flip、padding oracle、哈希长度扩展、弱随机(LCG) |

每篇写"什么时候用 → 怎么识别 → 怎么攻击 → sage/python 代码片段"，遵循 `$SHARED_DIR/knowledge-base/knowledge-writing-guide.md`。

### 2.2 类型识别表 + 索引更新（修改 2 文件）

- `crypto-analysis/knowledge-base/crypto-methodology.md`：类型识别表 +1 行（数论构造题）
- `agents/crypto-analysis.md`：阶段 A 类型识别表 +1 行；知识库索引 +1 行（number-theory-construction.md）

> 注：agent prompt 知识库索引已引用 rsa/lattice/ecc/symmetric 4 文件（第 115-119 行），方案 B 只需创建文件，无需改索引。

### 2.3 coordinator 路由描述更新（功能可调用性补全）

`security-coordinator.md` 现有 crypto 路由描述（第 45 行能力表、第 90 行路由决策表）只列"RSA/格/ECC/古典/对称/哈希"，不含"数论/位运算构造题（Python assert/oneline/整除约束）"。若不更新，coordinator 自动路由时会把这类题漏判（方案 A 的类型识别在自动路由场景下落空）。

改动：两处描述补充"数论构造题（Python assert / oneline / 整除 / 模运算约束）"。仅改描述文字，不改路由逻辑。

### 2.4 边界与归属

- 全部为**纯知识库新增 + 描述文字微调**，不涉及 Plugin/代码/detect_env 改动，风险低。
- 归属：均为通用密码学知识，放 `crypto-analysis/knowledge-base/`（不涉及移动端）。
- Coppersmith 边界：rsa-attacks.md 讲"一元小根开方"应用；lattice-attacks.md 讲"格构造原理 + 多维小根"；交叉引用不重复。

## §3 实现规范

### 改动范围表

| 项目 | 内容 |
|------|------|
| 新增文件 | 5 篇知识库（number-theory-construction / rsa-attacks / lattice-attacks / ecc-attacks / symmetric-and-hash） |
| 修改文件 | crypto-methodology.md（类型表 +1 行）、agents/crypto-analysis.md（类型表 +1 行 + 索引 +1 行）、security-coordinator.md（crypto 路由描述 2 处补"数论构造题"） |
| 高风险 | 无（纯知识新增 + 描述微调，不改 Plugin/代码/现有逻辑） |

### §3.1 实施步骤拆分

```
步骤 1. 新建 number-theory-construction.md（方案 A 核心）
  - 文件: crypto-analysis/knowledge-base/number-theory-construction.md（新建）
  - 预估行数: ~120 行
  - 验证点: 自包含（不依赖主 prompt）；含梅森数构造法的可执行 python 代码；
            含 oneline6ryp7o 的构造步骤（通用化，去题目特有细节）；人工读一遍逻辑正确
  - 依赖: 无

步骤 2. 新建 rsa-attacks.md
  - 文件: crypto-analysis/knowledge-base/rsa-attacks.md（新建）
  - 预估行数: ~150 行
  - 验证点: 覆盖 ≥6 种 RSA 攻击；每种含"何时用+识别+攻击+代码"；
            sage/python 代码片段可执行（无语法错误）；交叉引用 lattice-attacks 的 Coppersmith
  - 依赖: 无

步骤 3. 新建 lattice-attacks.md
  - 文件: crypto-analysis/knowledge-base/lattice-attacks.md（新建）
  - 预估行数: ~150 行
  - 验证点: 含 LLL 基础 + HNP + a*p+b*q + 截断 LCG；
            含 sage 格构造模板（matrix + LLL）；代码可执行
  - 依赖: 无

步骤 4. 新建 ecc-attacks.md
  - 文件: crypto-analysis/knowledge-base/ecc-attacks.md（新建）
  - 预估行数: ~130 行
  - 验证点: 含 Smart(anomalous)/MOV/Pohlig-Hellman/invalid curve/奇异曲线；
            sage EllipticCurve 代码可执行
  - 依赖: 无

步骤 5. 新建 symmetric-and-hash.md
  - 文件: crypto-analysis/knowledge-base/symmetric-and-hash.md（新建）
  - 预估行数: ~130 行
  - 验证点: 含 CBC bit flip + padding oracle + 哈希长度扩展 + 弱随机 LCG；
            python 代码可执行
  - 依赖: 无

步骤 6. 更新类型识别表 + 索引 + coordinator 路由描述
  - 文件: crypto-methodology.md（类型表 +1 行）、agents/crypto-analysis.md（类型表 +1 行 + 索引 +1 行）、security-coordinator.md（第 45、90 行 crypto 描述补"数论构造题"）
  - 预估行数: 改动 ≤15 行
  - 验证点: 两处 agent 类型表新增"数论构造题"行且指向 number-theory-construction.md；
            agent 索引新增 number-theory-construction.md；
            coordinator 第 45/90 行描述含"数论构造题"；无 markdown 语法破坏
  - 依赖: 步骤 1（引用该文件）

步骤 7. 端到端验证
  - 验证: ① 5 个新文件全部存在且自包含；
          ② agent prompt 知识库索引的 7 个文件全部存在（crypto-methodology/rsa/lattice/ecc/classical/symmetric/number-theory-construction）；
          ③ number-theory-construction.md 里的梅森数构造代码能跑通（复现 oneline6ryp7o）；
          ④ 各篇代码片段 python -c compile 无语法错误；
          ⑤ coordinator crypto 路由描述含"数论构造题"
  - 依赖: 全部
```

## §4 验收标准

### 功能验收
- [ ] 5 篇新知识库文件存在且自包含
- [ ] number-theory-construction.md 含梅森数二进制位构造法的可执行代码
- [ ] rsa/lattice/ecc/symmetric 4 篇各覆盖核心攻击且含可执行 sage/python 代码
- [ ] crypto-methodology.md 与 agent prompt 类型表新增"数论构造题"行
- [ ] agent prompt 知识库索引的 7 个文件全部存在
- [ ] security-coordinator.md 第 45/90 行 crypto 路由描述含"数论构造题"

### 回归验收
- [ ] 不改动 Plugin、detect_env、_base.py 等任何代码
- [ ] crypto-methodology.md / classical-crypto.md 现有内容不被破坏
- [ ] agent prompt 现有结构（阶段 A/B/C、核心原则）不变

### 架构验收
- [ ] 新文件位于 `crypto-analysis/knowledge-base/`
- [ ] 跨文件引用使用 `$AGENT_DIR` / `$SHARED_DIR` 变量
- [ ] 遵循 knowledge-writing-guide.md（场景驱动、具体可操作、不重复）

### 知识质量验收（规则 8）
- [ ] 准确性：代码示例可执行、参数精确
- [ ] 完整性：每条知识含"何时用+怎么检查+怎么利用"
- [ ] 一致性：术语与现有知识库一致
- [ ] 可操作性：有检查步骤和成功/失败判断标准
- [ ] 覆盖度：不偏科（不只基于一道题）

## §5 与现有需求文档的关系

- 呼应 `2026-06-27-crypto-analysis-agent.md`（crypto-analysis 创建需求，计划 6 篇知识库；本需求补齐其中缺失的 4 篇）
- 本需求额外新增第 7 篇 number-theory-construction.md（该类型在原需求中未规划，是本次复盘新增发现）
- 独立需求，不依赖其他未完成需求
