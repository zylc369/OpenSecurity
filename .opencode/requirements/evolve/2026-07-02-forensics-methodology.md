# 需求：Forensics 数字取证方法论（批次4）

> 创建: 2026-07-02
> 状态: ✅ 已完成（Phase 2-6 全通过，2026-07-02）
> 来源: 批次4；R3CTF 2024 TPA 系列（网络/移动/电脑/加密取证）暴露的全方向 gap
> 前置: 2026-07-02-gap-definition-clarity.md（批次1）

## §1 背景与目标

**痛点**: Forensics 在全知识库零覆盖（5方向 60+ 文件无 volatility/wireshark/pcap/内存取证/磁盘取证/forensic 任何提及）。R3CTF 2024 有 TPA 01-04（网络/移动/电脑/加密取证综合题）。AI 遇取证题只能从零摸索工具。

**素材现状**: 取证无系统素材仓库（不像 blockchain 有 minaminao）。基于通用取证方法论 + 命令行工具（Volatility 3 / tshark / foremost / strings）+ R3CTF TPA 题型。

**目标**: 新建 `binary-analysis/knowledge-base/forensics-methodology.md`，覆盖取证流程 + 各类取证（网络/内存/磁盘/日志）的工具命令与检查点。

**归属理由**: 取证核心是内存/磁盘/样本分析，与 binary 工具链（strings/反编译/样本逆向）重叠最多；命令行工具（vol/tshark）AI 可执行，规避 GUI 依赖。

## §2 技术方案

### 改动性质
- 新建 `binary-analysis/knowledge-base/forensics-methodology.md`（约 180 行，分2步）
- 修改 binary agent 方法论/索引：加 forensics 路由（让 binary agent 遇取证题能发现该文件）
- 风险：低（新增知识库 + 索引行）

### 文件结构（forensics-methodology.md）
```
# 数字取证 CTF 方法论
## 1. 取证类型识别与流程（拿到 dump/pcap/image 先做什么）
## 2. 网络取证（pcap/tshark/流量重组/文件提取）
## 3. 内存取证（Volatility 3 插件速查）
## 4. 磁盘/文件系统取证（autopsy/foremost/已删文件/注册表）
## 5. 日志分析（Windows 事件日志/syslog/WEB 日志）
## 6. 恶意样本提取与联动（和 binary 逆向衔接）
## 7. 工具速查（vol/tshark/foremost/strings/ripgrep）
```

## §3 实现规范

### 改动范围表
| 文件 | 类型 | 行数 |
|------|------|------|
| `binary-analysis/knowledge-base/forensics-methodology.md` | 新增 | ~180 |
| binary agent 方法论/索引 | 改（加 forensics 路由行） | +1~2 行 |

### §3.1 实施步骤拆分

**步骤 1. 写 §1-§3（流程+网络取证+内存取证）**
- 文件: `binary-analysis/knowledge-base/forensics-methodology.md`
- 预估: ~100 行（≤200）
- 验证点: writing-guide 四项；Volatility 3 插件名准确（pslist/netscan/filescan/hashdump）；tshark 语法
- 依赖: 无

**步骤 2. 续写 §4-§7（磁盘/日志/恶意样本/工具速查）+ binary agent 索引**
- 文件: 同上追加 + binary agent prompt/方法论索引
- 预估: ~80 行 + 1 索引行（≤200）
- 验证点: autopsy/foremost 用法；索引路径正确
- 依赖: 步骤 1

**步骤 3. 自检（规则11 + writing-guide）**
- 验证点: 命令均可命令行执行（非 GUI）；工具名/插件名准确

## §4 验收标准

### 功能验收
- [ ] 流程：拿到 dump/pcap/image 有明确第一步
- [ ] 网络/内存/磁盘/日志四类取证有工具命令 + 检查点
- [ ] Volatility 3 + tshark 命令准确

### 质量验收（writing-guide）
- [ ] 准确性：vol/tshark/foremost 命令语法正确
- [ ] 完整性：读者能开始取证分析
- [ ] 一致性：引用 `$AGENT_DIR`/`$SHARED_DIR`
- [ ] 可操作性：命令可执行（非 GUI 步骤）

### 架构验收
- [ ] 放 binary-analysis/，binary agent 索引能发现
- [ ] 不与现有知识库重复

## §5 与现有需求文档的关系
- 与 blockchain（批次3）并列：都是补方向级 gap
- forensics 放 binary（工具链重叠），blockchain 放 crypto（密码学重叠）—— 归属按"工具/知识最接近的现有方向"
- 恶意样本分析（§6）与 binary 逆向衔接，引用现有 binary 知识库
