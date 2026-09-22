# 自检噪音修复：占位符示例误展开 · 跳过分支日志分级 · crypto 规则补齐

> 来源: 2026-09-22 重启后自检（用户确认"1~3 都要修复"）

## §1 背景与目标

**来源**：用户重启 opencode 后要求自检。自检发现 3 个问题（均非重启引起、非近期改动引起），用户确认全部修复。

| # | 问题 | 现象 | 根因 |
|---|------|------|------|
| 1 | evolve prompt 示例被当真占位符 | 每次 evolve 请求产生 4 条 `Snippet not found: .../agents-rules/xxx.md`（2 条进 plugin_debug.log + 2 条进会话日志） | `agents/security-analysis-evolve.md` L47/L215 的字面量示例 `{{buwai-rule:xxx}}` 命中展开正则 `[a-zA-Z0-9_-]+` |
| 2 | 跳过分支 `[ERROR]` 误标 | build（非项目 agent，`agents/build.md` 不存在）、fresh-eyes（文件存在但无 id 且无占位符）每次 transform 刷 `[ERROR] ... 不包含 buwai-extension-id` | `expandedSnippet` 跳过分支不区分场景、统一 ERROR；真正该报警的"有占位符但缺 id"（配置漏声明）被淹没 |
| 3 | crypto 缺 probe-first-strategy | crypto-analysis.md 只有 6 个共享片段占位符，其余 4 个分析 agent（binary/web/mobile/ai）均有 7 个 | 疑似遗漏 |

**目标**：
- 问题 1：`xxx` 示例不再触发展开尝试（噪音清零；同时消除"若存在 `xxx.md` 片段则 evolve prompt 被意外替换"的隐患）
- 问题 2：跳过分支按场景分级——正常跳过（文件不存在 / 无占位符且无 id）降为 debug 记录；真配置错误（有占位符但缺 id）保留 `[ERROR]`
- 问题 3：crypto-analysis.md 补齐 `probe-first-strategy`，与其余分析 agent 结构一致

**预期收益**：
- 日志噪音：evolve 每轮 -4 条 not-found；build/fresh-eyes 每轮 -1 条 ERROR
- 准确度：插件能区分"有占位符但缺 id"的真配置错误（当前被统一 ERROR 文案淹没，无法区分）
- 一致性：crypto 的共享规则集与其他分析 agent 对齐

## §2 技术方案

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `.opencode/agents/security-analysis-evolve.md` | 2 行改 | L47/L215：`{{buwai-rule:xxx}}` → `{{buwai-rule:片段名}}`（CJK 不匹配展开正则，不再触发展开；保留文档语义） |
| `.opencode/plugins/lib/constants.ts` | 新增常量 | `PROJECT_AGENTS`（项目 agent 全集，含 evolve）；`ALL_REGISTERED_AGENTS` 改为由其派生（去掉 evolve，语义不变） |
| `.opencode/plugins/lib/snippet.ts` | 接口升级 | `hasBuwaiExtensionId(agentFile): boolean` → `inspectAgentFile(agentFile, isProjectAgent): AgentFileInspection`；新增占位符语法常量 `BUWAI_RULE_PLACEHOLDER_SOURCE` / `BUWAI_RULE_PLACEHOLDER_PREFIX`（供展开方复用） |
| `.opencode/plugins/security-analysis.ts` | 消费方升级 | import 更新 + `expandedSnippet` 三分支 + 展开正则改由共享源构建 |
| `.opencode/agents/crypto-analysis.md` | +4 行 | 阶段 B（analysis-planning-rules）之后插入 `### 试探优先策略` + 占位符，与 binary/web/mobile/ai 的结构一致 |

### 2.2 数据结构（规则 9）

```ts
// snippet.ts
export interface AgentFileInspection {
  exists: boolean;          // agent 文件是否存在
  hasExtensionId: boolean;  // frontmatter 是否声明 buwai-extension-id
  hasPlaceholders: boolean; // 内容是否含可展开的 {{buwai-rule:<名>}}（正则匹配判定，非 includes 字符串）
}

export function inspectAgentFile(agentFile: string): AgentFileInspection;

// 占位符语法单一来源（同文件相邻定义，防跨文件漂移）：
// - SOURCE：snippet.ts 用非全局实例做匹配；security-analysis.ts 用 new RegExp(SOURCE, "g") 做替换
// - PREFIX：security-analysis.ts 的快速跳过闸（includes 判断）
export const BUWAI_RULE_PLACEHOLDER_SOURCE = "\\{\\{buwai-rule:([a-zA-Z0-9_-]+)\\}\\}";
export const BUWAI_RULE_PLACEHOLDER_PREFIX = "{{buwai-rule:";
```

