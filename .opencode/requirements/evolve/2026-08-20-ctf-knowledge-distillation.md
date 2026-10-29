# 需求：外部 CTF 知识库全量提炼沉淀（记忆库 + 知识库 + 工具索引）

日期: 2026-08-20
状态: 已确认（用户三轮拍板，规划见会话记录）

## §1 背景与目标

**来源**: 用户购买的外部 CTF 知识库 `/Users/aserlili/Downloads/ctf教程`（112GB / 24.5 万文件），要求全量提炼通用知识进自有体系。用户四项硬要求：① 务必不遗漏（"遗漏就等于损失"）；② 不提取错；③ 对外部知识的正确性要有自己的判断；④ 提炼时去 CTF 化（不写 CTF/题目名等泛化性差的关键字），天然 CTF-only 知识除外。

**资产结构**（勘察实证）:

| 源 | 规模 | 性质 |
|---|---|---|
| ctf-skills-temp | 153 skill（SKILL.md 43,262 行 + references 587 MD） | Anthropic skills 格式，AI-native |
| CTF本地知识库 | 91 MD + 469 HTML（448 无 MD 配对）+ 13 PDF + 3.7GB 工具资产 | 深度长文 + 网页存档 |
| CTF个人笔记 | 41 MD（方法论 + 靶场复现） | 培训笔记 |
| 值得看的资料 | 24 PDF + 16 txt | 课件 |
| 本地知识库/WP汇总 | 82 文件 | writeup（也要提炼，剔除环境特定细节） |
| CtfTools2025 | 108GB / 22.8 万文件 | 工具资产（只做索引，不逐文件提炼） |

**目标产物**（三层）:
1. 记忆库条目（knowledge MCP store）：预计 800~1500 条，带来源与置信标注
2. 知识库 MD（knowledge-base/）：蒸馏知识按领域归堆成结构化文档
3. 工具依赖索引（单独 MD）：工具名 | 用途 | 被哪些知识引用 | 本地资产路径

## §2 技术方案

### 2.1 写入架构（2026-08-20 变更：委派 → 直写）

原方案: evolve 被排除 MCP 写入权限，须 task 委派领域 agent 透传 store。
变更: 用户给 evolve 开通 events/knowledge 两个 MCP 权限并重启，evolve 可直接调用 `knowledge_store_knowledge`（实测: 试点条目 id:1027 入库落盘成功）。

- **evolve（本 agent）**: 读源、提炼、判定、直接 store、写知识库 MD、维护 progress.md
- 委派映射仅保留给知识库 MD 落位参考（web→web-analysis/knowledge-base/ 等领域目录归属）
- 注意: plugin 的自动记录链（tool.execute.after → fireAndForgetMemory）是否仍按 constants.ts 白名单拦截 evolve，与 MCP 主动调用互不影响；本任务只需主动调用

### 2.2 双源机械选源管线（md/html 校验）

已实证 21 对中存在 MD 空壳（zlib: 821 vs 31,657 字符）、HTML 残缺、低相似度对。管线规则（脚本放 workspace/ctf-distill/，适用全部含 md/html 混杂的源，不限于本地知识库）:

```
同目录同 stem 配对 → 去标签归一化 → 相似度
  ratio>0.75 且体量相当 → 读 MD
  一方空壳/残缺        → 读完整方
  ratio 低但体量相当    → LLM 抽查差异段裁决
  HTML 无配对          → 独立知识源处理
```

### 2.3 三级置信标注

| 级别 | 判定 | 处理 |
|---|---|---|
| verified | 与既有知识无冲突 | 直接入库 |
| version-sensitive | 含版本号/CVE/工具参数 | websearch 抽查核验；核不动则标注"版本敏感，用前自验"后入库 |
| disputed | 与既有知识冲突 | 先 websearch 自证裁定；裁不动的进存疑清单（终版汇总报用户，预期 <10 条） |

### 2.4 去 CTF 化规则

- question 从"未来谁在什么场景会怎么搜"出发（如"PHP 反序列化 POP 链构造方法"），禁写"CTF 中 XX 题怎么做"
- 保留 payload/命令/原理/版本号，剥除题目名/flag 格式/比赛语境
- 天然 CTF-only 知识（misc 脑洞套路、flag 搜索策略）保留 CTF 语境

### 2.5 知识库 MD 归堆规则

- 写入前 grep 现有 knowledge-base 同主题：已存在 → 扩展原文件；不新建平行文件
- 领域落位: web→web-analysis/knowledge-base/，crypto→crypto-analysis/，binary/pwn/reverse/misc/取证→binary-analysis/，mobile→mobile-analysis/（不确定归属默认 binary-analysis/，与委派映射一致）
- 三处同主题（skills/本地库/笔记）融合为单一文件，多来源标注

### 2.6 进度真相源

`~/bw-security-analysis/workspace/ctf-distill/progress.md`（独立于会话任务目录，跨会话续跑）：全量文件清单逐项打勾 + 产出条数 + 跳过留痕（非技术文档标注原因）。

## §3 实施规范

