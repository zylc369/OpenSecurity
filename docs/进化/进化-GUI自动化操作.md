# 进化-GUI自动化操作

> 来源：用户与 AI 的深度讨论（2026-04-23），讨论记录见本轮对话上下文。
> 关联文档：`docs/进化/进化-解决GUI验证卡住问题.md`、`docs/进化/进化-分析TencentPediyKeygenMe2的问题和疑问记录.md`
> 本文档为 Phase 0-1 产出，待用户 REVIEW 后进入 Phase 2。

---

## Phase 0: 复盘分析

### 0.1 痛点统计

| # | 痛点 | 出现次数 | 后果 |
|---|------|---------|------|
| 1 | GUI 操作卡住（超时等待） | ≥3 次（TencentPediyKeygenMe2 分析过程） | 浪费 5+ 分钟/次，用户被迫中断 |
| 2 | Agent 因 GUI 卡住而走极端（"100% 静态分析"） | ≥2 次 | 方向偏移，错过最优路径 |
| 3 | GUI 操作需要用户手动介入 | ≥1 次（patch 二进制后请用户点击 Verify） | 自动化链断裂，需人工接力 |
| 4 | 验证结果不准确（作弊式验证） | ≥5 次（同一 binary 连续给错误 license） | 用户信任度下降 |
| 5 | `gui_verify.py` 对非标准控件无效 | 多次 | MFC/Qt/Electron 等框架完全不支持 |

### 0.2 根因分析

**当前 `gui_verify.py` 的 5 个根本缺陷**：

| # | 缺陷 | 代码位置 | 影响 |
|---|------|---------|------|
| 1 | 控件 ID 硬编码（1000/1001/1002） | L97-99 | 不同程序控件 ID 不同，直接失败 |
| 2 | 线性流水线 + 单一 timeout | L97-129 | 任何一步失败都静默等待到超时才返回 |
| 3 | 只能用 Win32 消息机制操作控件 | L232-243 | MFC/Qt/Electron/Delphi 部分控件不响应 `WM_SETTEXT` |
| 4 | 结果检测依赖 MessageBox 关键词匹配 | L101-102 | 静默失败（无弹窗）的程序无法判断结果 |
| 5 | 不截图不留痕 | 全文件 | 失败后无法诊断"哪一步出了问题" |

**更深层的原因**：当前方案试图用**控件级 API**（`GetDlgItem` + `SendMessage`）操作 GUI，这条路的通用性天花板很低——每种 GUI 框架的控件实现不同，不可能逐一适配。

### 0.3 用户提出的核心洞察

> "LLM 解决看和坐标的问题，GUI 自动化执行框架解决操作的问题，操作包括：点击、调用输入法输入，即完全模拟人的操作。"

这条路径的正确性已被验证：Anthropic Computer Use、OpenAI Operator 等产品已在走同样的架构——**截图 → 多模态理解 → 坐标级键鼠操作 → 再截图**。

### 0.4 关键约束

用户明确给出以下约束：

| # | 约束 | 说明 |
|---|------|------|
| 1 | 视觉理解能力 | 已有 zai-mcp-server MCP（GLM-4.6V），全局安装在 OpenCode 中，timeout 已设为 120s |
| 2 | 截图/录屏范围 | 全屏截图、全屏录屏（最大可能捕获完整窗口） |
| 3 | 文件存储 | 图片、视频存储到 `$TASK_DIR/view/`（工作目录的 view 子目录，MCP 需要本地文件路径） |
| 4 | 文件大小 | 在 AI 能识别的前提下尽量小（减少 MCP 处理时间和超时风险） |
| 5 | 可移植 | 能在不同电脑上运行 |
| 6 | 跨平台 | Windows 先做，后续支持 macOS/Linux |
| 7 | 双入口 | 用户能主动触发命令，Binary-Analysis agent 也能调用 |

---

## Phase 1: 候选方案评估

### 方案 A（推荐做）：视觉驱动 GUI 自动化

**核心思路**：用多模态 LLM（zai-mcp-server）识别截图中的控件位置和文字，用坐标级键鼠操作（pyautogui + pyperclip）模拟人的操作，用截图对比判断操作结果。

