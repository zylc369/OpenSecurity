# 进度: 分析持续性增强

## 日期: 2026-06-13

## 完成状态: ✅ 全部完成

## 改动要点

### 核心功能: session.idle 自动恢复

- 在 event hook 中捕获 `session.idle` 事件
- 判断是否为安全分析 Agent 的主 session（排除子 session 和 security-analysis-evolve）
- 通过 `client.session.promptAsync()` 发送恢复消息
- 恢复提示: "你之前的分析是否已经完成了？如果已经完成，请直接输出最终结论。如果尚未完成，请自主继续分析，不要停下来向用户提问。"
- 选择 `promptAsync`（异步）而非 `prompt`（同步流式），因为 event hook 是 fire-and-forget

### 持续性状态文件: `.persistence.json`

- 格式: `{ "max_duration_hours": 6, "resume_count": 3, "last_resume_at": "2026-06-13T10:30:00.000Z" }`
- `max_duration_hours`: 最大持续时间（小时），默认 6，范围 0 < h <= 24
- `resume_count`: 已发送恢复消息的次数（每次成功恢复后 +1）
- `last_resume_at`: 最近一次恢复的 ISO 时间戳
- 文件不存在或 JSON 无效时，回退到默认 6 小时

### compacting hook 增强恢复上下文

- 为安全分析 Agent 注入"分析持续性"提示
- 告诉 AI 压缩恢复后继续自主分析，不要停下来等待用户

### 修改文件

1. `.opencode/plugins/security-analysis.ts` — 核心实现（~160 行新增/修改）
2. `.opencode/binary-analysis/scripts/create_task_dir.py` — 新增 `_init_persistence` 函数和 `--max-duration` 参数
3. `.opencode/binary-analysis/knowledge-base/opencode-plugin-hooks-lifecycle.md` — 知识库更新（陷阱 5）
4. `.opencode/binary-analysis/knowledge-base/task-initialization.md` — 文档更新（`--max-duration` 参数）
5. `.opencode/commands/security-analysis-requirements/2026-06-13-analysis-persistence.md` — 需求文档

## 审计结果

### 第 1 轮审计（需求文档修复）
发现问题 4 个（已全部修复）:
1. 需求文档 §3.2 改动范围表未包含 `create_task_dir.py` 和 `task-initialization.md` → 已补充
2. 需求文档 §4.3 架构验收写"没有新增文件"→ 已更新为"主要在 security-analysis.ts 中"
3. 需求文档步骤 4 伪代码未反映 `taskDir` 检查 → 已补充
4. 需求文档 §4.1 验收标准缺少"无 taskDir 的 session 不触发恢复"→ 已补充

### 第 2 轮审计（代码实现审计）
发现问题 0 个。

### 纯审计轮（只记录问题，不修复）
发现问题 0 个。

### 审计后修复：opencodeClient 类型声明和 promptAsync 调用格式
发现并修复 2 个问题:
1. `opencodeClient` 手写窄类型声明 → 替换为 `OpencodeClient`（SDK 完整类型），消除维护负担
2. `promptAsync` 调用格式错误：v1 SDK 格式是 `{path: {id}, body: {parts}}`，而非 v2 的 `{sessionID, parts}` → 已修正

**结论: 审计通过**