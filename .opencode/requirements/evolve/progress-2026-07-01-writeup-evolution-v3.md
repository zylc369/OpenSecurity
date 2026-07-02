# 进度：writeup 知识进化 v3

需求文档: 2026-07-01-writeup-evolution-v3.md

## 第一组完成 ✅（步骤 1-8: 修复已有问题）

| 步骤 | 文件 | 改动 | 状态 |
|------|------|------|------|
| 1 | pwn-methodology.md | safe-linking key 修正 + ASLR 5.18+ 弱化 | ✅ |
| 2 | pwn-heap-methodology.md | 源码引用去元信息 + botcake 前提修正 + large_bin 步骤顺序修正 + "比最小还小"绕过路径 | ✅ |
| 3 | client-side-attacks.md | 删重复段 + 修断链引用 + trigram 双字符集 + sanitizer 修复状态 | ✅ |
| 4 | cache-poisoning.md | §4.2 改引用 §6 | ✅ |
| 5 | web-vulnerabilities.md | §1.6→§5.3 归类修正 + §8.2 payload 改引用 | ✅ |
| 6 | crypto-methodology.md | node split/nonsplit 修正 + HVZKP 精确等式 | ✅ |
| 7 | ecc-attacks.md | node 映射补 split/nonsplit + 阶 p±1 | ✅ |
| 8 | deobfuscation-selection.md | 删虚假引用 + GoReSym -v/版本表 + D-810 Z3 措辞 | ✅ |

## 第二组完成 ✅（步骤 9-13: 沉淀推荐做 P1-P5）

| 步骤 | 文件 | 改动 | 状态 |
|------|------|------|------|
| 9 | pwn-kernel-methodology.md | MADV_DONTNEED 机制 + cross-cache 数学 + PTE overlap 完整步骤 | ✅ |
| 10 | pwn-heap-methodology.md | Tangerine PAGE_MASK + stashing calloc + FSROP payload 模板 | ✅ |
| 11 | ecc-attacks.md | §6 重写: cusp/node 完整映射 + 一般 Weierstrass + operation=other + 复合环分解 | ✅ |
| 12 | idapython-conventions.md | IDA 9.0 迁移速查 + Microcode API 速查 | ✅ |
| 13 | client-side-attacks.md | XSS 无括号完整 payload + @container 绕 sanitizer + timing 扩展 + connection pool 价值 | ✅ |

## 第三组完成 ✅（步骤 14-20: 沉淀可选做 P6-P15）

| 步骤 | 文件 | 改动 | 状态 |
|------|------|------|------|
| 14 | arm64-pwn-methodology.md | PAC Key 提取第三法 | ✅ |
| 15 | crypto-methodology.md | Frozen Heart + SIDH 工程化 + broadcast 退路 | ✅ |
| 16 | race-conditions.md | partial-construction + leaky-bucket + fetch gadget | ✅ |
| 17 | pwn-heap-methodology.md | 现代 double free 4 路径 | ✅ |
| 18 | pwn-methodology.md | off-by-null 栈迁移 | ✅ |
| 19 | symmetric-and-hash.md | LCG 后门注入 | ✅ |
| 20 | ecc-attacks.md | PH 部分低位恢复 | ✅ |

## 第四组完成 ✅（步骤 21: 源文档修复）

| 步骤 | 文件 | 改动 | 状态 |
|------|------|------|------|
| 21 | mandiant-golang-internals.md | 从新 URL（Google Cloud TI blog）重新下载 + 修正 download_sources.py | ✅ |

## 全部步骤完成 ✅ — 进入 Phase 6 审计
