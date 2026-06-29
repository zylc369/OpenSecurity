# 需求文档：分析持续性恢复机制修复

## §1 背景与目标

### 来源
SekaiCTF apbq-rsa-iv 密码学题目分析（task `20260628_230927_14f7`）复盘中发现：session 的自动恢复（auto-resume）机制存在三个缺陷，导致分析中断后无法自动继续。

### 痛点（附数据）
1. **resume_count 持久化 + 只增不减 + 无重置入口**：02:26–02:38 的 12 分钟内消耗 19 次 resume 配额（平均 38 秒/次），50 次配额烧光后 session 永久死亡。重启 opencode、重新打开 session、用户手动发消息都无法恢复——`resume_count=50` 存在磁盘 `.persistence.json` 里，重启不重置。
2. **idle handler 无冷却**：AI 每回复完一轮 → 立即 idle → 立即发 resume prompt + count+1。无冷却导致配额被快速消耗。
3. **lastUserMessageAt 被 synthetic message 刷新**：resume prompt（synthetic）触发 `chat.message` → `upsert` 无条件更新 `lastUserMessageAt` → `max_duration`（6 小时）超时检查形同虚设（`elapsed` 永远只等于 AI 上一轮回复耗时，日志全是 `elapsed=0m`）。

### 预期收益
| 维度 | 改进前 | 改进后 |
|------|--------|--------|
| 配额耗尽后恢复 | 永久死亡，只能手动改文件 | 重启 opencode 即恢复（内存化） |
| 配额消耗速度 | 38 秒/次（12 分钟烧 19 次） | ≥90 秒/次（冷却） |
| 超时保护 | 失效（lastUserMessageAt 被刷新） | 恢复效力（synthetic 不刷新） |

### 不做（明确边界）
- **不改 resume prompt 措辞**（用户明确要求"再想想"，本需求不涉及）
- **不改 agent prompt 死局策略**（用户明确不做）
- **不清理旧 .persistence.json 文件**（不读 = 不存在，无需清理）

---

## §2 技术方案

### 改动 1：resume_count 内存化

**现状**：`resume_count` 存在磁盘 `.persistence.json`，由 `readPersistenceData`（persistence.ts:97）读取、`recordResumeAttempt`（persistence.ts:181）写入。

**方案**：移到 `SessionData`（内存 Map），重启 opencode 时 `SessionData` 全部重建，`resumeCount` 自然归零。

- `SessionData` 加字段 `resumeCount: number = 0`
- `recordResumeAttempt` 删除文件写入，改为 `session.resumeCount++`
- `maybeResumeAnalysis` 读 `session.resumeCount`
- 删除 `readPersistenceData` 函数（不再读 `.persistence.json`）
- `getMaxDuration` 直接返回 `MAX_DURATION_DEFAULT`（不再从文件读 `max_duration_hours`——它始终是默认值 6，无人修改）
- 删除 `PersistenceData` interface、`PERSISTENCE_FILE` import

### 改动 2：冷却机制（setTimeout 延迟发送）

**现状**：idle handler 无冷却，AI 回复完立即触发 resume。

**方案**：resume 后记录 `lastResumeAt`，下次 idle 时如果距上次 resume < 冷却阈值，用 `setTimeout` 延迟到冷却到期后发送。冷却阈值基于 resumeCount 线性退避（1s 起，每次 +1s，上限 10s）——只拦"极快回复"的异常循环，对正常分析（每轮 >10s）无感。

- `SessionData` 加字段 `lastResumeAt: number = 0`、`pendingResumeTimer: ReturnType<typeof setTimeout> | null = null`
- `constants.ts` 加 `RESUME_COOLDOWN_STEP_MS = 1000`、`RESUME_COOLDOWN_MAX_MS = 10 * 1000`
- 抽出 `sendResume(sessionID, session)` 函数（发送 resume prompt + 记录状态）
- `maybeResumeAnalysis` 在 resumeCount 检查之后、发送之前加冷却判断：
  - `now - lastResumeAt >= COOLDOWN` → 立即调用 `sendResume`
  - `< COOLDOWN` → `setTimeout(COOLDOWN - elapsed, sendResume)`，存 timer handle 到 `session.pendingResumeTimer`
