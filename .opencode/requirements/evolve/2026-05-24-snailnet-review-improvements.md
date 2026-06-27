# SnailNet 复盘改进 — 文件纪律 / $BA_PYTHON / Writeup 策略 / Web 公共工具

日期: 2026-05-24
来源: SnailNet CTF 题目分析复盘

---

## §1 背景与目标

### 1.1 来源

SnailNet Web CTF 题目（46.62.153.171:6767）完整分析过程复盘，发现以下痛点：

| # | 痛点 | 严重度 | 数据支撑 |
|---|------|--------|---------|
| P1 | 中间文件全部散落在 workspace 根目录，任务目录为空 | 高 | workspace 根 28 个散落文件；任务目录仅 logs/ |
| P2 | web-analysis 明确不使用 $BA_PYTHON，bs4 缺失导致执行中断 | 中 | 浪费 1 轮对话修改代码 |
| P3 | 找到 writeup 后仍花 ~40% 上下文重新推导 XSS 机制 | 高 | ~5 轮工具调用，零贡献于最终结果 |
| P4 | 多个测试脚本含重复 boilerplate（URL、session、CSRF） | 低 | 8 个 Python 脚本，公共模式重复 4+ 次 |

### 1.2 目标

1. **文件放置规则**：在所有 agent 的主 prompt 中强制文件写入 $TASK_DIR，消除 knowledge-base 中的重复描述
2. **$BA_PYTHON 对齐**：web-analysis 使用公共片段中的 $BA_PYTHON（不再覆盖）
3. **Writeup 策略**：找到已验证方案后直接使用，不重新推导机制
4. **Web 公共工具**：创建 web_helpers.py，封装 Web 分析高频操作

### 1.3 预期收益

| 指标 | 改进前 | 改进后 |
|------|--------|--------|
| 文件散落 | 全部在 workspace 根 | 全部在 $TASK_DIR |
| 包缺失导致的调试轮次 | 1-2 轮 | 0 轮 |
| Writeup 场景上下文浪费 | 20-40% | <5%（仅验证结果） |
| 测试脚本 boilerplate | 每次 ~30 行重复 | import 一行 |

---

## §2 技术方案

### 2.1 方案 A：文件放置规则（放入共享片段，移除 knowledge-base 重复）

**改动文件**：

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `agents-rules/execution-discipline.md` | 修改 | 添加"文件放置"纪律行 + 详细规则段 |
| `binary-analysis/knowledge-base/task-initialization.md` | 修改 | 移除 Step 1 中的文件放置描述（第 15 行），仅保留目录创建逻辑 |
| `agents/web-analysis.md` | 修改 | 移除安全规则中与文件放置重复的描述（第 254 行"Cookie/Token..."） |

**方案详情**：

在 `execution-discipline.md` 的纪律表中新增一行：

```
| **文件放置** | 所有中间文件（脚本、输出、调试数据、HTML 保存）写入 `$TASK_DIR`，禁止写入 workspace 根目录或项目根目录 |
```

在纪律表后新增"文件放置规则"段：

```markdown
### 文件放置规则

1. **所有中间文件写入 `$TASK_DIR`**：Python 脚本、HTTP 响应保存、cookie 文件、调试输出等
2. **禁止位置**：workspace 根目录（`~/bw-security-analysis/workspace/`）、项目根目录、系统临时目录
3. **敏感信息**：Cookie/Token 等必须在 `$TASK_DIR` 中存储
4. **临时脚本**：仍写入 `$TASK_DIR`（如 `$TASK_DIR/test_xss.py`），不写入其他位置
5. **异常**：`env_cache.json`、`config.json` 等全局配置文件写入 `~/bw-security-analysis/`（已在 task-initialization 中定义）
```

然后从 `binary-analysis/knowledge-base/task-initialization.md` 的 Step 1 中移除文件放置描述（第 15 行 "所有中间文件写入..."），因为规则已上移到共享片段。

### 2.2 方案 B：web-analysis 使用 $BA_PYTHON + Web 包安装

**改动文件**：

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `agents/web-analysis.md` | 修改 | 删除第 42 行（不必要的变量覆盖语句） |
| `binary-analysis/scripts/detect_env.py` | 修改 | REQUIRED_PACKAGES 加入 web 分析包 + `--agent` 参数支持 AGENT_NAME 环境变量 |
| `plugins/security-analysis.ts` | 修改 | `tool.execute.before` 注入 AGENT_NAME 环境变量 |
| `binary-analysis/knowledge-base/task-initialization.md` | 修改 | 移除 Step 2 中的 `--agent` 专属命令示例（已由环境变量自动传递替代） |

**方案详情（1）：web-analysis.md 删除变量覆盖语句**

