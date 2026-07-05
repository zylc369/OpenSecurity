# 需求文档: 移动端 WebView 视觉自动化操作

## §1 背景与目标

**来源**: 用户指出 mobile-analysis 遇到混合架构（WebView 加载网页）时完全无法操作 GUI。经 Phase 0 复盘确认当前无任何截图+UI 识别能力。

**痛点**:
1. `uiautomator dump` 遇到 WebView 只能看到 `<android.webkit.WebView bounds="...">` 一个壳节点，DOM 内部的按钮/输入框/弹窗全看不见
2. mobile-analysis 无截图脚本，无 MCP 视觉分析流程
3. `android-ui-automation.md` 只覆盖原生 View 的 XML dump + 坐标点击，对 WebView 场景完全无效
4. `mobile-methodology.md` 路径 4（Hybrid/WebView）只有静态分析（检查 assets/HTML），无运行时 GUI 交互

**核心洞察**: binary-analysis 已验证成熟的「截图→MCP 视觉识别→坐标操作→再截图验证」模式可迁移到移动端，工具从 pyautogui 换成 adb（`adb shell screencap` + `adb shell input tap`），MCP 视觉工具全局共享无需新增依赖。

**目标**: 为 mobile-analysis 建立设备截图能力 + WebView 场景的 MCP 视觉自动化流程。

**预期收益**:
- 上下文: WebView 场景从"无法操作"→可操作（从∞轮→5-8 轮完成交互）
- 轮次: agent 遇到 WebView 不用试探各种方案，直接走视觉路线
- 速度: 每次截图省 10-15 秒的手写 adb 命令
- 准确度: 脚本统一处理设备序列号、路径、错误，减少手写命令出错

## §2 技术方案

### 方案概览

| 方案 | 改动文件 | 核心内容 |
|------|---------|---------|
| 1: mobile_screenshot.py | 新建 `mobile-analysis/scripts/mobile_screenshot.py` | 设备截图工具（adb screencap + pull，输出图片 + 元数据 JSON） |
| 2: android-ui-automation.md | 更新 `mobile-analysis/knowledge-base/android-ui-automation.md` | 新增 WebView 视觉方案章节（截图→MCP→adb tap→验证） |
| 3: mobile-analysis.md prompt | 更新 `agents/mobile-analysis.md` | 工具表新增截图脚本 + 知识库索引更新 |
| 4: mobile-methodology.md | 更新 `mobile-analysis/knowledge-base/mobile-methodology.md` | 路径 4 增加动态交互指引 |
| 5: registry.json | 更新 `mobile-analysis/scripts/registry.json` | 新增截图脚本条目 |

---

### 方案 1: mobile_screenshot.py — 设备截图工具

**新建文件**: `.opencode/mobile-analysis/scripts/mobile_screenshot.py`

**功能**: 通过 `adb shell screencap` 截取 Android 设备屏幕，pull 到本地，输出图片文件 + 元数据 JSON。

**参数**:
| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| --output-dir | 是 | - | 输出目录（截图和 JSON 写入此目录） |
| --name | 否 | `screenshot` | 输出文件名前缀（不含扩展名） |
| --serial | 否 | - | 设备序列号（多设备时必填，单设备自动检测） |
| --format | 否 | `png` | 图片格式（adb screencap 原生输出 PNG，JPEG 通过 PIL 转换） |

**输出**: 在 `--output-dir` 下生成两个文件:
1. `<name>.png`（或 `<name>.jpg`）— 截图文件
2. `<name>.json` — 元数据

**元数据 JSON 格式**:
```json
{
  "success": true,
  "file": "screenshot.png",
  "format": "png",
  "device": "emulator5554",
  "screenshot_path": "/full/path/to/screenshot.png"
}
```

