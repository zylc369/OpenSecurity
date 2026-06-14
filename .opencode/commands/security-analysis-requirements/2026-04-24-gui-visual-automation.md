# 需求文档: 视觉驱动 GUI 自动化操作

## §1 背景与目标

**来源**: 复盘 `docs/进化/进化-GUI自动化操作.md`（Phase 0-1 产出，用户已确认做方案 A + B）。

**痛点**（来自 TencentPediyKeygenMe2 分析过程）:
1. `gui_verify.py` 控件 ID 硬编码（1000/1001/1002），不同程序直接失败
2. 只能用 Win32 消息机制操作控件，MFC/Qt/Electron 不响应 `WM_SETTEXT`
3. 结果检测依赖 MessageBox 关键词匹配，静默失败的程序无法判断
4. 不截图不留痕，失败后无法诊断
5. 线性流水线 + 单一 timeout，任何一步失败都静默等待到超时

**核心洞察**: 用多模态 LLM（zai-mcp-server）识别截图中的控件位置和文字，用坐标级键鼠操作（pyautogui + pyperclip）模拟人的操作，用截图对比判断操作结果。不依赖控件 API，跨框架通用。

**目标**: 替换 `gui_verify.py` 的 Win32 控件级方案，建立视觉驱动的 GUI 自动化体系。保留 `gui_verify.py` 的 Win32 discover/hook 能力作为方案 B 降级路径。

**预期收益**:
- 上下文: GUI 操作从"多轮对话排查卡住原因"到"一步到位截图→识别→操作"，减少 3-5 轮
- 轮次: GUI 操作从需要用户手动介入到全自动零人工，从 N 次人工 → 0 次
- 速度: 每步 5-10s（截图+MCP+操作），无超时等待
- 准确度: 视觉定位不依赖控件 API，根本性提升

## §2 技术方案

### 方案概览

| 方案 | 改动文件 | 核心内容 |
|------|---------|---------|
| A1: gui_capture.py | 新建 `scripts/gui_capture.py` | 截图工具（全屏/窗口，JPEG quality=50，输出文件 + 元数据 JSON） |
| A2: gui_act.py | 新建 `scripts/gui_act.py` | 键鼠操作（click/type/hotkey/scroll，通过 pyautogui + pyperclip） |
| A3: gui_launch.py | 新建 `scripts/gui_launch.py` | 进程/窗口管理（启动、查找、前台、kill，P0 Windows） |
| A4: gui-automation.md | 新建 `knowledge-base/gui-automation.md` | GUI 自动化操作规范（单点维护知识库） |
| A5: gui-interact-pc.md | 新建 `commands/gui-interact-pc.md` | OpenCode 命令（薄壳，引用知识库） |
| B: 降级策略 | 更新 `agents/binary-analysis.md`（验证决策树） + `knowledge-base/verification-patterns.md` | gui_verify.py 作为 MCP 不可用时的降级路径，降级护栏 |
| C: registry.json | 更新 `scripts/registry.json` | 新增 3 个脚本条目 |
| D: Agent prompt | 更新 `agents/binary-analysis.md`（GUI 脚本小节 + 知识库索引） | GUI 验证脚本小节改为视觉驱动首选 + gui_verify.py 降级 |

---

### 方案 A1: gui_capture.py — 截图工具

**新建文件**: `.opencode/binary-analysis/scripts/gui_capture.py`

**功能**: 全屏截图，输出图片文件 + 元数据 JSON。

**参数**:
| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| --output-dir | 是 | - | 输出目录（截图和 JSON 写入此目录） |
| --name | 否 | `screenshot` | 输出文件名前缀（不含扩展名） |
| --format | 否 | `jpeg` | 图片格式（jpeg/png） |
| --quality | 否 | 50 | JPEG 质量（1-100，仅 jpeg 有效） |

**输出**: 在 `--output-dir` 下生成两个文件:
1. `<name>.jpg`（或 `<name>.png`）— 截图文件
2. `<name>.json` — 元数据

**元数据 JSON 格式**:
```json
{
  "success": true,
  "file": "screenshot.jpg",
  "format": "jpeg",
  "quality": 50,
  "screen_resolution": [1920, 1080],
  "screenshot_size": [1920, 1080]
}
```

