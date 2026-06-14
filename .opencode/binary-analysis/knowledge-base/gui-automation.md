# GUI 自动化操作规范

> Binary-Analysis agent 和 gui-interact-pc 命令共享此规范。

## 前提条件

- 需要 `pyautogui` 和 `pyperclip`（通过 `$PYTHON_CMD` 运行脚本）
- 需要 `zai-mcp-server` MCP（视觉理解能力，全局安装在 OpenCode 中）
- 脚本路径: `$SHARED_DIR/scripts/gui_capture.py` / `gui_act.py` / `gui_launch.py`

**环境变量说明**:
- `$PYTHON_CMD`: venv Python 绝对路径（由 Plugin 保证可用，含 pyautogui/pyperclip 等所有第三方包）
- `$SHARED_DIR`: 脚本根目录（由 Plugin 环境信息注入，见系统提示"环境信息"段）
- `$TASK_DIR`: 当前任务的工作目录（`~/bw-security-analysis/workspace/<task_id>/`），截图放在 `view/` 子目录下

## 标准操作流程

### Step 1: 启动目标程序

```bash
"$PYTHON_CMD" "$SHARED_DIR/scripts/gui_launch.py" --action launch --exe <TARGET>
```

记录返回的 PID。如果目标程序已运行，脚本会自动 kill 后重启。

### Step 2: 等待窗口出现

```bash
"$PYTHON_CMD" "$SHARED_DIR/scripts/gui_launch.py" --action wait_window --pid <PID> --timeout 10
```

### Step 3: 截图定位控件

```bash
"$PYTHON_CMD" "$SHARED_DIR/scripts/gui_capture.py" --output-dir "$TASK_DIR/view" --name step1_initial
```

使用 MCP 分析截图（两种方式任选）:
- `zai-mcp-server_extract_text_from_screenshot`: 提取所有控件文字和坐标（推荐，更稳定）
- `zai-mcp-server_ui_to_artifact`（output_type='spec'）: 获取 UI 设计规范

**MCP 调用示例**:
- image_source: `$TASK_DIR/view/step1_initial.jpg`（本地文件路径）
- prompt: "识别截图中所有可交互控件（按钮、输入框、下拉框等），返回每个控件的文字内容和中心坐标 (x, y)"

### Step 4: 执行操作序列（连续执行，中间不截图）

```bash
# 点击输入框
"$PYTHON_CMD" "$SHARED_DIR/scripts/gui_act.py" --action click --x 460 --y 320

# 输入文本（推荐 paste 模式，支持中文）
"$PYTHON_CMD" "$SHARED_DIR/scripts/gui_act.py" --action type --text "username" --paste

# 点击下一个输入框
"$PYTHON_CMD" "$SHARED_DIR/scripts/gui_act.py" --action click --x 460 --y 380

# 输入 license
"$PYTHON_CMD" "$SHARED_DIR/scripts/gui_act.py" --action type --text "XXXX-XXXX" --paste

# 点击验证按钮
"$PYTHON_CMD" "$SHARED_DIR/scripts/gui_act.py" --action click --x 500 --y 440 --settle 1
```

### Step 5: 截图读取结果

```bash
"$PYTHON_CMD" "$SHARED_DIR/scripts/gui_capture.py" --output-dir "$TASK_DIR/view" --name step2_result
```

使用 MCP 判断结果:
- 首选: `zai-mcp-server_ui_diff_check`（对比 step1_initial 和 step2_result）
  - expected_image_source: `$TASK_DIR/view/step1_initial.jpg`
  - actual_image_source: `$TASK_DIR/view/step2_result.jpg`
  - prompt: "对比这两张截图，识别所有视觉变化（新弹窗、文字变化、控件状态变化等），判断操作是否成功"
- 退化（ui_diff_check 不可用或超时）: `zai-mcp-server_extract_text_from_screenshot`
  - 提取 step2_result 中的所有文字，由 agent 判断操作结果

### Step 6: 清理

```bash
"$PYTHON_CMD" "$SHARED_DIR/scripts/gui_launch.py" --action kill --pid <PID>
```

## 失败重试策略

