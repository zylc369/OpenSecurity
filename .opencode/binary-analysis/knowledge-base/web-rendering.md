# 网页渲染工具使用指南

## 概述

`web_render.py` 使用 Playwright 无头浏览器渲染网页，支持 JavaScript 执行。当 `webfetch` 工具无法获取 SPA（单页应用）页面内容时，使用本脚本作为替代。

## 与 webfetch 的区别

| 特性 | webfetch | web_render.py |
|------|---------|--------------|
| JavaScript 执行 | ❌ 纯 HTTP GET | ✅ 完整浏览器引擎 |
| SPA 页面 | ❌ 返回空壳 HTML | ✅ 等待渲染完成 |
| 截图 | ❌ | ✅ 支持视口/全页截图 |
| 速度 | 快（< 1 秒） | 较慢（2-10 秒） |
| 依赖 | 无 | Playwright + Chromium |

## 使用策略

**优先使用 webfetch**，仅在以下情况切换到 web_render.py：
1. webfetch 返回的内容明显是空壳（只有 `<div id="root"></div>` 之类）
2. 已知目标网站是 SPA（React/Vue/Angular）
3. 需要页面截图进行视觉分析

## 调用方式

```bash
# 基本用法：获取渲染后的 markdown 内容
$PYTHON_CMD "$SHARED_DIR/scripts/web_render.py" --url "https://example.com" --format markdown

# 获取纯文本
$PYTHON_CMD "$SHARED_DIR/scripts/web_render.py" --url "https://example.com" --format text

# 获取原始 HTML
$PYTHON_CMD "$SHARED_DIR/scripts/web_render.py" --url "https://example.com" --format html

# 同时截图
$PYTHON_CMD "$SHARED_DIR/scripts/web_render.py" --url "https://example.com" --format markdown --screenshot "$TASK_DIR/page.jpg"

# 全页截图
$PYTHON_CMD "$SHARED_DIR/scripts/web_render.py" --url "https://example.com" --format markdown --screenshot "$TASK_DIR/page.jpg" --screenshot-full-page

# 等待特定元素出现（适用于已知页面结构的情况）
$PYTHON_CMD "$SHARED_DIR/scripts/web_render.py" --url "https://example.com" --wait-selector ".content-loaded" --format markdown

# 输出到文件而非 stdout
$PYTHON_CMD "$SHARED_DIR/scripts/web_render.py" --url "https://example.com" --format markdown --output "$TASK_DIR/web.json"

# 自定义超时（默认 30 秒，最大 120 秒）
$PYTHON_CMD "$SHARED_DIR/scripts/web_render.py" --url "https://example.com" --timeout 60 --format markdown
```

## 参数说明

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `--url` | ✅ | - | 目标 URL（必须 http:// 或 https://） |
| `--format` | ❌ | markdown | 输出格式：markdown / text / html |
| `--screenshot` | ❌ | - | 截图保存路径（支持 jpg/png） |
| `--screenshot-full-page` | ❌ | false | 全页截图（默认仅视口 1280×720） |
| `--timeout` | ❌ | 30 | 渲染超时秒数（最大 120） |
| `--wait-selector` | ❌ | - | 等待 CSS 选择器匹配的元素出现 |
| `--output` | ❌ | stdout | JSON 输出路径 |
| `--user-agent` | ❌ | Chrome 143 | 自定义 User-Agent |

## 输出格式

成功时：
```json
{
  "success": true,
  "url": "https://example.com",
  "title": "页面标题",
  "content": "渲染后的内容",
  "content_type": "markdown",
  "screenshot": "截图路径（仅 --screenshot 时）",
  "metadata": {
    "status_code": 200,
    "final_url": "重定向后的 URL"
  }
}
```

失败时：
```json
{
  "success": false,
  "url": "https://example.com",
  "error": "错误描述"
}
```

## 截图配合图像分析

截图可用于 `analyze_image` 等工具进行视觉分析，适用于：
- 理解页面布局和导航结构
- 定位页面上的特定元素（如按钮、表单）
- 获取图表/数据可视化内容

示例流程：
1. `web_render.py --screenshot $TASK_DIR/page.jpg` 截图
2. 使用图像分析工具读取截图，分析页面内容

## 常见问题

**Q: 页面内容仍然不完整？**
A: 某些 SPA 页面需要用户交互才能加载内容。尝试 `--wait-selector` 等待特定元素出现，或增大 `--timeout`。

**Q: 渲染超时？**
A: 默认超时 30 秒，复杂页面可能需要更长。使用 `--timeout 60` 增加等待时间。最大 120 秒。

**Q: playwright 未安装？**
A: 运行 `$PYTHON_CMD "$SHARED_DIR/scripts/detect_env.py" --force` 自动安装 playwright 和 Chromium 浏览器。