**实现要点**:
- 使用 `pyautogui.screenshot()` 截图
- JPEG quality=50（实测 3440x1920 约 216KB，MCP 识别零损失）
- 坐标系统：`pyautogui.screenshot()` 和 `pyautogui.click()` 坐标系一致，无需映射
- 错误处理：pyautogui 不可用 → `{"success": false, "error": "pyautogui 未安装"}`
- 脚本自动创建输出目录（如果不存在）
- 通过 `$BA_PYTHON` 执行（依赖第三方包 pyautogui）

---

### 方案 A2: gui_act.py — 键鼠操作

**新建文件**: `.opencode/binary-analysis/scripts/gui_act.py`

**功能**: 坐标级键鼠操作，模拟人的操作。

**参数**:
| 参数 | 必填 | 说明 |
|------|------|------|
| --action | 是 | 操作类型：`click` / `double_click` / `type` / `hotkey` / `scroll` |
| --x | click/double_click 必填 | X 坐标 |
| --y | click/double_click 必填 | Y 坐标 |
| --text | type 必填 | 要输入的文本 |
| --keys | hotkey 必填 | 快捷键（如 `ctrl+c`，`+` 分隔） |
| --direction | scroll 必填 | 滚动方向：`up` / `down` |
| --clicks | scroll 必填（默认 3） | 滚动次数 |
| --button | 否 | 鼠标按钮：`left`（默认）/ `right` / `middle` |
| --paste | 否（flag，无值） | type 模式下用剪贴板粘贴代替逐字输入（推荐，更快更可靠） |
| --settle | 否 | 操作后等待时间（秒，默认 0.5） |

**输出 JSON 格式**:
```json
{
  "success": true,
  "action": "click",
  "params": {"x": 460, "y": 320},
  "settle_seconds": 0.5
}
```

**实现要点**:
- `click` / `double_click`: `pyautogui.click(x, y)` / `pyautogui.doubleClick(x, y)`
- `type`: 默认 `pyautogui.typewrite(text)`（英文）或 `pyperclip.paste()`（中文/特殊字符）
  - `--paste` 模式: `pyperclip.copy(text)` → `pyautogui.hotkey('ctrl', 'v')`（推荐，支持中文）
  - 无 `--paste` 时: 对纯 ASCII 文本用 `pyautogui.typewrite()`，含非 ASCII 字符时自动切换到 paste 模式
- `hotkey`: `pyautogui.hotkey(*keys.split('+'))`
- `scroll`: `pyautogui.scroll(clicks, x=x, y=y)`（正=up，负=down）
- 操作后 `time.sleep(settle)` 等待界面响应
- 错误处理：坐标超出屏幕 → 返回错误

---

### 方案 A3: gui_launch.py — 进程/窗口管理

**新建文件**: `.opencode/binary-analysis/scripts/gui_launch.py`

**功能**: 管理目标进程（启动、查找窗口、切前台、终止）。

**参数必填矩阵**:

| 参数 | launch | find_window | bring_to_front | kill | wait_window |
|------|--------|-------------|----------------|------|-------------|
| --action | ✓ | ✓ | ✓ | ✓ | ✓ |
| --exe | 必填 | | | | |
| --pid | | 必填 | 必填 | 必填 | 必填 |
| --title | | 可选 | | | 可选 |
| --timeout | | | | | 可选（默认 10） |

**参数**:
| 参数 | 必填 | 说明 |
|------|------|------|
| --action | 是 | `launch` / `find_window` / `bring_to_front` / `kill` / `wait_window` |
| --exe | launch 必填 | 可执行文件路径 |
| --pid | find_window/bring_to_front/kill/wait_window 必填 | 进程 ID |
| --title | find_window 可选 | 窗口标题匹配（子串匹配，大小写不敏感） |
| --timeout | 否 | 等待窗口出现的超时秒数（默认 10） |

**输出 JSON 格式**:

launch:
```json
{
  "success": true,
  "action": "launch",
  "pid": 12345,
  "exe": "C:\\path\\to\\target.exe"
}
```

find_window:
```json
{
  "success": true,
  "action": "find_window",
  "pid": 12345,
  "windows": [
    {"handle": 123456, "title": "MainWindow", "class": "Qt5QWindow", "rect": [100, 100, 800, 600]}
  ]
}
```

