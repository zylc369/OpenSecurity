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
   - 如果 `compacting` hook 正常工作，压缩后 Agent 应仍遵守关键规则
   - 如果 `event` hook 正常工作，session 创建/删除不会报错

### 3. 环境信息注入验证

**验证 system.transform 是否生效**:

1. 确保 `~/bw-security-analysis/config.json` 存在且有效
2. 切换到 BinaryAnalysis Agent（Tab 键）
3. 让 Agent "描述一下当前的环境信息"
4. 如果 Agent 能说出 IDA 路径、脚本目录、编译器信息 → `system.transform` 正常
5. 如果 Agent 说"未看到环境信息" → `system.transform` 未生效

**可能原因**:
- `config.json` 不存在或格式错误 → 检查文件内容和路径
- `env_cache.json` 不存在 → 运行 `detect_env.py --force` 生成
- Plugin 文件不在 `.opencode/plugins/` 目录
- Plugin 导出名称不是默认导出（应为 `export const SecurityAnalysisPlugin = ...`）

### 4. Compacting Hook 验证

**验证方法**:
1. 启动长对话，让上下文积累到触发压缩
2. 压缩后让 Agent "列出 BinaryAnalysis 的关键规则"
3. 如果 Agent 能列出 ①-⑧ 规则 → compacting hook 正常
4. 如果 Agent 完全不知道规则 → compacting hook 未生效

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
1. config.json 路径是否正确？
   → ~/bw-security-analysis/config.json
   → Windows: C:\Users\<用户名>\bw-security-analysis\config.json

2. config.json 格式是否有效 JSON？
   → 用 python -c "import json; json.load(open('config.json'))" 验证

3. env_cache.json 是否存在？
   → 同目录下，运行 detect_env.py 生成

4. output.system 是否正确使用？
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

1. 确认 `~/bw-security-analysis/config.json` 和 `env_cache.json` 存在
2. 切换到 BinaryAnalysis Agent
3. 问"当前环境有哪些工具？"
4. 验证：Agent 应列出 capstone、unicorn、gmpy2 等信息

### 场景 3: 压缩后规则保持测试

1. 进行长对话（直到触发压缩）
2. 压缩后问"BinaryAnalysis 有哪些关键规则？"
3. 验证：Agent 应至少知道"禁止作弊式验证"、"计算密集型用 C"等核心规则

---

## 常见问题 FAQ

| 问题 | 原因 | 解决 |
|------|------|------|
| Plugin 语法检查通过但不生效 | 导出名称不匹配 | 确认 `export const SecurityAnalysisPlugin` |
| 环境信息为空 | config.json 不存在 | 创建 `~/bw-security-analysis/config.json` |
| 压缩后规则丢失 | compacting hook 未注入 | 检查 output.context.push() 调用 |
| Agent 未在 Tab 列表中显示 | frontmatter 格式错误 | 检查 YAML --- 分隔符 |
| Agent 加载但不读知识库 | prompt 中引用路径错误 | 确认使用 `$SHARED_DIR/knowledge-base/` |
