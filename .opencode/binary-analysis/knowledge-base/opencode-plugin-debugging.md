# OpenCode Plugin 测试与排查指南

> SecurityAnalysis Plugin（`.opencode/plugins/security-analysis.ts`）的测试方法和问题排查流程。
> **警告**: Plugin API 可能随 OpenCode 版本变化，排查时注意版本差异。

## 测试方法

### 1. 语法检查

```bash
node --check .opencode/plugins/security-analysis.ts
```

验证 JS 语法正确，无模块解析错误。**这只能验证语法，不能验证 hook 是否正确触发。**

### 2. Plugin 加载验证

启动 OpenCode TUI 后，观察是否有 plugin 加载错误：

1. 启动 OpenCode
2. 发送一条消息
3. 观察：
   - 如果 `system.transform` 正常工作，Agent 的系统提示中应包含环境信息段
   - 如果 `compacting` hook 正常工作，压缩后 Agent 应仍能看到分析状态保留（TASK_DIR、已完成的分析结论）
   - 如果 `event` hook 正常工作，session 创建/删除不会报错

### 3. 环境信息注入验证

**验证 system.transform 是否生效**:

1. 环境信息由 system.transform 每轮注入（plugin 启动即生效，无需任何前置文件）
2. 切换到 BinaryAnalysis Agent（Tab 键）
3. 让 Agent "描述一下当前的环境信息"
4. 如果 Agent 能说出 IDA 路径、脚本目录、编译器信息 → `system.transform` 正常
5. 如果 Agent 说"未看到环境信息" → `system.transform` 未生效

**可能原因**:
- 环境变量缺失 → 查 plugin 日志中 system.transform 段；IDA_PRO_HOME 存于 $OPENCODE_ROOT/.ai_env
- Plugin 文件不在 `.opencode/plugins/` 目录
- Plugin 导出名称不是默认导出（应为 `export const SecurityAnalysisPlugin = ...`）

### 4. Compacting Hook 验证

**验证方法**:
1. 启动长对话，让上下文积累到触发压缩
2. 压缩后让 Agent "描述当前的任务目录和已完成的分析结论"
3. 如果 Agent 能说出 TASK_DIR 路径和之前的分析进度 → compacting hook 正常（分析状态保留 + justCompacted 触发 system.transform 重注入环境信息）
4. 如果 Agent 完全不知道任务目录或分析进度 → compacting hook 未生效（检查 output.context.push 和 justCompacted 标识）

**注**: agent prompt 本身在系统提示（不随压缩丢失），无需验证"规则保留"——规则丢失说明系统提示注入有问题，不是 compacting 问题。

**触发压缩的快捷方式**: 对话足够长后，OpenCode 会自动压缩。也可以在 OpenCode 设置中调低压缩阈值来加速测试。

---

## 排查流程

### 问题: Agent 完全不遵守 BinaryAnalysis 规则

```
检查 Agent 是否正确加载:
  1. .opencode/agents/binary-analysis.md 是否存在？
  2. frontmatter 格式是否正确？（--- 包裹的 YAML）
  3. 在 OpenCode TUI 中按 Tab，能看到 "binary-analysis" Agent 吗？

检查 Plugin 是否加载:
4. .opencode/plugins/security-analysis.ts 是否存在？
5. 语法是否正确？
6. 导出是否正确？（export const SecurityAnalysisPlugin = ...）

如果 Agent 加载但规则丢失:
  → 可能是压缩后丢失 → 检查 compacting hook
```

### 问题: 环境信息未注入

```
1. 控制台是否运行？
   → 端口文件 ~/bw-security-analysis/.opencode-control.port 首行即端口
   → curl http://127.0.0.1:<端口>/health 应返回 200

2. IDA_PRO_HOME 是否配置？
   → grep '^IDA_PRO_HOME=' $OPENCODE_ROOT/.ai_env
   → 配置后 shell.env 才会注入 $IDAT

3. output.system 是否正确使用？
   → 必须用 output.system.push(text)，不能是 output.system = text
```

### 问题: 压缩后分析状态丢失

```
1. compacting hook 的 output.context.push() 是否正确？
   → output 类型是 { context: string[] }

2. COMPACTION_CONTEXT_PROMPT 内容是否包含关键信息？
   → 检查 security-analysis.ts 中的 buildCompactionContextPrompt 函数

3. 压缩模型的上下文窗口是否足够？
   → 如果注入内容太长，可能被截断
```

### 问题: Plugin 加载报错

```
1. 查看 OpenCode 日志
   → 日志位置: /tmp/oh-my-opencode.log（Linux/Mac）或 %TEMP%\oh-my-opencode.log（Windows）

2. 检查 Plugin 文件编码
   → 必须是 UTF-8

3. 检查 ESM 语法
   → 使用 .ts 扩展名
   → import/export 语法正确

4. 检查 fs/path 等模块导入
   → Plugin 运行在 Node.js/Bun 环境，可以使用 fs、path、os 等
```

---

## 日志位置

| 平台 | 路径 |
|------|------|
| Linux/Mac | `/tmp/oh-my-opencode.log` |
| Windows | `%TEMP%\oh-my-opencode.log` |

oh-my-openagent 使用 `src/shared/logger.ts` 写日志，包含 hook 创建、事件分发、错误等信息。

---

## 端到端测试场景

### 场景 1: 基本功能测试

1. 启动 OpenCode，切换到 BinaryAnalysis Agent
2. 输入一个 .i64 文件路径和简单查询（如"列出所有函数"）
3. 验证：Agent 是否正确调用 idat、解析结果、输出分析摘要

### 场景 2: 环境信息测试

1. 确认控制台健康（curl http://127.0.0.1:<端口>/health → 200）
2. 切换到 BinaryAnalysis Agent
3. 问"当前环境有哪些工具？"
4. 验证：Agent 应列出 capstone、unicorn、gmpy2 等信息

### 场景 3: 压缩后分析状态保持测试

1. 进行长对话（直到触发压缩），期间产出分析结论（如已识别的函数地址）
2. 压缩后问"当前任务目录在哪？之前分析了什么？"
3. 验证：Agent 应能说出 $TASK_DIR 路径和已完成的分析结论（compacting 注入分析状态 + justCompacted 触发环境信息重注入）

---

## 常见问题 FAQ

| 问题 | 原因 | 解决 |
|------|------|------|
| Plugin 语法检查通过但不生效 | 导出名称不匹配 | 确认 `export const SecurityAnalysisPlugin` |
| 环境信息为空 | 控制台未启动或 IDA_PRO_HOME 未配置 | 控制台健康检查 + 配置页设置 IDA_PRO_HOME |
| 压缩后环境信息/分析状态丢失 | compacting 未注入或 justCompacted 未触发 system.transform 重注入 | 检查 output.context.push() + session.justCompacted 标识 |
| Agent 未在 Tab 列表中显示 | frontmatter 格式错误 | 检查 YAML --- 分隔符 |
| Agent 加载但不读知识库 | prompt 中引用路径错误 | 确认使用 `$SHARED_DIR/knowledge-base/` |
