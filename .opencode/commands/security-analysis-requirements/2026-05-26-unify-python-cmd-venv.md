# 进化需求：统一 $PYTHON_CMD 为 venv Python，消除双 Python 体系

## §1 背景与目标

### 来源

上一轮进化（`2026-05-26-plugin-inject-python-cmd.md`）注入了 `$PYTHON_CMD` 消除 python/python3 歧义，但遗留了双 Python 体系：
- `$PYTHON_CMD` = 系统 Python（无第三方包）
- `$BA_PYTHON` = venv Python（有第三方包）

双体系导致：
1. Agent 必须执行 Step 3 从 env_cache.json 提取 `$BA_PYTHON`（浪费 1-3 轮对话）
2. 知识库/片段中大量 `$BA_PYTHON` vs `$PYTHON_CMD` 的说明文字（浪费上下文）
3. Agent 可能用错 Python（系统 Python 没有 frida/capstone 等包）
4. venv 创建时序不确定（依赖 detect_env.py 先跑完）

### 目标

Plugin 启动时保证 venv 存在，`$PYTHON_CMD` 直接指向 venv Python 绝对路径。删除 `$BA_PYTHON` 概念。

**效果**：
- 1 个 Python 变量代替 2 个
- `$PYTHON_CMD` 是绝对路径（不可能用错）
- venv 创建由 Plugin 保证（不可能忘记初始化）
- task-initialization.md 从 3 Step 简化为 2 Step

## §2 技术方案

### 核心变更

```
Plugin 启动
  → ensureVenvPython(): 检测 ~/bw-security-analysis/.venv 是否存在且可用
  → 不存在 → findSystemPython() 找系统 Python → 创建 venv → 验证
  → 任一步失败 → throw Error（Plugin 加载失败，agent 停止）
  → 成功 → $PYTHON_CMD = venv python 绝对路径
```

### 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `plugins/security-analysis.ts` | 修改 | 新增 ensureVenvPython()，$PYTHON_CMD 改为 venv 路径，删除 $BA_PYTHON 注入 |
| `binary-analysis/scripts/detect_env.py` | 修改 | 删除 _ensure_venv()、_venv_python_path()，函数参数 venv_python → sys.executable |
| `binary-analysis/knowledge-base/task-initialization.md` | 修改 | 删除 Step 3，简化变量表 |
| `agents-rules/variable-initialization.md` | 修改 | 删除 $BA_PYTHON 行和强制规则 |
| `agents-rules/running-environment.md` | 修改 | 删除 BA_PYTHON vs PYTHON_CMD 段 |
| `agents-rules/task-initialization.md` | 修改 | $BA_PYTHON 引用改为 $PYTHON_CMD |
| `agents-rules/execution-discipline.md` | 修改 | $BA_PYTHON → $PYTHON_CMD（2 处） |
| `binary-analysis/knowledge-base/web-rendering.md` | 修改 | $BA_PYTHON → $PYTHON_CMD（10 处） |
| `binary-analysis/knowledge-base/verification-patterns.md` | 修改 | $BA_PYTHON → $PYTHON_CMD（2 处） |
| `binary-analysis/knowledge-base/gui-automation.md` | 修改 | $BA_PYTHON → $PYTHON_CMD（2 处） |
| `mobile-analysis/knowledge-base/mobile-frida.md` | 修改 | $BA_PYTHON → $PYTHON_CMD（4 处） |
| `agents/binary-analysis.md` | 修改 | 删除 $BA_PYTHON 注释行 |
| `binary-analysis/scripts/registry.json` | 修改 | $BA_PYTHON → $PYTHON_CMD（6 处）；python3 → $PYTHON_CMD（1 处） |
| `mobile-analysis/scripts/registry.json` | 修改 | $BA_PYTHON → $PYTHON_CMD（4 处） |
| `commands/gui-interact-pc.md` | 修改 | 删除 $BA_PYTHON 引用 |
| `binary-analysis/environment-setup.md` | 修改 | 重写为简化的两类环境说明，删除手动命令段 |
| `binary-analysis/scripts/web_render.py` | 修改 | docstring 中 $BA_PYTHON → $PYTHON_CMD |
| `web-analysis/scripts/web_helpers.py` | 修改 | docstring 中 $BA_PYTHON → $PYTHON_CMD |