- 单次读取 + `Map<string, { inspection: AgentFileInspection; mtime: number }>` 缓存（合并原 frontmatterCache，避免一份文件读两遍）
- 文件不存在（ENOENT）→ 返回全 `false`（不缓存）：**项目 agent**（`PROJECT_AGENTS`，isProjectAgent=true）缺失记 `[ERROR] ... 项目 Agent 文件缺失，占位符不会展开`；**非项目 agent**（内置 build/plan/general 等）缺失是常态、静默（跳过由调用方记录）
- 其他异常（EISDIR/EACCES/非法路径等）→ 不分项目与否，先记录 `[ERROR] inspectAgentFile 异常: <path> — <code> <message>` 再返回全 `false`（禁止静默吞错）

### 2.3 expandedSnippet 新分支

```
inspect = inspectAgentFile(agentFile)
├─ !exists              → debugLog("...不存在（非本项目 Agent），跳过占位符展开")，return
├─ !hasExtensionId
│   ├─ hasPlaceholders  → debugLog("[ERROR] ...含占位符但未声明 buwai-extension-id，占位符不会展开（请在 frontmatter 声明）")，return  ← 真配置错误
│   └─ 无占位符          → debugLog("...未声明 buwai-extension-id 且无占位符，跳过占位符展开")，return
└─ hasExtensionId       → 照旧执行展开（正则改用 BUWAI_RULE_PLACEHOLDER_SOURCE 构建）
```

展开循环的快筛 `includes("{{buwai-rule:")` 改用 `BUWAI_RULE_PLACEHOLDER_PREFIX`；替换正则改用 `new RegExp(BUWAI_RULE_PLACEHOLDER_SOURCE, "g")`——security-analysis.ts 内不再有字面量语法。

### 2.4 架构影响

- 无新增文件；依赖方向不变（`snippet.ts` ← `security-analysis.ts`）
- 接口变更消费方唯一（已 grep 验证：仅 security-analysis.ts）；旧函数 `hasBuwaiExtensionId` 删除——不留兼容别名、不留墓碑注释
- prompt 改动净增行数：evolve 0；crypto +4（展开后 +probe-first-strategy 片段 28 行）

## §3 实现规范

### 3.1 实施步骤

**步骤 1. evolve prompt 示例去武装**
- 文件: `.opencode/agents/security-analysis-evolve.md`（L47、L215）
- 预估行数: 2 改 0 增删
- 验证点: ① `grep "buwai-rule:xxx"` 在 `agents/` 目录 0 处（需求文档自身的描述文本不计）；② bun 仿真：对该文件跑展开正则 0 匹配、无 not-found 日志
- 依赖: 无

**步骤 2. snippet.ts：inspectAgentFile + 占位符语法常量**
- 文件: `.opencode/plugins/lib/snippet.ts`
- 预估行数: ~40（含 interface、缓存、注释）
- 验证点: bun import 后对四类真实/构造文件实测三字段——`agents/build.md`（缺失）、`agents/fresh-eyes.md`（存在/无 id/无占位符）、`agents/web-analysis.md`（存在/有 id/有占位符）、临时 fixture（存在/无 id/有占位符）
- 依赖: 无

**步骤 3. security-analysis.ts：消费方升级 + 三分支**
- 文件: `.opencode/plugins/security-analysis.ts`（import 块 + expandedSnippet）
- 预估行数: ~25
- 验证点: 临时副本 harness 5 用例（见 §4 功能验收）+ bun 导入通过
- 依赖: 步骤 2

**步骤 4. crypto-analysis.md 补齐 probe-first-strategy**
- 文件: `.opencode/agents/crypto-analysis.md`
- 预估行数: +4
- 验证点: 与 4 个对照 agent 的占位符集合 grep 对照一致；展开仿真 7 个占位符全解析成功
- 依赖: 无

