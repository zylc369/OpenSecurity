# 进度：基于 CTF writeup 的知识体系进化

需求文档: 2026-06-29-ctf-writeup-knowledge-evolution.md

## 当前阶段: 第三批完成 ✅（持续进化中）

## 已完成

### Phase 0-1: 调研与方案讨论 ✅
- [x] 盘点现有知识库覆盖范围（binary/mobile/web/ai/crypto 各方向已有内容）
- [x] 5 方向 writeup 调研完成（报告位置见需求文档 §2）
- [x] gap 分析完成（Pwn零覆盖 / 逆向缺反混淆 / Web缺客户端攻击 / ...）
- [x] 候选方案制定（A/B/C/D/E/F 六项）
- [x] 用户确认第一批: A(Pwn) + B(逆向反混淆) + C(Web客户端)
- [x] 方法论对齐（用户纠偏: 先建源文档库再沉淀，不直接从摘要提炼）
- [x] 下载可行性验证（GitHub源码/博客/官方文档 均可拿全文，质量足够）

## 进行中
（无）

## 阶段一完成记录（2026-06-29）

### 步骤1-4: 建立源文档库 ✅
- [x] 步骤1: 整理下载清单 → `docs/资料/writeup-sources/download-checklist.md`
- [x] 步骤2: 下载 Pwn 方向（10 个 how2heap PoC）→ `pwn/` + `_index.md`
- [x] 步骤3: 下载逆向方向（6 个文档）→ `reversing/` + `_index.md`
- [x] 步骤4: 下载 Web 方向（11 个博客/文档）→ `web/` + `_index.md`
- 总计 27 个源文档，3 个方向索引

### 下载工具
- 脚本: `docs/资料/writeup-sources/_download_sources.py`（curl + BeautifulSoup + markdownify）
- how2heap PoC: curl 直接下载 GitHub raw（纯文本无杂讯）
- 博客/文档: curl 下载 HTML → BeautifulSoup 清理 → markdownify 转换

### 发现的问题（已修复/已记录）
1. **mandiant-golang-internals.md 1.8MB 杂讯** → 修复：加 BeautifulSoup 正文提取，降至 28.8K ✅
2. **hexraysdeob-readme.md 仅 81 chars** → 仓库 README 本身只有一句话，内容真实但少（核心在源码注释）
3. **roderickwang ≠ roderickchan** → Pwn 报告笔误，roderickwang 是前端开发者，House of Apple 作者应是 roderickchan

### 待补充的源文档（标注待查找）
- ptr-yudai DiceCTF 2026 cornelslop（内核: MADV_DONTNEED+cross-cache+PTE overlap）— 博客在线(ptr-yudai.hatenablog.com)但具体文章URL待定位
- ctf-wiki kernel pwn — ctf-wiki.org 改版，所有路径 404，需确认新 URL
- House of Apple/Cat（roderickchan）— GitHub(roderickchan) 有 pwncli/kernel_pwn_tool 等仓库但无 House of Apple 文章，文章可能在 CSDN/掘金

## 待办

### 阶段一补充（不阻塞阶段二）

### 阶段二：沉淀知识（每个文件独立走 evolve 流程）
第一批（用户确认，依赖阶段一完成）:
- [x] **A1**. `pwn-methodology.md`（标准流程+mitigations速查+卡点突破+工具链）— 155行，审计通过
- [x] **A2**. `pwn-heap-methodology.md`（落点决策树+House模板+safe-linking）— 170行，审计通过
- [x] **A3**. `pwn-kernel-methodology.md`（结构体泄漏+msg_msg+Dirty PageTable+竞态扩大）— 174行，审计通过
- [x] **B1**. `deobfuscation-selection.md`（OLLVM/MBA/VM识别+工具选型D-810/deflat/QSynth）— 155行，审计通过
- [~] **B2**. 更新 `idapython-conventions.md` — **已撤销**（用户判定没必要，一直在用 IDA 9.X，不需要"从旧迁移"指南）
- [x] **C1**. `client-side-attacks.md`（bfcache+CSS trigram exfil+xsleak+iframe reparenting）— 146行，审计通过
- [x] **C2**. `race-conditions.md`（单包攻击+原型链污染gadget+解析器差异）— 107行，审计通过

第二批（视精力）:
- [x] **D**. 增强 `crypto-methodology.md`（参数→攻击速查表 + Coppersmith变种速查）— +82行，审计通过
- [x] **E**. `agent-attacks.md`（MCP/Tool poisoning/RAG/Computer Use + 自动化越狱工具对比）— 151行 + ai-security prompt索引

### 阶段三：同步更新 agent prompt
- [x] binary-analysis.md 加索引（+4行：pwn-methodology/heap/kernel + deobfuscation-selection）— 324行
- [x] web-analysis.md 加索引（+2行：client-side-attacks + race-conditions）— 318行
- [x] ai-security-analysis.md 加索引（+1行：agent-attacks）— 330行

### 最终审计 ✅
- Agent prompt 行数全部 < 450（324/318/330）
- 交叉引用一致性：16 个引用文件全部存在
- Agent prompt 索引全部添加（7 条新索引）

## 最终统计
- 新增知识库文件：8 个（1058 行）
- 增强现有文件：2 个（crypto-methodology +82行 / idapython-conventions +41行）
- Agent prompt 索引：3 个 agent（+7 行索引）
- 源文档库：27 个源文档 + 3 个索引 + 下载脚本
- 调研报告：5 个方向（Pwn 459行 + 逆向 + Web + 密码学 501行 + AI安全）

