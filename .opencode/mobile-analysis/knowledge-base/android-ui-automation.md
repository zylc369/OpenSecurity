# Android UI 自动化经验

> 通过 adb + uiautomator 实现非视觉的 Android GUI 操作。
> 适用于：在模拟器/真机上输入文本、点击按钮、滚动页面。

---

## adb shell input keyevent — 数字键映射表

**必须使用 keyevent 而非 `input text` 输入数字**（见下方陷阱）。

| 数字 | KeyEvent 常量 | 数值 |
|------|--------------|------|
| 0 | KEYCODE_0 | 7 |
| 1 | KEYCODE_1 | 8 |
| 2 | KEYCODE_2 | 9 |
| 3 | KEYCODE_3 | 10 |
| 4 | KEYCODE_4 | 11 |
| 5 | KEYCODE_5 | 12 |
| 6 | KEYCODE_6 | 13 |
| 7 | KEYCODE_7 | 14 |
| 8 | KEYCODE_8 | 15 |
| 9 | KEYCODE_9 | 16 |

### 使用示例

```bash
# 输入 "395926"（逐字发送）
adb shell input keyevent 10  # 3
adb shell input keyevent 16  # 9
adb shell input keyevent 12  # 5
adb shell input keyevent 16  # 9
adb shell input keyevent 9   # 2
adb shell input keyevent 13  # 6
```

---

## adb shell input text 的换行陷阱

**问题**：`adb shell input text "42"` 实际输入 `42\n`（自动追加换行符）。

**影响**：如果目标 app 对输入做 `Integer.parseInt()`，会抛出 `NumberFormatException: For input string: "42\n"`。

**解决方案**：用 `input keyevent` 逐字输入，而非 `input text`。

```bash
# ❌ 错误：会追加换行
adb shell input text "42"

# ✅ 正确：逐字输入
adb shell input keyevent 11  # 4
adb shell input keyevent 9   # 2
```

---

## uiautomator dump + 坐标点击流程

### 标准操作流程

```bash
# 1. 导出当前 UI 层级
adb shell uiautomator dump /sdcard/ui.xml
adb pull /sdcard/ui.xml

# 2. 解析 UI XML，找到目标控件的 bounds 和属性
# bounds 格式: [left,top][right,bottom]
# 中心点: x = (left+right)/2, y = (top+bottom)/2

# 3. 点击目标控件
adb shell input tap <x> <y>
```

### 快速解析 UI XML（Python 一行）

```bash
$PYTHON_CMD -c "
import xml.etree.ElementTree as ET
tree = ET.parse('ui.xml')
for node in tree.getroot().iter():
    text = node.get('text', '')
    clickable = node.get('clickable', '')
    bounds = node.get('bounds', '')
    rid = node.get('resource-id', '')
    if text or clickable == 'true':
        print(f'text=\"{text}\" | rid={rid} | click={clickable} | bounds={bounds}')
"
```

---

## ScrollView 中控件不可见的处理

**问题**：`uiautomator dump` 只导出当前可见区域的控件。如果按钮在 ScrollView 中且被滚动到屏幕外，dump 中不会出现该按钮。

**解决**：

```bash
# 1. 先 dump 当前可见区域，找到可滚动容器
# 2. 向下滑动
adb shell input swipe <x> <y1> <x> <y2> <duration_ms>
# 例: 从 (1280, 1000) 滑到 (1280, 400)
adb shell input swipe 1280 1000 1280 400 300

# 3. 重新 dump，检查是否有新控件出现
adb shell uiautomator dump /sdcard/ui2.xml
adb pull /sdcard/ui2.xml

# 4. 找到目标控件后点击
```

---

## 权限弹窗处理

Android 6.0+ 的 app 首次启动可能出现权限请求弹窗（permission controller），需要在操作 app 之前先处理：

```bash
# 1. dump UI 检查是否有权限弹窗
#    弹窗特征: package="com.android.permissioncontroller"
# 2. 点击"继续"或"允许"按钮
# 3. 如果有"专为旧版 Android 打造"的警告弹窗，点击"确定"
# 4. 处理完毕后重新 dump 确认进入 app 主界面
```