**实现要点**:
- 使用 `library.adb` 模块（复用 `resolve_device()`、`adb_shell()`）
- 需新增 `library.adb.pull_file()` 函数（当前只有 `push_file`，无 `pull_file`）
- 截图流程: `adb shell screencap -p /sdcard/<name>.png` → `adb pull /sdcard/<name>.png <local_path>` → `adb shell rm /sdcard/<name>.png`（清理设备临时文件）
- 格式转换: `--format jpeg` 时用 PIL 转换（quality=50，与 gui_capture.py 一致）；`--format png` 直接使用原始文件
- 设备临时文件路径: `/sdcard/<name>.png`，截图完成后删除
- 错误处理: adb 不可用 → `{"success": false, "error": "adb 未找到..."}`；无设备连接 → 复用 `resolve_device()` 的错误处理
- 不依赖 venv 第三方包（PNG 模式纯标准库；JPEG 模式可选依赖 PIL）
- 脚本自动创建输出目录（如果不存在）

---

### 方案 2: android-ui-automation.md — 新增 WebView 视觉方案

**改动文件**: `.opencode/mobile-analysis/knowledge-base/android-ui-automation.md`

**改动方式**: 在现有文件末尾新增章节（现有 uiautomator 内容不动）

**新增内容结构**:

```markdown
## WebView 场景: 视觉驱动方案

> 当 uiautomator dump 只返回 WebView 壳节点（看不到 DOM 内部控件）时使用。

### 触发条件

uiautomator dump 输出中满足以下任一条件:
- 只有 `<android.webkit.WebView>` 节点，无子控件
- 混合架构 App（Cordova/Ionic/React Native WebView 模式）
- Flutter/RN 的 WebView 组件

### 标准操作流程

#### Step 1: 设备截图
$PYTHON_CMD $AGENT_DIR/scripts/mobile_screenshot.py --output-dir $TASK_DIR/views --name step1_initial

#### Step 2: MCP 视觉分析
使用 MCP 分析截图:
- zai-mcp-server_extract_text_from_screenshot: 提取所有控件文字和坐标
- prompt: "识别截图中所有可交互控件（按钮、输入框、下拉框等），返回每个控件的文字内容和中心坐标 (x, y)"

#### Step 3: 执行操作（连续执行，中间不截图）
adb shell input tap <x> <y>           # 点击
adb shell input text "username"       # 输入英文
adb shell input keyevent ...          # 输入数字（见 keyevent 映射表）

#### Step 4: 截图验证结果
$PYTHON_CMD $AGENT_DIR/scripts/mobile_screenshot.py --output-dir $TASK_DIR/views --name step2_result

使用 MCP 判断结果:
- 首选: zai-mcp-server_ui_diff_check（对比 step1_initial 和 step2_result）
- 退化: zai-mcp-server_extract_text_from_screenshot（提取 step2_result 文字）

### 坐标系统说明

adb screencap 截图坐标与 adb shell input tap 坐标系统一致，MCP 返回的坐标可直接传给 adb tap，无需映射。

### 适用范围

- Android 原生 WebView
- Cordova/Ionic 混合 App
- React Native WebView 组件
- 不适用于: iOS（无 adb），Flutter 自绘 UI（uiautomator 也看不到控件，但不是 WebView）
```

---

### 方案 3: mobile-analysis.md prompt 更新

**改动文件**: `.opencode/agents/mobile-analysis.md`

**改动点**:

1. **移动端 Python 脚本表**（~119 行附近）新增一行:
```markdown
| mobile_screenshot.py | Android 设备截图（adb screencap + pull） | `$PYTHON_CMD $AGENT_DIR/scripts/mobile_screenshot.py --output-dir $TASK_DIR/views --name <名称>` |
```

2. **知识库索引表**（~160 行附近）更新 `android-ui-automation.md` 触发条件:
```markdown
| `android-ui-automation.md` | 需要 adb 输入文本、点击按钮、uiautomator 操作、WebView 视觉分析时 |
```

---

### 方案 4: mobile-methodology.md 路径 4 更新