**不修改**：`commands/security-analysis-requirements/` 下的历史需求文档（17 处 $BA_PYTHON 引用）——历史决策记录，不改。

### 架构影响

- **Plugin → Agent 交互**：`$PYTHON_CMD` 从 `"python"` 变为绝对路径如 `C:\Users\xxx\bw-security-analysis\.venv\Scripts\python.exe`。Agent 行为不变（执行命令时用变量值替换）。
- **detect_env.py**：不再创建 venv，由 Plugin 保证。但仍有 install packages 的职责。
- **删除 $BA_PYTHON**：EnvData 接口中的 `venv_python` 字段保留（兼容旧缓存），但 Plugin 不再注入它。

## §3 实现规范

### 编码规则

1. `$PYTHON_CMD` 在所有文件中是字面量字符串（agent 会从环境信息段获取实际值并替换）
2. 绝对路径只在 Plugin 的 TypeScript 代码中出现，md/json/py 文件中只有 `$PYTHON_CMD` 变量名
3. venv 创建失败时的错误信息必须包含具体原因和手动修复指引

### §3.1 实施步骤拆分

#### 步骤 1. Plugin 核心 — ensureVenvPython + $PYTHON_CMD 改为 venv 路径

- **文件**: `plugins/security-analysis.ts`
- **预估行数**: ~80
- **改动**:
  1. 新增 `ensureVenvPython()` 函数：检测 venv python 存在性 → 验证可执行 → 不存在则创建 → 失败则 throw
  2. `findSystemPython()`：从 `detectPythonCmd()` 重命名，仅用于创建 venv 时寻找系统 Python
  3. 模块级：`const PYTHON_CMD = ensureVenvPython();`（Plugin 加载时执行一次，缓存结果）
  4. `buildEnvSection()`：`系统 Python ($PYTHON_CMD): ${detectPythonCmd()}` → `Python ($PYTHON_CMD): ${PYTHON_CMD}`
  5. `buildEnvSection()`：删除 `if (envInfo.venv_python) { envSection += "- BA_PYTHON: ..." }` 代码块
  6. `buildSubSessionSystem()` 行 460：`${detectPythonCmd()}` → `$PYTHON_CMD`（字面量，agent 自行替换）；行 461：删除 `$BA_PYTHON 初始化仍需执行`
  7. `system.transform` 行 1367-1368：`${detectPythonCmd()}` → `${PYTHON_CMD}`
  8. `tool.execute.before` 行 1417：`${detectPythonCmd()}` → `${PYTHON_CMD}`
  9. 启动日志：记录 `PYTHON_CMD: <venv python path>`
- **验证点**: `node --check` 语法通过；日志中可见 `ensureVenvPython: verified <path>`

#### 步骤 2. detect_env.py — 删除 venv 创建逻辑

- **文件**: `binary-analysis/scripts/detect_env.py`
- **预估行数**: ~60
- **改动**:
  1. 删除 `_venv_python_path()` 函数（4 行）
  2. 删除 `_ensure_venv()` 函数（17 行）
  3. `run_detection()`：删除 `_ensure_venv()` 调用和失败处理（7 行）；所有 `venv_python` 参数替换为 `sys.executable`
  4. `_detect_package(name, venv_python, ...)` → `_detect_package(name, ...)`：内部用 `sys.executable`
  5. `_install_package(venv_python, ...)` → `_install_package(...)`：内部用 `sys.executable`
  6. `_detect_playwright_browser(venv_python)` → `_detect_playwright_browser()`：内部用 `sys.executable`
  7. `_post_install_playwright(venv_python, ...)` → `_post_install_playwright(...)`：内部用 `sys.executable`
  8. 输出 data 中删除 `venv_python` 字段
  9. `_load_cache()` 缓存验证：不再检查 `venv_python`，只检查时间戳有效
  10. 更新文件头 summary/description（删除"自动创建专用虚拟环境"）
