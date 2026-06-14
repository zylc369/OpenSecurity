# 环境信息注入时机修复 + Plugin 层变量替换

## §1 背景与目标

### 来源
2026-05-30 复盘：mobile-analysis agent 初始化时尝试读取 `~/.config/opencode/shared/knowledge-base/*`（不存在的路径），
触发项目外路径权限申请。此问题反复出现多次。

### 根因
OpenCode 新会话 step=1 时 fork 标题生成请求（`prompt.ts:1294`），它先触发 `system.transform`，
消耗 count=1 的注入槽位。主聊天请求拿到 count=2，`2 % 5 ≠ 1`，跳过环境信息注入。
LLM 在主聊天中看不到 `$SHARED_DIR` 等变量的实际值，猜测路径为 `~/.config/opencode/shared/`（错误）。

每次新会话第一条消息 100% 复现。

### 预期收益
- 上下文：从"有时缺失"变为"始终可用"
- 轮次：消除因路径错误导致的权限申请→用户拒绝→重试的浪费轮次
- 准确度：消除 LLM 猜错路径导致的文件读取失败

## §2 技术方案

### 方案 A：每次注入环境信息

**改动文件**: `plugins/security-analysis.ts`

将 `system.transform` hook 中的注入频率从"每 5 次"改为"每次"：
- 删除 `session.systemTransformCount` 计数器
- 删除 `shouldInject` 判断
- 每次 system.transform 调用都执行 env info 注入和 config 缺失检查

**注意**: 标题生成请求也会触发注入（~860 字符浪费到标题 prompt 中），但无害。
Plugin 无法区分标题生成和主聊天请求（input 只有 `sessionID` + `model`）。

### 方案 B：Plugin 层变量替换

**改动文件**: `plugins/security-analysis.ts`

在 snippet 展开之后、env info 注入之前，对 `output.system` 中的 agent prompt 做变量替换：
将 `$OPENCODE_ROOT`、`$AGENT_DIR`、`$SHARED_DIR`、`$PYTHON_CMD` 替换为实际路径值。

**替换时机**: 在 snippet 展开之后（因为展开后的 snippet 内容可能包含这些变量引用）

**替换范围**: 仅替换确定有值的变量（`$TASK_DIR` 可能为 null，不替换）

**替换变量列表**:
| 变量 | 来源 | 条件 |
|------|------|------|
| `$OPENCODE_ROOT` | `OPENCODE_ROOT` 常量 | 始终替换 |
| `$AGENT_DIR` | `getScriptDir(agentName)` | agentName 有映射时 |
| `$SHARED_DIR` | `join(OPENCODE_ROOT, AGENT_BINARY_ANALYSIS)` | 始终替换 |
| `$PYTHON_CMD` | `PYTHON_CMD` 常量 | 始终替换 |

**不替换的变量**:
- `$TASK_DIR` — 可能为 null（未初始化），由 agent 通过 bash 命令赋值
- `$IDAT` — 需 config.ida_path，且仅 binary-analysis agent 使用

**实现**: 构建变量→实际值的映射数组，遍历 `output.system` 逐元素做 replace。
替换逻辑放到独立函数中（`expandVariables`），与 `loadSnippet` 同级。

函数签名:
```typescript
function expandVariables(
  system: string[],
  agentName: string | undefined,
  sessionID?: string,
): void
```
- `system`: `output.system` 数组，就地修改
- `agentName`: 当前 agent 名，用于构建 `$AGENT_DIR` 映射
- `sessionID`: 仅用于 debug 日志
- 无返回值，直接修改 `system` 数组

### 数据格式变化
无。仅 Plugin 内部逻辑变更，不改变 JSON 输出格式或 agent prompt 文件。

### 架构影响
无。改动仅在 Plugin 的 `system.transform` hook 内部，不影响其他 hook 或外部接口。

## §3 实现规范

### 改动范围表

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `plugins/security-analysis.ts` | 修改 | 1) 删除 counter 逻辑 2) 新增 expandVariables 函数 3) 在 system.transform 中调用 |

### §3.1 实施步骤拆分

**步骤 1. 删除 systemTransformCount 计数器和 shouldInject 判断**
- 文件: `plugins/security-analysis.ts`
- 预估行数: ~10 行（删除 counter 递增、shouldInject 判断、if 分支）
- 验证点: `node --check` 语法检查通过
- 依赖: 无

**步骤 2. 新增 expandVariables 函数**
- 文件: `plugins/security-analysis.ts`
- 预估行数: ~25 行（函数签名 + 变量映射构建 ~10 行 + 遍历替换 ~10 行 + debug 日志 ~5 行）
- 验证点: `node --check` 语法检查通过
- 依赖: 无

**步骤 3. 在 system.transform hook 中调用 expandVariables**
- 文件: `plugins/security-analysis.ts`
- 预估行数: ~5 行（函数调用 + debug 日志）
- 调用位置: 在 snippet 展开循环（`for (let i = 0; i < output.system.length; i++)`）之后、完整性检查 `output.system.unshift(...)` 之前调用。此位置确保 snippet 展开后产生的变量引用也能被替换
- 验证点: `node --check` 语法检查通过 + 手动验证变量替换日志
- 依赖: 步骤 2

**步骤 4. 清理 SessionData 中不再使用的 systemTransformCount 字段**
- 文件: `plugins/security-analysis.ts`
- 预估行数: ~3 行（删除接口字段定义和 doEnsureSession 中的初始化赋值 `systemTransformCount: 0`）
- 验证点: `node --check` 语法检查通过 + grep 确认 `systemTransformCount` 在整个文件中无残留引用
- 依赖: 步骤 1（必须先删除 counter 用法，再删除字段定义）

**步骤 5. 端到端验证**
- 文件: 无代码改动
- 验证点:
  - 启动 OpenCode，创建新 mobile-analysis session
  - 确认第一条消息即可读取知识库文件，无权限申请
  - 确认 env info 在每次 LLM 请求中都被注入（检查日志）
  - 确认变量替换日志出现（$SHARED_DIR 等被替换为实际路径）
- 依赖: 步骤 1-4

## §4 验收标准

### 功能验收
1. 新会话第一条消息即可正确读取 `$SHARED_DIR/knowledge-base/task-initialization.md`，无权限申请
2. Plugin 日志显示每次 system.transform 都注入了环境信息
3. Plugin 日志显示变量替换已执行（$SHARED_DIR → 实际路径）
4. LLM 不再猜测路径（不出现 `~/.config/opencode/shared/`）

### 回归验收
1. binary-analysis agent 正常工作（idat 命令、脚本调用）
2. mobile-analysis agent 正常工作（apktool、jadx 命令）
3. web-analysis agent 正常工作
4. security-analysis-evolve agent 正常工作（当前 agent）
5. 上下文压缩后环境信息恢复正常（compacting hook 不受影响）
6. config.json 缺失时的拦截仍正常工作

### 架构验收
1. 未新增外部依赖
2. Plugin 导出接口未变更
3. agent prompt 文件未变更（变量替换在运行时完成）

## §5 与现有需求文档的关系

- `2026-05-26-plugin-inject-python-cmd.md` — 之前优化了 `$PYTHON_CMD` 注入，本次进一步确保每次注入
- `2026-05-03-agent-prompt-snippets.md` — 引入了 snippet 展开机制，本次在其后追加变量替换
- 两者无冲突，本次是补充增强
