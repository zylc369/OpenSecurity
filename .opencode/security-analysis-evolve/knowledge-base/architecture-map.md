# 架构地图

> security-analysis 体系的目录架构、归属规则、依赖方向、Plugin hooks、环境变量表。
> 触发: 新增/移动任何文件、判定知识/脚本归属、涉及 Plugin hook 交互时必读。不依赖主 prompt 上下文即可理解。

---

## 架构树

```
$OPENCODE_ROOT/                              # 由插件注入，项目级 .opencode/ 或全局 ~/.config/opencode/
├── agents/
│   ├── binary-analysis.md                # 二进制逆向分析 Agent（主 prompt，AI 编排器）
│   ├── mobile-analysis.md                # 移动端分析 Agent
│   ├── web-analysis.md                   # Web 安全分析 Agent
│   ├── ai-security-analysis.md           # AI 安全分析 Agent（提示注入 + 越狱攻击）
│   ├── knowledge-scout.md                # 知识侦察子 Agent（hidden: 不注入任何 agent 的可用列表，仅显式派发）
│   └── security-analysis-evolve.md       # 进化工程师 Agent（唯一知识库写入者）
├── agents-rules/                         # Agent prompt 共享片段（Plugin 自动展开 {{buwai-rule:片段名}}）
├── plugins/
│   ├── security-analysis.ts              # Plugin（上下文持久化 + session 管理 + 片段展开）
│   └── lib/constants.ts                  # AGENT_SCRIPT_DIRS 等映射表（新 agent 有专属目录时同步加映射）
├── binary-analysis/                      # 逆向分析核心工具与知识库（$SHARED_DIR，通用层）
│   ├── _base.py                          # 层 1: 基础设施
│   ├── _utils.py                         # 层 2: 共享业务工具
│   ├── _analysis.py                      # 层 2.5: 共享分析逻辑
│   ├── query.py                          # 层 3: 查询操作（13 种）
│   ├── update.py                         # 层 3: 更新操作（4 种）
│   ├── scripts/                          # 沉淀脚本 + 纯 Python 工具
│   └── knowledge-base/                   # 知识库（按需加载）: opencode-plugin-api / hooks-lifecycle /
│                                         #   plugin-development-guide / opencode-agent-format /
│                                         #   plugin-debugging / idapython-conventions / packer-handling /
│                                         #   script-generation / knowledge-writing-guide 等
├── mobile-analysis/                      # 移动端工具与知识库（scripts/ + knowledge-base/: android/ios-tools、mobile-methodology 等）
├── web-analysis/                         # Web 安全工具与知识库（knowledge-base/: web-methodology、
│                                         #   web-vulnerabilities、cache-poisoning、csp-bypass、client-side-attacks、
│                                         #   xss-advanced、race-conditions、sqli-advanced、bot-patterns 等; scripts/ 含探针）
├── ai-security-analysis/                 # AI 安全工具与知识库（llm-attack-methodology、prompt-injection-patterns、
│                                         #   audio-modality-attacks 等）
├── crypto-analysis/                      # 密码学攻击知识库（crypto-methodology、rsa/lattice/ecc-attacks、
│                                         #   classical-crypto、symmetric-and-hash、prng-attacks、exotic-algebra-attacks 等）
├── knowledge-scout/                      # 知识侦察专属（谁执行谁持有）
│   ├── knowledge-base/
│   │   └── knowledge-sourcing-guide.md   # 信源表/gap 判定/价值判断/下载方法/侦察报告格式
│   └── scripts/
│       └── download_sources.py           # 素材下载工具
├── security-analysis-evolve/             # 进化工程师专属
│   └── knowledge-base/
│       ├── architecture-map.md           # 本文件（架构/归属/依赖/hooks/变量）
│       ├── distillation-methodology.md   # 整库蒸馏六阶段
│       ├── retrospective-methodology.md  # 复盘方法论
│       ├── evolution-playbook.md         # 反模式/高风险/异常处理
│       ├── long-document-editing.md      # >300 行文档编辑策略
│       └── opencode-references.md        # OpenCode 开发文档索引 + 源码查阅
├── commands/                              # opencode 命令目录（opencode 只把 *.md 当命令；非命令 .md 勿放，会被误识别。可含命令配套的 .py 脚本）
└── requirements/
    └── evolve/                            # 进化需求文档（不放 commands/，避免被 opencode 当命令加载）
```

## 归属规则

- mobile-analysis/、web-analysis/、ai-security-analysis/、crypto-analysis/ 可引用 binary-analysis/（$SHARED_DIR）的知识库和脚本
- **binary-analysis/ 不可反向引用**上述任何专业目录的内容（单向依赖）
- agent 专属目录（knowledge-scout/、security-analysis-evolve/）各持各的方法论，互不引用; agent 间协作用 task 派发（非文档依赖）
- 知识/脚本归属判定: 通用（PC+移动都可能用）→ binary-analysis/; 移动端特有 → mobile-analysis/; 方向专属 → 各方向目录; 不确定 → 通用层
- 进化产物的落位速查: Agent prompt → agents/; Plugin → plugins/; IDAPython 脚本 → binary-analysis/ 对应层级; 独立 Python 工具/探针 → 对应方向 scripts/; 知识库 → 对应 knowledge-base/; 需求文档 → requirements/evolve/; **禁止散落到项目根目录或 $OPENCODE_ROOT 之外**

## 依赖方向（单向，禁止反向）

```
_base.py ← _utils.py ← _analysis.py ← query.py / update.py / scripts/*.py
```

禁止违反依赖方向。禁止循环依赖。

## Plugin hooks

| Hook | 用途 |
|------|------|
| chat.message | 追踪 session 的当前 agent 和主 agent |
| shell.env | 注入环境变量（$SESSION_ID/$PYTHON_CMD/$IDAT/$AGENT_DIR 等）到 bash 命令 |
| experimental.session.compacting | 压缩时注入分析状态保留提示 + TASK_DIR; 置 justCompacted 标识 |
| experimental.chat.system.transform | 每轮注入环境信息 + 占位符展开; 检测 justCompacted 强制重注入 |
| tool.execute.before | 记录工具执行时间线 |
| event | 管理 session 生命周期 + 子 session 继承 |

## 环境变量表

| 变量 | 来源 | 说明 |
|------|------|------|
| `$OPENCODE_ROOT` | 环境信息"配置根目录" | agents/、plugins/ 等目录的父目录 |
| `$AGENT_DIR` | 环境信息"Agent 目录" | 当前 Agent 的专属目录（每个 agent 会话各指各的: evolve → security-analysis-evolve/; scout → knowledge-scout/） |
| `$SHARED_DIR` | 环境信息"共享目录" | 通用分析能力目录（binary-analysis/） |
| `$SESSION_ID` / `$TASK_DIR` | shell.env 注入 | 会话/任务目录 |

值的实时注入以系统提示"环境信息"段为准——本表是语义参考，不是值的快照。
