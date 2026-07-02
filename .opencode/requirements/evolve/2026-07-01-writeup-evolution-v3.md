# 需求：writeup 知识进化 v3 — 查缺补漏 + 修复已有问题

> 创建: 2026-07-01
> 状态: Phase 2
> 来源: 用户要求"再次根据 writeup-sources 文章进行进化，查缺补漏；已有内容有问题就修复"
> 前置: 2026-06-29-ctf-writeup-knowledge-evolution.md（第一二轮沉淀）、2026-06-30-writeup-knowledge-evolution-v2.md（进化能力）

## §1 背景与目标

**痛点**: 前两轮沉淀了 9 个知识库文件，但经 4 方向源文档逐篇对比（pwn/web/crypto/reversing 共 54 个源文档 vs 21 个知识库文件），发现：
1. 已沉淀内容有 **25 处问题**（技术错误 4 处 + 结构问题 5 处 + writing-guide 违反 16 处）
2. 有 **17 个高/中价值技术点**未沉淀（其中 6 个是"卡住才找到"的盲点）
3. 1 个源文档抓取失败（mandiant-golang-internals.md 是营销页）

**目标**: 修复全部已有问题 + 沉淀全部推荐做(P1-P5)和可选做(P6-P15)技术点。

## §2 技术方案

### 改动性质
- **纯知识库内容修改**，不新增知识库文件，不新增脚本
- **不改 agent prompt**（所有增强都在已有索引指向的文件内，无需新索引行）
- **无架构变更**，无依赖方向问题
- 风险等级：低（文档修改，语法检查靠人工自包含性验证）

### 文件分工（14 个文件，按方向）

| 方向 | 文件 | 改动类型 |
|------|------|---------|
| Pwn | pwn-methodology.md | 修复 + 补充 |
| Pwn | pwn-heap-methodology.md | 修复 + 补充（量最大） |
| Pwn | pwn-kernel-methodology.md | 补充 |
| Pwn | arm64-pwn-methodology.md | 补充 |
| Web | client-side-attacks.md | 修复 + 补充（量最大） |
| Web | race-conditions.md | 补充 |
| Web | cache-poisoning.md | 修复（删重复） |
| Web | web-vulnerabilities.md | 修复 |
| Crypto | crypto-methodology.md | 修复 + 补充 |
| Crypto | ecc-attacks.md | 修复 + 补充（量最大） |
| Crypto | symmetric-and-hash.md | 补充 |
| Reversing | idapython-conventions.md | 补充（量最大） |
| Reversing | deobfuscation-selection.md | 修复 + 补充 |
| 源文档 | docs/资料/writeup-sources/reversing/mandiant-golang-internals.md | 重新抓取 |

## §3 实现规范

### §3.1 实施步骤拆分

> 每步改动 ≤ 200 行（不含注释空行）。验证点 = 人工读一遍确认自包含 + 写作规范四项检查。

---

#### 第一组：修复已有问题（低风险，优先做）

**步骤 1. pwn-methodology.md 修复**
- 文件: `$SHARED_DIR/knowledge-base/pwn-methodology.md`
- 改动: ① 行65/125 删除"通常为 0"错误描述（safe-linking key 是堆页号绝非 0）② §2 ASLR 行补 Linux 5.18+ 弱化特性
- 预估: ~8 行
- 验证点: safe-linking 描述无"通常为0"；ASLR 行有 5.18+ 注记

**步骤 2. pwn-heap-methodology.md 修复**
- 文件: `$SHARED_DIR/knowledge-base/pwn-heap-methodology.md`
- 改动: ① 行128/150 删源码引用无用元信息（"317行""含详细glibc代码行引用"）② 行52 house_of_botcake 补"malloc 腾位"中间步 ③ 行60-66 large_bin_attack 步骤顺序修正（先 free(p2) 再改 bk_nextsize）
- 预估: ~15 行
- 验证点: 源码引用只剩文件名；botcake 有 6 步；large_bin 顺序为 free→改→插入

