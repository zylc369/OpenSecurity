# 需求: 排名成绩类 OSINT 持久验证源知识库 + 推断性交付规范

## §1 背景与目标

**来源**: 2026-09-25 一次白名单制赛事的成绩溯源分析复盘。该任务中两个关键能力靠临场摸索获得: ①活动排行榜被平台删除后，成绩的持久验证源（证书 S3 直链、档案页证书栏入口）与平台 API 的 WAF 降级路径，耗费约 40 分钟和 5+ 条死路; ②目标值无法在线验证时，推断性交付格式（首选/备选+置信度+证据分级+剩余确证路径）是临场自创，无固化规范，质量靠运气。

**预期收益**:
- 同类任务（验证某账号/团队在任意带排行榜+证书平台上的历史成绩）直接命中硬证据源，省 30-60 分钟摸索
- 无法验证场景下的交付质量从"临场发挥"变为"规范保证"，用户不需要追问"该信哪个"

**知识中性化要求（铁律）**: 沉淀内容不得含赛事名、队名、题目标识、具体答案值、日期时间线——知识只回答"什么场景适用、怎么检查、怎么利用"。

## §2 技术方案

### 2.1 新建知识库文档（方案 1）

文件: `$OPENCODE_ROOT/web-analysis/knowledge-base/score-verification-osint.md`（新建，~120 行）

内容骨架:
```
# 排名与成绩类 OSINT 持久验证
> 适用场景（触发条件）
## 1. 验证源优先级（按持久性）
  ### 1.1 证书 = 记分板的固化（活动页易逝、证书长存）
     - 证书文件 S3 直链 URL 模式（通用格式，非特定平台专属）
     - 证书内容含官方排名/得分/完成数/日期
  ### 1.2 证书编号的三个入口
     - 当事人职业档案页证书栏 View Certificate 外链（含搜索引擎检索式）
     - 当事人帖子配图（证书截图 + OCR）
     - 平台内公开 profile 的证书区
     - 反面知识: 部分平台的活动类证书不进公开 profile 证书区（仅学习路径类证书显示），该入口可能为空——三个入口按命中率排序尝试
  ### 1.3 第三方成绩聚合/档案站镜像
## 2. 平台 API 访问
  ### 2.1 WAF 拦截与降级（curl 429 + Security Checkpoint → 真实浏览器指纹同 URL 访问）
  ### 2.2 公开端点发现（Playwright XHR 监听，resource_type=xhr/fetch 过滤）
     - 常见无需认证的公开端点族（scoreboard/public-profile/badges）
     - 活动型页面赛后删除的规律（API "not found"、衍生练习页锁定）
## 3. 双源矛盾裁决法
  - 触发条件: 两个当事人对同一数值各执一词（N vs N±1）
  - 规则一: 需求方声明"答案不在公开可检索单一来源"→ 搜索引擎可见值是被排除的捷径值
  - 规则二: 叙事含"冻结→刷新→位置变高"→ 取刷新后终态值
  - 规则三: 同分并列段常识 + 第三方名次锚点夹逼排除法
## 4. 辅助降级链
  - 本地 OCR 服务不可达 → tesseract CLI（命令模板）
```

### 2.2 web-methodology.md 补节（方案 2）

文件: `$OPENCODE_ROOT/web-analysis/knowledge-base/web-methodology.md`（修改）

在 `## 4a. 执行失败切换表` 之后、`## 5. 报告与文档` 之前插入 `## 4b. 无法在线验证时的推断性交付规范`（~35 行）:
- 适用条件: 目标值因平台关闭/白名单制/已删除无法提交验证
- 交付四件套: 首选+备选答案 / 分项置信度 / 证据分级（observed=inferred 标注每结论）/ 剩余确证路径（含具体操作步骤）
- 禁止项: 单答案无置信度、inferred 冒充 observed、确证路径只写"无法验证"

### 2.3 agent prompt 索引更新

文件: `$OPENCODE_ROOT/agents/web-analysis.md`（修改，+1 行）