当前第 42 行：
```
> **web-analysis 专属说明**：本 Agent 只使用 `$AGENT_DIR`、`$SHARED_DIR`、`$TASK_DIR`，不依赖 `$IDAT` 和 `$BA_PYTHON`。
```

**直接删除此行**。原因：
- `variable-initialization.md` 已定义所有变量来源，agent 按需使用，无需被告知"用哪些不用哪些"
- 之前的"不依赖 $BA_PYTHON"反而有害（阻止 agent 使用 venv Python）
- agent 不会无谓使用 $IDAT（Web 分析场景没有 IDA 数据库）

效果：`variable-initialization.md` 中的 $BA_PYTHON 初始化规则自然对 web-analysis 生效，无需额外改动。

**方案详情（2）：detect_env.py 加入 web 分析包 + AGENT_NAME 环境变量**

当前 `REQUIRED_PACKAGES` 只包含 binary-analysis 的包（capstone, unicorn, frida 等）。venv 是所有 agent 共享的，Web 分析需要的包加入同一列表即可。

新增条目：

```python
REQUIRED_PACKAGES = {
    # ... 现有 binary-analysis 包 ...
    "requests":      {"required": True,  "pip_name": "requests"},
    "bs4":           {"required": True,  "pip_name": "beautifulsoup4"},
    "lxml":          {"required": True,  "pip_name": "lxml"},
}
```

- `requests`: HTTP 客户端（Web 分析基础依赖）
- `beautifulsoup4`: HTML 解析（CSRF token 提取、响应分析）
- `lxml`: bs4 推荐的后端解析器，处理畸形 HTML 比 html.parser 更健壮，速度更快

`--agent` 参数新增环境变量支持：`os.environ.get("AGENT_NAME")` 作为默认值，命令行参数优先级更高。Plugin 已通过环境变量注入 agent name，detect_env.py 自动读取，文档中不再需要 `--agent` 参数说明。

**方案详情（3）：Plugin 注入 AGENT_NAME 环境变量**

在 `tool.execute.before` hook 中，与 `SESSION_ID` 一起注入 `AGENT_NAME` 环境变量。当前 session 的 agent name 已在 `chat.message` hook 中记录到 `session.agentName`。

效果：
- 所有 bash 命令自动携带 `AGENT_NAME=<agent-name>` 环境变量
- detect_env.py 自动获取 agent name 进行工具过滤
- 文档中去掉所有 `--agent` 参数描述，命令保持通用

### 2.3 方案 C：Writeup/已知方案处理策略

**改动文件**：

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `agents-rules/execution-discipline.md` | 修改 | 添加"已知方案处理策略"段 |

**方案详情**：

在 `execution-discipline.md` 末尾（"系统性卡住恢复"段之后）新增：

```markdown
### 已知方案处理策略

当通过 webfetch/搜索找到已验证的 writeup 或公开 exploit 代码时：

| 场景 | 处理方式 |
|------|---------|
| writeup 提供完整可运行 exploit | **直接使用**，不重新推导漏洞机制。执行后验证结果（是否拿到 flag/是否达成目标） |
| writeup 只描述攻击思路 | 基于思路实现 exploit，不验证 writeup 作者的每一步推理 |
| writeup 与自己的分析冲突 | 以实际测试结果为准，不花上下文辩论哪个分析"正确" |
| writeup 代码需要适配 | 只做必要的适配（URL/参数/token），不重写 |

**核心原则**：writeup 的价值在于"已验证的可行路径"，不在于"机制的完美解释"。**验证最终结果**，不验证中间推理。

**禁止**：找到完整 writeup 后仍花大量上下文重新推导已描述的漏洞机制。
```

### 2.4 方案 D：Web 分析公共工具

**新建文件**：

| 文件 | 说明 |
|------|------|
| `web-analysis/scripts/web_helpers.py` | Web 分析高频操作封装 |
| `web-analysis/scripts/registry.json` | 脚本注册表 |

**改动文件**：

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `agents/web-analysis.md` | 修改 | 工具清单中添加 web_helpers.py |

**web_helpers.py 功能清单**：

| 函数 | 用途 | 参数 |
|------|------|------|
| `create_session(base_url)` | 创建 requests.Session，设置默认 timeout | `base_url: str` |
| `get_csrf(session, url, field_name="csrf_token")` | 从页面提取 CSRF token | `session, url: str, field_name: str` → `str` |
| `register_and_login(session, base_url, username, password)` | 注册+登录，返回 session | `session, base_url, username, password` |
| `extract_flag_from_webhook(uuid, keyword="SK-CERT")` | 从 webhook.site API 提取 flag | `uuid: str, keyword: str` → `str|None` |
| `create_webhook()` | 创建 webhook.site 端点 | → `str`（UUID） |