---

## 清除输入框

```bash
# 方法 1：长按 → 全选 → 删除（适用于有内容的 EditText）
adb shell input keyevent KEYCODE_MOVE_END
adb shell input keyevent --longpress DEL  # 可能需要多次
adb shell input keyevent DEL

# 方法 2：重启 app（最可靠）
adb shell am force-stop <package>
adb shell am start -n <package>/<activity>
```

---

## WebView 场景: 视觉驱动方案

> 当 `uiautomator dump` 只返回 WebView 壳节点（看不到 DOM 内部控件）时使用此方案。
> 原理：截图 → MCP 视觉模型识别控件坐标 → `adb shell input tap` 操作 → 再截图验证。

### 触发条件

`uiautomator dump` 输出中满足以下任一条件:
- 只有 `<android.webkit.WebView>` 节点，无子控件
- 混合架构 App（Cordova/Ionic/React Native WebView 模式）
- 控件在 dump 中完全不可见（动态渲染、Canvas 绘制）

### 标准操作流程

#### Step 1: 设备截图

```bash
"$PYTHON_CMD" "$AGENT_DIR/scripts/mobile_screenshot.py" --output-dir "$TASK_DIR/views" --name step1_initial
```

#### Step 2: MCP 视觉分析

使用 MCP 工具分析截图（两种方式任选）:
- `zai-mcp-server_extract_text_from_screenshot`（推荐）: 提取所有控件文字和坐标
- `zai-mcp-server_ui_to_artifact`（output_type='spec'）: 获取 UI 设计规范

**MCP 调用参数**:
- image_source: 脚本输出的 JSON 中 `screenshot_path` 字段（格式由脚本自动决定，.png 或 .jpg）
- prompt: "识别截图中所有可交互控件（按钮、输入框、下拉框等），返回每个控件的文字内容和中心坐标 (x, y)"

#### Step 3: 执行操作（连续执行，中间不截图）

```bash
# 点击按钮/输入框（MCP 返回的坐标直接用）
adb shell input tap <x> <y>

# 输入英文文本
adb shell input text "username"

# 输入数字（必须用 keyevent，见上方映射表）
adb shell input keyevent 8   # 1
adb shell input keyevent 9   # 2
```

> **注意**: `adb shell input text` 不支持中文。中文输入需用 `adb shell input text` + URL 编码，或改用 Frida Hook 输入法。

#### Step 4: 截图验证结果

```bash
"$PYTHON_CMD" "$AGENT_DIR/scripts/mobile_screenshot.py" --output-dir "$TASK_DIR/views" --name step2_result
```

使用 MCP 判断结果:
- **首选**: `zai-mcp-server_ui_diff_check`（对比 step1_initial 和 step2_result）
  - expected_image_source: step1 截图 JSON 中的 `screenshot_path`
  - actual_image_source: step2 截图 JSON 中的 `screenshot_path`
  - prompt: "对比这两张截图，识别所有视觉变化（新弹窗、文字变化、控件状态变化等），判断操作是否成功"
- **退化**: `zai-mcp-server_extract_text_from_screenshot`（提取 step2 截图文字，由 agent 判断）

### 坐标系统说明

`adb shell screencap` 截图坐标与 `adb shell input tap` 坐标系统完全一致。MCP 返回的图片坐标 (460, 320) 可直接传给 `adb shell input tap 460 320`，无需映射。

### 产物管理

1. 截图存储到 `$TASK_DIR/views/`（脚本自动创建目录）
2. 文件名按操作阶段命名: step1_initial、step2_result、step3_diagnosis
3. 操作序列: 拿到坐标后连续执行所有 tap/text，中间不截图
4. 上下文压缩后: 操作前必须重新截图确认当前状态

### 适用范围

- ✅ Android 原生 WebView
- ✅ Cordova/Ionic 混合 App
- ✅ React Native WebView 组件
- ❌ iOS（无 adb，需另设方案）
- ❌ Flutter 自绘 UI（uiautomator 也看不到控件，但不是 WebView 场景）