kill:
```json
{
  "success": true,
  "action": "kill",
  "pid": 12345
}
```

**实现要点**:

**launch**:
- 检查目标进程是否已运行（按 exe 文件名匹配，P0 Windows 用 `tasklist /FI "IMAGENAME eq <basename>"` + 解析输出）→ 已运行则先 kill（避免两个同名窗口干扰截图）
- `subprocess.Popen([exe])` 启动
- 启动后立即检查 `proc.poll()` — 如果立即退出（exit code ≠ 0），读取 stderr 诊断
- 返回 pid

**find_window**:
- P0 Windows: 用 `ctypes` + `EnumWindows` + `GetWindowThreadProcessId` 查找
- 可选 `--title` 过滤（子串匹配）
- 返回窗口列表（handle、title、class、rect）

**bring_to_front**:
- P0 Windows: `SetForegroundWindow` + `ShowWindow(SW_RESTORE)`

**kill**:
- P0 Windows: `taskkill /PID <pid> /F`
- kill 自己启动的进程不需要管理员权限

**wait_window**:
- 轮询 `find_window`（同上），直到找到窗口或超时
- 返回值与 `find_window` 相同
- 超时 → `{"success": false, "error": "等待窗口超时"}`

**跨平台策略**: 对外暴露统一接口，内部按平台分发。P0 只实现 Windows（ctypes Win32 API），P1 macOS（osascript），P2 Linux（xdotool/wmctrl）。切换平台只改 gui_launch.py 内部，其他脚本和知识库不受影响。

---

### 方案 A4: gui-automation.md — 知识库

**新建文件**: `.opencode/binary-analysis/knowledge-base/gui-automation.md`

**功能**: GUI 自动化操作的完整规范。`gui-interact-pc` 命令和 Binary-Analysis agent 共享此文件（单点维护）。

**内容结构**:
```markdown
# GUI 自动化操作规范

> Binary-Analysis agent 和 gui-interact-pc 命令共享此规范。

## 前提条件

- 需要 `pyautogui` 和 `pyperclip`（通过 `$BA_PYTHON` 运行脚本）
- 需要 `zai-mcp-server` MCP（视觉理解能力）
- 脚本路径: `$SCRIPTS_DIR/scripts/gui_capture.py` / `gui_act.py` / `gui_launch.py`

## 标准操作流程

### Step 1: 启动目标程序
```
$BA_PYTHON $SCRIPTS_DIR/scripts/gui_launch.py --action launch --exe <TARGET>
```
记录返回的 PID。

### Step 2: 等待窗口出现
```
$BA_PYTHON $SCRIPTS_DIR/scripts/gui_launch.py --action wait_window --pid <PID> --timeout 10
```

### Step 3: 截图定位控件
```
$BA_PYTHON $SCRIPTS_DIR/scripts/gui_capture.py --output-dir $TASK_DIR/view --name step1_initial
```

使用 MCP 分析截图:
- `zai-mcp-server_extract_text_from_screenshot`: 提取所有控件文字和坐标
- 或 `zai-mcp-server_ui_to_artifact`（output_type='spec'): 获取 UI 规范

### Step 4: 执行操作序列（连续执行，中间不截图）
```
# 点击输入框
$BA_PYTHON $SCRIPTS_DIR/scripts/gui_act.py --action click --x 460 --y 320

# 输入文本（推荐 paste 模式，支持中文）
$BA_PYTHON $SCRIPTS_DIR/scripts/gui_act.py --action type --text "username" --paste

# 点击下一个输入框
$BA_PYTHON $SCRIPTS_DIR/scripts/gui_act.py --action click --x 460 --y 380

# 输入 license
$BA_PYTHON $SCRIPTS_DIR/scripts/gui_act.py --action type --text "XXXX-XXXX" --paste