**改动文件**: `.opencode/mobile-analysis/knowledge-base/mobile-methodology.md`

**改动方式**: 在路径 4（Hybrid/WebView 分析）的步骤末尾追加动态交互指引

**追加内容**:
```markdown
│     5. 如需动态操作 WebView 内部 GUI（填表单、点按钮）→ 视觉驱动方案
│        a. mobile_screenshot.py 截图
│        b. MCP extract_text_from_screenshot 识别控件坐标
│        c. adb shell input tap/text 操作
│        d. 再截图 + MCP ui_diff_check 验证
│        详见 android-ui-automation.md「WebView 场景: 视觉驱动方案」
```

---

### 方案 5: registry.json 更新

**改动文件**: `.opencode/mobile-analysis/scripts/registry.json`

**新增条目**:
```json
{
  "name": "mobile_screenshot",
  "description": "Android 设备截图工具（adb screencap + pull），输出图片 + 元数据 JSON",
  "file": "mobile_screenshot.py",
  "language": "python",
  "runner": "$PYTHON_CMD",
  "usage": "$PYTHON_CMD $AGENT_DIR/scripts/mobile_screenshot.py --output-dir $TASK_DIR/views --name <名称> [--serial <设备ID>] [--format png|jpeg]",
  "output_format": "PNG 图片 + JSON 元数据写入 --output-dir 目录",
  "note": "需要 adb（PATH 可用）。复用 library/adb.py 的 resolve_device 自动检测设备",
  "requires_venv": false
}
```

---

## §3 实现规范

### 改动范围表

| 文件 | 改动类型 | 方案 | 预估行数 |
|------|---------|------|---------|
| `mobile-analysis/scripts/library/adb.py` | 更新（新增 pull_file + 修复 import sys） | 1a | ~20 行新增 |
| `mobile-analysis/scripts/mobile_screenshot.py` | 新建 | 1b | ~120 行 |
| `mobile-analysis/knowledge-base/android-ui-automation.md` | 更新（追加章节） | 2 | ~80 行新增 |
| `agents/mobile-analysis.md` | 更新（2 处） | 3 | ~3 行改动 |
| `mobile-analysis/knowledge-base/mobile-methodology.md` | 更新（追加步骤） | 4 | ~8 行新增 |
| `mobile-analysis/scripts/registry.json` | 更新（追加条目） | 5 | ~10 行新增 |

### 编码规则

1. `mobile_screenshot.py` 复用 `library/adb.py` 的 `resolve_device()`、`adb_shell()`、新增的 `pull_file()`，不重复实现 adb 调用逻辑
2. 不依赖 venv 第三方包（PNG 模式纯标准库；JPEG 转换为可选功能，依赖 PIL 但缺失时优雅降级为 PNG）
3. 所有脚本输出 JSON（成功 `{"success": true, ...}` / 失败 `{"success": false, "error": "..."}`）
4. 日志使用中文，关键步骤有 `[*]`/`[+]`/`[!]` 日志打到 stderr
5. 知识库文件必须自包含（不依赖主 prompt 上下文即可理解）
6. 知识库文件中使用 `$AGENT_DIR`/`$SHARED_DIR` 变量引用路径

### §3.1 实施步骤拆分

**步骤 1a. 新增 library/adb.py 的 pull_file 函数**
- 文件: `.opencode/mobile-analysis/scripts/library/adb.py`
- 预估行数: ~15 行新增
- 验证点: `python -c "compile(open('<file>').read(), 'adb.py', 'exec')"` 语法检查通过
- 依赖: 无前置步骤

**步骤 1b. 新建 mobile_screenshot.py**
- 文件: `.opencode/mobile-analysis/scripts/mobile_screenshot.py`
- 预估行数: ~120 行
- 验证点: `python -c "compile(open('<file>').read(), 'mobile_screenshot.py', 'exec')"` 语法检查通过；`python mobile_screenshot.py --help` 显示参数说明；无设备连接时返回 `{"success": false, "error": "..."}` JSON
- 依赖: 步骤 1a