## 决策记录
1. **2026-06-29 用户纠偏**: 不要直接从 agent 摘要沉淀，先下载 writeup 原文建源文档库，再基于原文沉淀。二手摘要会丢细节、不可回溯。
2. **2026-06-29 用户确认方向**: 第一批做 A(Pwn)+B(逆向反混淆)+C(Web客户端)。
3. **2026-06-29 下载验证**: webfetch 可拿 GitHub源码/博客全文/官方文档，质量足够支撑沉淀。
4. **2026-06-29 源文档库选址**: `docs/资料/writeup-sources/`（与调研报告同在 docs/资料/ 下）。
5. **2026-06-29 roderickchan ≠ roderickwang**: Pwn 调研报告笔误。roderickwang(GitHub) 是前端开发者；House of Apple 作者应为 roderickchan，需找正确 URL。
6. **2026-06-29 BeautifulSoup 正文提取**: markdownify 的 strip 参数不足以清理 Mandiant 等含大量内联CSS/JS的页面，需先用 BeautifulSoup 提取 `<article>`/`<main>` 正文再转换。

## 教训记录
（执行过程中积累，持续更新）

## 第三批工作记录（2026-06-30，用户要求"继续抓取新知识自动执行"）

### 新调研（3 方向）
- [x] ZKP/FHE/PQC 调研 → `docs/资料/crypto-zkp-fhe-pqc-research/调研报告.md`
- [x] 移动端逆向新趋势调研 → `docs/资料/mobile-research-2023-2026/调研报告.md`
- [x] Pwn 实战新技术补充调研 → `.research/pwn-ctf-2023-2026/实战新技术补充-2024-2026.md`

### 源文档补充
- [x] ptr-yudai DiceCTF 2026 cornelslop writeup → `docs/资料/writeup-sources/pwn/2026-dicectf-cornelslop-ptr-yudai.md`（24KB，含350行exploit）
- [x] pwn/_index.md 更新（加入 ptr-yudai）
- [~] ctf-wiki kernel pwn — 网站改版+路径404，多路径尝试失败，待查找新 URL
- [~] House of Apple (roderickchan) — 博客在 RoderickChan.github.io 但具体文章 URL 未找到

### 新增知识库文件（2 个）
- [x] `arm64-pwn-methodology.md`（105行）— ARM64 调用约定/ROP/ret2csu/PAC/BTI/MTE，审计通过
- [x] `cross-platform-frameworks.md`（mobile, ~100行）— Flutter/RN/Hermes 逆向 + blutter/reFlutter/hermes-dec + frida-strace 反 Frida，审计通过

### 增强现有文件（3 个）
- [x] `pwn-heap-methodology.md` — +tcache_metadata_hijacking 详细步骤 + 2.42+ 落点决策树
- [x] `pwn-methodology.md` — +seccomp ORW 模板（shellcode/ROP）+ 栈迁移三法 + 格式化字符串偏移
- [x] `crypto-methodology.md` — 类型识别表 +ZKP/FHE/PQC 识别

### Agent prompt 索引（2 个）
- [x] binary-analysis.md +arm64-pwn-methodology 索引 → 325行
- [x] mobile-analysis.md +cross-platform-frameworks 索引 → 243行

### 审计 ✅
- 代码块全闭合；行数 < 450；交叉引用全存在；索引行验证通过

## 最终全局统计（截至 2026-06-30）

### 知识库文件
- **新增**: 9 个文件 / 1333 行
  - Pwn(4): pwn-methodology(177) + pwn-heap(201) + pwn-kernel(174) + arm64-pwn(103)
  - 逆向(1): deobfuscation-selection(155)
  - Web(2): client-side-attacks(146) + race-conditions(107)
  - AI安全(1): agent-attacks(151)
  - 移动端(1): cross-platform-frameworks(119)
- **增强**: 3 个现有文件（pwn-heap +pwn-methodology +crypto-methodology）

### Agent prompt 索引
- binary-analysis.md: 325行（+5行: pwn×3 + deobfuscation + arm64）
- web-analysis.md: 318行（+2行: client-side + race）
- ai-security-analysis.md: 330行（+1行: agent-attacks）
- mobile-analysis.md: 243行（+1行: cross-platform）

### 源文档库: 37 个文件
- pwn(12): 10 how2heap PoC + ptr-yudai cornelslop + _index
- web(12): 11 博客/文档 + _index
- reversing(7): 6 文档 + _index
- crypto(4): 3 ZKP/SIDH 参考文档 + _index
- 工具(2): _download_sources.py + download-checklist.md

### 调研报告: 8 份
- 原始5方向: Pwn(459行) + 逆向 + Web + 密码学(501行) + AI安全
- 补充3方向: ZKP/FHE/PQC + 移动端 + Pwn实战

### 覆盖的 gap（对照用户痛点"做题慢做不出"）
- ✅ Pwn 从零到 4 文件完整覆盖（标准流程+堆+内核+ARM64）
- ✅ 逆向反混淆选型（OLLVM/MBA/VM → D-810/deflat/QSynth）
- ✅ Web 客户端攻击（bfcache/CSS exfil/xsleak/iframe）+ 竞态（单包攻击/PP）
- ✅ AI安全 Agent 攻击面（MCP/Tool/RAG/Computer Use）+ 自动化越狱
- ✅ 密码学参数→攻击速查 + Coppersmith + ZKP/FHE/PQC 类型识别
- ✅ 移动端跨平台框架（Flutter/RN/Hermes）+ frida-strace 反 Frida
