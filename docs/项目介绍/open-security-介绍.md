# OpenSecurity：AI 驱动的多领域安全分析 Agent 平台

> 让 LLM 真正像一个"安全研究员团队"那样工作：会拆任务、会用 IDA Pro、会跑 Frida、会做 Web 渗透、会自我进化——而不是只会聊天。

## 一、为什么做这个项目

做安全分析的人都知道，一次完整的逆向或渗透任务里有大量重复性劳动：解包、反编译、字符串搜索、初轮壳检测、格式化输出……这些步骤本来就该脚本化，但每换一个目标就要重新拼一遍命令、重新走一遍流程。研究员真正有价值的判断（这个函数是不是加密入口、这个跳转是不是关键点、这个漏洞能不能利用）反而被淹没在工具调用的琐事里。

OpenSecurity 想做的事情很朴素：

**让 LLM 真正像一个研究员那样工作——拿到目标文件，自己编排工具链，一步步推进，最后产出一份可验证的报告。**

不是问一句答一句，不是停在"我建议你用 IDA 看看"，而是真的把 idat 启动起来、跑脚本、读输出、做推理、再决定下一步——直到任务完成。

要实现这个目标，需要解决三个具体问题：

1. **怎么让 LLM 操作专业工具**：IDA Pro、Frida、apktool 这些工具都有复杂的参数和输出格式，LLM 需要一个稳定的"接口层"才能可靠调用。
2. **怎么在长会话中保持上下文**：一次分析动辄几十轮工具调用、几个小时，LLM 的上下文窗口装不下，压缩又会丢失关键状态。
3. **怎么让平台越用越强**：每次实战中发现的模式（壳处理策略、算法识别技巧）应该沉淀下来，下次遇到类似场景直接复用。

后面整个项目的设计，都是在回答这三个问题。

## 二、整体架构

