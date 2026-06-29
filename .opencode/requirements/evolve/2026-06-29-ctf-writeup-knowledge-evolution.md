# 需求：基于 CTF writeup 的知识体系进化（2023-2026）

> 创建: 2026-06-29
> 状态: 进行中
> 进度文档: progress-2026-06-29-ctf-writeup-knowledge-evolution.md

## §1 背景与目标

**痛点**: 做 CTF 题非常慢甚至无法做出来。`docs/分析/` 下的实际案例（SekaiCTF 2026 等）只记录了题目元信息，没有解题过程。

**根因**（经 5 方向 writeup 调研确认）:
1. Pwn 方向知识库完全空白（CTF 核心方向零覆盖）
2. 近年新原语没沉淀（Web 客户端攻击、逆向反混淆选型、密码学速查表）
3. 缺"快速识别→选型"的决策表

**目标**: 通过研究近三年（2023-2026）CTF writeup，建立源文档库（writeup 原文），提炼通用可复用的知识沉淀到知识库，让 AI 下次做题时不从零摸索。

## §2 已完成调研

| 方向 | 报告位置 | 状态 |
|------|---------|------|
| Pwn | `.research/pwn-ctf-2023-2026/调研报告.md`（459行） | ✅ |
| 逆向 | `docs/资料/ctf-reversing-research-2023-2026/` | ✅ |
| Web | task_result 在线（已归档到本需求上下文） | ✅ |
| 密码学 | `ctf-crypto-research-2026/CTF-Crypto-Research-2026.md`（501行） | ✅ |
| AI 安全 | `research/ai-security-2026/AI安全攻击调研报告-2023-2026.md` | ✅ |

## §3 确认的进化方向

### 第一批（核心 gap，用户已确认）
- **A. Pwn 知识库从零搭建** —— 现有体系零覆盖，最高优先级
  - `pwn-methodology.md`：标准 8 步流程 + mitigations 应对速查表 + 卡点突破表 + 工具链
  - `pwn-heap-methodology.md`：glibc 版本→落点决策树 + House of Apple/Cat/Water/Tangerine 伪造模板 + safe-linking 绕过
  - `pwn-kernel-methodology.md`：结构体泄漏表 + msg_msg/Dirty PageTable 模板 + 竞态窗口扩大法 + cross-cache
- **B. 逆向反混淆技术选型** —— 逆向题最大卡点
  - `deobfuscation-selection.md`：OLLVM/MBA/Tigress/VM 识别特征 + 首选工具链（D-810/deflat/QSynth/angr）
  - 更新 `idapython-conventions.md`：IDA 9.0 移除 ida_struct/ida_enum 等变化
- **C. Web 客户端攻击方法论** —— 近年 Web 题趋势变化（顶级赛几乎全是 client-side）
  - `client-side-attacks.md`：bfcache 污染 + CSS trigram exfil + xsleak + iframe reparenting
  - `race-conditions.md`：单包攻击 + 原型链污染 gadget 速查 + 解析器差异

### 第二批（增强，视精力）
- D. 密码学参数特征→攻击速查表 + Coppersmith 模板整合
- E. AI 安全 Agent 攻击面（MCP/Tool poisoning）+ 自动化越狱工具

### 第三批（补充）
- F. 符号恢复（GoReSym）/ angr 避障探索 / idalib 无头调用

### 明确不做
- WASM 逆向（频率不够）、新处理器速查（CTF 低频）、具体赛事 trick、硬编码偏移

## §4 方法论决策（用户关键纠偏）

**用户要求的正确工作流**:
```
writeup 原文/PDF/工具文档 ──webfetch下载──▶ 源文档库（事实来源，可追溯）
                                                │
                                                ▼ 从原文提炼（可回溯核对）
                                            知识库（沉淀）
```