```
┌──────────┐     ┌──────────────┐     ┌──────────┐
│ 截图(Eye) │ ──→ │ MCP视觉(Brain)│ ──→ │ 键鼠(Hand)│
│ 全屏截图   │     │ 识别控件坐标   │     │ click/type│
└──────────┘     └──────────────┘     └──────────┘
       ↑                                    │
       └────── 再截图，对比前后变化 ←─────────┘
```

**架构设计**：

```
新增文件:
.opencode/commands/gui-interact.md      ← OpenCode 命令（薄壳，引用知识库）
.opencode/binary-analysis/
  scripts/
    gui_capture.py                       ← 截图/录屏（输出文件 + 元数据 JSON）
    gui_act.py                           ← 键鼠操作（click/type/hotkey）
    gui_launch.py                        ← 进程/窗口管理（启动、查找、前台、kill）
  knowledge-base/
    gui-automation.md                    ← GUI 自动化操作规范（单点维护）

删除/废弃:
  scripts/gui_verify.py                  ← 被 gui_capture + gui_act + gui_launch 替代
```

**关键设计决策**：

#### 决策 1：gui-interact 命令是薄壳

```markdown
# gui-interact.md 的全部内容（约 5 行）:
---
description: GUI 自动化交互 — 截图、视觉识别、键鼠操作
---
使用 Read 工具读取 $SCRIPTS_DIR/knowledge-base/gui-automation.md，按照其中的规范执行用户的 GUI 操作请求。
```

- 命令只是一个入口，所有逻辑写在 `knowledge-base/gui-automation.md`
- Binary-Analysis agent 需要操作 GUI 时，也读取同一个知识库文件
- **单点维护**：改知识库 = 命令和 agent 都更新
- **`$TASK_DIR` 来源**：
  - Binary-Analysis agent 调用时：使用 agent 已创建的任务目录 `$TASK_DIR`（`~/bw-ida-pro-analysis/workspace/<task_id>/`）
  - 用户直接调用命令时：由 `gui-automation.md` 中的指令创建任务目录 `~/bw-ida-pro-analysis/workspace/gui_<timestamp>/`，结构与 agent 创建的完全一致，截图和 index.json 放在其中的 `view/` 子目录下

#### 决策 2：截图对比判断操作结果（而非读回验证）

```
操作前截图 (before)
    ↓ 执行操作
    ↓ 等待 settle (0.5~1s)
操作后截图 (after)
```

**MCP 调用方式**：使用 `zai-mcp-server_ui_diff_check` 工具，将 before 作为 `expected_image_source`、after 作为 `actual_image_source` 传入，prompt 指定"对比这两张截图，识别所有视觉变化（新弹窗、文字变化、控件状态变化等）"。如果 `ui_diff_check` 不可用或超时，退化为用 `zai-mcp-server_extract_text_from_screenshot` 提取 after 截图中的所有文字，对比 before 截图的文字描述（由 agent 在调用 MCP 前记录）判断变化。`extract_text_from_screenshot` 比 `analyze_image` 更稳定、更不容易超时（实测验证）。

**为什么不用 `WM_GETTEXT` 读回验证**：只对 Win32 标准控件有效，Qt/Electron/WPF 不响应，不通用。截图对比是唯一跨框架通用的验证方式。

**静默失败场景的处理**：
- MCP 说"两张图片看起来一样" → 这本身就是诊断信息
- 策略：换一种操作方式重试一次（剪贴板粘贴 → 逐字输入）
- 仍然没变化 → 坐标可能偏了，重新截图让 MCP 再次定位

#### 决策 3：截图用 JPEG quality=50

实测数据（3440x1920 全屏截图，zai-mcp-server extract_text 识别）：

```
quality=75 → 272KB → ✅ 完整识别
quality=50 → 216KB → ✅ 完整识别  ← 默认选择
quality=30 → 186KB → ✅ 完整识别
quality=20 → 166KB → ✅ 完整识别（偶发超时）
quality=10 → 139KB → ✅ 完整识别
```

quality=50 时 UI 元素文字（包括中英文混合、代码路径、小字体标签）全部清晰可读，识别零损失。
quality=50 是保守选择，留足余量。如果未来确认更低质量稳定可用，可调整。

