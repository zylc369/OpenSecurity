# 需求文档: security-coordinator 路由决策树增强

## §1 背景与目标

### 背景

Phase 0 复盘发现 coordinator 的路由信息粒度太粗：

1. **能力表只说"做什么"，不说"边界在哪"** — 当前 4 行表格只列了能力和适用场景，没有排除项和边界规则
2. **5 类常见边界场景无路由指引** — 如"APK 中的 native .so 归 mobile 还是 binary"、"移动应用的后端 API 归 mobile 还是 web"
3. **Coordinator 从未实际分发过子任务**（历史日志 0 次 Task 调用），首次使用就会面临路由困难

### 目标

增强 coordinator prompt 中的路由决策信息，使 coordinator 在面对边界场景时能做出正确的 agent 路由：

1. 将简单能力表替换为路由导向表（新增"不擅长"、"关键工具"、"典型输入"三列）
2. 新增边界路由规则小节（核心原则："上下文归属"优于"技术归属"）
3. 新增拆分判断指引（何时该拆分、何时不该拆分）

### 预期收益

- 轮次: 减少用户纠正错误路由的对话（每次误路由省 2-3 轮）
- 准确度: 解决 5 类常见边界场景的误判风险
- 速度: 正确路由 = 子 Agent 直接从正确方向开始

### 约束

- 纯 prompt 改进，不修改任何代码
- prompt 从 226 行增至约 270 行（< 450，无需瘦身）
- 不修改各 agent 的 frontmatter description（那是 OpenCode Task 工具自动注入用的）

---

## §2 技术方案

### 改动文件

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `.opencode/agents/security-coordinator.md` | 编辑 | 替换能力表、新增边界规则、新增拆分判断 |

### 改动详情

#### 2.1 替换"可调用的专业 Agent"小节（第 35-44 行）

将当前的 3 列简单表替换为 5 列路由导向表：

| 列 | 说明 |
|----|------|
| subagent_type | agent 名称 |
| 擅长 | 明确的核心能力（保留现有内容，补充关键工具） |
| 不擅长 | **新增** — 边界排除，帮助 coordinator 避免误路由 |
| 关键工具 | **新增** — 影响 agent 能力的核心工具（IDA、Frida、playwright 等） |
| 典型输入 | **新增** — 文件格式和输入类型，帮助 coordinator 按输入快速匹配 |

#### 2.2 新增"边界路由规则"小节（决策流程之后，约第 67 行位置）

核心原则："上下文归属"优于"技术归属"——分析对象的上下文环境决定路由，而非分析使用的技术。

包含一个边界场景路由表，覆盖 8 类常见边界场景。

#### 2.3 增强"决策流程"中的拆分原则（第 58-61 行）

在拆分原则下新增"拆分判断指引"：
- 该拆分的信号（多个独立攻击面、各领域结果互为输入）
- 不该拆分的信号（上下文单一的跨技术任务、深度不足不值得并行）

---

## §3 实现规范

### 改动范围表

| 区域 | 操作 | 行号范围（当前） | 预估变化 |
|------|------|----------------|---------|
| 可调用的专业 Agent | 替换表格 | 39-44 | 净增 0 行（3列→5列，行数不变） |
| 决策流程-拆分原则 | 增强拆分指引 | 58-61 | +8 行 |
| 决策流程之后 | 新增边界路由规则小节 | 67 之后插入 | +25 行 |

### 编码规则

- 表格列对齐用 Markdown 标准（`|` 分隔）
- 边界场景表按"分析对象"分类，不按"技术"分类
- 保持与现有 prompt 风格一致（中文、简洁、无冗余修饰）

### §3.1 实施步骤拆分

#### 步骤 1. 替换能力表为路由导向表

- 文件: `.opencode/agents/security-coordinator.md`
- 改动: 替换表格部分（第 39-44 行），保留标题（第 35 行）和说明文字（第 37 行）
- 预估行数: 替换 6 行 → 6 行（3列扩展为5列，行数不变，内容更丰富）
- 验证点: Read 修改后的文件，确认表格格式正确、5 列完整、内容准确
- 依赖: 无

新表格内容：

```markdown
| subagent_type | 擅长 | 不擅长 | 关键工具 | 典型输入 |
|---------------|------|--------|---------|---------|
| `binary-analysis` | IDA Pro 静态逆向、算法还原、壳检测、漏洞挖掘 | 移动端设备交互、APK 整体上下文、Web 协议测试 | IDA Pro 9.1 + IDAPython 脚本体系 | .exe .dll .so .dylib .bin 固件镜像 |
| `mobile-analysis` | APK/IPA 反编译、Java/Native 混合分析、Frida 动态 Hook、设备交互 | 纯 Web 应用测试、独立 PC 二进制分析（无移动端上下文） | Frida + jadx + apktool + IDA（native 层） | .apk .ipa .dex .jar 已连接设备 |
| `web-analysis` | Web 漏洞审计、攻击链构造、框架安全分析、缓存投毒 | 二进制逆向、移动端设备交互、AI 模型越狱 | playwright + curl + webfetch | URL 源码目录 API 端点 |
| `ai-security-analysis` | LLM 提示注入、越狱攻击、数据泄露测试、对抗性输入 | 传统 Web 漏洞（XSS/SQLi）、二进制分析、移动端分析 | LLM 模拟客户端 + 提示注入 payload 库 | LLM 应用 URL 对话 API 模型名称 |
```