**设计原则**：
- 每个函数可独立使用（不强制组合调用）
- 不封装过度 — 只收口 3 次以上重复出现的模式
- 错误处理明确（抛异常，不静默返回）
- 依赖 requests + bs4（通过 $BA_PYTHON 调用，venv 中已安装）
- CSRF 提取使用 bs4（比正则更健壮，能处理各种 HTML 边界情况）

**调用方式**：web_helpers.py 是库模块（被 import），不是命令行工具。在临时脚本中通过以下方式使用：

```python
import sys
sys.path.insert(0, "$AGENT_DIR/scripts")  # 使 web_helpers 可被 import
from web_helpers import create_session, get_csrf, register_and_login
```

---

## §3 实现规范

### 3.0 改动范围表

| 文件 | 改动类型 | 预估行数 |
|------|---------|---------|
| `agents-rules/execution-discipline.md` | 修改（添加规则） | +25 行 |
| `binary-analysis/knowledge-base/task-initialization.md` | 修改（删除重复 + 删除 `--agent`） | -5 行 |
| `agents/web-analysis.md` | 修改（删除覆盖 + 移除重复 + 工具清单） | ~4 行 |
| `binary-analysis/scripts/detect_env.py` | 修改（添加 web 包 + AGENT_NAME 支持） | +5 行 |
| `plugins/security-analysis.ts` | 修改（注入 AGENT_NAME 环境变量） | +3 行 |
| `web-analysis/scripts/web_helpers.py` | 新建 | ~120 行 |
| `web-analysis/scripts/registry.json` | 新建 | ~15 行 |

### 3.1 实施步骤拆分

```
步骤 1. execution-discipline.md 添加文件放置规则 + writeup 策略
  - 文件: agents-rules/execution-discipline.md
  - 预估行数: +25 行
  - 验证点: 文件语法正确（markdown 无格式错误）；新规则与现有纪律表格式一致
  - 依赖: 无

步骤 2. 移除重复/已替代的片段内容
  - 文件: binary-analysis/knowledge-base/task-initialization.md、agents/web-analysis.md
  - 改动内容:
    - task-initialization.md: 移除第 15 行（文件放置规则，已上移到 execution-discipline.md）
    - task-initialization.md: 移除 Step 2 中的 `--agent` 专属命令示例（已由环境变量自动传递替代）
    - web-analysis.md: 移除第 254 行（"Cookie/Token...仅在任务目录中存储，不输出到非预期位置"已完全被 execution-discipline.md 文件放置规则覆盖）
  - 预估行数: -6 行（task-initialization -5 + web-analysis -1）
  - 验证点:
    - task-initialization.md 仍自包含；不丢失"禁止使用 workdir"等关键规则
    - task-initialization.md Step 2 命令为通用版（无 `--agent` 参数）
    - Grep "--agent" 在 task-initialization.md 中无结果
    - Grep "中间文件写入" 在 task-initialization.md 中无结果
  - 依赖: 步骤 1（确保替代规则已就位后再删除旧规则）

步骤 3. web-analysis.md 删除变量覆盖语句
  - 文件: agents/web-analysis.md
  - 预估行数: -1 行（删除第 42 行）
  - 验证点: 第 42 行不存在"专属说明"块引用；variable-initialization.md 的 $BA_PYTHON 规则不再被覆盖
  - 依赖: 无

步骤 4. detect_env.py 添加 web 分析包 + AGENT_NAME 环境变量支持
  - 文件: binary-analysis/scripts/detect_env.py
  - 预估行数: +5 行（REQUIRED_PACKAGES +3 行 + --agent 环境变量默认值 ~2 行）
  - 验证点:
    - python -c "compile(open(...).read(), ..., 'exec')" 语法检查通过
    - AGENT_NAME=test-agent python3 detect_env.py --skip-install → 日志中体现 agent=test-agent
  - 依赖: 无

步骤 5. Plugin 注入 AGENT_NAME 环境变量
  - 文件: plugins/security-analysis.ts
  - 预估行数: +3 行（tool.execute.before 中与 SESSION_ID 并列注入 AGENT_NAME）
  - 验证点:
    - node --check 语法检查通过
    - Plugin 逻辑正确：从 session.agentName 获取值，非 PRIMARY_AGENT 时不注入
  - 依赖: 无

步骤 6. 创建 web_helpers.py
  - 文件: web-analysis/scripts/web_helpers.py（新建）
  - 预估行数: ~120 行
  - 验证点: python -c "compile(open(...).read(), ..., 'exec')" 语法检查通过
  - 依赖: 无

步骤 7. 创建 registry.json
  - 文件: web-analysis/scripts/registry.json（新建）
  - 预估行数: ~15 行
  - 验证点: python -c "import json; json.load(open(...))" JSON 语法检查通过
  - 依赖: 步骤 6（注册的脚本必须已存在）

步骤 8. web-analysis.md 添加 web_helpers.py 到工具清单
  - 文件: agents/web-analysis.md
  - 预估行数: +6 行（工具表 1 行 + import 模板 5 行）
  - 验证点: 工具清单表格格式一致；引用路径使用 $AGENT_DIR 变量；包含 sys.path.insert + import 模板
  - 依赖: 步骤 6、7（工具必须已存在才能引用）

步骤 9. 端到端验证
  - 文件: 无
  - 预估行数: 0
  - 验证点:
    - detect_env.py --force 运行成功（AGENT_NAME 由 Plugin 自动注入）
    - venv python 可 import requests、bs4、lxml
    - web_helpers.py 可被 venv python import
  - 依赖: 步骤 4、5、6（包声明、AGENT_NAME 注入、脚本必须已存在）

步骤 10. web-analysis.md Prompt 瘦身检查
  - 文件: agents/web-analysis.md
  - 预估行数: 0（纯检查）
  - 验证点: 展开后行数 < 450 行
  - 依赖: 步骤 3、8（所有修改完成后统计）
```