**改动范围**: 零代码改动（不碰 plugin/constants/MCP server）。新增产物: 记忆库条目（委派入库）、知识库 MD（若干）、工具索引 MD（1 份）、选源脚本（1 份）、progress.md。

**提炼规则**（每条入库前过检）:
- 只提原文明确陈述的技术事实；推理不加工；原文含糊标注含糊
- 一条一个知识点；保留限定语（Vary 教训: caveat 丢失 = 有损蒸馏误导）
- 每批自检: 抽样回读原文对照（防失真）+ search 同主题查重（防重复入库）+ 回搜验证可命中性

## §3.1 实施步骤拆分

1. 建工作区与全量清单
   - 文件: workspace/ctf-distill/progress.md、类型普查脚本临时产物
   - 验证点: 清单覆盖 5 目录全部文件（文件数对上勘察值）；扩展名普查表完整
2. 选源脚本落地
   - 文件: workspace/ctf-distill/pick_source.py（同目录配对 + 相似度 + 选源判定输出）
   - 验证点: 对已实证的 21 对跑出正确判定（zlib 选 html、SSTI 选 md）
3. 直写链路实测（已随架构变更完成）
   - 动作: 直接 store 1 条试点条目（缓存投毒 unkeyed header 探针清单，查重判定为 id:159 扩展后入库）
   - 验证点: ✅ id=1027 入库、sqlite 落盘 590 字节、knowledge 分区 100 条
4. 试点批: web skills 10 个
   - 验证点: 25-40 条入库可回搜；抽样 5 条回读原文无失真；进度清单打勾
5. 批量提炼（十批次，每批一个独立循环）
   ① skills·web(≈30) ② skills·crypto ③ skills·pwn/binary ④ skills·reverse ⑤ skills·misc/取证 ⑥ 本地知识库（91MD+448独立HTML+工具使用/常用脚本目录文档普查） ⑦ 个人笔记 41 ⑧ 全部 PDF（24+13）+16txt ⑨ WP汇总 82+靶场复现 ⑩ 工具资产: CtfTools2025 等目录级索引 + 全库按扩展名普查文档类文件（md/pdf/txt/doc/ppt 等，量小，纳入提炼）
   - 每批验证点: 清单全勾/跳过留痕；查重通过；存疑清单更新；蒸馏产物知识库 MD 当批归堆落位（grep 查重后扩展或新建）
6. 工具依赖索引 MD
   - 文件: $SHARED_DIR/knowledge-base/tool-dependency-index.md
   - 验证点: 覆盖提炼中引用的全部外部工具；每条含四字段
7. 收尾勾稽
   - 验证点: progress.md 全清单零未处理项；存疑清单终版；条数统计报告；记忆库回搜抽查 10 条命中
8. 提取质量审计（2026-08-24 追加，用户要求的复核）
   - 动作: 三维审计——完成度（源文件抽样复核零增量判定）/准确性（记忆库条目回读原文对照）/归类（文件落位+平行文件检查）
   - 验证点: 每批分层抽样≥2 个源文件重读对照; 记忆库每批抽 5-10 条回读原文无失真; grep 全库无同主题平行文件; 发现问题全部修复并留痕
9. 引用完整性审计（2026-08-24 追加，用户要求的可发现性保障）
   - 动作: 知识库文件引用链全覆盖检查——agent prompt 知识库索引 → 文件 → 互引; 记忆库条目归堆位置 ↔ 知识库文件双向核对
   - 验证点: 五领域 agent prompt 索引覆盖全部知识库文件（孤儿清单清零; 挂索引后 prompt 展开仍 <450 行）; 抽样双向引用核对通过; tool-dependency-index 覆盖抽查

（步骤 5 内部每批 ≤200 行"改动"约束天然满足——产物是条目与 MD，非代码；单批超载则拆子批记录到 progress.md）

## §4 验收标准

**功能验收**: ① 五目录全量文件处理完毕（完成/跳过留痕，零悬空）；② 记忆库新增条目全部可回搜命中；③ 知识库 MD 无重复主题文件、领域落位正确；④ 工具索引四字段完整。
**回归验收**: ① 现有 95 条记忆库条目无污染（查重机制保障）；② 现有知识库文件只扩展不破坏；③ 零代码改动 → 无运行时回归面。
**架构验收**: ① 遵守知识双轨分离（evolve 不直接 store，全部走委派）；② 知识库/记忆库/工具索引三层各归其位；③ 依赖方向无违反。

## §5 与现有需求文档的关系

- 无功能重叠: 现有 4 份（控制台前端、依赖分层+OCR、MCP 收口、plugin 写入收口）均为基础设施改造，本需求是知识工程，不动它们改过的任何文件
- 相关联动: 复用 2026-08-16-deps-layering-and-local-ocr 落地的本地 OCR（扫描版 PDF 走 glm-ocr）；遵守 2026-08-17 两份收口后的写入路径约定
- progress 文档: 本需求的进度记录在 workspace/ctf-distill/progress.md（数据量大于常规 progress，不建 requirements/evolve/progress-*.md 双份）
