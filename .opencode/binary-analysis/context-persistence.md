# BinaryAnalysis 上下文持久化方案

## 问题

OpenCode 长对话中存在三类上下文丢失问题：
1. **规则丢失**: 多轮交互后 Agent 不再遵守 BinaryAnalysis 规则
2. **知识丢失**: 压缩后之前发现的分析结论（如"二进制有 bug，需要 r==1"）丢失
3. **环境丢失**: 每轮对话无法感知 IDA 路径、编译器、工具包等环境信息

## 当前方案：Plugin + 多 Agent 架构

### 架构

安装位置（二选一）：
- **项目级**: `<项目根>/.opencode/`
- **全局**: `~/.config/opencode/`

以下结构以项目级为例，全局安装时将 `.opencode/` 替换为 `~/.config/opencode/` 即可。

```
.opencode/                             # 或 ~/.config/opencode/
├── agents/
│   ├── binary-analysis.md            # IDA Pro 逆向分析 Agent
│   └── mobile-analysis.md            # 移动端分析 Agent
├── plugins/
│   └── security-analysis.ts          # Plugin（按 Agent 注入 + 动态 compacting）
├── binary-analysis/                   # IDA Pro 工具与知识库
└── mobile-analysis/                   # 移动端工具与知识库
```

### Plugin 使用的 Hooks

| Hook | 作用 | 触发时机 |
|------|------|---------|
| `chat.message` | 追踪 session 的当前 agent 和主 agent（primaryAgent），支持子 session 继承 | 用户发送消息时 |
| `experimental.session.compacting` | 按Agent注入分析状态保留提示 + 动态COMPACT_REMINDER | 上下文压缩前 |
| `experimental.chat.system.transform` | 按Agent注入环境信息（IDA路径、编译器、工具包、外部工具） | 每轮对话 |
| `tool.execute.before` | 注入 SESSION_ID 环境变量到 bash 命令 | 工具执行前 |
| `event` | 管理 session 生命周期（created/deleted/compacted），子 session primaryAgent 继承 | session 状态变化 |

### Hook API 签名（基于 oh-my-openagent 源码确认）

```typescript
// chat.message: 追踪 agent 映射
async (input: {
  sessionID: string;
  agent?: string;
  model?: { providerID: string; modelID: string };
}, output: {
  message: Record<string, unknown>;
  parts: Array<{ type: string; text?: string }>;
}) => Promise<void>

// system.transform: 修改系统提示
(input: { sessionID?: string; model: { id: string; providerID: string; [key: string]: unknown } },
 output: { system: string[] }) => Promise<void>
// 使用 output.system.push(content) 注入

// compacting: 压缩时注入上下文
(input: { sessionID: string },
 output: { context: string[] }) => Promise<void>
// 使用 output.context.push(content) 注入

// tool.execute.before: 工具执行前拦截
(input: { tool: string; sessionID?: string; args: Record<string, unknown> },
 output: { args: Record<string, unknown> }) => Promise<void>

// event: 响应 session 生命周期事件
(input: { event: { type: string; properties?: Record<string, unknown> } }) => Promise<void>
// 事件类型: session.created, session.deleted, session.compacted
```

### 路径自定位机制

Plugin 通过 `import.meta.url` 自定位：插件文件位于扩展目录下的 `plugins/security-analysis.ts`，由此推导 `PLUGIN_DIR`（plugins/）和扩展根目录（Plugin 的父目录）。Agent 脚本目录由 Plugin 根据映射表（如 `binary-analysis` → `<扩展根>/binary-analysis`）推导并注入到系统提示，不依赖 config.json 中的路径配置。此机制同时支持项目级（`.opencode/`）和全局（`~/.config/opencode/`）安装。

### 数据流

1. **环境信息**（每轮）: `~/bw-security-analysis/config.json`（ida_path + tools）+ `env_cache.json` → Plugin 读取，按 Agent 过滤 tools → `system.transform` 注入到系统提示
2. **分析规则**（压缩时）: Plugin 动态生成 COMPACT_REMINDER（按 agentName） → `compacting` hook 注入
3. **分析状态**（压缩时）: Plugin 动态生成 compaction context（通用部分 + 按 agent 追加） → 告知压缩模型保留分析结论
4. **知识库**（按需）: Agent 通过 Read 工具按需加载 `knowledge-base/` 下的文档

### 环境数据缓存

- 环境检测结果缓存到 `~/bw-security-analysis/env_cache.json`，有效期 24 小时
- 检测脚本: `scripts/detect_env.py`
- Agent prompt 中有环境检测阶段指引

### 知识库按需加载

知识库文件位于 `knowledge-base/`，Agent prompt 中的"知识库索引"表列出每个文件的触发条件。Agent 不会在分析开始时全部加载，而是根据场景标签按需读取。

## 扩展方向

- **分析状态持久化**: 将分析中的关键发现写入 `~/bw-security-analysis/workspace/<task_id>/findings.json`，跨 session 复用
- **压缩后自动恢复**: 通过 `event` hook 的 `session.compacted` 事件，自动读取 findings.json 并注入