### 3.2 编码规则

- Markdown: 遵循现有片段的格式（表格、标题层级、代码块）
- Python (web_helpers.py): 使用 type hints、docstring、中文日志；依赖 requests + bs4（通过 $BA_PYTHON 调用）
- JSON (registry.json): 遵循 binary-analysis/scripts/registry.json 的格式
- 路径: 禁止硬编码绝对路径，必须使用 $AGENT_DIR / $SHARED_DIR / $TASK_DIR 变量

---

## §4 验收标准

### 4.1 功能验收

| # | 验收项 | 验证方式 |
|---|--------|---------|
| F1 | 文件放置规则在 execution-discipline.md 中存在且自包含 | Read 文件确认 |
| F2 | task-initialization.md 中不再有文件放置规则 | Grep "中间文件写入" 确认无结果 |
| F2.5 | web-analysis.md 安全规则中不再有与文件放置重复的描述 | Grep "Cookie/Token.*任务目录" 确认无结果 |
| F3 | web-analysis.md 第 42 行变量覆盖语句已删除 | Grep "专属说明" 在 web-analysis.md 中无结果 |
| F4 | detect_env.py 包含 requests、bs4、lxml | Grep 确认 REQUIRED_PACKAGES 中有这三个包 |
| F4.5 | detect_env.py `--agent` 支持环境变量 AGENT_NAME，命令行参数优先级更高 | Grep "AGENT_NAME" 确认存在 |
| F4.6 | Plugin 注入 AGENT_NAME 环境变量 | Read tool.execute.before 确认与 SESSION_ID 并列注入 |
| F5 | web_helpers.py 可 import 且无语法错误 | `$BA_PYTHON -c "import sys; sys.path.insert(0,...); import web_helpers"` |
| F6 | registry.json 格式正确 | `python -c "import json; json.load(open(...))"` |
| F7 | web-analysis.md 工具清单引用 web_helpers.py | Read 确认 |
| F8 | venv 可 import requests、bs4、lxml | `$BA_PYTHON -c "import requests; import bs4; import lxml"` |

### 4.2 回归验收

| # | 验收项 | 验证方式 |
|---|--------|---------|
| R1 | binary-analysis.md 引用的 execution-discipline 仍正常展开 | 检查 {{buwai-rule:execution-discipline}} 占位符 |
| R2 | mobile-analysis.md 引用的 execution-discipline 仍正常展开 | 同上 |
| R3 | web-analysis.md 展开后行数 < 450 行 | 计算: .md 行数 - 占位符行数 + 片段行数之和 |

### 4.3 架构验收

| # | 验收项 |
|---|--------|
| A1 | 文件放置规则只存在一份（execution-discipline.md），不重复 |
| A2 | web-analysis/scripts/ 遵循归档规则（agent 专属目录） |
| A3 | 依赖方向正确: web-analysis 可引用 shared (binary-analysis)，不反向 |
| A4 | web_helpers.py 通过 $BA_PYTHON 调用（venv 中有 requests + bs4 + lxml），不要求系统 Python 可用 |
| A5 | AGENT_NAME 通过 Plugin 环境变量自动注入，文档中不硬编码 `--agent` 参数 |

---

## §5 与现有需求文档的关系

| 相关需求 | 关系 |
|---------|------|
| `2026-05-05-web-analysis-agent.md` | 本次改进基于该文档创建的 web-analysis agent |
| `2026-05-03-agent-prompt-snippets.md` | 使用了该文档建立的共享片段机制 |
| `2026-04-28-task-dir-persistence.md` | 文件放置规则是该文档的补充强化 |
