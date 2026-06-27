# 需求文档: Yipiter CTF 复盘进化

## §1 背景与目标

### 背景

Yipiter CTF 解题过程暴露了多个系统性问题：

1. **10 次卡住**（6 次命令阻塞 + 4 次 LLM 生成阻塞）
2. **知识库缺失**：iframe sandbox 逃逸、blob URL origin 继承、开放重定向等关键知识未沉淀，AI 从零摸索耗费大量轮次
3. **Bot 类题目分类不足**：当前只有 Cookie 模式，缺少 localStorage/DOM/Session 变体
4. **搜索工具指引不足**：webfetch 和 web_render.py 的使用场景不清晰
5. **无法事后复盘工具执行时间线**

### 目标

| 方案 | 目标 | 预期收益 |
|------|------|---------|
| A | 沉淀 iframe sandbox 逃逸 + blob URL + 开放重定向知识 | 下次遇到同类题减少 10-20 轮推理 |
| B | 扩展 Bot 类题目攻击模式分类 | 更早锁定攻击方向，减少 5-10 轮 |
| C | Plugin 时间线日志 | 事后复盘有客观数据，不再靠人工回忆 |
| D | prompt 防卡住规则 | 减少 LLM 无响应和命令阻塞次数 |
| F | 搜索工具使用指引 | AI 选择正确的页面获取工具，减少试错 |

### 约束

- web-analysis.md 展开后 379 行（< 450 行阈值），本次不需要瘦身
- 不改动 web-analysis.md 的核心分析框架（阶段 A/B/C 不变）
- 不改动 Plugin 的核心 session 管理逻辑

---

## §2 技术方案

### 2.1 方案 A：沉淀知识到知识库

**改动文件**：`web-analysis/knowledge-base/web-vulnerabilities.md`

在现有文件中增加两个新章节：

**新增 1.5 节：iframe Sandbox 逃逸**

内容包括：
- iframe sandbox 的权限标志含义（allow-scripts / allow-popups / allow-same-origin / allow-popups-to-escape-sandbox）
- 没有 `allow-same-origin` 时的后果（origin 变为 null，无法访问 localStorage/Cookie）
- **逃逸技术 1：blob URL 作为顶级页面加载** — 在 sandboxed iframe 中获取 blob URL，通过 window.open / 重定向等方式使其脱离 iframe 加载，sandbox 消失。注意：blob URL 继承创建者的 origin（详见第 7 节"开放重定向"中的 blob URL origin 继承机制），这是逃逸生效的前提
- **逃逸技术 2：postMessage 传递 blob URL** — iframe 中 JS 通过 postMessage 将 blob URL 传给外部页面，外部页面构造重定向使 blob URL 成为顶级页面。本节只描述逃逸的利用方式，blob URL 为什么能通过 origin 检查的原理在第 7 节
- 识别方法：源码中搜索 `<iframe sandbox` 看权限标志
- 检查清单

**新增 7 节：开放重定向与 URL 验证绕过**

内容包括：
- SSO/OAuth 回调的 return 参数验证逻辑（检查 `new URL(candidate).origin === window.location.origin`）
- **blob URL 绕过**：`new URL('blob:http://x.com/uuid').origin` 返回 `'http://x.com'`——blob URL 继承创建者的 origin。这是 blob URL 的核心特性，也是被 sandbox 逃逸利用的前提（1.5 节的逃逸技术依赖此行为通过 origin 检查）
- 其他绕过：`javascript:` URL（origin 为 null）、`data:` URL（origin 为 null）、`@` 符号混淆
- 识别方法：搜索源码中的 `redirect`、`return` 参数、`window.location.assign`、`new URL` origin 检查
- 利用步骤

**归属判定**：放在 `web-analysis/knowledge-base/`（Web 安全特有知识）

### 2.2 方案 B：扩展 Bot 攻击模式分类

**改动文件**：`web-analysis/knowledge-base/web-methodology.md` 1.5 节

将当前"1.5 Bot + Cookie 类题目分析方法"扩展为更通用的"Bot 类题目分析方法"：

- 重命名标题（去掉"+ Cookie"）
- 增加"按 flag 存储位置分类"的表格：