除非需要 OCR 精细识别（OCR 用 PNG 更清晰），默认用 JPEG quality=50。

#### 决策 4：坐标系统 — 统一用 pyautogui，无需映射

截图和操作统一使用 `pyautogui`，**不需要坐标换算**。原因：`pyautogui.screenshot()` 返回的图片像素尺寸和 `pyautogui.click()` 使用的坐标系统是一致的（都是物理像素坐标），pyautogui 内部处理了 DPI 缩放。MCP 返回图片坐标 (460, 320) → 直接 `pyautogui.click(460, 320)` 即可。

`gui_capture.py` 截图时输出的元数据仅用于记录和调试，不参与坐标换算：

```json
{
  "screenshot": "screen.jpg",
  "screen_resolution": [1920, 1080],
  "screenshot_size": [1920, 1080],
  "format": "jpeg",
  "quality": 50
}
```

**注意**：如果未来切换到 `mss` 截图（性能更好），mss 返回的是原始物理像素，需要确认与 pyautogui.click() 的坐标系统是否一致后再决定是否需要映射。

#### 决策 5：录屏不用于判断操作成功

MCP 视频理解基于关键帧提取（不是逐帧分析），无法可靠判断"按钮是否被点击"这种瞬时事件。视频限制 8MB 也严重限制录屏时长。录屏不作为操作成功判断的手段。

#### 决策 6：进程管理策略

- 启动前检查目标进程是否已运行 → 已运行则 kill 再启动（而非切到后台）
- kill 自己启动的进程不需要管理员权限（`proc.terminate()` 即可）
- 避免"两个同名窗口同时显示干扰截图识别"
- **启动失败处理**：如果程序启动后立即退出（exit code ≠ 0），读取 stderr 输出诊断原因（路径错误、DLL 缺失、UAC 弹窗等），报告给 agent 而非静默等待窗口出现

#### 决策 7：先做 Windows，后续扩展

`gui_launch.py` 对外暴露统一接口（`launch / find_window / bring_to_front / kill`），内部按平台分发实现。P0 只实现 Windows 版本，P1/P2 补充 macOS/Linux 实现时只改 gui_launch.py 内部，其他脚本和知识库不受影响。

| 期 | 平台 | 截图 | 操作 | 窗口管理 |
|----|------|------|------|---------|
| P0 | Windows | pyautogui | pyautogui + pyperclip | subprocess + ctypes Win32 |
| P1 | macOS | pyautogui | pyautogui + subprocess("osascript") | subprocess("open") + AppleScript |
| P2 | Linux | pyautogui | pyautogui + xdotool | xdotool + wmctrl |

每期脚本接口相同，内部实现按平台切换。MCP 视觉理解层完全不需要改。

**四维度量评估**（基于历史体验的定性估计，无精确对照数据）：

| 维度 | 改进前（gui_verify.py） | 改进后（视觉驱动） | 提升 |
|------|------------------------|-------------------|------|
| 上下文 | GUI 卡住后多轮对话排查 | 一步到位，截图→识别→操作 | 减少 3-5 轮 |
| 轮次 | GUI 操作经常需要用户介入 | 全自动，零人工介入 | 从 N 次人工 → 0 次 |
| 速度 | 卡住等待 30s timeout × N 步 | 每步 5-10s（截图+MCP+操作） | 显著 |
| 准确度 | 控件 ID 猜错/消息机制不生效 | 视觉定位，不依赖控件 API | 根本性提升 |

```
结论: 推荐做
实现成本: 新增 4 个文件（gui_capture.py ~100行, gui_act.py ~80行, gui_launch.py ~100行, gui-automation.md ~150行），废弃 1 个文件
上下文成本: 主 prompt 仅加 2-3 行引用，详细内容在知识库
风险: 依赖 zai-mcp-server MCP 的可用性和响应速度；依赖 pyautogui/pyperclip 的安装
```

---

### 方案 B（可选做）：保留 gui_verify.py 作为降级策略