# 点击验证按钮
$BA_PYTHON $SCRIPTS_DIR/scripts/gui_act.py --action click --x 500 --y 440 --settle 1
```

### Step 5: 截图读取结果
```
$BA_PYTHON $SCRIPTS_DIR/scripts/gui_capture.py --output-dir $TASK_DIR/view --name step2_result
```

使用 MCP 判断结果:
- 首选: `zai-mcp-server_ui_diff_check`（对比 step1_initial 和 step2_result）
- 退化: `zai-mcp-server_extract_text_from_screenshot`（提取 step2_result 文字）

### Step 6: 清理
```
$BA_PYTHON $SCRIPTS_DIR/scripts/gui_launch.py --action kill --pid <PID>
```

## 失败重试策略

| 失败现象 | 重试方式 |
|---------|---------|
| MCP 说"两张图片看起来一样" | 换操作方式（剪贴板粘贴 → 逐字输入）重试一次 |
| 仍然没变化 | 重新截图让 MCP 再次定位坐标 |
| MCP 超时连续 2 次 | 降级到 gui_verify.py（Win32 控件方案，仅标准 Win32 有效） |
| MCP 完全不可用 | 降级到 gui_verify.py |

## 视觉分析产物管理（强制）

1. 截图时机：只在需要信息时截图（定位控件、读结果、诊断故障），不在每步操作前后都截
2. 操作序列：拿到坐标后，连续执行所有操作（click/type），中间不截图
3. 结果验证：操作序列完成后，等 0.5-1s，截一张图让 MCP 判断结果
4. 产物存储：所有截图存储到 `$TASK_DIR/view/`
5. 每次新的截图，文件名按操作阶段命名：step1_initial、step2_result、step3_diagnosis
6. 上下文压缩后：操作 GUI 前必须拍新截图确认当前状态（不能用旧截图）

## 坐标系统说明

截图和操作统一使用 pyautogui，坐标系统一致。MCP 返回的坐标 (460, 320) 可直接传给 gui_act.py --x 460 --y 320，无需映射。
```

---

### 方案 A5: gui-interact-pc.md — OpenCode 命令

**新建文件**: `.opencode/commands/gui-interact-pc.md`

**内容**（薄壳，约 5 行）:
```markdown
---
description: GUI 自动化交互 — 截图、视觉识别、键鼠操作
---

使用 Read 工具读取 `$SCRIPTS_DIR/knowledge-base/gui-automation.md`，按照其中的规范执行用户的 GUI 操作请求。

如果 `$SCRIPTS_DIR` 未设置，从 `~/bw-security-analysis/config.json` 的 `scripts_dir` 字段读取。如果 `$TASK_DIR` 未设置，创建 `~/bw-security-analysis/workspace/gui_<timestamp>/` 作为工作目录，截图放在其中的 `view/` 子目录下。
```

---

### 方案 B: 降级策略（gui_verify.py 作为后备）

**改动文件**:
- `.opencode/agents/binary-analysis.md` — 验证决策树 + GUI 验证脚本小节
- `.opencode/binary-analysis/knowledge-base/verification-patterns.md` — GUI 程序分支更新

#### B1: Agent prompt 验证决策树更新

将 `binary-analysis.md` 的验证决策树中 GUI 分支更新:

```
└─ GUI → 视觉驱动 GUI 自动化
         ├─ 截图 → MCP 定位控件 → 键鼠操作 → 截图读结果
         ├─ MCP 连续 2 次超时或不可用 → 降级 gui_verify.py
         │   ├─ 控件 ID 未知 → --discover
         │   ├─ 标准操作 → 默认模式
         │   ├─ 输入不进去 → --hook-inject
         │   ├─ 读不出结果 → --hook-result
         │   └─ 全部失败 → Patch 排除法 → 用户人工确认
         └─ 全部失败 → Patch 排除法 → 用户人工确认
```

**降级护栏（写死在 prompt 中）**:
1. Agent 默认走视觉驱动方案（方案 A）
2. 降级触发条件：MCP 连续 2 次超时 或 MCP 完全不可用
3. 恢复机制：降级后每次 GUI 操作前仍尝试 MCP（1 次），恢复则切回视觉驱动
4. 方案 B 不出现在主路径上，只在"MCP 不可用"的错误处理分支中

#### B2: verification-patterns.md 更新

在 verification-patterns.md 的决策树中"GUI 程序 → gui_verify.py（方案 A）"那一行（编辑前第 25 行）及其子分支（第 26-30 行），替换为:

```markdown
### GUI 程序 → 视觉驱动 GUI 自动化（首选）

1. 截图 → MCP 识别控件坐标和文字
2. 键鼠操作（gui_act.py）模拟点击和输入
3. 再截图 → MCP 对比判断结果

详细操作流程见 `$SCRIPTS_DIR/knowledge-base/gui-automation.md`。

### 降级: gui_verify.py（仅当 MCP 不可用时）

触发条件: MCP 连续 2 次超时 或 MCP 服务完全不可用。
一旦降级，每次操作前仍尝试 MCP（1 次），恢复则切回视觉驱动。
```

#### B3: GUI 验证脚本小节更新（与方案 D2 合并执行）

替换 `binary-analysis.md` 的 `### GUI 验证脚本` 小节（编辑前第 333-351 行），具体替换内容见方案 D2 中的代码块。

---

### 方案 C: registry.json 更新

在 `scripts/registry.json` 的 `scripts` 数组中新增 3 个条目:

```json
{
  "name": "gui_capture",
  "file": "gui_capture.py",
  "description": "全屏截图工具，输出 JPEG/PNG 图片 + 元数据 JSON",
  "params": ["--output-dir", "--name", "--format", "--quality"],
  "example_call": "$BA_PYTHON $SCRIPTS_DIR/scripts/gui_capture.py --output-dir $TASK_DIR/view --name step1_initial",
  "added_at": "2026-04-24",
  "verified": false
},
{
  "name": "gui_act",
  "file": "gui_act.py",
  "description": "坐标级键鼠操作（click/type/hotkey/scroll），支持剪贴板粘贴",
  "params": ["--action", "--x", "--y", "--text", "--keys", "--direction", "--clicks", "--button", "--paste", "--settle"],
  "example_call": "$BA_PYTHON $SCRIPTS_DIR/scripts/gui_act.py --action click --x 460 --y 320",
  "added_at": "2026-04-24",
  "verified": false
},
{
  "name": "gui_launch",
  "file": "gui_launch.py",
  "description": "进程和窗口管理（launch/find_window/bring_to_front/kill），P0 仅 Windows",
  "params": ["--action", "--exe", "--pid", "--title", "--timeout"],
  "example_call": "$BA_PYTHON $SCRIPTS_DIR/scripts/gui_launch.py --action launch --exe TARGET.EXE",
  "added_at": "2026-04-24",
  "verified": false
}
```

---

### 方案 D: Agent prompt 更新

#### D1: 知识库索引新增

在 `binary-analysis.md` 的知识库索引表中新增:

```markdown
| `gui-automation.md` | GUI 自动化操作（视觉驱动方案） |
```

#### D2: GUI 验证脚本小节更新

替换 `binary-analysis.md` 的 `### GUI 验证脚本` 小节，新增视觉驱动方案脚本:

```markdown
### GUI 自动化工具

> 视觉驱动 GUI 自动化方案详情见 `$SCRIPTS_DIR/knowledge-base/gui-automation.md`。
> 以下为脚本快速参考。

#### 视觉驱动方案（首选）

```bash
# 启动目标程序
"$BA_PYTHON" "$SCRIPTS_DIR/scripts/gui_launch.py" --action launch --exe <TARGET>

# 截图定位控件
"$BA_PYTHON" "$SCRIPTS_DIR/scripts/gui_capture.py" --output-dir "$TASK_DIR/view" --name step1_initial

# 键鼠操作（MCP 返回坐标后执行）
"$BA_PYTHON" "$SCRIPTS_DIR/scripts/gui_act.py" --action click --x 460 --y 320
"$BA_PYTHON" "$SCRIPTS_DIR/scripts/gui_act.py" --action type --text "license" --paste

# 截图读结果
"$BA_PYTHON" "$SCRIPTS_DIR/scripts/gui_capture.py" --output-dir "$TASK_DIR/view" --name step2_result

# 清理
"$BA_PYTHON" "$SCRIPTS_DIR/scripts/gui_launch.py" --action kill --pid <PID>
```

#### 降级方案（MCP 不可用时）: gui_verify.py

```bash
# 标准模式
"$BA_PYTHON" "$SCRIPTS_DIR/scripts/gui_verify.py" --exe <TARGET> --username <USER> --license <LICENSE> --output "$TASK_DIR/gui_result.json"