| 变体 | Flag 存储位置 | 攻击目标 | 识别信号 |
|------|-------------|---------|---------|
| Bot+Cookie | Cookie | XSS → document.cookie | Bot 代码中有 setCookie / Cookie 域设置 |
| Bot+localStorage | localStorage | XSS → localStorage.getItem() | 源码中用 localStorage 存储数据（无 Cookie 设置，数据存在浏览器本地） |
| Bot+DOM | 页面 DOM | XSS → 读取页面内容 | 需要登录后才能看到的页面中有 flag |
| Bot+Session | 服务端 Session | CSRF / Session Fixation | 非 XSS 类，flag 只在服务端 |

- 增加 Bot 时间线分析模式：当 Bot 先访问用户 URL 后保存 flag 时，恶意 JS 需要"活着"等到 flag 被保存（轮询机制）
- 在 1.5.4 Cookie 外泄方式表前增加 localStorage 窃取 payload 示例

### 2.3 方案 C：Plugin 时间线日志

**改动文件**：`plugins/security-analysis.ts`

在 Plugin 中增加时间线记录功能：

**数据结构**：

```typescript
type TimelineEventType = "tool.before" | "tool.after" | "session.status" | "session.error" | "heartbeat";
interface TimelineEvent {
  timestamp: number;       // Date.now()
  type: TimelineEventType;
  tool?: string;           // 工具名（tool.before/after 时）
  detail?: string;         // 命令前 80 字符（Bash tool.before 时）或错误信息（session.error 时）
  duration?: number;       // 毫秒（tool.after 时）
}
```

**记录时机**：
- `tool.execute.before`：记录工具名 + 时间戳 + 命令前 80 字符（记录注入前的原始命令，不包含 SESSION_ID 前缀）
- `tool.execute.after`：记录工具名 + 时间戳 + 耗时（毫秒）
- `event` 钩子中 `session.status` 变化：记录状态 + 时间戳（从 `event.properties` 解析，类型为 BusEvent 的 `session.status` / `session.idle` 等）
- `event` 钩子中 `session.error`：记录错误信息 + 时间戳（从 `event.properties.error` 提取）
- `event` 钩子中 `message.part.updated`：记录心跳 + 时间戳（`event.properties.part.type === "text"` 时记录，表示 Shell 有输出更新）

**写入位置**：`$TASK_DIR/logs/timeline.log`。如果 session 未初始化（没有 TASK_DIR），写回到集中日志目录 `LOGS_DIR/timeline-{sessionID}.log`。

**边界情况**：session 未初始化时（没有调用 create_task_dir.py），`getTaskDir(sessionID)` 返回 null。此时使用集中日志目录作为 fallback。

**格式**：每行一条 JSON

```
[2026-05-24 14:30:25] {"ts":1716538225000,"type":"tool.before","tool":"bash","detail":"curl -v http://target"}
[2026-05-24 14:30:28] {"ts":1716538228000,"type":"tool.after","tool":"bash","duration":3000}
[2026-05-24 14:30:30] {"ts":1716538230000,"type":"session.status","detail":"busy"}
[2026-05-24 14:35:30] {"ts":1716538530000,"type":"session.status","detail":"idle"}
```

**内存管理**：使用内存 buffer（最多 500 条），当 buffer 满或 session 切换为 idle 时 flush 到文件。避免每次事件都写磁盘。

**不影响现有功能**：时间线记录是追加逻辑，不修改任何现有的 hook 行为。

### 2.4 方案 D：prompt 防卡住规则

**改动文件**：`agents-rules/execution-discipline.md`

在现有纪律表后增加两条规则：

| 纪律 | 规则 |
|------|------|
| **禁止长驻进程** | 禁止在 Bash 工具中启动 HTTP server、tunnel（cloudflared/ngrok）、代理等长驻服务进程。这类进程会阻塞工具执行且无法在 Bash 工具中管理。需要外部服务时使用在线托管平台（webhook.site、httpbin.org 等） |
| **长文档分段** | 生成/修改超过 300 行的文档（解题报告、分析报告等）时，必须拆分为多次 Edit 调用，每次只改一个小节。禁止用 Write 工具一次生成超过 300 行的文档 |

增加一条补充说明：

**卡住预防**：
- 所有命令依赖 Bash 工具的默认超时（120 秒），不需要手动设置超时
- 如果命令预期耗时超过 120 秒（如长时间运行的 Python 脚本），应使用 `$BA_PYTHON` 运行并在脚本内部实现超时控制
- 连续 2 次工具调用无有效输出（空输出 / 超时提示）→ 暂停评估当前方向是否可行