**思路**：对于确认是标准 Win32 对话框的程序（`discover` 模式检测到 `Edit`/`Button` 类名），保留 `gui_verify.py` 作为快速验证路径（不需要 MCP 调用，速度更快）。

**降级护栏（防止 agent 钻牛角尖）**：

1. **入口优先级**：agent 默认走方案 A（视觉驱动），方案 B 仅作为 MCP 不可用时的降级路径
2. **降级触发条件（写死在 prompt 中）**：MCP 连续 2 次超时 **或** MCP 服务完全不可用（连接失败）→ 才允许切方案 B。不允许 agent 主动选择方案 B
3. **恢复机制**：一旦降级到方案 B，每次 GUI 操作前仍应尝试 MCP（1 次），如果 MCP 恢复则立即切回方案 A。不允许"降级后就一直用方案 B"
4. **方案 B 不作为并行选项**：在 agent prompt 的验证决策树中，方案 B 不出现在主路径上，只在"MCP 不可用"的错误处理分支中提及

```
结论: 可选做，作为方案 A 的降级策略
原因: 方案 A 完全覆盖 gui_verify.py 的能力。保留的收益是"MCP 挂掉时仍能验证标准 Win32 程序"。但必须加护栏防止 agent 在 MCP 正常时走方案 B 而放弃视觉驱动路线。建议：方案 A 稳定后再实施。
```

---

### 方案 C（暂不做）：录制视频用于用户回看

**思路**：在 GUI 自动化操作过程中录制全屏视频，操作结束后用户可以回看视频了解操作过程。

```
结论: 暂不做，保留设计备忘
原因: 对分析准确度无直接提升，但对用户信任度和调试有帮助。实现成本低（gui_capture.py 加一个 --record 参数），但增加了文件管理复杂度。方案 A 稳定后可作为增强功能添加。
```

---

### 方案 D（不建议做）：用录屏 + MCP 视频分析判断操作成功

**思路**：录制操作过程视频 → 让 MCP 分析视频 → 判断按钮是否被点击、输入是否成功。

```
结论: 不建议做
原因:
1. MCP 视频理解是关键帧提取（3-5 帧），不是逐帧分析，按钮点击（1-2帧/33ms）大概率被跳过
2. 视频限制 8MB，全屏录屏 5-10 秒就超限
3. 无法区分"操作没执行"和"操作执行了但程序静默失败"
4. 截图对比方案更可靠、更快、文件更小
```

---

### 方案 E（不建议做）：WM_GETTEXT 读回验证

**思路**：输入文本后用 `WM_GETTEXT` 读回编辑框内容，验证输入是否成功。

```
结论: 不建议做
原因: 只对 Win32 标准控件有效，Qt/Electron/WPF/Delphi 部分控件不响应。作为跨框架通用方案不成立。
```

---

## MCP 超时问题（已解决）

**问题**：`zai-mcp-server_analyze_image` 调用慢，出现 `Request timed out` 后 OpenCode fallback 到 GLM5.1 模型，导致"当前模型不支持图像输入"错误。

**已采取措施**：
1. `opencode.json` 中 `zai-mcp-server` 的 `timeout` 已改为 `120000`（120 秒）
2. 截图默认使用 JPEG quality=50（实测 3440x1920 全屏约 216KB，比 PNG 的 1-3MB 显著减小），从根源减少 MCP 处理时间

**待观察**：实际使用中 120s 是否足够，更小的截图文件是否减少超时频率（实测显示超时更多与 MCP 服务端波动有关，与文件大小关联不明显）。

---

## 视觉分析产物管理

### 截图时机

**只在需要信息时截图，不在每步操作前后都截。** 原理和人操作 GUI 一样：看一眼 → 记住位置 → 闭眼操作 → 看结果。

| 时机 | 目的 | MCP 调用 |
|------|------|---------|
| 程序启动后 / 需要操作控件前 | 定位控件坐标 | `extract_text_from_screenshot` 或 `ui_to_artifact`：返回所有控件坐标和文字 |
| 操作序列执行完、等待 settle 后 | 读取操作结果 | `ui_diff_check`（对比前后）或 `extract_text_from_screenshot`（提取当前文字） |
| 操作失败、需要诊断时 | 排查哪一步出了问题 | 按需调用 |

