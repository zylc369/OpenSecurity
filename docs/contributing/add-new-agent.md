# 如何为 OpenSecurity 添加新 Agent

这篇指南会带你从零创建一个新的安全分析 Agent——从职责设计、prompt 编写、工具脚本组织，到 Plugin 注册、Coordinator 集成、测试验证。

> 阅读前建议先看完 [项目深度介绍](../项目介绍/open-security-介绍.md)，理解平台的三层架构（编排层 / 工具层 / 知识库层）。

## 一、什么时候需要新 Agent

先问自己三个问题：

| 问题 | 是 | 否 |
|------|-----|-----|
| 这个领域有**独特的工具链**吗？（不是 IDA / Frida / HTTP 客户端的简单组合） | → 候选 | → 考虑扩展现有 Agent |
| 这个领域有**独特的分析方法论**吗？（不只是套用已有模板） | → 候选 | → 考虑扩展现有 Agent |
| 这个领域会**经常被独立使用**吗？（用户经常单独提这类任务） | → 候选 | → 考虑做成现有 Agent 的子能力 |

**三个都是"是"** → 创建新 Agent。

**部分是** → 优先考虑扩展现有 Agent（在它的 `knowledge-base/` 里加文档，或在工具层加脚本）。新 Agent 的维护成本不低，能复用就复用。

### 已有 Agent 的职责边界（避免重叠）

| 现有 Agent | 边界 |
|------------|------|
| `binary-analysis` | 静态/动态分析任意二进制（PE/ELF/Mach-O/.so/.dylib/.sys） |
| `mobile-analysis` | APK/IPA 整体分析（含 Java/smali 层），需要逆向 native 库时**调用** binary-analysis |
| `web-analysis` | URL 或源码的漏洞审计，不涉及客户端应用本身 |
| `ai-security-analysis` | LLM 应用的应用层和模型层攻击 |

**例子**：
- 想分析 IoT 固件 → 新 Agent（独特工具链：binwalk、固件解包、嵌入式架构）
- 想分析 PWN 题 → 扩展 binary-analysis（在它的知识库里加 pwn 方法论）
- 想分析区块链智能合约 → 新 Agent（独特工具链：EVM 反编译、链上数据）
- 想分析 macOS 应用 → 扩展 mobile-analysis（IPA 路径覆盖一部分，其余加知识库）

## 二、完整流程（7 步）

### 步骤 1：设计 Agent 职责边界

动笔前先回答：

1. **输入是什么**：文件路径？URL？源码目录？模型名？
2. **输出是什么**：漏洞列表？算法描述？license/key？攻击 PoC？
3. **核心工具链**：列出 5-10 个这个 Agent 必备的工具
4. **与现有 Agent 的协作关系**：会调用其他 Agent 吗？会被其他 Agent 调用吗？
5. **场景分类**：常见的分析场景有哪几类？（参考 binary-analysis 的场景分类：CTF / 壳 / 驱动 / 算法）

把答案写到 PR 描述里，让 reviewer 理解你的设计意图。

### 步骤 2：创建 Agent prompt

新建 `.opencode/agents/<your-agent>.md`。

**最小可用的 frontmatter**：

```markdown
---
description: 一句话说明这个 Agent 做什么 — 输入 X，自动完成 Y
mode: all
buwai-extension-id: <your-agent>
permission:
  external_directory:
    ~/bw-security-analysis/**: allow
    ~/Downloads/**: allow
  read:
    "~/Downloads/**/*.env": allow
    "~/Downloads/**/*.env.*": allow
---
```

字段说明：
- `description`：显示在 OpenCode TUI 的 Agent 切换菜单，要简短有信息量
- `mode: all`：允许在主 session 和子 session 中使用（详见 OpenCode 文档）
- `buwai-extension-id`：**必须与文件名一致**，Plugin 据此判断是否做占位符展开
- `permission`：固定模板，允许 Agent 读写任务目录和 Downloads

**prompt 正文骨架**（参考 `binary-analysis.md` 的结构）：

