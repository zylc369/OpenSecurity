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