- 新 resume 前清旧 timer（防重复）

**风险**：`setTimeout` 回调在 opencode 退出时丢失。可接受——内存化已解决重启问题（重启后 `resumeCount=0`）。

### 改动 3：修 lastUserMessageAt（synthetic message 不刷新）

**现状**：`chat.message` 的 `upsert` 无条件更新 `lastUserMessageAt`（session-manager.ts:75）。resume prompt 触发的 synthetic message 也走这条路径，导致超时检查失效。

**方案**：用 `resumeMarker` 判断是否是 resume 回声。时序保证：`maybeResumeAnalysis` 发 prompt 后同步设 `resumeMarker`（persistence.ts:265）→ resume prompt 触发 `chat.message` → `chat.message` 读 `resumeMarker`（非空 = synthetic）→ `upsert` 跳过 `lastUserMessageAt` 更新 → 然后清 `resumeMarker`（line 444）。

- `upsert` 加参数 `isSynthetic?: boolean`，为 true 时不更新 `lastUserMessageAt`
- `chat.message` 在 `upsert` 前检查 `existing?.resumeMarker`，判断 `isResumeEcho`
- 额外：`chat.message` 检测到真实用户消息时，清 `pendingResumeTimer`（用户手动介入 = 取消冷却中的自动 resume）

---

## §3 实现规范

### 涉及文件

| 文件 | 改动类型 |
|------|---------|
| `plugins/lib/session-manager.ts` | SessionData 加 3 个字段；upsert 加参数 |
| `plugins/lib/constants.ts` | 加 RESUME_COOLDOWN_MS |
| `plugins/lib/persistence.ts` | 删除文件读写；resume_count 改内存；加冷却；抽 sendResume |
| `plugins/security-analysis.ts` | chat.message 判断 synthetic + 清 timer |

### 编码规则
- 遵循现有代码风格（debugLog 打日志、Result 模式）
- `maybeResumeAnalysis` 的冷却判断和 sendResume 抽取保持函数职责清晰
- 冷却相关的 debugLog 要打关键信息（等待时间、timer 创建/取消）

### §3.1 实施步骤拆分

**步骤 1. SessionData 加字段 + constants 加冷却常量**
- 文件：`session-manager.ts`、`constants.ts`
- 预估行数：~15 行
- 改动：
  - `SessionData` 加 `resumeCount = 0`、`lastResumeAt = 0`、`pendingResumeTimer: ReturnType<typeof setTimeout> | null = null`
  - `constants.ts` 加 `export const RESUME_COOLDOWN_MS = 90 * 1000;`
- 验证点：`node --check` 两个文件通过
- 依赖：无

**步骤 2. resume_count 内存化 + 删除 .persistence.json 读写**
- 文件：`persistence.ts`
- 预估行数：~50 行（删除 ~40 行 + 修改 ~10 行）
- 改动：
  - 删除 `PersistenceData` interface、`readPersistenceData` 函数
  - `getMaxDuration` 简化为直接返回 `MAX_DURATION_DEFAULT`（删除 sessionID 参数）
  - 删除 `recordResumeAttempt` 函数（逻辑移入 sendResume）
  - `maybeResumeAnalysis` 里：`resumeCount` 改读 `session.resumeCount`
  - 删除 `PERSISTENCE_FILE`、`readFileSync`、`writeFileSync`、`join` 的 import（grep 确认 join 仅在 readPersistenceData/recordResumeAttempt 中使用，删除后无残留引用）
- 验证点：`node --check persistence.ts` 通过；grep 确认无残留的 `.persistence.json` 引用；grep 确认 persistence.ts 内无 `join(` 残留
- 依赖：步骤 1