| 失败现象 | 重试方式 |
|---------|---------|
| MCP 说"两张图片看起来一样" | 换操作方式（剪贴板粘贴 → 逐字输入）重试一次 |
| 仍然没变化 | 重新截图让 MCP 再次定位坐标，可能是坐标偏移 |
| MCP 超时连续 2 次 | 降级到 gui_verify.py（Win32 控件方案，仅标准 Win32 有效） |
| MCP 完全不可用 | 降级到 gui_verify.py |

## 降级到 gui_verify.py

当 MCP 连续 2 次超时或完全不可用时，降级到 gui_verify.py（仅对标准 Win32 对话框有效）:

```bash
# 控件探测
"$PYTHON_CMD" "$SHARED_DIR/scripts/gui_verify.py" --exe <TARGET> --discover --output "$TASK_DIR/discover.json"

# 标准模式
"$PYTHON_CMD" "$SHARED_DIR/scripts/gui_verify.py" --exe <TARGET> --username <USER> --license <LICENSE> --output "$TASK_DIR/gui_result.json"

# Hook 注入
"$PYTHON_CMD" "$SHARED_DIR/scripts/gui_verify.py" --exe <TARGET> --hook-inject --hook-func-addr 0x401000 --hook-inputs-file "$TASK_DIR/inputs.json" --output "$TASK_DIR/result.json"

# Hook 读取结果
"$PYTHON_CMD" "$SHARED_DIR/scripts/gui_verify.py" --exe <TARGET> --username <USER> --license <LICENSE> --hook-result --hook-compare-addr 0x401200 --output "$TASK_DIR/result.json"

# Hook 注入 + Hook 读取结果 组合模式
"$PYTHON_CMD" "$SHARED_DIR/scripts/gui_verify.py" --exe <TARGET> --hook-inject --hook-func-addr 0x401000 --hook-inputs-file "$TASK_DIR/inputs.json" --hook-result --hook-compare-addr 0x401200 --hook-trigger-addr 0x401500 --output "$TASK_DIR/result.json"
```

降级后每次操作前仍尝试 MCP（1 次），恢复则切回视觉驱动。

## 再降级到 process_patch.py

当 gui_verify.py 所有模式也失败时（如 MFC DDX 控件无法通过 API 输入、Hook 地址不确定），降级到 process_patch.py 进行底层内存操作：

```bash
# Code cave 注入 + 捕获计算结果（CRACKME3 典型场景）
"$PYTHON_CMD" "$SHARED_DIR/scripts/process_patch.py" \
  --exe TARGET.EXE \
  --write-code 0x40234E:56578D... \
  --patch 0x401000:E9... \
  --capture 0x422480:16 \
  --signal 0x42248C:DEADBEEF \
  --trigger click:1002 \
  --output "$TASK_DIR/patch_result.json"
```

完整参数参考见 `$SHARED_DIR/knowledge-base/process-patch-reference.md`。

## 视觉分析产物管理（强制）

1. **截图时机**: 只在需要信息时截图（定位控件、读结果、诊断故障），不在每步操作前后都截
2. **操作序列**: 拿到坐标后，连续执行所有操作（click/type），中间不截图
3. **结果验证**: 操作序列完成后，等 0.5-1s（通过 gui_act.py 的 --settle 参数控制），截一张图让 MCP 判断结果
4. **产物存储**: 所有截图存储到 `$TASK_DIR/view/`（脚本自动创建目录）
5. **命名约定**: 按操作阶段命名 — `step1_initial`（定位）、`step2_result`（读结果）、`step3_diagnosis`（诊断故障）
6. **上下文压缩后**: 操作 GUI 前必须拍新截图确认当前状态（不能用旧截图的坐标）

## 坐标系统说明

截图和操作统一使用 pyautogui，坐标系统一致。MCP 返回的图片坐标 (460, 320) 可直接传给 gui_act.py --x 460 --y 320，无需换算。

pyautogui 内部处理了 DPI 缩放，`pyautogui.screenshot()` 返回的图片像素尺寸和 `pyautogui.click()` 使用的坐标系统是一致的。