### 3.2 编码规则

- 规则 9：`AgentFileInspection` interface + 类型化缓存 Map；禁止 `any`
- debugLog 文案含唯一可 grep 关键词：`不存在（非本项目 Agent）` / `且无占位符` / `含占位符但未声明`
- 异常可见性：`inspectAgentFile` 仅对"非项目 agent 缺失"静默；"项目 agent 缺失"与所有非 ENOENT 异常必须先 `debugLog`（`[ERROR]` 前缀）再返回全 `false`
- 占位符语法单一来源：`SOURCE` 与 `PREFIX` 两个常量在 snippet.ts 相邻定义；security-analysis.ts 内不再出现字面量语法
- 删除 `hasBuwaiExtensionId` 后，插件与 agent 文件内 grep 零残留（含注释；需求文档的变更描述不计）

## §4 验收标准

**功能验收**（临时副本 harness 6 用例 + 异常用例 E1-E5，temp 隔离环境：OPENCODE_ROOT 指向含真实 agent 副本 + fixture 的临时根、agents-rules 软链真身、CT_DIR 指向 temp 根（C6 删除 crypto 副本用）、DATA_DIR 指向 temp 以捕获日志）：

1. agent=build（文件不存在）→ 日志含"不存在（非本项目 Agent）"，无 `[ERROR]`，`output.system` 不变
2. agent=fresh-eyes（无 id 无占位符）→ 日志含"且无占位符"，无 `[ERROR]`
3. fixture（无 id 有占位符）→ 日志含 `[ERROR]`"含占位符但未声明"，占位符保持原文
4. agent=security-analysis-evolve（有 id，示例已去武装）→ 日志含"开始占位符展开"与"检测到 buwai-extension-id"，但不含 `Snippet not found`；system 不变
5. agent=web-analysis（有 id 有效占位符）→ `{{buwai-rule:...}}` 全部被替换（回归）
6. 异常路径：目录路径（EISDIR）/非法路径 → `[ERROR] inspectAgentFile 异常`（不分项目与否）；**项目 agent** 文件缺失（isProjectAgent=true）→ `[ERROR] ... 项目 Agent 文件缺失` + 调用方跳过行；**非项目 agent** 缺失（如 build）→ 无 `[ERROR]`，仅调用方跳过行

harness 实现要点（沿用既有 ct-test 模式）：
- 从当前 `security-analysis.ts` 生成临时副本：`./lib/*` 相对导入改写为绝对路径；末尾追加 `globalThis.__expandedSnippet = expandedSnippet;`
- 每用例 mock：session `{ sessionID: "sn-test-<case>", agentName: "<agent 名>" }`；output `{ system: ["..."] }`——case 5 的 system 串内放真实占位符，其余用例放中性文本
- 日志断言：记录 `DATA_DIR/logs/plugin_debug.log` 用例前后长度、读增量（未知 session → `getAgentName` 返回 undefined → 落 DEFAULT_LOG）；断言含/不含对应关键词
- temp 根：`agents/` = 9 个真实 agent 文件副本 + `fixture-noid.md`（无 id、含 `{{buwai-rule:evidence-discipline}}`）；`agents-rules/` 软链真身；`DATA_DIR` 独立隔离

**回归验收**：
- 全 9 agent 占位符解析仿真零失败（含 `dynamic-by-agent_searcher` 5 个版本）
- `verifyCognitionSelfCheck` 一致（`verifyMirrors()` 返回空）
- 插件 bun import 无错；重启后日志复验：evolve 0 条 not-found、build/fresh-eyes 无 `[ERROR]`

**架构验收**：
- `hasBuwaiExtensionId` 在插件与 agent 文件内零残留（需求文档的变更描述不计）；无墓碑注释；无新文件；依赖方向不变

**生效条件**：插件与 agent prompt 改动均需重启 opencode；重启后按上述日志项复验。

## §5 与现有需求文档的关系

- 独立小修，不改 `2026-09-21-cognitive-intervention-system.md` 的范围与产出；本次发现源自该系统的日志体系自检。
- 明确不做：evolve prompt 体量瘦身（当前 634 行 > 600 阈值，但本次净增 0 行；若后续需往 evolve prompt 新增内容，先立瘦身需求）。