# 控件探测（ID 未知时先探测）
"$BA_PYTHON" "$SCRIPTS_DIR/scripts/gui_verify.py" --exe <TARGET> --discover --output "$TASK_DIR/discover.json"

# Hook 注入（GUI 输入不进去时，推荐用文件传参避免转义问题）
"$BA_PYTHON" "$SCRIPTS_DIR/scripts/gui_verify.py" --exe <TARGET> --hook-inject --hook-func-addr 0x401000 --hook-inputs-file "$TASK_DIR/inputs.json" --output "$TASK_DIR/result.json"

# Hook 读取结果（读不出结果时）
"$BA_PYTHON" "$SCRIPTS_DIR/scripts/gui_verify.py" --exe <TARGET> --username <USER> --license <LICENSE> --hook-result --hook-compare-addr 0x401200 --output "$TASK_DIR/result.json"

# Hook 注入 + Hook 读取结果 组合模式（GUI 无法输入也无法读取结果时）
"$BA_PYTHON" "$SCRIPTS_DIR/scripts/gui_verify.py" --exe <TARGET> --hook-inject --hook-func-addr 0x401000 --hook-inputs-file "$TASK_DIR/inputs.json" --hook-result --hook-compare-addr 0x401200 --hook-trigger-addr 0x401500 --output "$TASK_DIR/result.json"
```
```

---

## §3 实现规范

### 改动范围表

| 文件 | 改动类型 | 方案 | 预估行数 |
|------|---------|------|---------|
| `scripts/gui_capture.py` | 新建 | A1 | ~60 行 |
| `scripts/gui_act.py` | 新建 | A2 | ~80 行 |
| `scripts/gui_launch.py` | 新建 | A3 | ~120 行 |
| `knowledge-base/gui-automation.md` | 新建 | A4 | ~120 行 |
| `commands/gui-interact-pc.md` | 新建 | A5 | ~10 行 |
| `agents/binary-analysis.md` | 更新 | B1+D | ~30 行改动 |
| `knowledge-base/verification-patterns.md` | 更新 | B2 | ~15 行改动 |
| `scripts/registry.json` | 更新 | C | ~30 行新增 |
| `plugins/security-analysis.ts` | 无改动 | - | - |

### 编码规则

1. 新脚本（gui_capture.py/gui_act.py/gui_launch.py）是**纯 Python 脚本**，不依赖 IDA 运行时，不使用 `_base.py` 基础设施
2. 通过 `$BA_PYTHON` 执行（依赖 pyautogui/pyperclip 第三方包）
3. 所有脚本输出 JSON（成功 `{"success": true, ...}` / 失败 `{"success": false, "error": "..."}`）
4. 日志使用中文，关键步骤有 `[*]`/`[+]`/`[!]` 日志
5. gui-automation.md 必须自包含（不依赖主 prompt 上下文即可理解）
6. 知识库文件中使用相对路径引用（`$SCRIPTS_DIR/knowledge-base/xxx.md`）

### §3.1 实施步骤拆分

**步骤 1. 新建 gui_capture.py**
- 文件: `.opencode/binary-analysis/scripts/gui_capture.py`
- 预估行数: ~60 行
- 验证点: `python -c "compile(open('.opencode/binary-analysis/scripts/gui_capture.py').read(), 'gui_capture.py', 'exec')"` 语法检查通过；`python .opencode/binary-analysis/scripts/gui_capture.py --output-dir /tmp/test_gui --name test` 执行成功并在指定目录生成截图文件和 JSON

**步骤 2. 新建 gui_act.py**
- 文件: `.opencode/binary-analysis/scripts/gui_act.py`
- 预估行数: ~80 行
- 验证点: `python -c "compile(open('.opencode/binary-analysis/scripts/gui_act.py').read(), 'gui_act.py', 'exec')"` 语法检查通过；`python .opencode/binary-analysis/scripts/gui_act.py --action click --x 100 --y 100` 执行不报错

**步骤 3. 新建 gui_launch.py**
- 文件: `.opencode/binary-analysis/scripts/gui_launch.py`
- 预估行数: ~120 行
- 验证点: `python -c "compile(open('.opencode/binary-analysis/scripts/gui_launch.py').read(), 'gui_launch.py', 'exec')"` 语法检查通过；`python .opencode/binary-analysis/scripts/gui_launch.py --action launch --exe notepad` 能启动记事本并返回 JSON

