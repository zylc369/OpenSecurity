# Playwright 网页渲染脚本

## §1 背景与目标

**来源痛点**：用户访问 XCTF 网站（SPA）时 webfetch 返回空内容。检查 webfetch 源码确认其为纯 HTTP GET + HTML→Markdown 字符串转换，无 JavaScript 执行能力。对于 React/Vue/Angular 等框架构建的 SPA 网站，服务端返回的是空壳 HTML（`<div id="root"></div>`），webfetch 无法获取动态渲染后的内容。

**预期收益**：为 Agent 提供一个能渲染 JavaScript 的网页获取工具，当 webfetch 无法获取有效内容时作为替代方案。同时支持截图，便于 Agent 用图像分析能力理解页面内容。

**四维度量预期**：
- 上下文：webfetch 对 SPA 返回空（100% 信息丢失）→ Playwright 渲染后可获取完整内容
- 轮次：减少 1-2 轮（无需用户手动查+粘贴）
- 速度：省去用户手动浏览器查+粘贴时间（首次安装 Playwright 浏览器约 1-2 分钟）
- 准确度：解决 SPA 页面内容无法获取的问题

## §2 技术方案

### 2.1 新增文件

| 文件 | 位置 | 说明 |
|------|------|------|
| `web_render.py` | `$SHARED_DIR/scripts/web_render.py` | Playwright 网页渲染脚本（渲染 + 截图） |
| `web-rendering.md` | `$SHARED_DIR/knowledge-base/web-rendering.md` | 使用指南知识库 |

### 2.2 修改文件

| 文件 | 位置 | 改动内容 |
|------|------|---------|
| `detect_env.py` | `$SHARED_DIR/scripts/detect_env.py` | 添加 playwright 为必须依赖 + 浏览器安装 |
| `registry.json` | `$SHARED_DIR/scripts/registry.json` | 注册 web_render 脚本 |
| `binary-analysis.md` | `$OPENCODE_ROOT/agents/binary-analysis.md` | 添加 web_render 工具引用 |
| `mobile-analysis.md` | `$OPENCODE_ROOT/agents/mobile-analysis.md` | 添加 web_render 工具引用 |

### 2.3 web_render.py 接口设计

```
用法: $BA_PYTHON $SHARED_DIR/scripts/web_render.py [选项]

选项:
  --url URL                  目标 URL（必须 http:// 或 https://）
  --format FORMAT            输出格式: markdown(默认) | text | html
  --screenshot PATH          截图保存路径（可选，JPEG 格式）
  --screenshot-full-page     全页截图（默认仅视口）
  --timeout SECONDS          渲染超时（默认 30，最大 120）
  --wait-selector SELECTOR   等待特定 CSS 选择器出现（可选）
  --output PATH              JSON 输出路径（可选，不指定则 stdout）
  --user-agent UA            自定义 User-Agent（可选）

输出 JSON 格式:
{
  "success": true,
  "url": "https://example.com",
  "title": "页面标题",
  "content": "渲染后的 markdown/text/html 内容",
  "content_type": "markdown",
  "screenshot": "截图路径（仅 --screenshot 时）",
  "metadata": {
    "render_time_ms": 1234,
    "final_url": "重定向后的 URL（如有）",
    "status_code": 200
  }
}
```

### 2.4 detect_env.py 改动设计

在 `REQUIRED_PACKAGES` 中添加 playwright：

```python
"playwright": {
    "required": True,
    "pip_name": "playwright",
    "post_install": True,  # 标记需要安装后额外步骤（浏览器二进制）
},
```

新增机制：`post_install` 字段指定 pip 安装成功后需要执行的额外步骤。playwright pip 包安装后，需运行 `playwright install chromium` 下载 Chromium 浏览器二进制（约 150-200MB）。

新增辅助函数：
- `_post_install_playwright(venv_python)`: 执行 `playwright install chromium`
- `_detect_playwright_browser(venv_python)`: 检测 Chromium 是否已安装

### 2.5 架构影响

```
改动位置在架构中的定位:

binary-analysis/scripts/
├── detect_env.py          ← 修改: 添加 playwright 依赖
├── registry.json          ← 修改: 注册 web_render
└── web_render.py          ← 新增: 网页渲染脚本

binary-analysis/knowledge-base/
└── web-rendering.md       ← 新增: 使用指南

agents/
├── binary-analysis.md     ← 修改: 添加工具引用
└── mobile-analysis.md     ← 修改: 添加工具引用

依赖方向: 无违反。web_render.py 是独立脚本，不依赖 _base/_utils/_analysis
```

## §3 实现规范

### 3.0 改动范围表

