# OpenCode 插件开发实战指南

> 从零创建 OpenCode Plugin 的完整流程，包含最小模板和常见模式。
> 前置阅读: `opencode-plugin-api.md`（API 签名）、`opencode-plugin-hooks-lifecycle.md`（时序与陷阱）。

## 一、最小 Plugin 模板

```typescript
// .opencode/plugins/my-plugin.ts
import type { Plugin } from "@opencode-ai/plugin";

export const MyPlugin: Plugin = async ({ directory }) => {
  return {
    "experimental.chat.system.transform": async (input, output) => {
      output.system.push("自定义系统提示内容");
    },
  };
};
```

**要点**:
- 文件放在 `.opencode/plugins/` 或 `~/.config/opencode/plugins/`
- 导出名称任意，但必须是具名导出且类型为 `Plugin`
- `directory` 参数是项目根目录路径
- 返回对象，key 为 hook 名，value 为处理函数

## 二、插件文件定位技巧

```typescript
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url));
const OPENCODE_ROOT = dirname(PLUGIN_DIR);
```

通过 `import.meta.url` 定位插件文件位置，向上推导目录结构。此机制同时支持项目级和全局安装。

## 三、状态管理模式

### 推荐：多 Map 模式

```typescript
const sessionData = new Map<string, string>();

export const MyPlugin: Plugin = async ({ directory }) => {
  return {
    "chat.message": async (input) => {
      const sid = (input as { sessionID?: string })?.sessionID;
      if (sid) sessionData.set(sid, "value");
    },

    event: async (input) => {
      if (input.event.type === "session.deleted") {
        const sid = input.event.properties?.sessionID as string;
        if (sid) sessionData.delete(sid);
      }
    },
  };
};
```

**清理规则**: `session.deleted` 中必须清理所有 Map 条目，否则内存泄漏。

### 读取 sessionID 的正确方式

```typescript
// event hook 中
const props = input.event.properties || {};
const sessionID = props.info?.id ?? props.sessionID;

// 其他 hook 中（如 chat.message、system.transform）
const sessionID = (input as { sessionID?: string })?.sessionID;
```

优先用 `props.info.id`（`session.created` 事件中更权威），回退到 `props.sessionID`。

## 四、常见 Hook 组合模式

### 模式 1：每轮注入系统提示

```typescript
"experimental.chat.system.transform": async (input, output) => {
  output.system.push(envInfo);
},
```

注意: `output.system` 每次 LLM 请求都重建（空数组），必须每次都 push。详见 `opencode-plugin-hooks-lifecycle.md` 规则 2。

### 模式 2：压缩时保留关键信息

```typescript
"experimental.session.compacting": async (input, output) => {
  output.context.push("压缩后必须保留的信息");
},
```

配合 `event` hook 的 `session.compacted` 事件做状态恢复。

### 模式 3：工具调用拦截

```typescript
"tool.execute.before": async (input, output) => {
  if (input.tool === "bash") {
    const cmd = output.args?.command;
    if (typeof cmd === "string") {
      output.args.command = `ENV_VAR=value ${cmd}`;
    }
  }
},
```

### 模式 4：session 生命周期管理

```typescript
event: async (input) => {
  const { event } = input;
  if (event.type === "session.created") {
    // 初始化状态（fire-and-forget，不保证顺序）
  }
  if (event.type === "session.deleted") {
    // 清理所有状态
  }
  if (event.type === "session.compacted") {
    // 压缩后恢复状态（只读事件）
  }
},
```

## 五、开发流程

### 步骤 1：确定需求

明确插件需要哪些 hook:
- 需要注入系统提示？→ `system.transform`
- 需要在压缩时保留信息？→ `compacting` + `event: session.compacted`
- 需要追踪 session 状态？→ `chat.message` + `event`
- 需要修改工具行为？→ `tool.execute.before/after`

### 步骤 2：编写插件

1. 参考 `opencode-plugin-api.md` 获取 hook 签名
2. 参考 `opencode-plugin-hooks-lifecycle.md` 理解执行时序
3. 从最小模板开始，逐步添加 hook

### 步骤 3：验证

1. `node --check .opencode/plugins/my-plugin.ts` — 语法检查
2. 启动 OpenCode，发送消息测试 hook 是否触发
3. 参考 `opencode-plugin-debugging.md` 排查问题

## 六、注意事项

### event hook 是 fire-and-forget

`session.created` 事件不阻塞宿主，不能在其中做需要顺序保证的逻辑。安全的做法是只做状态初始化（设置 Map 条目）。

### 子 session 需要继承父 session 状态

Task 工具创建子 session 时，通过 `parentID` 关联。插件应在 `chat.message` 中设置主 session 的 primaryAgent，子 session 通过 `ensureSession` 递归查询父链自动继承。

### 配置文件持久化

插件运行在 Node.js/Bun 环境，可以直接使用 `fs`、`path`、`os` 等模块读写文件。建议使用 `~/` 下的固定目录存储持久数据，避免污染项目目录。
