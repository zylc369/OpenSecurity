# 需求：创建 AI 安全分析 Agent

## §1 背景与目标

**来源**：Ultimate Essay Grader CTF（8ksec AI Labs）的分析经验。在这次分析中积累了 AI 安全（LLM 提示注入、社会工程学式攻击）的方法论和工具，现在将这些能力固化为独立的 Agent，让后续 AI 安全分析不再从零摸索。

**痛点**：
- 现有 4 个 Agent（binary/mobile/web/coordinator）都不覆盖 AI 安全领域
- AI 安全（提示注入、越狱、数据投毒）的分析方法论与 Web 安全不同，需要独立的工具链和知识库
- 已有的 `deepseek_client.py`、`essay_grader_sim.py` 等脚本散落在任务目录中，不可复用

**预期收益**：
- 上下文：新 Agent 有独立的知识库和工具，不需要从 writeup 或对话历史中推断方法论
- 轮次：后续 AI 安全 CTF 可直接进入分析阶段，省去方法论文档搜索和工具开发
- 准确度：沉淀的方法论经过提炼，比临时推理更可靠

---

## §2 技术方案

### 2.1 新增文件清单

| # | 文件 | 类型 | 说明 |
|---|------|------|------|
| 1 | `.opencode/agents/ai-security-analysis.md` | Agent prompt | Agent 主 prompt |
| 2 | `.opencode/ai-security-analysis/knowledge-base/llm-attack-methodology.md` | 知识库 | LLM 攻击方法论（攻击面分析、渐进式实验、payload 构造） |
| 3 | `.opencode/ai-security-analysis/knowledge-base/prompt-injection-patterns.md` | 知识库 | 提示注入模式速查（直接/间接/社会工程学/多轮，含 payload 模板） |
| 4 | `.opencode/ai-security-analysis/knowledge-base/ai-security-defense.md` | 知识库 | AI 安全防御方案（输入层/System Prompt/输出层/架构层） |
| 5 | `.opencode/ai-security-analysis/scripts/deepseek_client.py` | 脚本 | LLM API 多轮对话客户端（通用化版，支持 DeepSeek/OpenAI） |
| 6 | `.opencode/ai-security-analysis/scripts/llm_sim.py` | 脚本 | LLM 应用模拟器（通用化版，从 essay_grader_sim.py 提炼） |
| 7 | `.opencode/ai-security-analysis/scripts/registry.json` | 配置 | 脚本注册表 |

### 2.2 修改文件清单

| # | 文件 | 改动 | 说明 |
|---|------|------|------|
| 8 | `.opencode/plugins/security-analysis.ts` | 新增常量 + 加入数组 | 注册新 Agent 到 PRIMARY_AGENTS |
| 9 | `.opencode/agents/security-coordinator.md` | 新增表格行 | 把 ai-security-analysis 加入可调用的专业 Agent 列表 |

### 2.3 架构位置

```
.opencode/
├── agents/
│   ├── ai-security-analysis.md          # ← 新增
│   ├── binary-analysis.md
│   ├── mobile-analysis.md
│   ├── web-analysis.md
│   ├── security-coordinator.md          # ← 修改（新增 Agent 条目）
│   └── security-analysis-evolve.md
├── ai-security-analysis/                # ← 新增目录
│   ├── knowledge-base/
│   │   ├── llm-attack-methodology.md    # LLM 攻击方法论
│   │   ├── prompt-injection-patterns.md # 提示注入模式速查
│   │   └── ai-security-defense.md       # AI 安全防御方案
│   └── scripts/
│       ├── deepseek_client.py           # 通用 LLM API 客户端
│       ├── llm_sim.py                   # 通用 LLM 应用模拟器
│       └── registry.json                # 脚本注册表
├── plugins/
│   └── security-analysis.ts             # ← 修改（注册新 Agent）
└── ...
```

### 2.4 依赖关系

- `ai-security-analysis/` 可引用 `binary-analysis/knowledge-base/`（通过 `$SHARED_DIR`）
- `ai-security-analysis/scripts/` 依赖 `$PYTHON_CMD`（venv Python，由 Plugin 保证可用）
- `deepseek_client.py` 独立，无外部脚本依赖
- `llm_sim.py` 依赖 `deepseek_client.py`

### 2.5 Agent frontmatter