**步骤 4. 新建 gui-automation.md 知识库**
- 文件: `.opencode/binary-analysis/knowledge-base/gui-automation.md`
- 预估行数: ~120 行
- 验证点: 人工审阅自包含性 + 引用路径使用 `$SCRIPTS_DIR` 相对路径

**步骤 5. 新建 gui-interact-pc.md 命令**
- 文件: `.opencode/commands/gui-interact-pc.md`
- 预估行数: ~10 行
- 验证点: 人工审阅格式正确

**步骤 6. 更新 registry.json**
- 文件: `.opencode/binary-analysis/scripts/registry.json`
- 预估行数: ~30 行新增
- 验证点: `python -c "import json; json.load(open('.opencode/binary-analysis/scripts/registry.json'))"` 语法检查通过

**步骤 7. 更新 verification-patterns.md（方案 B2）**
- 文件: `.opencode/binary-analysis/knowledge-base/verification-patterns.md`
- 预估行数: ~15 行改动
- 验证点: 人工审阅 — GUI 程序分支包含视觉驱动首选 + 降级策略 + 降级护栏

**步骤 8. 更新 agents/binary-analysis.md（方案 B1+D）**
- 文件: `.opencode/agents/binary-analysis.md`
- 预估行数: ~30 行改动
- 验证点: 1) 验证决策树 GUI 分支更新为"视觉驱动首选 + MCP 不可用时降级 gui_verify.py"；2) GUI 验证脚本小节包含视觉驱动和降级两套脚本示例；3) 知识库索引表包含 gui-automation.md；4) 总行数 < 450 行

---

## §4 验收标准

### 功能验收

| 编号 | 验收项 | 验证方法 |
|------|--------|---------|
| F1 | gui_capture.py 全屏截图并输出 JPEG + 元数据 JSON | 执行命令，检查输出文件存在且 JSON 格式正确 |
| F2 | gui_capture.py JPEG quality=50 产出的截图可被 MCP 识别 | 截图后用 zai-mcp-server_extract_text_from_screenshot 验证 |
| F3 | gui_act.py click/type/hotkey/scroll 操作正确执行 | 各操作类型逐一测试 |
| F4 | gui_act.py --paste 模式支持中文输入 | 输入中文字符并截图验证 |
| F5 | gui_launch.py launch/kill 正常工作 | 启动 notepad 并 kill |
| F6 | gui_launch.py find_window 能返回窗口信息 | 启动 notepad 后查找 |
| F7 | gui-automation.md 自包含可理解 | 不读主 prompt 的情况下能理解全部内容 |
| F8 | Agent prompt 验证决策树 GUI 分支正确 | 人工审阅 — 视觉驱动首选 + 降级路径清晰 |

### 回归验收

| 编号 | 验收项 |
|------|--------|
| R1 | gui_verify.py 所有模式（discover/standard/hook-inject/hook-result）不受影响 |
| R2 | Agent prompt 总行数 < 450 行 |
| R3 | registry.json 所有现有条目不受影响 |

### 架构验收

| 编号 | 验收项 |
|------|--------|
| A1 | 新脚本不依赖 IDA 运行时（纯 Python） |
| A2 | 新脚本不依赖 `_base.py` / `_utils.py` / `_analysis.py`（独立脚本） |
| A3 | 依赖方向合规：知识库文件之间只做引用，不产生循环依赖 |
| A4 | gui-interact-pc.md 是薄壳，所有逻辑在 gui-automation.md 中单点维护 |
| A5 | gui-automation.md 被 agent 和命令共享（单点维护原则） |

## §5 与现有需求文档的关系

| 现有需求 | 关系 |
|---------|------|
| `2026-04-23-verification-framework.md` | 本需求在其验证决策树基础上新增视觉驱动 GUI 方案，将 gui_verify.py 从主路径降级为后备路径。gui_verify.py 代码本身不改动 |
| `2026-04-22-environment-dependency-hardening.md` | 新脚本依赖 pyautogui/pyperclip，通过 `$BA_PYTHON` 执行，环境检测由该需求保障 |
| `2026-04-22-plugin-and-architecture-improvements.md` | 无直接关系，本需求不改 Plugin |