典型流程（license 验证）：

```
Step 1: 截图 → MCP 拿所有控件坐标（1 次截图，1 次 MCP）
Step 2: click 用户名框 → type → click license 框 → type → click Verify（0 次截图，0 次 MCP）
Step 3: 等待 0.5-1s
Step 4: 截图 → MCP 读结果（1 次截图，1 次 MCP）
总计: 2 次截图，2 次 MCP 调用
```

失败时追加诊断截图，成本和"每步都截"失败后一样——**成功时省了，失败时没多花**。

### 产物存储

所有视觉分析产物（截图、MCP 分析结果）持久化到当前任务的工作目录下的 `view/` 子目录，通过 JSON 索引文件管理。

**`$TASK_DIR` 来源**：
- Binary-Analysis agent 调用时：使用 agent 已创建的任务目录 `~/bw-ida-pro-analysis/workspace/<task_id>/`
- 用户直接调用命令时：创建 `~/bw-ida-pro-analysis/workspace/gui_<timestamp>/`，结构完全一致

#### 目录结构

```
~/bw-ida-pro-analysis/workspace/<task_id>/
├── initial.json                ← IDA 初始分析结果
├── view/                       ← 视觉分析产物
│   ├── index.json              ← 操作日志（所有截图和 MCP 结果的索引）
│   ├── step1_initial.jpg       ← 截图文件
│   ├── step2_result.jpg
│   └── ...
└── summary.json                ← 任务归档
```

#### index.json 格式

```json
{
  "entries": [
    {
      "id": "step1_initial",
      "file": "step1_initial.jpg",
      "timestamp": "2026-04-23T23:52:00",
      "context": "首次启动后，定位控件坐标",
      "mcp_analyzed": true,
      "mcp_summary": "发现两个输入框（User Name, License Code）和一个 Verify 按钮",
      "mcp_coordinates": {
        "User Name 输入框": {"x": 460, "y": 320},
        "License Code 输入框": {"x": 460, "y": 380},
        "Verify 按钮": {"x": 500, "y": 440}
      }
    },
    {
      "id": "step2_result",
      "file": "step2_result.jpg",
      "timestamp": "2026-04-23T23:52:15",
      "context": "输入 license 并点击 Verify 后，读取结果",
      "mcp_analyzed": true,
      "mcp_summary": "弹窗显示 'Registration Successful'",
      "mcp_coordinates": {}
    }
  ]
}
```

#### MCP 结果复用规则

**只复用 MCP 分析结果，不复用截图**。对同一张截图文件，如果 `mcp_analyzed: true` 且 agent 需要的信息在 `mcp_summary` / `mcp_coordinates` 中已存在，直接读取，不重复调用 MCP。

这一条规则覆盖以下场景：
- **同一 step 内多次引用坐标**：比如 Step 1 的 MCP 返回了所有控件坐标，后续操作不需要再调 MCP
- **上下文压缩后恢复**：agent 被压缩后，重新读取 `index.json` 即可知道之前做过哪些操作、拿到过哪些信息。但**如果需要重新操作 GUI，必须拍新截图确认当前状态**，不能假设之前的截图还反映当前界面

#### id 命名约定

按操作阶段命名：`step1_initial`（定位）、`step2_result`（读结果）、`step3_diagnosis`（诊断故障）。同一阶段不重复截图，不同阶段各一张。

#### Agent prompt 中的引用

知识库 `gui-automation.md` 中写明：

```
## 视觉分析产物管理（强制）

1. 截图时机：只在需要信息时截图（定位控件、读结果、诊断故障），不在每步操作前后都截
2. 操作序列：拿到坐标后，连续执行所有操作（click/type），中间不截图
3. 结果验证：操作序列完成后，等 0.5-1s，截一张图让 MCP 判断结果
4. MCP 复用：调用 MCP 前先读 index.json，同一张文件已分析过则直接用缓存结果
5. 每次新的截图和 MCP 结果，追加写入 index.json
6. 上下文压缩后：读 index.json 恢复历史信息，但操作 GUI 前必须拍新截图确认当前状态
```

---

## 确认

做方案A、B。
