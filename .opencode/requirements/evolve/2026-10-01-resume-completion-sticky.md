# 续跑完成态固化（resume completion sticky）

- 日期：2026-10-01
- 类型：缺陷修复（认知干预系统 / auto-resume 完成检测）
- 状态：代码完成 + 单元验证通过；**待用户重启 opencode 加载生效**（未提交）

## 1. 现象：完成 → 压缩 → 续跑 死循环

现场会话 `ses_f249b838affeOGqdn2tZQMLWQB`（agent 由 evolve 切到 mobile-analysis），plugin.log 实测时间线：

| 时刻 | 事件 |
|---|---|
| 13:35:58 | 反思纸条 #1（忙时通道） |
| 13:37:21 | 反思唤醒 #2（空闲通道） |
| 13:38:11 / 13:38:14 | resume #1 / #2（marker 8a62 / 7f83） |
| 13:39:34 | resume #3（marker c517） |
| 13:40:42 | `跳过恢复 — 检测到完成标记 c517`（机制成功） |
| 13:41:01 | `compacting ... (justCompacted=true)` — 上下文压缩 |
| 13:42:24 | `event: session.compacted` |
| 13:42:26 | `未检测到完成标记 c517, lastText=## Objective …`（lastText 已是压缩摘要）→ resume #4（marker 342e） |

即：agent 输出完成标记 → 本轮确实跳过 ✓ → 上下文压缩把历史替换为摘要 → 摘要成为"最后一条 assistant 消息"（不含 marker）→ 文本检测失效 → 再次续跑。长会话反复压缩会让该循环持续（resumeCount 80 上限只是兜底）。

## 2. 根因

`maybeResumeAnalysis` 的完成检测**只依赖"最后一条 assistant 消息文本是否包含本轮 marker"**（`getLastAssistantText`），完成事实没有固化到会话状态。压缩摘要一旦覆盖该文本，已完成的事实被抹掉。

## 3. 修复

把"本轮完成"固化为**粘性会话状态**，跨压缩保持，仅由真实用户消息解除：

- `SessionData.resumeCompletedAt: number | null`（内存，不持久化，语义同 `resumeCount`）
  + `isAnalysisCompleted()`：`resumeCompletedAt !== null && resumeCompletedAt > lastUserMessageAt`（防过期：完成时刻早于最后用户消息 → 不生效）
- `persistence.ts`：
  - 完成标记命中分支：置 `resumeCompletedAt = Date.now()`（固化点）
  - 新增粘性完成态检查点，位于**反思唤醒分支与 resume 分支之前** → 完成态同时抑制唤醒与续跑（压缩只改文本、不改状态）
- `session-manager.ts` upsert 真实用户消息分支：`resumeCompletedAt = null`（与 `resumeMarker = null` 同步，新一轮恢复判定）
- 恢复提示词回声路径不变（`isResumeEcho` 契约：不刷新 `lastUserMessageAt`、不清 marker）

覆盖范围：resume（`sendResume`）与反思唤醒（`sendReflection`）都植入 `resumeMarker`、共用同一完成检测 → 两个通道的完成态都被固化。

## 4. 验证

- 新增 `plugins/tests/test-resume-completion.ts` **7/7**：未完成初值 / 命中固化 / 压缩粘性（幂等）/ 真实消息解除 / 过期完成态防御 / 回声契约 / 未完成不抑制
- 回归全绿：`test-reflection-clock` 8/8、`test-reflection-config` 2/2、`test-permission-timeout` 17/17、`test-control` 11/11（合计 45/45）
- 编译冒烟：`bun build`（session-manager / persistence / 新测试）OK
- 活体验证：**待用户重启**；生效后本会话（再压缩）不会再被唤醒/续跑

## 5. 边界与未测

- **未持久化**：插件重启后完成态归零（同 resumeCount）→ 重启后最多再发生一轮续跑，之后完成即粘性
- 若 agent 误判完成（输出 marker 但实际继续工作），该轮唤醒/续跑会被抑制到用户下次发言——marker 既有语义，非本次引入
- **未测**：压缩发生在"marker 已植入、agent 尚未回复完成标记"的窗口内（完成态尚未固化 → 压缩后仍会续跑一次）；需真实压缩与时序配合，本轮未构造
- resumeCount 上限 80 仍为最终兜底；用户中断（abort）路径不受影响

## 6. 变更文件（未提交）

- `plugins/lib/session-manager.ts`（字段 + `isAnalysisCompleted()` + upsert 清空）
- `plugins/lib/persistence.ts`（固化点 + 粘性检查点）
- `plugins/tests/test-resume-completion.ts`（新增）
