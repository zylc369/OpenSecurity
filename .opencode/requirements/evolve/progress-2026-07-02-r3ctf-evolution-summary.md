# 进度：R3CTF writeup 调研触发的全批次进化（汇总）

> 任务: 基于 R3CTF 2024 往年 writeup 调研的进化
> 日期: 2026-07-02
> 状态: ✅ 全部完成（批次1-4 + 技术点级）

## 批次总览

| 批次 | 内容 | 产出 | 需求文档 | 状态 |
|------|------|------|---------|------|
| 1 | meta: 明确 gap 两维定义(方向级+技术点级) | evolve prompt 2处改 | 2026-07-02-gap-definition-clarity.md | ✅ |
| 2 | FHE 攻击方法论(crypto 补充) | fhe-attacks.md(144行)+methodology §5 索引 | 2026-07-02-fhe-attacks-methodology.md | ✅ |
| 3 | Blockchain 智能合约(crypto 补充) | blockchain-attacks.md(228行)+methodology §1 路由 | 2026-07-02-blockchain-attacks.md | ✅ |
| 4 | Forensics 取证(binary 补充) | forensics-methodology.md(166行)+binary agent 索引 | 2026-07-02-forensics-methodology.md | ✅ |
| 贯穿 | 技术点级 gap | nSMC: deobfuscation-selection §6; PHP: web-vulnerabilities §9 | (含在各方向) | ✅ |

## 改动文件清单

**Agent prompt（2）**:
- `agents/security-analysis-evolve.md` — 批次1: gap 两维定义(入口C指引 L254 + §5 b点)
- `agents/binary-analysis.md` — 批次4: forensics-methodology 索引行

**新增知识库（3）**:
- `crypto-analysis/knowledge-base/fhe-attacks.md` — FHE 方案识别+4攻击向量+SEAL API
- `crypto-analysis/knowledge-base/blockchain-attacks.md` — 智能合约环境识别+20+攻击模式+7大详解+Foundry/Slither
- `binary-analysis/knowledge-base/forensics-methodology.md` — 网络/内存/磁盘/日志取证+Vol3/tshark

**修改知识库（3）**:
- `crypto-analysis/knowledge-base/crypto-methodology.md` — §1 类型识别加 blockchain 行 + §5 加 FHE 子节
- `binary-analysis/knowledge-base/deobfuscation-selection.md` — §1表加SMC行 + §6 SMC章节(原§6→§7)
- `web-analysis/knowledge-base/web-vulnerabilities.md` — §9 PHP特有漏洞(type juggling/反序列化/伪协议/disable_functions)

## 审计记录
- 每批次均走 Phase 2(需求)→3(审计)→5(实施)→6(审计)
- 累计修复问题: gap定义3个(框图宽度/sourcing-guide关联/端到端验收) + FHE 1个(invariant_noise_budget标注) + blockchain 1个(孤儿目录归属→crypto) + nSMC/PHP 各准确性自查通过

## 遗留事项（未做，有理由）
1. **BabyVM (VMware 虚拟机逃逸)** — 不建议做：0 solve、极小众、受众极窄
2. **sourcing-guide §3 联动加强** — 批次1 §5 已声明，留待后续独立小改（本次聚焦 gap 定义本身）
3. **FHE galois 完整解法 / DeFi 深度(治理快照/AMM/sandwich)** — FHE writeup 公开稀缺(galois 写原理不编造)；DeFi 列速查遇题深入
