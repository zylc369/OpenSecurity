# 需求：Blockchain 智能合约攻击方法论（批次3）

> 创建: 2026-07-02
> 状态: ✅ 已完成（Phase 2-6 全通过，2026-07-02）
> 来源: 批次3；R3CTF 2024 DAO（delegatecall+治理）+ 2025（Solidity）暴露的全方向 gap
> 前置: 2026-07-02-gap-definition-clarity.md（批次1）

## §1 背景与目标

**痛点**: Blockchain 在全知识库零覆盖（5方向 60+ 文件无 solidity/EVM/delegatecall/web3 任何提及）。R3CTF 2024 有 DAO/Super Secure Store 两题、2025 整场 Solidity。AI 遇到智能合约题只能从零学。

**素材**: minaminao/ctf-blockchain（★1085，攻击模式分类框架）+ R3CTF DAO 源码（delegatecall+Uniswap+治理）+ 智能合约攻击通用知识。注：R3CTF 2024 无专门 writeup 仓库。

**目标**: 新建 `blockchain-analysis/knowledge-base/`（独立方向）+ `smart-contract-attacks.md`，覆盖方案识别 + 攻击模式速查表 + 核心模式（delegatecall/重入/整数溢出/access control/签名/随机数/flash loan+Oracle）的识别-检查-利用。

**规模控制**: 本批次做核心合约漏洞 + flash loan/Oracle 基础（一个文件）；DeFi 深度（治理快照/AMM/sandwich）列速查不展开，遇题再深入。

## §2 技术方案

### 改动性质
- **放 `crypto-analysis/knowledge-base/`**（复用现有 crypto agent，避免新建"孤儿目录"——单独建 blockchain-analysis/ 但无 agent 入口，coordinator 无法路由、crypto agent 的 $AGENT_DIR 也不指向它；智能合约涉及签名/hash/Merkle 等密码学，crypto agent 可覆盖；将来 blockchain 题量大了再独立成方向）
- 新建 `blockchain-attacks.md`（约 200 行，分2步实施）
- 无脚本、不改现有 agent prompt、无新目录
- 风险：低（新增知识库文件）

### 文件结构（blockchain-attacks.md）
```
# 智能合约 CTF 攻击方法论
## 1. 环境与方案识别（Foundry/Hardhat/链/RPC）
## 2. 攻击模式速查表（30+ 模式 → 一句话定位）
## 3. delegatecall 滥用（存储覆盖/上下文）— DAO 案例
## 4. 重入攻击
## 5. access control 与权限漏洞
## 6. 整数溢出（unchecked/assembly 绕过）
## 7. 签名验证漏洞（重放/可延展/ecrecover address(0)）
## 8. 链上随机数弱点（block.timestamp/blockhash）
## 9. flash loan 与 Oracle 操纵（基础）
## 10. 工具速查（Foundry/Slither/cast）
```

## §3 实现规范

### 改动范围表
| 文件 | 类型 | 行数 |
|------|------|------|
| `crypto-analysis/knowledge-base/blockchain-attacks.md` | 新增 | ~200 |

### §3.1 实施步骤拆分

**步骤 1. 写 §1-§5（识别+速查+delegatecall+重入+access control）**
- 文件: `crypto-analysis/knowledge-base/blockchain-attacks.md`
- 预估: ~110 行（≤200）
- 验证点: writing-guide 四项；delegatecall 对照 DAO 源码（R3Dao.execute delegatecall）准确
- 依赖: 无

**步骤 2. 续写 §6-§10（整数/签名/随机数/flash loan+Oracle/工具）**
- 文件: 同上（追加）
- 预估: ~90 行（≤200）
- 验证点: Solidity 版本边界准确（≥0.8 整数自动检查）；flash loan 机制准确；Foundry 命令可执行
- 依赖: 步骤 1

**步骤 3. 自检（规则11 + writing-guide）**
- 验证点: 逐条规则11；代码示例（Foundry test/cast）语法正确；DAO 案例对照源码

## §4 验收标准

### 功能验收
- [ ] 方案识别：能判定合约题环境（Foundry/RPC/链）
- [ ] 速查表覆盖 ≥20 攻击模式
- [ ] delegatecall/重入/access control/整数/签名/随机数/flash loan 七大模式有"识别+检查+利用"
- [ ] DAO 作为 delegatecall 案例（对照源码）

### 质量验收（writing-guide）
- [ ] 准确性：Solidity 版本边界、Foundry 命令、攻击 payload 准确
- [ ] 完整性：读者能开始分析合约题
- [ ] 一致性：引用用 `$AGENT_DIR`（blockchain-analysis 视角）
- [ ] 可操作性：有 Solidity payload/Foundry test 示例

### 架构验收
- [ ] 复用 crypto-analysis/ 方向，不新建目录、不违反依赖方向
- [ ] 不与现有方向知识库重复（blockchain 此前零覆盖）

## §5 与现有需求文档的关系
- 与 FHE（批次2）并列：两者都是补 crypto 相邻方向空白，但 blockchain 独立成目录（攻击模式体量大）
- 源自 gap 定义改进（批次1）：批次1 让 agent 识别 blockchain 是方向级 gap，本批次填补
