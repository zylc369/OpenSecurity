# 信源注册表双层架构与调用即自进化

> 需求 ID: 2026-09-26-source-registry
> 状态: 执行中
> 来源: 2026-09-26 对话复盘——stack1245 三库蒸馏后追问"knowledge-scout 能否发现高质量源"，暴露信源体系三断链（发现方法未沉淀/作者未回流/无作者扩展反射），经四轮方案迭代收敛（末位淘汰无状态判据 ← 否决跨轮计数伪指标; 双层数据 ← 解决 scout 零写入与数据维护的矛盾; 调用即进化 ← 否决 launchd 定时重方案）。取代暂存方案 `2026-09-26-source-lifecycle-plan.md`（其活力机制内容已并入本文档）。

## §1 背景与目标

**痛点**（均有实证）:
1. 信源表是死清单: 只入不出，劣化源永久占据扫描预算
2. 发现链断三层: 卡壳检索方法未沉淀（PwnSec 命中时无方法论记载）、作者未回流（stack1245 不在表）、无作者扩展反射（命中 PwnSec 后 K17/BHMEA 靠用户转手）
3. scout 零写入（工具白名单机制化）与"每次使用要留下状态增量"矛盾

**目标**:
- 信源数据从方法论文档拆出为双层 JSON: curated（沉淀基线）+ staging（自更新唯一写入目标）
- scout 每次出勤即自进化: 状态更新/引用提取与计数/末位标记/pending 验证四个动作寄生在主任务里
- 发现与活力统一为一条生命周期流水线，审核收口（evolve review 后转正）

**预期收益**（四维）: 减少轮次（用户不再人肉喂源，实证: K17/BHMEA 两跳转手）; 准确度（已验证作者新产出质量先验高）; 上下文（引用提取与计数零额外请求）; 速度（90 天追新从"用户看到"提速到"出勤即扫"）。

## §2 技术方案

### 2.1 数据结构

`knowledge-scout/data/sources-curated.json`（沉淀层，随 git）:
```json
{
  "schema_version": 1,
  "sources": [{
    "domain": "r3kapig.com",
    "tier": "S1",
    "status": "active",
    "last_seen": "2026-09-26",
    "refs_in": 0,
    "added_at": "2026-09-26",
    "profile": "top10 战队官方站…（自然语言: 是什么/怎么扫/注意什么）"
  }],
  "aggregators": [{
    "domain": "ctftime.org",
    "tier": "AG",
    "status": "active",
    "last_seen": "2026-09-26",
    "refs_in": 0,
    "added_at": "2026-09-26",
    "profile": "聚集体入口…（自然语言: 入口类型/下钻路径）"
  }]
}
```

`knowledge-scout/data/sources-staging.json`（工作层，结构同上 + 条目多 `proposal` 自然语言字段: 发现途径+证据+建议动作）。

**字段二分法**: 机器判定用固定字段（domain 主键 / tier: S1站点级·S2作者级·O一次性·AG聚集体 / status: active·reduced·archive / last_seen / refs_in / added_at）; 指导行为用自然语言（profile/proposal——原 directions+note 合一，消费方是大模型）。

**读取规则**: 优先 staging，不可用（不存在/空/损坏 json parse 失败）回退 curated。> 勘误（实施后修订）: 实际落地为**逐条目合并语义**（curated 全量基线 + staging 同 domain 条目覆盖 + 新 domain 附加），非整文件替换——以 sourcing-guide §1 为唯一权威。

### 2.2 调用即自进化（scout 出勤四动作，寄生主任务）

1. **状态更新**: 每扫描一源，bash 更新 staging 该源 last_seen + 产出证据（自然语言追加 profile 或 proposal）
2. **引用提取与计数**: 读过的 writeup 顺手 grep 外链，滤噪音（图床/cdn/社交/规范/题目实例域名），命中 curated/aggregators 已有源则 refs_in+1，新域名追加 staging 条目（带 proposal: 引用来源+被引次数）
3. **末位标记**: 本轮接触的源当次计算无状态判据——近 30 天有效产出=0 且最新>30 天 → staging 标记建议降频; 90 天窗末位且产出<中位数 1/3 → 标记建议移出 archive
4. **pending 顺带验证**: 本轮方向扫描碰到 staging pending 源时，顺带核对 90 天≥2 机制级产出，达标则在 proposal 里升级建议（"建议入表 S1"），证据齐

### 2.3 审核转正（唯一人工/agent 关卡）

用户在 evolve 会话触发（或蒸馏任务前 evolve 顺带）: 读 staging → 对照判据 + 抽查可信性 → 可信: merge 进 curated（新增/状态迁移生效）→ 清 staging 对应条目; 不可信: 删条目，否决理由留在审核报告一页。

### 2.4 引用提取与计数进蒸馏流程

distillation-methodology 的蒸馏流程加一步: 素材归档后、gap 判定前，对全部 writeup 跑外链提取（命令级: python3 正则提取 https?:// 链接，滤噪音正则见 §3），结果追加 staging。

### 2.5 归属与依赖