```yaml
---
description: AI 安全分析 — 输入 LLM 应用 URL/源码/描述和分析需求，自动完成 AI 安全分析
mode: all
buwai-extension-id: ai-security-analysis
permission:
  external_directory:
    ~/bw-security-analysis/**: allow
    ~/Downloads/**: allow
  read:
    "~/Downloads/**/*.env": allow
    "~/Downloads/**/*.env.*": allow
---
```

---

## §3 实现规范

### 3.1 改动范围表

| 文件 | 新增行 | 修改行 | 总行数 |
|------|--------|--------|--------|
| ai-security-analysis.md | ~200 | 0 | ~200 |
| llm-attack-methodology.md | ~120 | 0 | ~120 |
| prompt-injection-patterns.md | ~150 | 0 | ~150 |
| ai-security-defense.md | ~100 | 0 | ~100 |
| deepseek_client.py（通用化版） | ~350 | 0 | ~350 |
| llm_sim.py | ~200 | 0 | ~200 |
| registry.json | ~30 | 0 | ~30 |
| security-analysis.ts | +3 | +1 | +4 |
| security-coordinator.md | +3 | 0 | +3 |

### 3.2 脚本通用化要点

用户明确要求："脚本必须通用，如果不通用下次分析其他工作时还要改"。

**`deepseek_client.py` 通用化改造**：
1. 去掉 `_KNOWN_PROJECT_ROOTS` 硬编码路径
2. API Key 来源：环境变量 `LLM_API_KEY` > 环境变量 `DEEPSEEK_API_KEY` > `.privacy-data/privacy-data.json` 的 `apiKey.deepSeek` 字段
3. base_url 和 model 作为参数传入，不绑定 DeepSeek（支持 OpenAI 等兼容 API）
4. 类名从 `DeepSeekClient` 改为 `LLMClient`（保持 `DeepSeekClient` 作为别名向后兼容）
5. 文档字符串从"DeepSeek API 多轮对话客户端"改为"LLM API 多轮对话客户端（兼容 DeepSeek/OpenAI 等兼容 API）"

**`llm_sim.py` 通用化改造**（从 `essay_grader_sim.py` 提炼）：
1. 去掉论文评分特定的 system prompt 模板（`GRADER_SYSTEM_PROMPTS`）
2. 核心能力：接收任意 system prompt + user input，调用 LLM，返回结构化结果
3. 通用化的 `LLMSimulator` 类：
   - `__init__`: 接收 system_prompt（可选）、model、temperature 等参数
   - `query(user_input, **kwargs)`: 单轮查询
   - `query_multiturn(messages, **kwargs)`: 多轮查询
   - `query_batch(inputs, **kwargs)`: 批量查询（用于稳定性测试）
4. `ResponseParser` 辅助类：从 LLM 输出中提取结构化信息（Grade/Score 等通用 pattern）
5. 保留 `read_docx` 工具函数（通用）
6. 保留命令行入口（接收 `--system-prompt` 参数，不再绑定论文评分）

**不沉淀 `pen_test_multiturn.py`**：
- 该脚本绑定 Essay Grader 特定的 payload（硬编码了论文内容），不可通用化
- 其核心思想（渐进式攻击）已沉淀到 `llm-attack-methodology.md` 知识库中
- 后续 AI 安全分析时，Agent 根据知识库指导 + `llm_sim.py` 工具自行构造 payload

### §3.3 实施步骤拆分

**步骤 1. Plugin 注册新 Agent**
  - 文件: `.opencode/plugins/security-analysis.ts`
  - 预估行数: ~4 行（1 个新常量 + 1 行加入数组）
  - 验证点: `node --check security-analysis.ts` 通过
  - 依赖: 无

**步骤 2. 创建目录结构**
  - 文件: 创建 `.opencode/ai-security-analysis/knowledge-base/` 和 `.opencode/ai-security-analysis/scripts/`
  - 预估行数: 0 行（仅目录创建）
  - 验证点: `ls -la .opencode/ai-security-analysis/` 显示两个子目录
  - 依赖: 无

**步骤 3. 沉淀脚本 `deepseek_client.py`（通用化版）**
  - 文件: `.opencode/ai-security-analysis/scripts/deepseek_client.py`
  - 预估行数: ~350 行
  - 验证点: `python -c "compile(open('<文件>').read(), '<文件>', 'exec')"` 通过
  - 依赖: 步骤 2

