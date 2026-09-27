# OpenCode 开发参考

> Plugin/Agent 开发所需的文档索引与源码查阅流程。
> 触发: 涉及 Plugin Hook、Agent 文件格式、插件调试、需查 vendor 源码时。不依赖主 prompt 上下文即可理解。

---

## 知识库文档（优先查找）

| 文档路径 | 触发条件 |
|----------|---------|
| `$SHARED_DIR/knowledge-base/knowledge-writing-guide.md` | 沉淀知识到任何知识库文件之前 |
| `$SHARED_DIR/knowledge-base/opencode-plugin-api.md` | 查看 Hook 签名、input/output 类型 |
| `$SHARED_DIR/knowledge-base/opencode-plugin-hooks-lifecycle.md` | 理解 Hook 执行时序、awaited vs fire-and-forget、常见陷阱 |
| `$SHARED_DIR/knowledge-base/opencode-plugin-development-guide.md` | 从零创建插件、最小模板、状态管理模式 |
| `$SHARED_DIR/knowledge-base/opencode-agent-format.md` | 创建/修改 Agent 文件格式、frontmatter 字段（mode/hidden/tools/description 路由写法） |
| `$SHARED_DIR/knowledge-base/opencode-plugin-debugging.md` | 排查 Plugin 问题、测试验证方法 |
| `$SHARED_DIR/knowledge-base/idapython-conventions.md` | 生成 IDAPython 脚本时的编码规范 |

## 源码参考（知识库不足时）

| 源码 | 用途 |
|------|------|
| `vendor/opencode/packages/opencode/src/` | OpenCode 核心源码: session 管理、plugin 调度、LLM 交互、agent 加载（agent/agent.ts 的 frontmatter schema、tool/task.ts 的派发解析、session/prompt.ts 的列表注入过滤） |
| `vendor/oh-my-openagent/src/` | 社区参考插件: 完整 Plugin 实现示例（context collector、message transform、event 处理） |

查阅流程:
1. 先搜索上表知识库文档
2. 知识库无答案 → 在 `vendor/` 中搜索相关关键词（hook 名、函数名、类型签名）
3. 找到答案后，将新知识补充到对应知识库文档（下次不用再查源码）

## opencode 平台行为实证记录

### MCP 子进程 env 是合并语义（无白名单选项）

opencode spawn MCP server 时（`packages/opencode/src/mcp/index.ts`）:

```ts
env: {
  ...process.env,                    // 全量继承 opencode 主进程
  ...(cmd === "opencode" ? { BUN_BE_BUN: "1" } : {}),
  ...mcp.environment,                // 配置的 environment 铺在上面
}
```

- **语义**: `mcp.add` 的 `environment` 字段是**合并**（叠加覆盖同名键），
  不是替换——无法通过该字段剔除继承键（业务键/conda 杂键必然进入 MCP 子进程）。
- **字段名必须是 `environment`**: 历史上误写 `env` 被静默丢弃。
- **如需收紧 MCP env**: command 前置 `/usr/bin/env -i KEY=VAL ... <原command>`
  （exec 层清空一切父 env，只留显式键; win32 无 env 命令不适用; 已验证握手
  正常——本仓库当前未启用，MCP 保持合并语义直跑）。
- **验证方式**: MCP 子进程 `ps eww <pid>` 看 environ 键集合（快照=execve
  传入值，不反映运行时 os.environ 修改）。