**步骤 3. client-side-attacks.md 修复**
- 文件: `$AGENT_DIR/knowledge-base/client-side-attacks.md`（web-analysis）
- 改动: ① 行75-80 删重复的"无 @import/url 触发器" ② 行146 修跨文件引用（删"解析器差异详解"，本就在 §6）③ 行55 trigram 补 alphanum 36³ ④ 行64-68 sanitizer 补"Chromium 已修复"注记
- 预估: ~10 行（主要是删）
- 验证点: 无重复段；§8 引用不指向虚空；trigram 有双字符集

**步骤 4. cache-poisoning.md 修复**
- 文件: `$AGENT_DIR/knowledge-base/cache-poisoning.md`（web-analysis）
- 改动: §4.2 改为一行引用 §6（删缩略版重复）
- 预估: ~3 行
- 验证点: §4.2 不再展开，只引用

**步骤 5. web-vulnerabilities.md 修复**
- 文件: `$AGENT_DIR/knowledge-base/web-vulnerabilities.md`（web-analysis）
- 改动: ① §1.6 归类修正（移出 §5，改标题去编号或归合理章节）② §8.2 payload 重复改引用 §1.1.1
- 预估: ~10 行
- 验证点: 无编号错位；payload 不重复

**步骤 6. crypto-methodology.md 修复**
- 文件: `$AGENT_DIR/knowledge-base/crypto-methodology.md`（crypto-analysis）
- 改动: ① L105 node 改为"split(阶p-1)/nonsplit(阶p+1)" ② L145 HVZKP "≈" 改精确等式 "="
- 预估: ~4 行
- 验证点: node 有 split/nonsplit；HVZKP 无 ≈

**步骤 7. ecc-attacks.md 修复**
- 文件: `$AGENT_DIR/knowledge-base/ecc-attacks.md`（crypto-analysis）
- 改动: §6（L110-114）node 映射补 split/nonsplit + 阶 p±1（与步骤6一致）
- 预估: ~6 行
- 验证点: node 映射有双分支

**步骤 8. deobfuscation-selection.md 修复**
- 文件: `$SHARED_DIR/knowledge-base/deobfuscation-selection.md`
- 改动: ① L155 删虚假引用"含 IDA 9.0 API 变化"（改为不提，或待步骤12补完后保留）② L129 GoReSym 补 `-v` 参数 ③ L35 D-810 Z3 改"推荐安装，部分规则需要"
- 预估: ~6 行
- 验证点: 无虚假引用；GoReSym 有 -v；Z3 措辞为推荐

---

#### 第二组：沉淀推荐做 P1-P5

**步骤 9. pwn-kernel-methodology.md 补充（P1 内核三件套）**
- 文件: `$SHARED_DIR/knowledge-base/pwn-kernel-methodology.md`
- 改动: ① §5 MADV_DONTNEED 补机制段（zap_page_range→fault风暴→mmap_lock争用）② §6 cross-cache 补阈值数学（cpu_partial/objs_per_slab + 为什么单CPU不够）③ §3 落点C 补 PTE overlap 完整步骤（双类PTE喷射→D bit回写→shebang）
- 预估: ~45 行
- 验证点: MADV_DONTNEED 有机制解释；cross-cache 有数学；PTE overlap 有完整步骤
- 源文档依据: 2026-dicectf-cornelslop-ptr-yudai.md

**步骤 10. pwn-heap-methodology.md 补充（P2 堆约束）**
- 文件: `$SHARED_DIR/knowledge-base/pwn-heap-methodology.md`
- 改动: ① §5 House of Tangerine 补 PAGE_MASK/fencepost 约束 ② §3 速查表 tcache_stashing_unlink 补"必须 calloc" ③ §3 新增 large_bin_attack"比最小还小"绕过路径 ④ §4 落点A 补 FSROP stderr 完整 payload 模板
- 预估: ~50 行
- 验证点: Tangerine 有 PAGE_MASK 公式；stashing 有 calloc 前提；FSROP 有可执行 payload
- 源文档依据: how2heap-house_of_tangerine.c, how2heap-tcache_stashing_unlink_attack.c, how2heap-large_bin_attack.c, ptr-yudai 多篇