```markdown
## 角色

你是 <领域> 安全分析编排器。你的职责是：
1. <职责 1>
2. <职责 2>
3. ...

**可用工具**：Bash、Read、Write、Glob/Grep、<其他>

**核心约束**：
- <约束 1>
- <约束 2>

---

## 阶段 0：任务初始化（强制）

{{buwai-rule:task-initialization}}

---

## 分析执行框架（强制）

### 阶段 A：信息收集（自动、强制）
<列出初始分析流水线>

### 阶段 B：分析规划（强制）
<读取 knowledge-base/analysis-planning.md，按场景选方案>

### 阶段 C：执行与监控
{{buwai-rule:execution-discipline}}

### 循环控制
{{buwai-rule:loop-control}}

---

## 知识库索引

| 文档 | 触发条件 |
|------|---------|
| `<topic>.md` | <何时加载> |

---

## 输出格式

{{buwai-rule:output-format}}

> **Agent 专属补充**：
> - <领域特有的输出要求>

---

## 后续交互处理

- 记住当前会话中的 <关键状态>
- 新问题针对同一目标 → <如何处理>

### 变量丢失自愈（压缩恢复后执行）

如果上下文压缩后变量丢失，从 Plugin 注入的环境信息段重新提取。

---

## 任务存档

{{buwai-rule:task-archive}}

---

## 安全规则

- <领域特有的安全红线>
- 失败后不静默忽略，必须说明失败原因
```

**关键原则**：
- 大量复用 `agents-rules/` 里的共享片段，减少重复
- 领域特有的逻辑（工具脚本调用、场景分类、验证模式）才写在自己 prompt 里
- 不要把知识库内容塞进 prompt，用"知识库索引"表登记触发条件

### 步骤 3：创建工具与知识库目录

```
.opencode/<your-agent>/
├── README.md              # 工具脚本说明（参考 binary-analysis/README.md）
├── scripts/
│   ├── registry.json      # 脚本注册表
│   ├── initial_analysis.py  # 阶段 A 的初始分析流水线
│   └── <其他脚本>.py
└── knowledge-base/
    ├── analysis-planning.md  # 阶段 B 的方案模板
    └── <其他知识库文档>.md
```

**最小内容**：
- `scripts/registry.json`：空对象 `{}` 即可，后续沉淀脚本时填充
- `scripts/initial_analysis.py`：实现阶段 A 的初始信息收集（输出 JSON）
- `knowledge-base/analysis-planning.md`：列出场景分类和对应方案

**关于工具脚本**：
- 如果脚本是纯 Python（不依赖 IDA），直接写标准 Python
- 如果脚本走 IDA headless，必须遵守 [IDAPython 编码规范](../../.opencode/binary-analysis/knowledge-base/idapython-conventions.md)
- **优先复用 binary-analysis 的基础层**：`from _base import ...`、`from _utils import ...`（通过 `$SHARED_DIR` 访问）

**单向依赖规则**：
- 你的 Agent **可以**引用 `binary-analysis/` 的脚本和知识库（通过 `$SHARED_DIR`）
- 你的 Agent **不可以**被 `binary-analysis/` 反向引用
- 你的 Agent 与 `mobile-analysis/`、`web-analysis/`、`ai-security-analysis/` 之间**默认无依赖**，需要协作时通过 Coordinator 编排

### 步骤 4：在 Plugin 中注册

编辑 `.opencode/plugins/security-analysis.ts`，**改两处**：

```typescript
// 1. 新增常量（约第 30-44 行的 AGENT_* 常量区）
const AGENT_YOUR_AGENT = "your-agent";

// 2. 加入 PRIMARY_AGENTS 数组
const PRIMARY_AGENTS = [
  AGENT_BINARY_ANALYSIS,
  AGENT_MOBILE_ANALYSIS,
  AGENT_WEB_ANALYSIS,
  AGENT_AI_SECURITY_ANALYSIS,
  AGENT_SECURITY_ANALYSIS_EVOLVE,
  AGENT_SECURITY_COORDINATOR,
  AGENT_YOUR_AGENT,  // ← 新增
];

// 注意：AGENT_SCRIPT_DIRS 是循环生成的，加入 PRIMARY_AGENTS 后会自动添加映射
// 映射结果：AGENT_SCRIPT_DIRS["your-agent"] = join(OPENCODE_ROOT, "your-agent")
```

修改后**必须重启 OpenCode** 让 Plugin 重新加载。

### 步骤 5：（可选）注册到 Coordinator

如果你希望 Coordinator 能把复合任务分发到你的 Agent，编辑 `.opencode/agents/security-coordinator.md`：