在知识库索引表（`### Web 安全知识库` 节）加一行:
`| score-verification-osint.md | 需要验证某账号/团队在某平台的历史成绩（排名/得分），活动页已删除或无法访问时。证书 S3 直链、档案页证书入口、API WAF 降级、双源矛盾裁决 |`

## §3 实现规范

### 改动范围表

| 文件 | 操作 | 预估行数 |
|------|------|---------|
| `web-analysis/knowledge-base/score-verification-osint.md` | 新建 | ~120 |
| `web-analysis/knowledge-base/web-methodology.md` | 插入 §4b | ~35 |
| `agents/web-analysis.md` | 索引表 +1 行 | +1 |

编码规则:
- 知识库文件必须自包含（不依赖主 prompt 上下文）
- 跨文件引用用 `$AGENT_DIR`/`$SHARED_DIR` 变量，禁止硬编码绝对路径
- 叙事词零容忍: 不出现赛事名/队名/题目标识/具体答案数字/"比赛"限定词; 平台域名与 API 路径作为技术标识允许保留（保证可操作性）
- URL 模式写通用格式（`<平台名>-certificates.s3.<region>.amazonaws.com`），不绑定单一平台叙事

### §3.1 实施步骤拆分

步骤 1. 创建 score-verification-osint.md
  - 文件: `web-analysis/knowledge-base/score-verification-osint.md`（新建）
  - 预估行数: ~120 行
  - 验证点: ①文件存在且 `wc -l` 在 90-150 区间; ②`rg -i "CTF|比赛|赛事|锦标赛|writeup" <文件>` 零命中; ③人工通读确认每个小节都有"触发条件+操作步骤"结构
  - 依赖: 无

步骤 2. web-methodology.md 插入 §4b
  - 文件: `web-analysis/knowledge-base/web-methodology.md`（Edit 插入）
  - 预估行数: ~35 行
  - 验证点: ①`grep -n "^## 4b\|^## 5" <文件>` 确认 §4b 在 §4a 与 §5 之间; ②原文档 §5 之后章节无变动（diff 确认）; ③章节内容含四件套+禁止项
  - 依赖: 无（与步骤 1 并行可行）

步骤 3. agent prompt 索引 +1 行
  - 文件: `agents/web-analysis.md`（Edit 插入索引表）
  - 预估行数: +1 行
  - 验证点: ①索引表格式与相邻行一致（`\| 文件名 \| 触发条件 \|`）; ②展开后行数 < 450（口径: `wc -l` 文件行数 - `{{buwai-rule:}}` 占位符行数 + 各片段文件行数之和）; ③触发条件表述与 score-verification-osint.md 的"适用场景"段一致
  - 依赖: 步骤 1（索引指向的文件必须已存在）

## §4 验收标准

**功能验收**:
- [ ] score-verification-osint.md 存在、自包含、四大部分（验证源/API/裁决法/降级链）齐全
- [ ] web-methodology.md §4b 存在且位于正确位置，四件套规范完整
- [ ] agents/web-analysis.md 索引含新文件且触发条件准确

**回归验收**:
- [ ] web-methodology.md §1-§4a、§5-§9 原文无损（diff 仅新增 §4b 块）
- [ ] agents/web-analysis.md 展开后 < 450 行
- [ ] 全部产出文件叙事词零命中（rg 验证）; 界定: §1 按需求文档模板保留来源描述（不写具体赛事名/队名），作为知识蓝本的 §2/§3 对叙事零容忍

**架构验收**:
- [ ] 新文件位于 `web-analysis/knowledge-base/`（归属正确: Web OSINT 特有能力）
- [ ] 无依赖方向违反（知识库文档不引用 agent prompt; 如需引用脚本仅用 `$SHARED_DIR/scripts/`）
- [ ] 需求文档知识蓝本段（§2/§3）叙事零命中

## §5 与现有需求文档的关系

- `requirements/evolve/` 下无同类方向需求（目录已确认），本需求为新增
- 与记忆库条目 5758（排名成绩验证源，中性版）的关系: 记忆库为运行时快速检索入口，本需求的 score-verification-osint.md 为权威全文; 两者内容同源不冲突
- 无已实施需求需要修订
