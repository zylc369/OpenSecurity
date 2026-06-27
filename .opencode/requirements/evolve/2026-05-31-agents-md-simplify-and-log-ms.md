# 需求：AGENTS.md 精简 + Plugin 日志毫秒精度

## §1 背景与目标

**来源**: 用户对前次进化（描述清理）的后续反馈。

**三个改动点**:
1. AGENTS.md Agent 索引表中"切换方式（Tab 键）"列对 AI 无信息量，删除
2. AGENTS.md"目录结构"节与 security-analysis-evolve.md 架构图重复且容易过时，删除整个节
3. Plugin 日志时间戳缺少毫秒，排查时序问题时精度不够，加 `.[三位毫秒数]`

## §2 技术方案

| # | 文件 | 改动内容 |
|---|------|---------|
| 1 | `AGENTS.md` | Agent 索引表删除"切换方式（Tab 键）"列 |
| 2 | `AGENTS.md` | 删除"目录结构"节（L16-30 整段） |
| 3 | `security-analysis.ts` L74 | 时间戳追加毫秒 `.{毫秒3位}` |

改动 3 的具体实现：
```typescript
// 改动前
const ts = new Date().toLocaleString("zh-CN", { hour12: false });
// 改动后
const now = new Date();
const ts = now.toLocaleString("zh-CN", { hour12: false }) + `.${String(now.getMilliseconds()).padStart(3, "0")}`;
```

## §3 实现规范

### §3.1 实施步骤拆分

**步骤 1. 精简 AGENTS.md**
- 文件: `AGENTS.md`
- 预估行数: ~15 行改动（删除列 + 删除整个节）
- 验证点: 1) Agent 索引表只有 Agent 和职责两列；2) 文件中无"目录结构"节；3) 表格 markdown 格式正确
- 依赖: 无

**步骤 2. Plugin 日志加毫秒**
- 文件: `.opencode/plugins/security-analysis.ts`
- 预估行数: 2 行改动（L74 拆为两行）
- 验证点: `node --check` 语法通过
- 依赖: 无

## §4 验收标准

### 功能验收
- [ ] AGENTS.md Agent 索引表只有"Agent"和"职责"两列
- [ ] AGENTS.md 无"目录结构"节
- [ ] Plugin 日志时间戳格式为 `[YYYY/M/D HH:mm:ss.毫秒]`

### 回归验收
- [ ] AGENTS.md 仍包含全部 6 个 agent 条目
- [ ] Plugin 无语法错误

### 架构验收
- [ ] 无信息丢失（目录结构信息在 security-analysis-evolve.md 架构图中完整保留）

## §5 与现有需求文档的关系

前次需求 `2026-05-31-binary-agent-description-cleanup.md` 的后续。本次改动将删除前次需求中新增的目录结构条目（因为整个节被删除）。