在"可调用的专业 Agent"表格中加一行：

```markdown
| `your-agent` | <能力简述> | <适用场景> |
```

并在"决策流程"部分补充你的 Agent 与其他 Agent 的协作关系。

### 步骤 6：测试

**最小测试清单**：

1. **Plugin 加载验证**：启动 OpenCode，切换到你的 Agent，确认 system prompt 顶部出现：
   ```
   [系统完整性] Plugin 已加载。当前 Agent: your-agent。...
   ```

2. **环境信息注入验证**：确认 system prompt 包含 `## 全局环境和目录位置信息` 段，且 `$AGENT_DIR` 指向你的 Agent 目录。

3. **占位符展开验证**：确认 prompt 中的 `{{buwai-rule:xxx}}` 都被替换为实际内容（不是原始占位符文本）。

4. **端到端分析测试**：用一个真实目标跑完整流程：
   - 阶段 A 输出符合预期
   - 阶段 B 能根据场景选方案
   - 阶段 C 能调用工具脚本
   - 最终报告符合输出格式要求

5. **压缩恢复测试**（可选但推荐）：分析跑到中段时手动触发上下文压缩，确认 Agent 能恢复关键状态继续分析。

6. **idle 恢复测试**（可选）：让 Agent 跑到空闲，确认 Plugin 发送了恢复消息（检查任务目录下的 `logs/plugin.log`）。

### 步骤 7：文档更新

- [ ] `README.md` 的 Agent 表格加一行
- [ ] `docs/项目介绍/open-security-介绍.md` 的"六个 Agent"章节扩展（或改为"七个 Agent"）
- [ ] 你的 Agent 目录下的 `README.md` 写工具脚本说明
- [ ] 如果有独特概念，在 `docs/` 下补充专题文档

## 三、模板示例：最小可运行的 Dummy Agent

下面是一个端到端可运行的"echo Agent"，演示完整集成：

### `.opencode/agents/echo-analysis.md`

```markdown
---
description: Echo 分析 — 输入文件路径，输出文件基本信息（演示用）
mode: all
buwai-extension-id: echo-analysis
permission:
  external_directory:
    ~/bw-security-analysis/**: allow
    ~/Downloads/**: allow
  read:
    "~/Downloads/**/*.env": allow
    "~/Downloads/**/*.env.*": allow
---

## 角色

你是文件基本信息分析编排器。你的职责是：
1. 接收用户给出的文件路径
2. 调用 `initial_analysis.py` 收集文件元信息（大小、类型、hash）
3. 输出结构化报告

**可用工具**：Bash（执行 Python 脚本）、Read（读取输出）

**核心约束**：
- 不修改目标文件
- 失败时说明原因，不静默跳过

---

## 分析执行框架

### 阶段 A：信息收集（自动、强制）

\`\`\`bash
ECHO_OUTPUT="$TASK_DIR/initial.json" \
  "$PYTHON_CMD" "$AGENT_DIR/scripts/initial_analysis.py" "<目标文件>"
\`\`\`

读取 `$TASK_DIR/initial.json`，获取 size、mime、sha256、first_bytes。

### 阶段 B：报告产出

按输出格式整理结果。

---

## 输出格式

{{buwai-rule:output-format}}

> **Agent 专属补充**：
> - 必须包含：文件路径、大小、MIME 类型、SHA256、前 64 字节 hex 预览

---

## 后续交互处理

- 记住当前会话中的目标文件路径
- 用户追问细节 → 重新读取 `initial.json`

### 变量丢失自愈（压缩恢复后执行）

从 Plugin 注入的环境信息段重新提取变量。

---

## 任务存档

{{buwai-rule:task-archive}}

---

## 安全规则

- 只读分析，不修改目标文件
- 失败后不静默忽略，必须说明失败原因
```

### `.opencode/echo-analysis/scripts/initial_analysis.py`

