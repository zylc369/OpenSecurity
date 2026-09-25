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