**关键决策**: 先建立源文档库（下载 writeup 全文），再基于原文沉淀知识。不能直接从 agent 摘要沉淀——二手资料会丢细节、不可回溯、二次有损压缩。

**已验证可行性**（2026-06-29）:
- GitHub 源码（how2heap .c）：完美拿到完整源码含注释
- 博客 writeup（huli blog）：拿到完整正文 + exploit 全代码（含导航杂讯可清理）
- 官方文档（PortSwigger）：拿到完整技术内容（含导航杂讯可清理）

**限制**: 图片只能拿 URL 不能下载本体；部分博客繁体中文（不影响理解）。

## §5 源文档库组织结构

```
docs/资料/writeup-sources/
├── README.md                    ← 源文档库说明 + 使用方法
├── pwn/
│   ├── _index.md                ← 本方向索引（文件名→来源→覆盖技术点）
│   └── <按来源命名的源文档>
├── web/
│   ├── _index.md
│   └── ...
├── reversing/
│   ├── _index.md
│   └── ...
├── crypto/
│   └── _index.md
└── ai-security/
    └── _index.md
```

每篇源文档头部含 YAML 元信息:
```yaml
---
来源: <URL>
类型: 博客writeup / GitHub源码 / 官方文档 / 论文
赛事: <赛事名 年份>（适用时）
获取日期: 2026-06-29
覆盖技术: <技术点列表>
---
```

## §6 实施步骤拆分（§3.1）

### 阶段一：建立源文档库

| 步骤 | 内容 | 预估 | 验证点 |
|------|------|------|--------|
| 1 | 从 5 份调研报告提取所有 writeup 链接，去重整理成下载清单 | ~100行清单 | 清单覆盖第一批方向的核心技术 |
| 2 | 下载 Pwn 方向核心 writeup 全文（~10篇）+ 建索引 | ~10文件 | 每篇全文可读、元信息完整 |
| 3 | 下载逆向方向核心 writeup（反混淆相关，~8篇） | ~8文件 | 同上 |
| 4 | 下载 Web 方向核心 writeup（客户端攻击，~10篇） | ~10文件 | 同上 |
| 5 | （第二批）下载密码学 + AI安全 writeup | ~15文件 | 同上 |

### 阶段二：基于源文档沉淀知识

每个知识库文件**独立走 evolve 流程**（Phase 2 需求→Phase 3 审计→Phase 5 执行→Phase 6 审计），生成独立需求文档引用本总览。

沉淀原则（对照 `knowledge-writing-guide.md`）:
- 写"场景→检查→利用"，不写原理详解、不写经验来源
- 抄录**完整可执行的 payload/PoC**（从源文档原文，不是凭摘要猜）
- 决策树驱动（看到 X 就走 Y）
- 自包含、可回溯到源文档

### 阶段三：同步更新 agent prompt

每沉淀一个知识库文件后，在对应 agent prompt 增加索引行（渐进式披露，展开后 < 450 行）。

## §7 验收标准

### 功能验收
- 源文档库: 第一批方向各 8-15 篇核心 writeup 全文，`_index.md` 完整
- 知识库: 每个新增文件通过 `knowledge-writing-guide.md` 的四项质量检查（准确性/完整性/一致性/可操作性）
- agent prompt: 展开后行数 < 450

### 回归验收
- 不破坏现有知识库文件
- 不违反依赖方向（mobile/web/ai/crypto 可引用 binary，反向禁止）

### 架构验收
- 源文档库放 `docs/资料/writeup-sources/`（不散落到根目录）
- 知识库放 `$SHARED_DIR` 或 `$AGENT_DIR` 的 `knowledge-base/`
- 需求/进度文档放 `.opencode/requirements/evolve/`

## §8 与现有需求文档的关系

- 本需求是"CTF 能力提升"的总览，每个具体知识库文件沉淀时生成独立需求文档引用本总览
- 调研报告位置见 §2（这些是研究产物，非知识库文件，不进 `.opencode/`）
