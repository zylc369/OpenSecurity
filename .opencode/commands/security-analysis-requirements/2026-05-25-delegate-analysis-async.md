# delegate_analysis 改为 promptAsync + poll 模式

## §1 背景与目标

**来源**: 2026-05-25 web CTF 知识沉淀任务复盘。coordinator 通过 `delegate_analysis` 并行分发 3 个子任务到 web-analysis agent，全部失败（超时中断）。coordinator 被迫降级为直接分析。

**痛点**:
- `delegate_analysis` 使用 `session.prompt`（同步阻塞 HTTP），tool execute 线程被 HTTP 响应卡死
- 没有超时控制，3 个子会话跑 35 分钟才被 OpenCode 框架强杀
- 没有 abort 机制，coordinator 取消时子会话不会被清理
- 整个 coordinator 编排功能不可用

**预期收益**:
- 子任务从"必定失败"变为"正常完成"
- 有明确的超时控制（默认 30 分钟）
- coordinator 取消时子会话被 abort 清理
- 减少上下文占用（不再因降级而重复分析）

**参考实现**: oh-my-openagent `src/tools/delegate-task/` 的 `promptAsync` + poll 模式，已在生产环境验证。

---

## §2 技术方案

### 2.1 核心变更

将 `security-analysis.ts` 中 `delegate_analysis` 的 execute 函数从：

```
session.create → session.prompt（同步阻塞等完成）→ 提取文本
```

改为：

```
session.create → session.promptAsync（立即返回）→ 轮询 session.status → session.messages 提取结果
```

### 2.2 改动文件

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `.opencode/plugins/security-analysis.ts` | 修改 | delegate_analysis execute 函数重写 + opencodeClient 类型声明扩展 |
| `.opencode/binary-analysis/knowledge-base/subsession-orchestration.md` | 新增 | OpenCode 子会话编排模式知识库文档 |

### 2.3 API 对照

| API | 作用 | SDK 方法 | HTTP 端点 |
|-----|------|---------|----------|
| 创建子会话 | 创建子会话（不变） | `session.create` | `POST /session` |
| 发送任务 | **改**：异步发送，立即返回 | `session.promptAsync` | `POST /session/{id}/prompt_async` |
| 查询状态 | **新增**：轮询子会话状态 | `session.status` | `GET /session/status` |
| 读取消息 | **新增**：提取子 Agent 输出 | `session.messages` | `GET /session/{id}/message` |
| 中止会话 | **新增**：超时/取消时清理 | `session.abort` | `POST /session/{id}/abort` |

### 2.4 轮询逻辑设计

参照 oh-my-openagent `sync-session-poller.ts`：

```
轮询循环（while Date.now() - startTime < TIMEOUT_MS）:
  1. 检查父会话是否被中断 → 是则 abort 子会话 + 返回错误
  2. sleep(2000ms)
  3. 调用 session.status() 检查子会话状态
  4. 如果状态为 idle → break（完成）
  5. 每 10 次轮询记录一次 debug 日志（避免日志膨胀）

超时处理:
  调用 session.abort() 强制终止子会话
  返回超时错误信息

结果提取:
  调用 session.messages() 获取子会话消息列表
  从最后一个 assistant message 提取 text parts
```

### 2.5 超时参数

| 参数 | 值 | 说明 |
|------|---|------|
| `POLL_INTERVAL_MS` | 2000 | 轮询间隔（oh-my-openagent 用 1000，我们任务更重用 2000） |
| `DEFAULT_POLL_TIMEOUT_MS` | 30 * 60 * 1000 | 默认超时 30 分钟 |
| `promptAsync` 超时 | 120000 | promptAsync 本身的 HTTP 超时（与 oh-my-openagent 一致） |

### 2.6 opencodeClient 类型声明扩展

需要新增以下方法签名：

```typescript
promptAsync: (options: {
  path: { id: string };
  body: {
    agent?: string;
    system?: string;
    parts: Array<{ type: string; text?: string }>;
  };
}) => Promise<{ data?: unknown; error?: unknown }>;
status: () => Promise<{ data?: Record<string, { type: string }> }>;
messages: (options: {
  path: { id: string };
}) => Promise<{ data?: Array<{
  info: { role: string; finish?: string; id: string; time?: { created: number } };
  parts?: Array<{ type: string; text?: string }>;
}> }>;
abort: (options: {
  path: { id: string };
}) => Promise<{ error?: unknown }>;
```

### 2.7 子会话完成判断

参照 oh-my-openagent `sync-session-poller.ts` 第 35-51 行的 `isSessionComplete`：