- **验证点**: `python -c "compile(open(...).read(), ..., 'exec')"` 语法通过；`python detect_env.py --help` 正常输出

#### 步骤 3. task-initialization.md 知识库 — 删除 Step 3

- **文件**: `binary-analysis/knowledge-base/task-initialization.md`
- **预估行数**: ~25
- **改动**:
  1. 删除 `## Step 3：初始化 $BA_PYTHON` 整段（11 行）
  2. 变量总结表删除 `$BA_PYTHON` 行，添加说明 `$PYTHON_CMD 由 Plugin 保证可用，无需手动初始化`
  3. 末尾变量表只保留 `$TASK_DIR`（来自 Step 1），其他变量由 Plugin 注入
- **验证点**: 文件无 `$BA_PYTHON` 引用；Step 1 和 Step 2 完整自包含

#### 步骤 4. agents-rules 片段（4 文件）— 删除 $BA_PYTHON 引用

- **文件**: `agents-rules/variable-initialization.md`, `agents-rules/running-environment.md`, `agents-rules/task-initialization.md`, `agents-rules/execution-discipline.md`
- **预估行数**: ~20
- **改动**:
  - `variable-initialization.md`：删除 `$BA_PYTHON` 行和 `$BA_PYTHON` 强制规则；说明 `$PYTHON_CMD` 由 Plugin 保证可用（已含 venv 包）
  - `running-environment.md`：删除 `BA_PYTHON vs PYTHON_CMD` 整段（1 行），更新说明为 `$PYTHON_CMD 由 Plugin 检测并注入（venv Python 绝对路径，含所有第三方包）`
  - `task-initialization.md`（snippet）：`$TASK_DIR 和 $BA_PYTHON` → `$TASK_DIR`；变量表删除 `$BA_PYTHON` 行；说明改为 `$PYTHON_CMD 由 Plugin 保证`
  - `execution-discipline.md`：`$BA_PYTHON` → `$PYTHON_CMD`（2 处）
- **验证点**: 4 个文件中 grep 无 `$BA_PYTHON` 匹配

#### 步骤 5. 知识库文件（4 文件）— $BA_PYTHON → $PYTHON_CMD

- **文件**: `binary-analysis/knowledge-base/web-rendering.md`, `binary-analysis/knowledge-base/verification-patterns.md`, `binary-analysis/knowledge-base/gui-automation.md`, `mobile-analysis/knowledge-base/mobile-frida.md`
- **预估行数**: ~20（纯替换）
- **改动**: 所有 `$BA_PYTHON` 替换为 `$PYTHON_CMD`（共 18 处）
- **验证点**: 4 个文件中 grep 无 `$BA_PYTHON` 匹配

#### 步骤 6. registry + agent prompt + commands + docstrings（6 文件）

- **文件**: `binary-analysis/scripts/registry.json`, `mobile-analysis/scripts/registry.json`, `agents/binary-analysis.md`, `commands/gui-interact-pc.md`, `binary-analysis/scripts/web_render.py`, `web-analysis/scripts/web_helpers.py`
- **预估行数**: ~15
- **改动**:
  - `registry.json`（binary）：`$BA_PYTHON` → `$PYTHON_CMD`（6 处）；`python3` → `$PYTHON_CMD`（1 处，create_task_dir 的 example_call）
  - `registry.json`（mobile）：`$BA_PYTHON` → `$PYTHON_CMD`（4 处：runner 字段 2 + usage 字段 2）
  - `binary-analysis.md` 行 216：删除 `> 注意: detect_env.py 使用系统 Python（$PYTHON_CMD），不用 $BA_PYTHON。`（此行不再需要）
  - `gui-interact-pc.md`：删除 `$BA_PYTHON` 相关句子，改为 `$PYTHON_CMD` 由 Plugin 注入
  - `web_render.py` docstring：`$BA_PYTHON` → `$PYTHON_CMD`
  - `web_helpers.py` docstring：`$BA_PYTHON` → `$PYTHON_CMD`