**步骤 2. 更新 android-ui-automation.md（新增 WebView 视觉方案章节）**
- 文件: `.opencode/mobile-analysis/knowledge-base/android-ui-automation.md`
- 预估行数: ~60 行新增
- 验证点: 人工审阅 — 触发条件明确、操作流程完整（截图→MCP→adb tap→验证）、坐标系统说明正确、引用路径使用 `$AGENT_DIR`
- 依赖: 步骤 1b（引用 mobile_screenshot.py）

**步骤 3. 更新 mobile-methodology.md（路径 4 追加动态交互指引）**
- 文件: `.opencode/mobile-analysis/knowledge-base/mobile-methodology.md`
- 预估行数: ~8 行新增
- 验证点: 人工审阅 — 路径 4 新增步骤 5 指向视觉方案，引用 android-ui-automation.md 正确
- 依赖: 步骤 2

**步骤 4. 更新 registry.json（新增截图脚本条目）**
- 文件: `.opencode/mobile-analysis/scripts/registry.json`
- 预估行数: ~10 行新增
- 验证点: `python -c "import json; json.load(open('<file>'))"` 语法检查通过；新条目格式与现有条目一致
- 依赖: 步骤 1b

**步骤 5. 更新 mobile-analysis.md agent prompt（工具表 + 知识库索引）**
- 文件: `.opencode/agents/mobile-analysis.md`
- 预估行数: ~3 行改动
- 验证点: 1) 移动端 Python 脚本表包含 mobile_screenshot.py；2) 知识库索引 android-ui-automation.md 触发条件包含 WebView；3) prompt 总行数 < 450 行
- 依赖: 步骤 1-4

---

## §4 验收标准

### 功能验收

| 编号 | 验收项 | 验证方法 |
|------|--------|---------|
| F1 | mobile_screenshot.py 能截取设备屏幕并输出 PNG + JSON | 有设备时实际执行；无设备时验证错误 JSON 输出 |
| F2 | mobile_screenshot.py --format jpeg 在 PIL 可用时转 JPEG | 检查输出 .jpg 文件 |
| F3 | mobile_screenshot.py 无设备连接时返回错误 JSON | 执行脚本验证 `{"success": false, ...}` |
| F4 | android-ui-automation.md WebView 章节自包含可理解 | 不读主 prompt 的情况下能理解全部内容 |
| F5 | agent prompt 工具表和知识库索引正确 | 人工审阅 |

### 回归验收

| 编号 | 验收项 |
|------|--------|
| R1 | android-ui-automation.md 现有 uiautomator 内容不受影响 |
| R2 | mobile-methodology.md 路径 1-3、5-6 不受影响 |
| R3 | registry.json 所有现有条目不受影响 |
| R4 | agent prompt 总行数 < 450 行 |

### 架构验收

| 编号 | 验收项 |
|------|--------|
| A1 | mobile_screenshot.py 复用 library/adb.py，不重复实现 adb 逻辑 |
| A2 | mobile_screenshot.py 不依赖 venv 第三方包（标准库即可运行） |
| A3 | 依赖方向合规：mobile-analysis 可引用 binary-analysis 共享内容 |
| A4 | 知识库文件自包含，不产生循环依赖 |

## §5 与现有需求文档的关系

| 现有需求 | 关系 |
|---------|------|
| `2026-04-24-gui-visual-automation.md` | 本需求是其移动端对应版本。PC 端用 pyautogui 截图 + MCP 识别；移动端用 adb screencap 截图 + 同一套 MCP 识别。两者共享 MCP 视觉工具，截图机制各自独立 |
| `2026-04-29-mobile-analysis-agent.md` | 本需求在 mobile-analysis agent 基础上新增 WebView 视觉能力，不改动现有工具链 |