```
从 messages 列表（倒序）找到最后的 user 和 assistant message:
  - assistant 没有 finish 字段 → 未完成
  - assistant.finish 为 "tool-calls" → 未完成（还有工具调用在执行）
  - assistant 有 pending tool parts → 未完成
  - user.id >= assistant.id → 未完成（assistant 还没回复）
  - 其他 → 完成
```

---

## §3 实现规范

### 3.0 依赖方向

本需求不涉及 Python 文件，不影响 `binary-analysis/` 下的任何模块依赖方向。

### 3.1 实施步骤拆分

**步骤 1. 扩展 opencodeClient 类型声明**
- 文件: `.opencode/plugins/security-analysis.ts` 第 471-503 行区域
- 预估行数: 新增 ~30 行（类型声明）
- 验证点: `node --check security-analysis.ts` 语法通过
- 依赖: 无

**步骤 2. 新增轮询辅助函数**
- 文件: `.opencode/plugins/security-analysis.ts`，在 `buildSubSessionSystem` 函数之后新增
- 预估行数: 新增 ~80 行（`pollSubSession` + `isSessionComplete` + `fetchSessionResult` + 常量）
- 验证点: `node --check security-analysis.ts` 语法通过
- 依赖: 步骤 1（需要扩展后的 opencodeClient 类型）

**步骤 3. 重写 delegate_analysis execute 函数**
- 文件: `.opencode/plugins/security-analysis.ts` 第 895-933 行区域
- 预估行数: 修改 ~50 行（替换 session.prompt 调用为 promptAsync + poll + fetch）
- 验证点:
  1. `node --check security-analysis.ts` 语法通过
  2. 代码中不再有 `session.prompt` 调用（grep 验证）
  3. 代码中有 `session.promptAsync`、`session.status`、`session.messages`、`session.abort` 调用
- 依赖: 步骤 2（需要 pollSubSession 等辅助函数）

**步骤 4. 新增知识库文档**
- 文件: `.opencode/binary-analysis/knowledge-base/subsession-orchestration.md`（新增）
- 预估行数: 新增 ~100 行
- 验证点:
  1. 文件存在且内容完整
  2. 自包含（不依赖主 prompt 上下文即可理解）
  3. 包含：场景、API 选型（prompt vs promptAsync）、轮询模式、完成判断、超时处理
- 依赖: 无

### 3.2 编码规则

- 保持现有代码风格（中文注释、debugLog 日志）
- 轮询函数使用 `new Promise(resolve => setTimeout(resolve, ms))` 实现 sleep（简单可靠，不依赖 SharedArrayBuffer）
- 错误消息使用中文，与现有风格一致
- `finally` 块中清理 `sessions.delete(subSessionID)` 必须保留
- 子会话注册（sessions.set + task session 映射写入）保持不变

---

## §4 验收标准

### 4.1 功能验收

| 验收项 | 验证方法 |
|--------|---------|
| delegate_analysis 不再使用 session.prompt | `grep "session.prompt" security-analysis.ts` 无结果（排除 promptAsync） |
| delegate_analysis 使用 promptAsync | `grep "promptAsync" security-analysis.ts` 有结果 |
| 轮询超时后子会话被 abort | 代码中 pollSubSession 函数有 abort 调用 |
| 轮询间隔和超时可配置 | POLL_INTERVAL_MS 和 DEFAULT_POLL_TIMEOUT_MS 为顶层常量 |
| 结果提取正确 | fetchSessionResult 从 assistant message 的 text parts 提取内容 |
| sessions Map 清理在 finally 中 | 代码检查 |

### 4.2 回归验收

| 验收项 | 验证方法 |
|--------|---------|
| security-analysis.ts 语法正确 | `node --check` 通过 |
| Plugin export 正确 | 文件存在且 export 不变 |
| 其他 hook 不受影响 | system.transform / tool.execute.before / tool.execute.after 代码未被修改 |
| 子会话创建逻辑不变 | sessions.set + task session 映射写入代码未被修改 |

### 4.3 架构验收

| 验收项 | 验证方法 |
|--------|---------|
| 知识库文件在正确位置 | `binary-analysis/knowledge-base/subsession-orchestration.md` 存在 |
| 知识库文件自包含 | 人工阅读确认不依赖主 prompt 上下文 |
| 依赖方向未违反 | Plugin 文件不引用 mobile-analysis 或 web-analysis 目录 |

---

## §5 与现有需求文档的关系

| 需求文档 | 关系 |
|---------|------|
| `2026-05-22-security-coordinator.md` | 本次需求修复 coordinator 的核心工具，是 coordinator 需求的延续 |
| `2026-05-23-enforce-no-ask-user.md` | 本次保留 question deny 权限设置，无冲突 |
| `2026-05-05-web-analysis-agent.md` | 无关，web-analysis agent prompt 不变 |