### 2.5 方案 F：搜索工具使用指引

**改动文件**：`agents/web-analysis.md` 工具清单节

在"网页渲染工具"部分增加清晰的使用场景指引：

```
页面内容获取工具选择：

| 场景 | 工具 | 原因 |
|------|------|------|
| 获取静态页面 HTML | webfetch | 快速，无 JS 执行开销 |
| 获取 API/JSON 响应 | webfetch | 不需要渲染 |
| 页面需要 JS 渲染才能看到内容（SPA） | web_render.py | 需要 JS 执行 |
| 需要页面截图 | web_render.py | webfetch 无法截图 |
| 需要登录后的页面内容 | 编写 Playwright 脚本（`$TASK_DIR/render_auth.py`），在脚本中设置 Cookie/Token 后渲染 | web_render.py 不支持传入认证信息，需要自行编写带认证的渲染脚本 |
| 获取 CTF writeup / 技术文章 | webfetch | 文章类页面通常不需要 JS |
```

---

## §3 实现规范

### 3.0 改动范围表

| 文件 | 操作 | 预估行数 | 说明 |
|------|------|---------|------|
| `web-analysis/knowledge-base/web-vulnerabilities.md` | 修改 | +80 行 | 增加 Sandbox 逃逸 + 开放重定向章节 |
| `web-analysis/knowledge-base/web-methodology.md` | 修改 | +40 行 | 扩展 Bot 攻击模式分类 |
| `plugins/security-analysis.ts` | 修改 | +100 行 | 增加时间线记录逻辑 |
| `agents-rules/execution-discipline.md` | 修改 | +15 行 | 增加防卡住规则 |
| `agents/web-analysis.md` | 修改 | +12 行 | 增加搜索工具使用指引 |

**总改动**: ~247 行，5 个文件

### 3.1 实施步骤拆分

**步骤 1. 沉淀 Sandbox 逃逸知识（方案 A-1）**
  - 文件: `web-analysis/knowledge-base/web-vulnerabilities.md`
  - 预估行数: +50 行（新增 1.5 节）
  - 验证点:
    - 文件包含"iframe Sandbox 逃逸"章节
    - 包含 blob URL 顶级页面逃逸技术的完整描述（触发条件 + 检查方法 + 利用步骤）
    - 包含 postMessage 传递 blob URL 的利用链描述
    - 知识自包含：不依赖主 prompt 或其他文件即可理解
  - 依赖: 无

**步骤 2. 沉淀开放重定向知识（方案 A-2）**
  - 文件: `web-analysis/knowledge-base/web-vulnerabilities.md`
  - 预估行数: +30 行（新增第 7 节）
  - 验证点:
    - 文件包含"开放重定向与 URL 验证绕过"章节
    - 包含 blob URL origin 继承绕过的描述和代码示例
    - 包含识别方法和检查清单
    - 知识自包含
  - 依赖: 步骤 1（同一文件，顺序编辑避免冲突）

**步骤 3. 扩展 Bot 攻击模式分类（方案 B）**
  - 文件: `web-analysis/knowledge-base/web-methodology.md`
  - 预估行数: +40 行（修改 1.5 节 + 新增表格）
  - 验证点:
    - 1.5 节标题不再局限于"Bot + Cookie"
    - 包含按 flag 存储位置分类的表格（Cookie / localStorage / DOM / Session）
    - 包含 Bot 时间线分析模式（先访问用户 URL 后保存 flag 的场景）
    - 包含 localStorage 窃取的 payload 示例
  - 依赖: 无

**步骤 4. 增加防卡住规则（方案 D）**
  - 文件: `agents-rules/execution-discipline.md`
  - 预估行数: +15 行
  - 验证点:
    - 纪律表包含"禁止长驻进程"行
    - 纪律表包含"长文档分段"行
    - 包含"卡住预防"补充说明
    - web-analysis.md 展开后包含这些规则
  - 依赖: 无

**步骤 5. 增加搜索工具使用指引（方案 F）**
  - 文件: `agents/web-analysis.md`
  - 预估行数: +12 行
  - 验证点:
    - 工具清单节包含"页面内容获取工具选择"表格
    - 表格覆盖 webfetch 和 web_render.py 的使用场景
    - web-analysis.md 展开后行数仍 < 450 行
  - 依赖: 无