#### 步骤 2. 增强拆分原则

- 文件: `.opencode/agents/security-coordinator.md`
- 改动: 在拆分原则（第 58-61 行）的代码块之后，新增拆分判断指引
- 预估行数: +8 行
- 验证点: Read 确认新增内容位置正确（在代码块 ``` 之后、`---` 之前）
- 依赖: 无

新增内容：

```markdown
**拆分判断指引**:
- 该拆分: 分析对象包含多个独立攻击面（如 IoT 固件的 ELF + Web 管理界面）
- 该拆分: 各领域分析结果互为输入（如先逆向加密算法，再用密钥测试 Web API）
- 不该拆分: 看似跨技术但上下文单一（如 APK 中的 native 层 → 归 mobile-analysis，不拆分给 binary-analysis）
- 不该拆分: 深度不足（如"扫一眼这个 URL 有没有 LLM 功能"→ 先 web-analysis，再决定是否追加 ai-security-analysis）
```

#### 步骤 3. 新增边界路由规则小节

- 文件: `.opencode/agents/security-coordinator.md`
- 改动: 在决策流程的 `---` 分隔线之后（约第 67 行），新增一个完整小节
- 预估行数: +25 行
- 验证点: Read 确认新小节位置在"决策流程"和"阶段 0"之间，格式完整
- 依赖: 步骤 2（需要确认插入位置的正确性）

新增小节：

```markdown
## 边界路由规则

**核心原则："上下文归属"优于"技术归属"** — 分析对象的上下文环境决定路由，而非分析使用的技术。

| 分析对象 | 路由到 | 原因 |
|---------|--------|------|
| APK/IPA 中的 native 库（.so/.dylib） | mobile-analysis | 需要 APK 整体上下文（Java 层调用关系、加固脱壳） |
| 独立的 .so/.exe/.dll（非移动端） | binary-analysis | 纯二进制分析，无需移动端上下文 |
| 移动应用的后端 API | web-analysis | API 测试是 Web 安全领域，不需要移动端设备 |
| 移动应用的 WebView 内嵌页面 | mobile-analysis | 需要应用容器上下文（Cookie、JS Bridge） |
| IoT 固件（ELF 二进制 + Web 管理界面） | 拆分 → binary-analysis + web-analysis | 两个独立攻击面，分别有价值 |
| LLM 应用的传统 Web 漏洞（XSS/SQLi） | web-analysis | 传统 Web 漏洞归 web-analysis，ai-security 只管 LLM 相关 |
| Web 应用中的 LLM 功能 | 拆分 → web-analysis + ai-security-analysis | 传统 Web 部分 + LLM 交互部分，两个攻击面 |
| AI 模型文件（.gguf/.safetensors） | binary-analysis | 本质是二进制文件格式分析 |
```

---

## §4 验收标准

### 功能验收

| # | 验收项 | 验证方式 |
|---|--------|---------|
| 1 | 路由导向表有 5 列（subagent_type/擅长/不擅长/关键工具/典型输入） | Read 文件确认 |
| 2 | "不擅长"列内容准确——不会误导 coordinator 做出错误排除 | 人工审查 |
| 3 | 边界路由规则覆盖 8 类场景 | Read 确认表格行数 |
| 4 | 拆分判断指引包含 4 条规则（2 条该拆分 + 2 条不该拆分） | Read 确认 |
| 5 | 新增内容位置正确：路由表替换原表、拆分指引在决策流程内、边界规则在决策流程之后 | Read 确认 |

### 回归验收

| # | 验收项 | 验证方式 |
|---|--------|---------|
| 1 | coordinator prompt 总行数 < 300 | `wc -l` |
| 2 | frontmatter 未被修改 | Read 前 12 行确认 |
| 3 | 阶段 0/阶段 1/结果聚合/执行纪律等现有小节未被破坏 | Read 全文确认结构完整 |
| 4 | 占位符（buwai-extension-id）仍在 frontmatter 中 | Read 确认 |

### 架构验收

| # | 验收项 |
|---|--------|
| 1 | 仅修改 agent prompt，不涉及 Plugin 代码或 Python 脚本 |
| 2 | 未新增文件，未修改依赖方向 |

---

## §5 与现有需求文档的关系

| 文档 | 关系 |
|------|------|
| `2026-05-22-security-coordinator.md` | 原始创建文档。本次增强不改变 coordinator 的核心机制（Task 工具分发） |
| `2026-05-29-coordinator-task-tool.md` | 切换到内置 Task 工具的文档。本次增强与之兼容（仍在 Task 工具框架内） |
| `2026-05-26-coordinator-stability-and-web-knowledge-align.md` | 稳定性修复。本次增强不涉及稳定性 |

本次改动是 coordinator prompt 的内容增强，不涉及架构变更。