**步骤 4. 沉淀脚本 `llm_sim.py`（通用化版）**
  - 文件: `.opencode/ai-security-analysis/scripts/llm_sim.py`
  - 预估行数: ~200 行
  - 验证点: `python -c "compile(open('<文件>').read(), '<文件>', 'exec')"` 通过 + `python llm_sim.py --help` 输出参数说明 + 内部使用 `from deepseek_client import LLMClient`（通用名）
  - 依赖: 步骤 3

**步骤 5. 创建脚本注册表 `registry.json`**
  - 文件: `.opencode/ai-security-analysis/scripts/registry.json`
  - 预估行数: ~30 行
  - 验证点: `python -c "import json; json.load(open('<文件>'))"` 通过
  - 依赖: 步骤 3, 4

**步骤 6. 沉淀知识库 `llm-attack-methodology.md`**
  - 文件: `.opencode/ai-security-analysis/knowledge-base/llm-attack-methodology.md`
  - 预估行数: ~120 行
  - 验证点: 人工读一遍确认自包含性 + 引用路径正确
  - 依赖: 无

**步骤 7. 沉淀知识库 `prompt-injection-patterns.md`**
  - 文件: `.opencode/ai-security-analysis/knowledge-base/prompt-injection-patterns.md`
  - 预估行数: ~150 行
  - 验证点: 人工读一遍确认自包含性 + payload 模板可直接使用
  - 依赖: 无

**步骤 8. 沉淀知识库 `ai-security-defense.md`**
  - 文件: `.opencode/ai-security-analysis/knowledge-base/ai-security-defense.md`
  - 预估行数: ~100 行
  - 验证点: 人工读一遍确认自包含性
  - 依赖: 无

**步骤 9. 创建 Agent prompt `ai-security-analysis.md`**
  - 文件: `.opencode/agents/ai-security-analysis.md`
  - 预估行数: ~200 行
  - 验证点: 计算展开后行数 < 450 行。计算方法：Agent .md 行数 - 占位符行数（`{{buwai-rule:xxx}}` 占 1 行）+ 各 agents-rules 片段文件行数之和。使用的片段：running-environment（1行）、variable-initialization（9行）、task-initialization（21行）、execution-discipline（76行）、analysis-planning-rules（6行）、loop-control（5行）、output-format（15行）、task-archive（1行）
  - 依赖: 步骤 1, 5, 6, 7, 8

**步骤 10. 更新 `security-coordinator.md`**
  - 文件: `.opencode/agents/security-coordinator.md`
  - 预估行数: ~3 行（新增 1 行表格 + 2 行说明）
  - 验证点: 读取文件确认新增内容正确
  - 依赖: 步骤 9

---

## §4 验收标准

### 4.1 功能验收

- [ ] Agent 可通过 Tab 键选择 `ai-security-analysis` 并启动
- [ ] Agent 的 `$AGENT_DIR` 正确指向 `.opencode/ai-security-analysis/`
- [ ] `deepseek_client.py` 可作为模块导入（`from deepseek_client import LLMClient`）
- [ ] `llm_sim.py` 可作为模块导入（`from llm_sim import LLMSimulator`）
- [ ] `llm_sim.py --help` 输出参数说明
- [ ] `security-coordinator.md` 的可调用 Agent 列表包含 ai-security-analysis

### 4.2 回归验收

- [ ] 现有 4 个 Agent（binary/mobile/web/evolve）的 prompt 无变化
- [ ] Plugin 编译通过（`node --check security-analysis.ts`）
- [ ] `deepseek_client.py` 保留 `DeepSeekClient` 别名，现有调用方不受影响

### 4.3 架构验收

- [ ] 新文件全部在 `.opencode/` 目录内，不散落到项目根目录
- [ ] 知识库文件自包含（不依赖主 prompt 上下文即可理解）
- [ ] 依赖方向正确：ai-security-analysis 可引用 binary-analysis（通过 $SHARED_DIR），反向不行
- [ ] Agent prompt 展开后 < 450 行
- [ ] 脚本无硬编码路径（API Key 从环境变量或配置文件加载）

---

## §5 与现有需求文档的关系

无依赖。本需求是独立的，不修改任何现有 Agent 的行为（除 security-coordinator 增加一行条目和 Plugin 注册）。
