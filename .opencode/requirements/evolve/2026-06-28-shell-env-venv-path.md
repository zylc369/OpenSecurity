# 需求: shell.env 注入 venv/bin 到 PATH

## §1 背景与目标

**来源痛点**: crypto-analysis agent 用 sage CLI（知识库代码示例为 `sage script.sage`），但 venv/bin 不在 shell PATH。其他会话已实际遇到 `sage: command not found`，需手动用完整路径 `/Users/.../.venv/bin/sage` 绕过。

**根因**: shell.env hook 当前只注入绝对路径变量（PYTHON_CMD/IDAT/AGENT_DIR...），刻意不碰 PATH——因为 `$PYTHON_CMD` 是绝对路径，绕过了 PATH。但 sage CLI 没有 `$SAGE` 变量，裸命令 `sage` 依赖 PATH 解析，而 venv/bin 不在 PATH。

**技术可行性（已验证）**: 从 opencode 二进制提取的 `ShellTool.shellEnv` 逻辑确认：
```js
return {...process.env, ...hookOutput.env}  // hook 的 output.env 覆盖 process.env
```
故 `output.env.PATH = X` 会覆盖子进程 PATH，方案可行。

**预期收益**:
- crypto-analysis 的 `sage` 命令直接可用，知识库代码示例无需改
- venv 的所有 CLI 工具（sage/pip 等）对所有 security agent 可用
- `python` 也指向 venv python（与 `$PYTHON_CMD` 一致，期望行为）

**用户决策**: 方案 A（注入 venv/bin 到 PATH），对所有 security agent 生效。

## §2 技术方案

在 `security-analysis.ts` 的 `shell.env` hook 里，PYTHON_CMD 注入后追加 PATH 注入：
```ts
const pythonCmd = getPythonCmd();
if (pythonCmd) {
  output.env.PYTHON_CMD = pythonCmd;
  const venvBin = dirname(pythonCmd);              // venv 可执行目录(POSIX:bin, Windows:Scripts)
  output.env.PATH = [venvBin, process.env.PATH].filter(Boolean).join(delimiter);
}
```
- `dirname(pythonCmd)` 得到 venv 的可执行目录（POSIX: `bin`，Windows: `Scripts`，自动适配平台）
- `filter(Boolean).join(delimiter)` 过滤空 PATH 避免末尾分隔符(=当前目录, PATH injection 风险)；`delimiter`(POSIX:`:` Windows:`;`)跨平台，与 constants.ts 的 Windows 支持一致
- 与 PYTHON_CMD 同条件（pythonCmd 非 null），保证 venv 就绪才注入

**为什么不按 agent 区分**：venv 是体系共享 Python 环境（`$PYTHON_CMD` 已对所有 agent 注入），venv/bin 加 PATH 是自然延伸；统一注入避免"哪个 agent 需要哪个不需要"的判断；注入 PATH 不被 LLM 模仿累积（环境变量不出现在 command 字符串）。

**副作用分析**：venv/bin 前置后，`python`/`pip` 也指向 venv。这与体系约定一致（agent prompt 要求用 `$PYTHON_CMD`=venv python），不产生歧义。

## §3 实现规范

### 改动范围表

| 项目 | 内容 |
|------|------|
| 修改文件 | `plugins/security-analysis.ts`（import 加 dirname；shell.env hook 加 PATH 注入；debugLog 记录 PATH） |
| 新增文件 | 无 |
| 高风险 | Plugin 改动（影响所有 security agent 的 shell 环境） |

### §3.1 实施步骤拆分

```
步骤 1. import 加 dirname/delimiter + shell.env hook 注入 PATH
  - 文件: plugins/security-analysis.ts
    - 第 2 行: `import { join } from "path";` → `import { join, dirname, delimiter } from "path";`
    - shell.env hook: PYTHON_CMD 注入块内追加 PATH 注入（filter(Boolean).join(delimiter)，+4 行）
  - 预估行数: 改动 ~6 行
  - 验证点: bun transpile 通过（node 不支持 TS 语法检查）；shell.env hook 逻辑正确（pythonCmd 非 null 时注入 PATH）
  - 依赖: 无

步骤 2. debugLog 记录 PATH 注入
  - 文件: plugins/security-analysis.ts（shell.env hook 的 debugLog）
  - 预估行数: 改动 ~1 行（加 PATH=... 到日志模板）
  - 验证点: debugLog 含 PATH 字段（便于排查）
  - 依赖: 步骤 1

步骤 3. 端到端验证
  - 验证: ① bun transpile 通过；② crypto-analysis session 的 shell 里 `sage --version` 直接可用（无需完整路径）；③ `$PYTHON_CMD -c "print('ok')"` 仍正常；④ PATH 含 venv/bin；⑤ PATH 为空时不产生末尾分隔符（无 PATH injection）
  - 依赖: 全部
```

## §4 验收标准

### 功能验收
- [ ] bun transpile security-analysis.ts 通过（node 不支持 TS 语法检查）
- [ ] shell.env hook 注入 PATH（pythonCmd 非 null 时）
- [ ] debugLog 记录 PATH
- [ ] crypto-analysis session 的 shell 里 `sage --version` 直接可用

### 回归验收
- [ ] `$PYTHON_CMD` 仍正常（PYTHON_CMD 注入不受影响）
- [ ] 其他环境变量（SESSION_ID/AGENT_DIR/IDAT 等）不受影响
- [ ] pythonCmd 为 null 时不注入 PATH（不破坏无 venv 的兜底场景）

### 架构验收
- [ ] 改动仅在 shell.env hook，不涉及其他 hook
- [ ] 遵循现有注入模式（output.env.XXX）

## §5 与现有需求文档的关系

独立需求。与 `2026-06-27-crypto-analysis-agent.md`（crypto agent 创建）和 `2026-06-28-crypto-knowledge-completion.md`（知识库完善）配套——前两者建立了 crypto 能力，本需求修复其运行环境（sage CLI 可用性）。