**步骤 6. Plugin 时间线日志（方案 C-1：数据结构与 buffer）**
  - 文件: `plugins/security-analysis.ts`
  - 预估行数: +40 行
  - 验证点:
    - 定义 TimelineEvent 接口
    - 定义内存 buffer（最多 500 条）
    - 定义 flushTimeline 函数（写文件到 $TASK_DIR/logs/timeline.log）
    - TypeScript 语法通过（node --check）
  - 依赖: 无

**步骤 7. Plugin 时间线日志（方案 C-2：在 hook 中记录事件）**
  - 文件: `plugins/security-analysis.ts`
  - 预估行数: +60 行
  - 验证点:
    - tool.execute.before 中记录工具名 + 时间戳 + 命令前 80 字符
    - tool.execute.after 中记录工具名 + 时间戳 + 耗时
    - event 钩子中记录 session.status / session.error / message.part.updated
    - session idle 时 flush buffer
    - TypeScript 语法通过（node --check）
    - 现有功能无影响（时间线记录不修改任何现有 hook 的 output）
  - 依赖: 步骤 6

**步骤 8. 语法检查与回归验证**
  - 文件: 所有修改文件
  - 预估行数: 0 行（验证步骤）
  - 验证点:
    - `security-analysis.ts`: `node --check` 通过
    - `web-vulnerabilities.md`: 人工读一遍确认自包含
    - `web-methodology.md`: 人工读一遍确认自包含
    - `execution-discipline.md`: 内容完整
    - `web-analysis.md`: 展开后行数 < 450 行
    - Plugin 现有功能（占位符展开、环境注入、session 管理）无改动
  - 依赖: 步骤 1-7

---

## §4 验收标准

### 功能验收

- [ ] `web-vulnerabilities.md` 包含"iframe Sandbox 逃逸"章节（1.5 节），描述 blob URL 顶级页面逃逸技术
- [ ] `web-vulnerabilities.md` 包含"开放重定向与 URL 验证绕过"章节（第 7 节），描述 blob URL origin 继承绕过
- [ ] `web-methodology.md` 1.5 节包含按 flag 存储位置分类的表格（至少 4 种变体）
- [ ] `web-methodology.md` 1.5 节包含 Bot 时间线分析模式
- [ ] `execution-discipline.md` 包含"禁止长驻进程"和"长文档分段"纪律行
- [ ] `web-analysis.md` 工具清单节包含"页面内容获取工具选择"表格
- [ ] `security-analysis.ts` 在 `tool.execute.before` 中记录时间线条目
- [ ] `security-analysis.ts` 在 `tool.execute.after` 中记录时间线条目（含耗时）
- [ ] `security-analysis.ts` 在 `event` 钩子中记录 session.status / session.error 事件
- [ ] 时间线日志写入 `$TASK_DIR/logs/timeline.log`

### 回归验收

- [ ] `web-analysis.md` 展开后行数 < 450 行
- [ ] Plugin 占位符展开功能正常（`{{buwai-rule:xxx}}` 正确替换）
- [ ] Plugin 环境注入功能正常（每 10 轮注入一次）
- [ ] Plugin session 管理功能正常（chat.message、compacting、event）
- [ ] Plugin config.json 拦截功能正常
- [ ] `agents-rules/` 下其他片段文件无改动
- [ ] `web-analysis/knowledge-base/` 下其他文件无改动

### 架构验收

- [ ] 知识库文件自包含（不依赖主 prompt 上下文即可理解）
- [ ] 知识库文件使用 `$AGENT_DIR` / `$SHARED_DIR` 变量引用其他文件
- [ ] Plugin 时间线记录不修改任何现有 hook 的 output（纯追加逻辑）
- [ ] 不引入循环依赖或反向依赖

---

## §5 与现有需求文档的关系

- 独立于所有已有需求文档
- 与 `2026-05-23-enforce-no-ask-user.md` 互补：那次解决了"问用户"问题，本次解决"卡住"和"知识缺失"问题
- 与 `2026-05-24-autonomous-exploration.md` 互补：那次增加了自主探索规则，本次增加防卡住规则
- 方案 C（时间线日志）为未来的复盘提供客观数据基础