整个平台构建在 [OpenCode](https://github.com/anomalyco/opencode) 之上（一个开源的 AI 编程 Agent 框架），在其之上做了一层安全分析专用的扩展：

```
.opencode/
├── agents/                          # 6 个 Agent 的主 prompt（LLM 的"工作守则"）
│   ├── security-coordinator.md      # 编排器：复合安全任务拆分 + 分发到专业 Agent
│   ├── binary-analysis.md           # 二进制逆向：算法还原、壳检测、漏洞挖掘
│   ├── mobile-analysis.md           # 移动端逆向：APK/IPA 反编译与 Java/Native 分析
│   ├── web-analysis.md              # Web 安全：URL/源码的漏洞审计与攻击链构造
│   ├── ai-security-analysis.md      # AI 应用安全：LLM 应用的提示注入与越狱
│   └── security-analysis-evolve.md  # 自我进化：从实战复盘中沉淀脚本与知识库
├── agents-rules/                    # 跨 Agent 共享的 prompt 片段（Plugin 自动展开）
├── plugins/
│   └── security-analysis.ts         # Plugin（TypeScript）：上下文持久化、session 管理
├── binary-analysis/                 # 二进制 Agent 的工具脚本 + 知识库
├── mobile-analysis/                 # 移动端 Agent 的工具脚本 + 知识库
├── web-analysis/                    # Web Agent 的工具脚本 + 知识库
├── ai-security-analysis/            # AI 安全 Agent 的工具脚本 + 知识库
└── commands/                        # 自定义斜杠命令
```

### 设计理念：编排器 + 工具 + 知识库 三层分离

| 层 | 内容 | 谁负责 |
|----|------|--------|
| **AI 编排层** | Agent prompt（何时调用什么工具、如何推理） | LLM |
| **工具层** | Python/Bash 脚本（query.py、update.py、initial_analysis.py...） | 工程师维护 |
| **知识库层** | 按需加载的 Markdown（壳处理策略、Unicorn 模板、Frida 速查...） | evolve Agent 持续沉淀 |

**关键决策**：LLM 不直接操作 GUI。例如，所有 IDA 操作都走 `idat -A -S<script>` headless 模式 + IDAPython 脚本。这让 AI 能稳定复现分析过程，而不依赖鼠标点击的时序。

## 三、六个 Agent 各自做什么

### 1. `security-coordinator` — 任务编排器

用户给的复合任务（比如"逆向这个 APK，分析它的网络通信加密算法，再用 Web 端的接口验证一下"）会被自动拆分：

```
用户: "分析这个 APK 的加密协议，对照它的后端接口验证"
        │
        ├─ #1 mobile-analysis  → 反编译 APK，定位 native 加密函数
        ├─ #2 binary-analysis  → 逆向 .so，还原加密算法（依赖 #1）
        └─ #3 web-analysis     → 调后端接口验证算法输出（依赖 #2）
```

Coordinator 通过 Task 工具分发子任务，每个子任务由对应的专业 Agent 在独立 session 中执行，结果聚合到父任务目录下。

### 2. `binary-analysis` — 二进制逆向

这是最成熟的一个 Agent。它的工作循环是：

```
阶段 A: initial_analysis.py → 拿到段/入口点/导入/字符串/壳检测/场景分类
阶段 B: 读取 analysis-planning.md → 根据场景（CTF/壳/驱动/算法）选方案
阶段 C: 循环执行 → query.py（13 种查询）/ update.py（4 种更新）/ 自定义脚本
阶段 D: verification-patterns.md → 验证结论（Hook/Unicorn/GUI 自动化）
```

工具脚本采用分层架构，避免重复造轮子：

```
_base.py      →  日志、JSON 输出、headless 入口、auto_wait/qexit
   ↑
_utils.py     →  thunk 追踪、地址解析、数据读取
   ↑
_analysis.py  →  段、入口点、导入、字符串、壳检测、场景分类
   ↑
query.py / update.py / scripts/*.py
```

**13 种查询类型** 覆盖逆向常用操作：`decompile`、`xrefs_to`、`xrefs_from`、`packer_detect`、`read_data`（支持 `auto/string/bytes/pointer` 四种模式）……

### 3. `mobile-analysis` — 移动端逆向

针对 APK/IPA 设计了独立路径：

- **APK**：apktool 解包 → jadx 反编译 → AndroidManifest 分析 → 列出 native 库 → 需要时调 binary-analysis 处理 `.so`
- **IPA**：unzip → 定位主二进制 → otool/nm 分析 → 需要时调 binary-analysis 处理 Mach-O

支持真机交互：通过 adb 启动应用、Frida Hook Java/Native 方法、内存 dump DEX。

### 4. `web-analysis` — Web 安全

覆盖三种分析模式：

| 模式 | 触发条件 | 工具链 |
|------|---------|--------|
| 白盒 | 提供源码目录 | 框架识别 → 源码审计 → 漏洞定位 |
| 黑盒 | 提供 URL | HTTP 探测 → 攻击面枚举 → 注入测试 |
| 灰盒 | 源码 + URL | 源码引导的黑盒验证 |

知识库里有专门的 **Web Cache Poisoning 专题**、**框架安全速查**（Django/Flask/Laravel/Express 常见配置缺陷）。

### 5. `ai-security-analysis` — AI 应用安全

针对 LLM 应用（ChatGPT-like 服务、AI Agent、RAG 系统）的攻击面：

- **应用层**：提示注入（直接/间接/RAG 投毒）、越狱（角色扮演/编码绕过/多轮诱导）
- **模型层**：通过 LLM API 客户端批量测试对抗性输入，识别 system prompt 泄露、数据回流

工具链包括 LLM 模拟器（白盒测试时模拟目标模型）、Playwright 浏览器自动化（黑盒测试时驱动 Web UI）。

### 6. `security-analysis-evolve` — 自我进化

**这是整个平台最"反常识"的设计**：让 AI 自己改进这个平台。

工作流程：

```
1. 复盘近期分析任务（读 timeline.log、报告、失败记录）
2. 识别高价值改进点（某个反复踩的坑、某个重复构造的脚本）
3. 提出 candidate（新增脚本 / 修改知识库 / 调整 prompt）
4. 与用户讨论确认（不能私自修改）
5. 按质量流程实施（先测试、再合并、记录变更）
```

这让平台**越用越强**：每次实战中发现的模式，会沉淀成可复用的脚本或知识库条目，下次遇到类似场景直接调用。

## 四、Plugin：让 Agent 在长会话中"不迷路"

`security-analysis.ts` 是整个平台的"操作系统"。它解决了一个 OpenCode 生态里很现实的问题——**LLM 的上下文窗口是有限的，但安全分析动辄几小时、几十轮工具调用**。

Plugin 的核心机制：

### 1. 环境变量注入

每次 LLM 请求前，Plugin 通过 `experimental.chat.system.transform` hook 把关键运行时变量注入 system prompt：

```
## 全局环境和目录位置信息
- $OPENCODE_ROOT = /Users/.../.opencode
- $AGENT_DIR     = /Users/.../.opencode/binary-analysis
- $SHARED_DIR    = /Users/.../.opencode/binary-analysis
- $PYTHON_CMD    = /Users/.../bw-security-analysis/.venv/bin/python
- IDA Pro        = /Applications/IDA Pro 8.4/idat
- 编译器         = clang (/usr/bin/clang)
- Python 包      = capstone@5.0.3, unicorn@2.1.3, frida@17.2.1, ...
```

Agent 在 prompt 里看到 `$PYTHON_CMD` 就能直接拼出完整命令，不需要猜路径。

### 2. 上下文压缩自愈

OpenCode 在上下文接近窗口上限时会自动压缩历史。但安全分析的中间状态（IDA 数据库路径、已识别的函数地址、已尝试的失败方向）一旦丢失，整个分析就废了。

Plugin 通过 `experimental.session.compacting` hook，在压缩发生**之前**强制注入：

- **环境信息摘要**（变量路径）
- **分析状态保留清单**（已完成的分析、已识别的函数、当前阶段、失败记录）
- **TASK_DIR**（通过 sessionID → 文件映射恢复，不依赖上下文）

压缩后 LLM 收到的提示是：

> 上下文刚被压缩。继续分析前必须：1. 重新读取 agent prompt 获取完整规则；2. 恢复 $OPENCODE_ROOT、$TASK_DIR 等关键变量。

### 3. 分析持续性恢复

安全分析中常见的失败模式：LLM 输出一段报告后判断"已完成"，停下来等用户。但用户可能在睡觉、在开会、在写别的代码——分析就这么挂在那。

Plugin 监听 `session.idle` 事件，当主 session 空闲且任务目录存在时，自动发送恢复消息：

> 你之前的分析是否已经完成了？如果已经完成，请直接输出最终结论。如果尚未完成，请自主继续分析，不要停下来向用户提问。

配合 `.persistence.json` 控制最大持续时间（默认 6 小时），避免无限恢复。

### 4. 占位符展开

Agent prompt 里大量使用 `{{buwai-rule:片段名}}` 引用共享片段：

```markdown
## 运行环境
{{buwai-rule:running-environment}}

## 阶段 0：任务初始化（强制）
{{buwai-rule:task-initialization}}
```

Plugin 在 system.transform 阶段把占位符替换为 `agents-rules/<name>.md` 的实际内容。修改共享规则只需改一个文件，所有 Agent 同步生效。带 mtime 缓存，文件改完下次调用立即生效。

### 5. 工具拦截与命令注入

`tool.execute.before` hook 做两件事：

- **拦截未初始化的命令**：`config.json` 不存在时，只放行 `create_task_dir`/`detect_env` 等初始化命令，其他全部拦截并提示用户先跑环境检测
- **注入环境变量**：每次 bash 命令前缀 `SESSION_ID=... AGENT_NAME=...`，让 Python 脚本能识别当前 session（用于日志路由、task 目录映射）

## 五、几个"反直觉"但关键的设计

### 1. 禁止"作弊式验证"

> 绝对禁止用自己重实现代码验证自己重实现的结果。

逆向出一个加密算法后，很容易陷入自欺欺人：用 Python 重写算法 → 用重写后的代码算 license → 算出来 → "我成功了！"。但如果重写本身就错了，验证就是错的。

正确的验证路径（决策树）：

```
能否定位到验证函数？
├─ 能 → 函数纯计算吗？
│       ├─ 是 → Unicorn 模拟原函数（直接跑原始字节码）
│       └─ 否 → Hook 注入参数 + Hook 读返回值
└─ 不能 → 程序类型？
          ├─ 命令行 → subprocess 传参，读 stdout/退出码
          ├─ DLL → ctypes 加载，调导出函数
          └─ GUI → 视觉驱动自动化（截图 → MCP 定位 → 键鼠）
```

### 2. "找关键点，不逆向机制"

逆向新手最大的陷阱是"我把这个函数从头到尾读懂"。实际上 90% 的场景只需要找到：

- 关键调用（哪个函数做加密/校验）
- 关键值（正确的 license / key 是什么）
- 关键跳转（哪个 `jnz` 决定成功失败）

**绕过优先于逆向**。除非用户明确要求分析保护机制本身，否则寻找最短绕过路径：Patch 跳转 > Hook 返回值 > 完整理解算法。

### 3. 事实 vs 推测分离

每条结论都必须标注来源：

- **事实**：来自 IDA 数据库的字节码、反编译输出、工具的直接输出
- **推测**：AI 的推理（"这个函数看起来像 MD5"），必须标注置信度

低置信度的推测**不允许直接报告**，必须继续验证。

### 4. 单向依赖

工具与知识库的依赖是单向的：

```
mobile-analysis ─┐
web-analysis ────┼──→ binary-analysis（$SHARED_DIR）
ai-security ─────┘
```

`binary-analysis/` 是基础设施层，其他三个领域可以复用它的脚本和知识库，但反过来不行。这避免了循环依赖和知识库污染。

## 六、一次真实的分析长什么样

以一个 CTF reverse 题为例（实际任务目录会持久化所有中间产物）：

```
~/bw-security-analysis/workspace/<task_id>/
├── task.json                 # 任务元信息（目标文件、需求、agent）
├── initial.json              # 阶段 A 输出（segments/imports/strings/packer_detect）
├── initial.log               # idat 日志
├── decompiled/
│   ├── sub_401000.c          # 反编译输出
│   └── sub_4023F0.c
├── screenshots/              # GUI 自动化的截图
│   ├── 01_launch.png
│   ├── 02_input.png
│   └── 03_result.png
├── solve.py                  # 求解脚本（Unicorn 模拟验证函数）
├── report.md                 # 最终报告（含执行统计、置信度标注）
└── logs/
    ├── plugin.log            # Plugin 行为日志
    └── timeline.log          # 工具调用时间线（每个工具的耗时）
```

用户只需要丢一句话：

> 帮我逆向 /Users/me/Downloads/crackme.exe，找出正确的 license

然后去喝杯咖啡，回来看 `report.md`。

## 七、工程化细节

### 数据与代码分离

- **代码**：`.opencode/` 目录，git 管理
- **数据**：`~/bw-security-analysis/`，gitignore，包含 venv、config、workspace、logs

### Python 虚拟环境自动管理

Plugin 加载时确保 `~/bw-security-analysis/.venv` 存在且可用，失败则整个 Plugin 加载失败。所有 Agent 用同一个 `$PYTHON_CMD`，避免依赖漂移。

### 工具脚本沉淀机制

每次实战中如果生成了可复用的脚本（比如"针对 VMProtect 3.x 的 OEP 定位"），evolve Agent 会把它沉淀到 `scripts/` 并注册到 `registry.json`。下次遇到类似场景，Agent 直接调用沉淀脚本而不是从头构造。

### IDAPython 编码规范

为了 AI 生成的脚本可维护，制定了严格的 IDAPython 编码规范：

- 使用 `from _base import run_headless, log, ...` 导入公共模块
- headless 入口在模块级执行（不在 `if __name__` 内）
- 禁止 `import idc`、`import idaapi`、`from ida_xxx import yyy`（统一走 `_base` 封装）
- 字符串使用双引号、日志使用中文、必须调用 `auto_wait()` 和 `qexit()`

## 八、目前的状态与限制

**已稳定可用的领域**：
- 二进制逆向（IDA Pro headless，最成熟）
- Web 安全（黑白盒审计）
- 移动端逆向（APK，IPA 路径稍弱）

**需要持续打磨的**：
- AI 安全分析（LLM 攻击方法论还在沉淀）
- GUI 自动化（依赖目标程序的控件可访问性）
- Windows 内核驱动分析（需要双机调试环境）

**依赖的外部工具**：
- IDA Pro（商业软件，必须配置 `ida_path`）
- Frida、apktool、jadx（开源，自动检测）
- Playwright（Web/AI Agent 用）

## 九、适合谁用

- **CTF 选手**：reverse/pwn/web 题目的快速求解
- **漏洞挖掘研究员**：批量分析样本、定位关键函数
- **移动安全工程师**：APK/IPA 自动化审计
- **AI 安全研究者**：LLM 应用的攻击面探索
- **Agent 框架开发者**：参考"如何让 LLM 真正操作专业工具链"的工程实践

## 十、写在最后

OpenSecurity 不是一个"AI 替代安全研究员"的项目——优秀的分析仍然需要人的判断和经验。

它做的是**把研究员从重复性劳动中解放出来**：让 AI 跑那些本来就该脚本化的步骤（解包、反编译、字符串搜索、初轮壳检测），让人专注于策略决策和结果验证。

如果你对项目的某个部分感兴趣（Plugin 机制、某个 Agent 的实现、工具脚本的设计），欢迎在对应目录下深入阅读。每个 Agent 的 prompt 都附带了详细的 `knowledge-base/` 文档，按需加载、不堆砌上下文。

---

**延伸阅读**：
- Plugin 开发实战：`.opencode/binary-analysis/knowledge-base/opencode-plugin-development-guide.md`
- Hook 时序与陷阱：`.opencode/binary-analysis/knowledge-base/opencode-plugin-hooks-lifecycle.md`
- Agent 文件格式规范：`.opencode/binary-analysis/knowledge-base/opencode-agent-format.md`