**步骤 3. 冷却机制 + 抽出 sendResume**
- 文件：`persistence.ts`
- 预估行数：~50 行
- 改动：
  - 抽出 `async function sendResume(sessionID, session)`：发 promptAsync + 设 resumeMarker + resumeCount++ + lastResumeAt
  - sendResume 开头做防护：检查 `ctx.client` 可用 + `ctx.sessionManager.get(sessionID) === session`（session 仍在 Map 中，未被 session.deleted 清除）。任一不满足则 debugLog + return
  - `maybeResumeAnalysis` 在 resumeCount 检查后加冷却判断：
    - `sinceLastResume >= COOLDOWN` → `await sendResume(...)`
    - `< COOLDOWN` → 清旧 timer + setTimeout 延迟 sendResume
  - import `RESUME_COOLDOWN_MS`、`SessionData` 类型
- 验证点：`node --check persistence.ts` 通过；人工读 maybeResumeAnalysis 确认冷却逻辑正确（边界：首次 lastResumeAt=0 时 sinceLastResume 巨大，立即发送）
- 依赖：步骤 1、2

**步骤 4. 修 lastUserMessageAt + chat.message 清 timer**
- 文件：`session-manager.ts`、`security-analysis.ts`
- 预估行数：~20 行
- 改动：
  - `upsert(sessionID, agentName, isSynthetic?)`：`isSynthetic` 为 true 时跳过 `lastUserMessageAt` 更新
  - `chat.message`：upsert 前检查 `existing?.resumeMarker` 判断 `isResumeEcho`，传给 upsert
  - `chat.message`：真实用户消息（非 isResumeEcho）时清 `pendingResumeTimer`
- 验证点：`node --check` 两个文件通过；人工读 chat.message 确认 isResumeEcho 判断在 upsert 之前
- 依赖：步骤 1、3

**步骤 5. 端到端验证**
- 无代码改动，纯验证
- 验证点：
  1. `node --check` 全部 4 个文件通过
  2. 触发 crypto-analysis session 的 resume 循环，观察日志：resume 间隔 ≥ 90s
  3. 检查任务目录下 `.persistence.json` 不再被更新（mtime 不变）
  4. grep plugin.log 确认无 `readPersistenceData` / `recordResumeAttempt` 的日志
  5. 人工读代码确认：重启后 resumeCount 从 0 开始（SessionData 构造函数初始化）
- 依赖：步骤 1-4

---

## §4 验收标准

### 功能验收
- [ ] resume_count 存在内存（SessionData），不再读写 `.persistence.json`
- [ ] 重启 opencode 后 resumeCount 归零
- [ ] resume 之间有 ≥90s 冷却间隔（setTimeout 延迟发送）
- [ ] 冷却期间 session 不会永久停止（setTimeout 到期自动恢复）
- [ ] synthetic message（resume 回声）不刷新 lastUserMessageAt
- [ ] 真实用户消息刷新 lastUserMessageAt + 清 pendingResumeTimer
- [ ] max_duration 超时检查恢复效力（elapsed 基于真实用户消息时间）

### 回归验收
- [ ] resume 的其他检查逻辑不受影响（evolve agent 跳过、taskDir 检查、超时检查、aborted 检查、marker 完成检测）
- [ ] 完成标记机制（resumeMarker）不受影响
- [ ] chat.message 的其他逻辑不受影响（环境检测、预装检查、agent 切换）
- [ ] system.transform、compacting 等 hook 不受影响

### 架构验收
- [ ] 无循环依赖
- [ ] 依赖方向不变（_base ← _utils ← _analysis ← query/update）
- [ ] 改动限于 plugins/lib/ 和 plugins/security-analysis.ts，不涉及 agent prompt

---

## §5 与现有需求文档的关系

- **2026-06-13-analysis-persistence.md**：建立了 `.persistence.json` 和 resume 机制。本需求是对该机制的修复（resume_count 改内存化、加冷却），不否定原有设计，而是修正其缺陷。
- **2026-05-31-agents-md-simplify-and-log-ms.md**：日志格式统一。本需求的 debugLog 遵循其格式规范。
- 无冲突文档。