- 数据文件: `knowledge-scout/data/`（agent 专属目录内，谁执行谁持有，architecture-map 目录树同步加节点）
- 方法论: sourcing-guide 判据/流程节改写（evolve 维护）
- scout prompt: 自进化动作 + 零写入铁律的 bash 数据文件例外（与其"下载素材落盘"同源逻辑: 信源状态是侦察产出的运行时数据，不是知识库变更）
- 不改: plugin、agent 间派发协议、download_sources.py

## §3 实现规范

- 改动范围: 2 新数据文件 + 1 方法论重写节 + 2 prompt 增段 + 1 暂存文档标注
- JSON 一律 `python3 -c "import json; json.load(open(...))"` 验证; md 人工读自包含性
- 滤噪音正则（引用提取与计数用）: `gyazo|imgur|st-hatena|zenn\.studio|wikipedia|php\.net|mozilla|chrom(e|ium)|googlesource|whatwg|mitre|x\.com|twitter|tiktok|esm\.sh|02\.rs|transfer\.sh|siam\.org|localhost|127\.0\.0\.1|example|attacker\.com|vulnerable|chal\.ctf|flagyard|forms\.gle|t\.co|hexo\.io|unpkg|linkedin|medium\.com|<|server`（实测 101 篇归档调优）

### §3.1 实施步骤

1. 创建 curated 注册表（16 源 + 2 聚集体初始化）
   - 文件: knowledge-scout/data/sources-curated.json
   - 预估行数: ~150 行
   - 验证点: json load 通过; 条目数 = 原 sourcing-guide §1 表 15 行(14+新增 r3kapig) + stack1245(S2) + 2 聚集体(ctftime.org/stats 入口 + hatena 圈 d.hatena.ne.jp); 每条字段齐全
   - 依赖: 无

2. 巡检 6 候选源质量 → 达标入 curated / 边缘进 staging
   - 文件: sources-curated.json + 创建 sources-staging.json
   - 预估行数: ~80 行
   - 验证点: 每候选有 90 天产出巡检记录（curl 实测）; 用户已预授权"质量好可以入表"
   - 依赖: 1

3. sourcing-guide §1 改写 + 新增三节（自进化动作/判据/审核转正）
   - 文件: knowledge-scout/knowledge-base/knowledge-sourcing-guide.md
   - 预估行数: ~120 行（改写 30 + 新增 90）
   - 验证点: §1 表替换为注册表读取规则后，原表的"获取方式"列信息不丢失（转入 profile）; 判据节含无状态淘汰判据表; 下载方法/价值判断/gap 判定节零改动
   - 依赖: 1

4. scout prompt 对齐（自进化四动作 + 报告骨架加"信源维护"段 + 铁律例外说明）
   - 文件: agents/knowledge-scout.md
   - 预估行数: ~35 行
   - 验证点: 展开行数 <450; 零写入铁律与 bash 数据文件例外表述无矛盾; 调用链（knowledge-search 命令→task 派发→scout 读 guide）不受影响
   - 依赖: 3

5. distillation-methodology 加引用提取与计数步 + 暂存文档标注已立项
   - 文件: security-analysis-evolve/knowledge-base/distillation-methodology.md、requirements/evolve/2026-09-26-source-lifecycle-plan.md
   - 预估行数: ~25 行
   - 验证点: 引用计数步骤在流程图内且命令级可执行; 暂存文档头部标注"已并入 2026-09-26-source-registry 立项"
   - 依赖: 无

6. 回归 + 审计
   - 验证点: 双 json 合法; 16 文件知识库本轮无叙事词污染（本任务不碰知识库 md——替换为: guide/prompt 增段叙事词零命中）; architecture-map 目录树含 data/ 节点; 展开行数复核; 交叉引用（guide↔prompt↔注册表路径）全部存在
   - 依赖: 1-5

## §4 验收标准

**功能**: ① 新 clone 只有 curated 也能完整跑 knowledge-search（回退逻辑在 guide 有明文）② staging 条目含 proposal 自然语言 ③ 滤噪音正则对 101 篇归档实测产出与方案对话一致（6 候选可复现）④ 末位判据无状态（全部当次可算）
**回归**: ① 原 §1 表 15 源全部在 curated 找到 ② 原 guide 的下载方法/CTF Base API 节/gap 判定/价值判断零丢失 ③ scout prompt 铁律/输入解析/报告骨架原有段落零删除
**架构**: ① data/ 在 architecture-map 有节点 ② scout 零写入白名单未改（bash 落盘是既有能力）③ 双层文件都在 knowledge-scout/ 专属目录内 ④ 需求/暂存文档关系标注清晰

## §5 与现有需求文档的关系

- 取代 `2026-09-26-source-lifecycle-plan.md`（暂存活力机制方案，全部内容并入本文档 §2.2/§2.3）
- 承接 K17 蒸馏复盘的"发现链三断链"教训（本需求是其体系化解决）
- 与 `2026-09-25-knowledge-distill-command.md`（蒸馏命令化）互补: 蒸馏流程的引用提取与计数步是本需求的 §2.4