| 文件 | 改动类型 | 预估行数 |
|------|---------|---------|
| detect_env.py | 修改 | ~40 行 |
| web_render.py | 新增 | ~120 行 |
| registry.json | 修改 | ~10 行 |
| web-rendering.md | 新增 | ~60 行 |
| binary-analysis.md | 修改 | ~10 行 |
| mobile-analysis.md | 修改 | ~10 行 |

### 3.1 实施步骤拆分

**步骤 1. 修改 detect_env.py — 添加 playwright 必须依赖 + 浏览器安装**
- 文件: `$SHARED_DIR/scripts/detect_env.py`
- 预估行数: ~40 行
- 验证点: 
  1. `python -c "compile(...)"` 语法检查通过
  2. `python detect_env.py --force --skip-install` 运行后，输出 JSON 中 `packages.playwright` 字段存在（有 `available` 和 `version` 字段）
  3. `python detect_env.py --force` 运行后，playwright pip 包和 chromium 浏览器都安装成功
- 依赖: 无

**步骤 2. 创建 web_render.py 脚本**
- 文件: `$SHARED_DIR/scripts/web_render.py`
- 预估行数: ~120 行
- 验证点:
  1. `python -c "compile(...)"` 语法检查通过
  2. `$BA_PYTHON web_render.py --help` 输出正确的参数说明
  3. `$BA_PYTHON web_render.py --url https://example.com --format markdown` 返回包含 HTML 内容的 JSON
  4. `$BA_PYTHON web_render.py --url https://example.com --format markdown --screenshot /tmp/test.jpg` 返回 JSON 并生成截图文件
- 依赖: 步骤 1（需要 playwright 已安装）

**步骤 3. 更新 registry.json**
- 文件: `$SHARED_DIR/scripts/registry.json`
- 预估行数: ~10 行
- 验证点:
  1. `python -c "import json; json.load(open('registry.json'))"` JSON 格式正确
  2. 包含 web_render 条目，字段完整
- 依赖: 步骤 2

**步骤 4. 创建知识库 web-rendering.md**
- 文件: `$SHARED_DIR/knowledge-base/web-rendering.md`
- 预估行数: ~60 行
- 验证点:
  1. 人工读一遍确认自包含性（不依赖主 prompt 上下文即可理解）
  2. 引用路径使用 `$SHARED_DIR` 变量
- 依赖: 步骤 2

**步骤 5. 更新 binary-analysis.md Agent prompt**
- 文件: `$OPENCODE_ROOT/agents/binary-analysis.md`
- 预估行数: ~10 行（新增）
- 验证点:
  1. 添加 web_render 到工具清单表格
  2. 添加 web-rendering.md 到知识库索引
  3. 总行数 < 450
- 依赖: 步骤 4

**步骤 6. 更新 mobile-analysis.md Agent prompt**
- 文件: `$OPENCODE_ROOT/agents/mobile-analysis.md`
- 预估行数: ~10 行（新增）
- 验证点:
  1. 在"通用知识库"索引中添加 web-rendering.md
  2. 在工具清单中提及 web_render
  3. 总行数 < 450
- 依赖: 步骤 4

## §4 验收标准

### 功能验收
- [ ] `detect_env.py --force` 能自动安装 playwright pip 包 + chromium 浏览器
- [ ] `web_render.py --url <静态页面> --format markdown` 返回正确的 markdown 内容
- [ ] `web_render.py --url <静态页面> --format text` 返回正确的纯文本
- [ ] `web_render.py --url <静态页面> --format html` 返回正确的 HTML
- [ ] `web_render.py --url <SPA页面> --format markdown` 返回 JS 渲染后的内容
- [ ] `web_render.py --screenshot <path>` 生成有效的 JPEG 截图
- [ ] `web_render.py --screenshot <path> --screenshot-full-page` 生成全页截图
- [ ] 超时场景正确处理（返回错误 JSON，不崩溃）
- [ ] 无效 URL 正确处理（返回错误 JSON，不崩溃）

### 回归验收
- [ ] detect_env.py 其他包的检测不受影响（REQUIRED_PACKAGES 循环逻辑不变）
- [ ] detect_env.py 缓存机制正常（playwright 字段出现在缓存中）
- [ ] registry.json 其他脚本条目不受影响

### 架构验收
- [ ] web_render.py 不依赖 _base.py / _utils.py / _analysis.py（独立脚本）
- [ ] 依赖方向正确：web_render.py ← Agent prompt（Agent 通过 bash 调用脚本）
- [ ] 文件放置位置正确：web_render.py 在通用层（binary-analysis/scripts/）
- [ ] 两个 Agent prompt 都引用了新工具和知识库

## §5 与现有需求文档的关系

独立需求，不依赖其他未完成的需求文档。