**步骤 11. ecc-attacks.md 补充（P3 奇异曲线完整映射）**
- 文件: `$AGENT_DIR/knowledge-base/ecc-attacks.md`（crypto-analysis）
- 改动: §6 扩写: ① cusp 显式映射 φ=x/y + 点平移步骤 ② node split/nonsplit 完整映射 ③ 一般 Weierstrass 判别式(b₂/b₄/b₆/b₈) ④ 自定义群 discrete_log(operation="other") ⑤ 新增"复合环 Z_N 上 EC 报错分解"小节
- 预估: ~70 行
- 验证点: cusp 有 φ=x/y 公式；node 有双分支+阶；有一般 Weierstrass 公式；有 operation="other"
- 源文档依据: pcw109550-2023-TSG-Delta-Force-solve.sage

**步骤 12. idapython-conventions.md 补充（P4 IDA 9.0 + Microcode）**
- 文件: `$SHARED_DIR/knowledge-base/idapython-conventions.md`
- 改动: ① 新增"IDA 9.0 迁移"节（ida_struct/ida_enum 移除→ida_typeinf、IDA32取消、idalib、find_binary，精选6项）② 新增"Hex-Rays Microcode API 速查"节（四数据结构、maturity、optinsn_t/optblock_t 注册、防崩溃策略）
- 预估: ~80 行
- 验证点: 有 ida_struct→ida_typeinf；有 maturity 阶段；有"原地改对象"防崩策略
- 源文档依据: ida90-release-notes.md, hex-rays-microcode-api.md

**步骤 13. client-side-attacks.md 补充（P5 Web payload 回填）**
- 文件: `$AGENT_DIR/knowledge-base/client-side-attacks.md`（web-analysis）
- 改动: ① §6"XSS 无括号"扩写为完整 payload（Chrome/Firefox 差异，5+条 payload）② §3 补 @container/@scope 绕 sanitizer + :host-context() ③ §4 扩展 timing 侧信道（指数膨胀 phrase 链 + iframe.src=iframe.src reload 计时）④ §6 connection pool 补"style-src 'self' 时仍能递归 leak"价值 + buffer CSS
- 预估: ~60 行
- 验证点: XSS 有 5+ 具体 payload；有 @container payload；timing 有 phrase 链示例
- 源文档依据: 2025-xss-no-paren-huli.md, 2024-googlectf-huli.md, 2025-corctf-challenge-dev-2.md, 2024-dicectf-huli.md

---

#### 第三组：沉淀可选做 P6-P15

**步骤 14. arm64-pwn-methodology.md 补充（P6 PAC Key 提取）**
- 文件: `$SHARED_DIR/knowledge-base/arm64-pwn-methodology.md`
- 改动: §4 PAC 绕过新增第三法"Key 提取"（context switch 存内核→扫描 direct map→pauth_computepac_architected 伪造）
- 预估: ~25 行
- 验证点: PAC 绕过有 3 种方法
- 源文档依据: 2025-ptr-yudai-apr.md

**步骤 15. crypto-methodology.md 补充（P7 SIDH + P8 Frozen Heart + P14 broadcast）**
- 文件: `$AGENT_DIR/knowledge-base/crypto-methodology.md`（crypto-analysis）
- 改动: ① §5 ZKP 速查补 Frozen Heart 行（challenge 操纵为常量）② §5 SIDH 行扩写工程化要点（two_i 提取、j_invariant 恢复、性能 patch）③ §6 Coppersmith 表补 broadcast+Coppersmith 组合行
- 预估: ~35 行
- 验证点: ZKP 速查有 Frozen Heart；SIDH 有 two_i；Coppersmith 有 broadcast 退路
- 源文档依据: castryck-decru-sidh-readme.md, pcw109550-2022-CODEGATE-Final-README.md, pcw109550-2023-Dice-BBBB-solve.sage