- **验证点**: 6 个文件中 grep 无 `$BA_PYTHON` 匹配；2 个 JSON 文件 `python -c "json.load(open(...))"` 通过

#### 步骤 7. environment-setup.md — 重写为简化版本

- **文件**: `binary-analysis/environment-setup.md`
- **预估行数**: ~40
- **改动**:
  1. "虚拟环境策略"段：重写为"Plugin 自动管理 venv，无需手动操作"
  2. "三类 Python 环境"表 → "两类"（删除"系统 Python"行，保留 venv Python 和 IDA Python）
  3. "自动检测"段：删除手动命令，改为"启动 agent 会话时 Plugin 自动处理"
  4. 各平台"Python 包"段：保留手动安装命令（venv python 路径），作为故障恢复参考
  5. "常见问题"段：删除 `python3 命令不存在` 条目（已无意义）
- **验证点**: 文件无 `$BA_PYTHON` 引用；无 `python3` 命令模板

#### 步骤 8. 最终全量验证

- **文件**: 无代码改动
- **验证点**:
  1. 全目录 grep `$BA_PYTHON`：仅在 `commands/security-analysis-requirements/` 历史文档中出现（预期）
  2. 全目录 grep `$PYTHON_CMD`：确认所有活跃文件使用正确
  3. Plugin `node --check` 通过
  4. 所有修改过的 `.py` 文件 `compile()` 通过
  5. 所有修改过的 `.json` 文件 `json.load()` 通过
  6. agent prompt 展开后行数 < 450

## §4 验收标准

### 功能验收

- [ ] `$PYTHON_CMD` 在环境信息中显示为 venv python 绝对路径
- [ ] 环境信息中不存在 `BA_PYTHON`
- [ ] task-initialization.md 只有 2 个 Step（Step 3 已删除）
- [ ] variable-initialization.md 变量表只有 3 行（$AGENT_DIR, $SHARED_DIR, $IDAT）
- [ ] detect_env.py 不包含 `_ensure_venv` 或 `_venv_python_path` 函数
- [ ] `commands/security-analysis-requirements/` 之外无 `$BA_PYTHON` 出现

### 回归验收

- [ ] Plugin 加载成功，日志中可见 `PYTHON_CMD: <venv path>`
- [ ] Agent 能正常读取环境信息并执行 `$PYTHON_CMD` 命令
- [ ] detect_env.py 用 `$PYTHON_CMD` 执行后能正确安装/检测包
- [ ] registry.json 中所有脚本能被 agent 正确调用

### 架构验收

- [ ] venv 创建职责从 detect_env.py 收口到 Plugin
- [ ] `$PYTHON_CMD` 是唯一的 Python 变量，无 `$BA_PYTHON`
- [ ] 所有活跃文件（非历史文档）中无 `$BA_PYTHON` 引用
- [ ] 依赖方向未违反（Plugin → agent → knowledge-base，单向）

## §5 与现有需求文档的关系

- **替代** `2026-05-26-plugin-inject-python-cmd.md` 中的 `$BA_PYTHON` 相关部分（该文档中 `$PYTHON_CMD` 注入部分已完成，本次进化删除遗留的 `$BA_PYTHON`）
- **继承** `2026-04-22-environment-dependency-hardening.md` 中引入 `$BA_PYTHON` 的设计决策，并将其推进到最终形态（$PYTHON_CMD 统一 venv Python）
- **不影响** 其他需求文档中的功能实现