```python
"""文件基本信息收集（演示用）"""
import hashlib
import json
import mimetypes
import os
import sys


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"success": False, "error": "未指定目标文件"}))
        sys.exit(1)

    target = sys.argv[1]
    if not os.path.exists(target):
        print(json.dumps({"success": False, "error": f"文件不存在: {target}"}))
        sys.exit(1)

    size = os.path.getsize(target)
    mime, _ = mimetypes.guess_type(target)

    sha256 = hashlib.sha256()
    with open(target, "rb") as f:
        first_bytes = f.read(64)
        sha256.update(first_bytes)
        # 大文件分块读完
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            sha256.update(chunk)

    result = {
        "success": True,
        "data": {
            "path": target,
            "size": size,
            "mime": mime or "application/octet-stream",
            "sha256": sha256.hexdigest(),
            "first_bytes": first_bytes.hex(),
        },
        "error": None,
    }

    output = os.environ.get("ECHO_OUTPUT")
    if output:
        with open(output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[*] 输出已写入 {output}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

### `.opencode/echo-analysis/scripts/registry.json`

```json
{}
```

### `.opencode/echo-analysis/README.md`

```markdown
# EchoAnalysis 工具脚本

演示用 Agent，仅包含一个初始分析脚本。

## 调用方式

\`\`\`bash
ECHO_OUTPUT=<输出路径> "$PYTHON_CMD" "$AGENT_DIR/scripts/initial_analysis.py" <目标文件>
\`\`\`
```

注册到 Plugin（步骤 4）后即可在 OpenCode 中切换到 `echo-analysis` 测试。

## 四、常见陷阱

### 1. `buwai-extension-id` 与文件名不一致

**症状**：占位符 `{{buwai-rule:xxx}}` 没被展开，LLM 看到的是原始文本。

**原因**：Plugin 通过 frontmatter 的 `buwai-extension-id` 字段判断是否做展开，它必须**与 `.md` 文件名（去掉扩展名）完全一致**。

**修复**：检查 `agents/<name>.md` 的 frontmatter。

### 2. 忘了在 Plugin 的 `PRIMARY_AGENTS` 注册

**症状**：Agent 能用，但 Plugin 不注入环境信息、不做工具拦截、不触发 idle 恢复。

**原因**：Plugin 只对 `PRIMARY_AGENTS` 列表里的 agent 做 hook 处理。

**修复**：在 `security-analysis.ts` 的 `PRIMARY_AGENTS` 数组中加入你的 agent 常量。

### 3. 工具脚本不走 `_base.py`

**症状**：脚本能跑，但日志格式不统一、JSON 输出不稳定、idat 不退出。

**原因**：直接 `import idc` 而不走 `_base.py` 的封装。

**修复**：参考 `binary-analysis/query.py` 的导入方式：
```python
from _base import run_headless, log, JSONEncoder, ...
from _utils import resolve_addr, ...
```

### 4. 知识库文档过大塞进 Agent prompt

**症状**：每次 LLM 请求 token 数暴涨，响应变慢。

**原因**：把知识库内容直接写进 `agents/<name>.md`，而不是放在 `knowledge-base/` 按需加载。

**修复**：大段专题内容移到 `knowledge-base/<topic>.md`，在 prompt 的"知识库索引"表格中登记触发条件。

### 5. 循环依赖

**症状**：你的 Agent 引用了 mobile-analysis 的内容，mobile-analysis 又想引用你的内容。

**修复**：遵守单向依赖规则。需要双向协作时，**通过 Coordinator 编排**，不要让两个 Agent 直接互相引用代码。

### 6. 没测试压缩恢复

**症状**：用户实际使用时遇到上下文压缩，Agent 丢失关键状态、重复已完成的步骤。

**修复**：测试时主动跑到中段，触发压缩（在 OpenCode 中可以模拟），确认 Agent 能恢复。

## 五、提交 PR 前的清单

- [ ] frontmatter 字段完整（`description`、`mode`、`buwai-extension-id`、`permission`）
- [ ] `buwai-extension-id` 与文件名一致
- [ ] 已在 `plugins/security-analysis.ts` 的 `PRIMARY_AGENTS` 注册
- [ ] （如需 Coordinator 分发）已更新 `security-coordinator.md`
- [ ] 工具脚本走 `_base.py` 封装（如适用）
- [ ] 知识库文档按需加载，未塞进 prompt
- [ ] 端到端测试通过（用一个真实目标）
- [ ] 压缩恢复测试通过
- [ ] README.md 的 Agent 表格已更新
- [ ] 自己的 Agent 目录下有 `README.md`

---

有疑问随时在 [GitHub Discussions](https://github.com/zylc369/OpenSecurity/discussions) 开帖讨论。新 Agent 是高价值贡献，我们会在 PR 阶段提供充分的 review 支持。