**步骤 16. race-conditions.md 补充（P9 partial-construction + leaky-bucket）**
- 文件: `$AGENT_DIR/knowledge-base/race-conditions.md`（web-analysis）
- 改动: ① §1 适用场景补 partial-construction 类 ② §1 方法论补 leaky-bucket 延迟对齐 ③ §2 gadgets 补通用 fetch() headers PP
- 预估: ~20 行
- 验证点: 有 partial-construction；有 leaky-bucket
- 源文档依据: portswigger-single-packet-attack.md, portswigger-prototype-pollution.md

**步骤 17. pwn-heap-methodology.md 补充（P10 double free 4 路径）**
- 文件: `$SHARED_DIR/knowledge-base/pwn-heap-methodology.md`
- 改动: §1 漏洞升级表 DF 行补"现代 glibc（bcdaad21 后）4 条绕过路径"
- 预估: ~15 行
- 验证点: DF 行有 4 路径
- 源文档依据: 2025-ptr-yudai-mar.md

**步骤 18. pwn-methodology.md 补充（P11 off-by-null + P12 已在步骤1）**
- 文件: `$SHARED_DIR/knowledge-base/pwn-methodology.md`
- 改动: §4 卡点表补"off-by-null + leave;ret 栈迁移"行
- 预估: ~5 行
- 验证点: 卡点表有 off-by-null 行
- 源文档依据: 2024-ptr-yudai-nov.md

**步骤 19. symmetric-and-hash.md 补充（P13 LCG 后门）**
- 文件: `$AGENT_DIR/knowledge-base/symmetric-and-hash.md`（crypto-analysis）
- 改动: §6 LCG 补"反向：参数注入造循环"（选 a 为 x^k-1 单位根）
- 预估: ~15 行
- 验证点: §6 有后门注入
- 源文档依据: pcw109550-2023-Dice-BBBB-solve.sage

**步骤 20. ecc-attacks.md 补充（P15 PH 部分恢复）**
- 文件: `$AGENT_DIR/knowledge-base/ecc-attacks.md`（crypto-analysis）
- 改动: §4 Pohlig-Hellman 补"order=q·2^k 时部分低位恢复"
- 预估: ~15 行
- 验证点: §4 有部分恢复
- 源文档依据: pcw109550-2022-angstromCTF-logloglog-solve.sage

---

#### 第四组：源文档修复

**步骤 21. mandiant-golang-internals.md 重新抓取**
- 文件: `docs/资料/writeup-sources/reversing/mandiant-golang-internals.md`
- 改动: 用 download_sources.py --url 重新抓取；若 URL 失效则尝试 web.archive.org 归档；若仍失败则标注源损坏，reversing/_index.md 更新说明
- 预估: 0 行代码（抓取操作）
- 验证点: 文件含 pclntab 技术内容（非营销页）；或已标注损坏

---

## §4 验收标准

### 功能验收
- [ ] 25 处已有问题全部修复（步骤 1-8）
- [ ] P1-P5 全部沉淀（步骤 9-13）
- [ ] P6-P15 全部沉淀（步骤 14-20）
- [ ] 源文档 mandiant 修复或标注（步骤 21）

### 回归验收
- [ ] 所有修改文件通过写作规范四项检查（准确性/完整性/一致性/可操作性）
- [ ] 无新增 docs/ 引用（规则 10）
- [ ] 无写赛事名/作者名（writing-guide）
- [ ] 无源文档路径引用（writing-guide）

### 架构验收
- [ ] 知识库文件位置不变（都在原 $SHARED_DIR 或 $AGENT_DIR）
- [ ] 无 agent prompt 改动（不触发瘦身检查）
- [ ] 无新增文件（除源文档修复）

## §5 与现有需求文档的关系

- 继承 2026-06-29 的源文档库和沉淀方法论
- 本需求是"第三轮查缺补漏"，聚焦修复 + 补全，不再建新基础设施
