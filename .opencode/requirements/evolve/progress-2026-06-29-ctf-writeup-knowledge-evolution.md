# 进度：基于 CTF writeup 的知识体系进化

需求文档: 2026-06-29-ctf-writeup-knowledge-evolution.md

## 当前阶段: 阶段一完成（第一批方向），准备进入阶段二

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
- ptr-yudai DiceCTF 2026 cornelslop（内核: MADV_DONTNEED+cross-cache+PTE overlap）— 需查找博客 URL
- ctf-wiki kernel pwn — 需下载
- House of Apple/Cat（roderickchan）— 需查找正确 URL

## 待办

### 阶段一补充（不阻塞阶段二）

### 阶段二：沉淀知识（每个文件独立走 evolve 流程）
第一批（用户确认，依赖阶段一完成）:
- [x] **A1**. `pwn-methodology.md`（标准流程+mitigations速查+卡点突破+工具链）— 155行，审计通过
- [x] **A2**. `pwn-heap-methodology.md`（落点决策树+House模板+safe-linking）— 170行，审计通过
- [x] **A3**. `pwn-kernel-methodology.md`（结构体泄漏+msg_msg+Dirty PageTable+竞态扩大）— 174行，审计通过
- [x] **B1**. `deobfuscation-selection.md`（OLLVM/MBA/VM识别+工具选型D-810/deflat/QSynth）— 155行，审计通过
- [ ] **B2**. 更新 `idapython-conventions.md`（IDA 9.0 API 变化）— 完成，新增 IDA 9.0 迁移章节
- [x] **C1**. `client-side-attacks.md`（bfcache+CSS trigram exfil+xsleak+iframe reparenting）— 146行，审计通过
- [x] **C2**. `race-conditions.md`（单包攻击+原型链污染gadget+解析器差异）— 107行，审计通过

第二批（视精力）:
- [ ] **D**. 增强 `crypto-methodology.md`（参数→攻击速查 + Coppersmith模板整合）
- [ ] **E**. `agent-attacks.md`（MCP/Tool poisoning/Computer Use）

### 阶段三：同步更新 agent prompt
- [x] binary-analysis.md 加索引（+4行：pwn-methodology/heap/kernel + deobfuscation-selection）— 324行
- [x] web-analysis.md 加索引（+2行：client-side-attacks + race-conditions）— 318行

## 决策记录
1. **2026-06-29 用户纠偏**: 不要直接从 agent 摘要沉淀，先下载 writeup 原文建源文档库，再基于原文沉淀。二手摘要会丢细节、不可回溯。
2. **2026-06-29 用户确认方向**: 第一批做 A(Pwn)+B(逆向反混淆)+C(Web客户端)。
3. **2026-06-29 下载验证**: webfetch 可拿 GitHub源码/博客全文/官方文档，质量足够支撑沉淀。
4. **2026-06-29 源文档库选址**: `docs/资料/writeup-sources/`（与调研报告同在 docs/资料/ 下）。
5. **2026-06-29 roderickchan ≠ roderickwang**: Pwn 调研报告笔误。roderickwang(GitHub) 是前端开发者；House of Apple 作者应为 roderickchan，需找正确 URL。
6. **2026-06-29 BeautifulSoup 正文提取**: markdownify 的 strip 参数不足以清理 Mandiant 等含大量内联CSS/JS的页面，需先用 BeautifulSoup 提取 `<article>`/`<main>` 正文再转换。

## 教训记录
（执行过程中积累，持续更新）
