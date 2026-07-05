# PentAGI 进化 — 阶段 1：基础进化与多 agent 协作基础

## §1 背景与目标

### 1.1 来源

来源：对 PentAGI（`github.com/vxcontrol/pentagi`）的深度调研。PentAGI 是基于 AI agent 的自动化渗透测试平台，其 prompt 工程技巧、多 agent 协作机制、进程管理策略经过产品级验证。

本次进化将 PentAGI 中**与 OpenSecurity 形态兼容**的成熟机制借鉴过来，提升 OpenSecurity 在真实安全分析场景下的能力。

### 1.2 核心约束（不可变更）

> **OpenSecurity 面向真实安全分析场景，不是 CTF 工具。**
>
> CTF 只是训练和验证 agent 能力的手段。OpenSecurity 的最终目标是面向真实渗透测试、真实漏洞审计、真实威胁分析。所有决策必须以"真实场景下是否必要"为标尺，不能以"CTF 场景下够用"为标尺。
>
> 这个定位影响每一项改动：
> - detach 模式：真实渗透有反弹 shell / 中间人代理 / HTTP 回调监听 → 必要
> - scope control：真实渗透有严格的授权边界 → 必要
> - Playwright 持久化：真实渗透要爬取整个网站几十个页面 → 必要
> - 多 agent 协作：真实渗透是多步骤复杂任务 → 必要

### 1.3 阶段 1 的 9 项改动概览

| # | 能力 | 类型 | 来源 |
|---|------|------|------|
| 1 | detach 模式 | 修改 execution-discipline + Plugin 检测 | PentAGI terminal.go 的 detach 机制 |
| 2 | scope control | 新建 agents-rules/scope-control.md | PentAGI scope_of_work_pentest.md |
| 3 | 授权框架 | 新建 agents-rules/authorization-frame.md | PentAGI 所有 agent 的 authorization_status |
| 4 | 输出最小化 | execution-discipline 追加 | PentAGI pentester.tmpl 的 terminal_protocol |
| 5 | 渗透工具检测 | detect_env.py 扩充 | PentAGI Kali 工具集 |
| 6 | 语言策略 | 新建 agents-rules/language-policy.md | PentAGI 所有 agent 的 language_policy |
| 7 | 多 agent 协作 | 新建 agents-rules/sub-agent-orchestration.md | PentAGI team_specialists + delegation_rules |
| 8 | Sploitus 集成 | 新增 curl 包装脚本 | PentAGI sploitus.go |
| 9 | 浏览器自动化服务 | 新增 web_render_server.py + 启动脚本 | 对标 PentAGI scraper 服务 |

### 1.4 后续阶段路线图（不在本次实施）

| 阶段 | 内容 | 说明 |
|------|------|------|
| 阶段 2 | 完整多 agent 协作栈 | embedding（智谱）+ vector store（sqlite-vec）+ Graphiti（Neo4j）+ 持久化子 agent + 条件触发的 Adviser |
| 阶段 3 | Docker 沙箱隔离 | docker exec 替代直接 bash，提供隔离边界 |

### 1.5 不做的事项（与 OpenSecurity 形态根本冲突）

| 能力 | 不做的原因 |
|------|----------|
| Langfuse（LLM 可观测性） | 单用户 CUI，用户在 opencode 界面看 token，不需要多用户成本核算 |
| OpenTelemetry（分布式追踪） | OpenSecurity 是单进程（opencode），不是微服务架构，timeline.log 已覆盖工具时间线 |
| OAuth2 / JWT / GraphQL / REST API / React Web UI | 这些是 Web 产品的功能（多用户/对外接口/图形界面），CUI 形态不需要 |
| 固定多 agent 工种架构重写 | 借鉴 PentAGI 的工种定义和调度规则（阶段 1 第 7 项），但不重写 OpenSecurity 的领域分工架构 |
| coordinator 进化 | 本次不涉及 coordinator 的任何改动 |

---

## §2 技术方案

### 2.1 detach 模式（修改 execution-discipline + Plugin 检测）

**来源**：PentAGI `terminal.go` 的 detach 机制 + `pentester.tmpl` 的 terminal_protocol。

**问题**：现有 `execution-discipline.md` 的"长驻进程控制"段**一刀切禁止裸长驻进程**，要求"短命脚本 + sys.exit"。这在真实渗透测试的 4 类高频场景下完全失效：

| 场景 | 现有规则下的 AI 行为 | 结果 |
|------|--------------------|------|
| 反弹 shell 监听（`nc -lvp`） | 选 webhook.site → 内网靶机访问不到 | 失败 |
| SSRF 回调接收 | 选 webhook.site → 只能收 HTTP 不是 raw TCP | 失败 |
| Bot 监听（XSS/CSRF） | 起短命 server + sys.exit → bot 来之前退出 | 失败 |
| 中间人代理（mitmproxy） | 直接禁止 | 无法做 |

**方案**：用 Unix 的 `timeout` 命令作为进程死亡的硬保证（等价 PentAGI 的 container 销毁兜底），允许 detach 模式。

**硬约束三层**：
1. **核心硬约束**：`timeout -k 5 N` 命令包装（内核级 SIGKILL 保证，进程必然在 N+5 秒内死亡）
2. **进程组隔离**：`setsid` 创建独立会话（便于 kill 整个进程树）
3. **Plugin 强制检测**：`tool.execute.before` 钩子检测后台命令无 timeout → 拒绝执行

**detach 命令模板**：
```bash
setsid timeout -k 5 600 <command> > $TASK_DIR/<name>.log 2>&1 &
echo $! > $TASK_DIR/<name>.pid
```

**为什么 setsid 在 timeout 外面**：
- `setsid` 创建新 session + 新进程组，然后 exec `timeout`（PID 不变）
- `timeout` fork 出实际命令（如 nc）
- kill `$!`（setsid/timeout 的 PID）→ timeout 收到信号 → 转发给子进程（nc）→ 全部退出
- 如果 setsid 在 timeout 里面（`timeout setsid nc`），nc 会脱离 timeout 的进程组，kill timeout 时 nc 收不到信号

**timeout 上限**：
- 默认 600 秒（10 分钟）—— 覆盖反弹 shell / SSRF 回调 / Bot 监听
- 允许 AI 显式调高到 1800 秒（30 分钟）—— 用于 mitmproxy 等长任务
- 最高不超过 1800 秒

**Plugin 检测逻辑**（`tool.execute.before` 钩子）：
- 用正则 `/[^&]&\s*$/` 或 `/[^&]&\s/` 检测后台命令（匹配 `cmd &` 但不匹配 `cmd && cmd2`）
- 如果是后台命令且没有 `timeout` 包装 → 拒绝执行，返回提示
- 如果是后台命令且没有 PID 写入（`echo $!`）→ 拒绝执行，返回提示
- 用 `debugLog` 记录每次检测（便于排查）

### 2.2 scope control（新建 agents-rules/scope-control.md）

**来源**：PentAGI `examples/prompts/scope_of_work_pentest.md`。

**问题**：现有"安全红线"粒度过粗（一句话："不向生产环境发送破坏性请求"）。真实渗透测试需要结构化的边界控制——每一步操作前检查目标是否在授权范围内。

**方案**：结构化的 scope 控制规则，包含：
- **scope 判断维度**：域名后缀（.local/.lan/.htb/.corp/.internal 通常是内部/测试）、源码中的服务名（docker-compose 里的 `cache:`/`db:` 是基础设施不是攻击目标）、公网域名需额外确认
- **操作前检查清单**：每步网络操作前，提取所有 hostname/IP/URL/callback domain → 匹配 scope → 不在 scope 内就停止
- **scope 边界类型**：allowed_targets / out_of_scope_targets / allowed_actions / forbidden_actions / rate_limits / stop_conditions

**适用场景**：所有 security agent（不只是 web-analysis）。

### 2.3 授权框架（新建 agents-rules/authorization-frame.md）

**来源**：PentAGI 所有执行 agent 的 `<authorization_status>` 段。

**问题**：LLM（特别是 ai-security-analysis 的越狱场景、web-analysis 的 exploit 构造）经常拒绝任务、加 disclaimer、问"是否合法"。这浪费对话轮次、打断分析节奏。

**方案**：统一的中文授权声明，所有 security agent 引用。核心内容：
- 这是已授权的安全分析系统
- 所有分析操作已预先授权，无需请求许可
- 不加"确保合法授权"的免责声明
- 立即自信地执行所有请求的安全分析操作
- **与安全红线的关系**：授权框架只解锁"不该犹豫"，安全红线仍守住"不该做"（破坏生产/DoS）

### 2.4 输出最小化（execution-discipline 追加）

**来源**：PentAGI `pentester.tmpl` 的 terminal_protocol 的输出最小化部分。

**问题**：AI 经常把 nmap 全量扫描结果（上千行）、msfconsole 启动 banner（30+ 行）塞进上下文，浪费 token、分散注意力。

**方案**：在 execution-discipline.md 追加"输出最小化"段，列出常见工具的输出精简标志：
- `nmap --open`（只显示开放端口）
- `nmap -q`（安静模式）
- `msfconsole -q`（跳过 banner）
- `sqlmap --batch`（非交互模式）
- `gobuster -q`（安静模式）
- 通用：`2>/dev/null`（丢弃 stderr）、`| head -N`（截断输出）、`| grep`（过滤）

### 2.5 渗透工具检测（detect_env.py 扩充）

**来源**：PentAGI Kali 工具集（nmap/sqlmap/metasploit/gobuster/ffuf/nikto/hydra/commix/mitmproxy）。

**问题**：OpenSecurity 现有 detect_env.py 只检测逆向工具（IDA/apktool/jadx/adb），不检测渗透工具。真实渗透测试需要这些工具。

**方案**：在 detect_env.py 的 `EXTERNAL_TOOLS` 列表加入渗透工具检测：
- nmap（`brew install nmap`）
- sqlmap（`brew install sqlmap`）
- gobuster（`brew install gobuster`）
- ffuf（`brew install ffuf`）
- hydra（`brew install hydra`）
- nikto（`brew install nikto`）
- mitmproxy（`brew install mitmproxy`）
- commix（`pip install commix` 或 git clone）

每个工具的 `agents` 字段标注哪些 agent 需要（主要是 web-analysis，部分也用于 mobile-analysis）。

**注意**：metasploit 在 macOS 上安装困难，暂不检测（未来用 docker Kali 解决）。

### 2.6 语言策略（新建 agents-rules/language-policy.md）

**来源**：PentAGI 所有 agent 的 `<language_policy>` 双语通道分离。

**问题**：偶尔 LLM 会把英文技术内容翻译成中文（导致搜索失败）、把 payload 用中文描述包装、在报告里中英文术语混用不一致。

**方案**：双语通道分离规则：
- **技术通道（保持英文原样）**：shell 命令、CVE 编号、IP/端口、payload、shellcode、API 端点、文件路径、错误码、搜索查询
- **沟通通道（用中文）**：给用户的回复、运行日志、报告叙述

### 2.7 多 agent 协作（新建 agents-rules/sub-agent-orchestration.md）

**来源**：PentAGI `primary_agent.tmpl` 的 team_specialists + delegation_rules。

**问题**：OpenSecurity 的分析 agent 在长任务里上下文爆炸——信息收集的冗长输出、exploit 调试的反复迭代都累积在同一个上下文里。

**方案**：借鉴 PentAGI 的工种定义和调度规则，让每个分析 agent 内部支持多 agent 协作。

**工种定义**（照抄 PentAGI 6 工种，根据 OpenSecurity 实际情况微调）：

| 工种 | 职责 | 适用场景 | 各领域具体方法 |
|------|------|---------|--------------|
| searcher | 信息收集、技术调研 | 查 CVE、收集目标信息、查文档 | web 用 curl/gobuster；binary 用 IDA/strings；mobile 用 apktool/jadx |
| coder | 代码开发 | 写 exploit、写脚本、写 payload | 通用（Python/bash） |
| attacker | 攻击执行 | 运行 exploit、测试 payload、验证攻击 | web 用 curl/浏览器；binary 用 pwntools；mobile 用 Frida |

**与 PentAGI 的差异**（微调）：
- PentAGI 的 installer（环境维护）→ OpenSecurity 用 detect_env 替代，不需要子 agent
- PentAGI 的 memorist（记忆检索）→ OpenSecurity 用阶段 2 的 vector store 替代
- PentAGI 的 adviser（策略咨询）→ OpenSecurity 用阶段 2 的条件触发 Adviser 替代

**调度规则**（照抄 PentAGI delegation_rules）：
- 仅当专家明显更适合任务时才委派
- 委派时提供完整上下文（背景+目标+已有发现+期望输出+约束）
- 验证并整合专家结果回工作流
- 维护跨多次委派的任务连贯性
- 同一方向失败 2 次后切换（OpenSecurity 现有 loop-control 规则）

**委派策略**（何时该委派、何时不该）：

| 场景 | 是否委派 | 理由 |
|------|---------|------|
| 命令输出冗长（如 nmap 全端口扫描） | ✅ 委派给 searcher | 避免冗长输出污染主上下文 |
| 需要反复迭代的代码生成 | ✅ 委派给 coder | 子 agent 在独立上下文迭代 |
| 独立性强的子任务 | ✅ 委派 | 子任务有明确边界 |
| 简单一次性命令（curl 单个 URL） | ❌ 主 agent 自己做 | 创建子 agent 的成本 > 收益 |

**领域内 Refiner**：
- 子 agent 完成后，检查报告的 `<discovered_surfaces>` 段（新发现的攻击面）
- 基于新发现决定是否追加新的子任务（创建新子 agent）
- 子 agent 报告格式包含：`<discovered_surfaces>` 和 `<unsolved_challenges>`

### 2.8 Sploitus 集成（新增 curl 包装脚本）

**来源**：PentAGI `sploitus.go`。

**问题**：真实渗透测试需要查 CVE 和 exploit——"这个服务版本有什么已知漏洞"、"有没有现成的 exploit 可用"。OpenSecurity 现在只能用 webfetch 手动搜索。

**方案**：新增 Sploitus 搜索脚本（Python，~50 行）。Sploitus 是免费的漏洞/exploit 搜索引擎（`sploitus.com/search`），不需要 API key。

**脚本功能**：
- 输入：搜索关键词（如 "Apache 2.4.49" 或 CVE 编号）
- 输出：JSON 格式的搜索结果（exploit 标题、链接、类型、日期）
- 放在 `$SHARED_DIR/scripts/sploitus_search.py`

### 2.9 浏览器自动化服务（新增 web_render_server.py + 启动脚本）

**来源**：对标 PentAGI 的独立 scraper 服务，但用 Python HTTP server 实现（更轻量）。

**问题**：
1. web_render.py 每次调用都启动新的 Chromium（冷启动 2-5 秒）——真实渗透测试爬取整个网站（几十个页面），延迟累积不可接受
2. web_render.py 是无状态的一次性渲染——无法保持登录状态、无法做多步骤交互、无法模拟用户操作。**真实渗透测试的核心需求就是有状态的浏览器操作**（认证后渗透、多步骤攻击链、XSS 交互验证、CSRF 操作模拟）

**方案**：常驻 HTTP 服务（方案 A），提供完整的浏览器自动化 API。

**架构**：
```
web_render_server.py（常驻 HTTP 服务，监听 localhost:8888）
  ├── 浏览器管理：
  │   ├── 启动时 launch chromium + 默认 context
  │   ├── 所有请求共享同一个 context（cookie/session 自动保持）
  │   └── 崩溃时自动重启
  ├── API 端点：
  │   ├── /render — 渲染页面返回内容（当前 web_render.py 的能力，向后兼容）
  │   ├── /navigate — 导航到 URL
  │   ├── /click — 点击元素
  │   ├── /type — 输入文本
  │   ├── /submit — 提交表单
  │   ├── /screenshot — 截图
  │   ├── /execute — 执行 JavaScript
  │   ├── /cookies — GET 获取 cookie / POST 设置 cookie
  │   ├── /content — 获取页面内容（DOM/markdown/text/html）
  │   ├── /reset — 重置 context（清空所有状态）
  │   └── /health — 健康检查
  └── 会话管理：
      ├── 默认共享 context（登录后所有后续操作自动带 cookie）
      ├── /reset 清空状态（切到新会话）
      └── 多 page 并发（同一 context 下多个 tab）
```

**agent 调用流程**：
```bash
# 1. 任务开始时启动持久浏览器服务（detach 模式）
bash $SHARED_DIR/scripts/start_browser_server.sh
# → 输出服务地址: http://localhost:8888

# 2. 简单渲染（和当前 web_render.py 用法兼容）
curl -s http://localhost:8888/render -d '{"url":"https://target.com"}'

# 3. 认证后渗透（核心新能力）
curl -s http://localhost:8888/navigate -d '{"url":"https://target.com/login"}'
curl -s http://localhost:8888/type -d '{"selector":"#username","text":"admin"}'
curl -s http://localhost:8888/type -d '{"selector":"#password","text":"pass"}'
curl -s http://localhost:8888/click -d '{"selector":"#submit"}'
# 登录成功后，cookie 自动保持在 context 里
curl -s http://localhost:8888/navigate -d '{"url":"https://target.com/admin/dashboard"}'
# ← 自动带着登录 cookie，能访问需要认证的页面

# 4. XSS 交互验证
curl -s http://localhost:8888/navigate -d '{"url":"https://target.com/search?q=<script>document.title=\"XSS\"</script>"}'
curl -s http://localhost:8888/execute -d '{"script":"return document.title"}'
# ← 返回 "XSS"，证明脚本执行了

# 5. 任务结束前清理
kill $(cat $TASK_DIR/browser_server.pid)
```

**与现有 web_render.py 的关系**：
- web_render.py 保留，作为降级方案（服务不可用时直接启动浏览器）
- web_render_server.py 是主方案（常驻服务，功能完整）
- web-rendering.md 说明何时用哪个

**阶段 1 已知限制**（阶段 2 解决）：
- 单 context 设计——所有操作共享同一个 browser context。如果多个子 agent 同时操作（一个在登录、另一个在导航），会互相干扰
- 阶段 2 加入多 context 支持（每个 agent 分配独立的 context ID）

**服务管理（与 detach 模式配合）**：
- start_browser_server.sh 用 detach 模式启动 web_render_server.py
- `setsid timeout -k 5 3600 $PYTHON_CMD web_render_server.py --port 8888 > $TASK_DIR/browser_server.log 2>&1 & echo $! > $TASK_DIR/browser_server.pid`
- 默认 3600 秒（1 小时）——浏览器服务需要长时间运行

---

## §3 实施规范

### 改动范围表

| 文件 | 改动类型 | 步骤 |
|------|---------|------|
| `agents-rules/scope-control.md` | 新建 | 步骤 1 |
| `agents-rules/authorization-frame.md` | 新建 | 步骤 2 |
| `agents-rules/language-policy.md` | 新建 | 步骤 3 |
| `agents-rules/execution-discipline.md` | 修改（替换+追加） | 步骤 4 |
| `agents-rules/sub-agent-orchestration.md` | 新建 | 步骤 5 |
| `agents-rules/cross-agent-delegation.md` | 修改（扩展） | 步骤 6 |
| `binary-analysis/scripts/detect_env.py` | 修改（扩充） | 步骤 7 |
| `binary-analysis/scripts/sploitus_search.py` | 新建 | 步骤 8 |
| `binary-analysis/scripts/web_render_server.py` | 新建（步骤 9-11 分批） | 步骤 9/10/11 |
| `binary-analysis/scripts/start_browser_server.sh` | 新建 | 步骤 12 |
| `plugins/security-analysis.ts` | 修改（detach 检测） | 步骤 13 |
| `agents/*.md`（5 个分析 agent） | 修改（引用新规则） | 步骤 14 |
| `binary-analysis/knowledge-base/web-rendering.md` | 修改（浏览器服务 API 说明） | 步骤 15 |

### 编码规则

1. **中文优先**：所有 agents-rules 文件用中文（与现有规则一致）
2. **片段引用**：新增的 agents-rules 文件通过 `{{buwai-rule:xxx}}` 在 agent prompt 中引用
3. **依赖方向**：不违反现有架构依赖方向（agents-rules → agent prompt → 知识库）
4. **无 docs/ 引用**：所有知识沉淀自包含，不引用 docs/ 目录

---

## §3.1 实施步骤拆分

### 步骤 1. 新建 agents-rules/scope-control.md

- **文件**: `agents-rules/scope-control.md`（新建）
- **预估行数**: ~60 行
- **验证点**: 
  - 文件存在且语法正确（.md 无自动检查，人工读一遍确认自包含性）
  - 包含：scope 判断维度（域名后缀/服务名/公网域名）、操作前检查清单、scope 边界类型
  - 可被 `{{buwai-rule:scope-control}}` 引用
- **依赖**: 无

### 步骤 2. 新建 agents-rules/authorization-frame.md

- **文件**: `agents-rules/authorization-frame.md`（新建）
- **预估行数**: ~40 行
- **验证点**:
  - 包含：统一中文授权声明、与安全红线的关系说明
  - 明确"授权框架解锁不该犹豫，安全红线守住不该做"
  - 可被 `{{buwai-rule:authorization-frame}}` 引用
- **依赖**: 无

### 步骤 3. 新建 agents-rules/language-policy.md

- **文件**: `agents-rules/language-policy.md`（新建）
- **预估行数**: ~30 行
- **验证点**:
  - 包含：技术通道（英文）vs 沟通通道（中文）的字段分类
  - 列出必须保持英文的内容类型（命令/CVE/IP/payload/路径/错误码/搜索查询）
- **依赖**: 无

### 步骤 4. 修改 agents-rules/execution-discipline.md — detach 模式 + 输出最小化

- **文件**: `agents-rules/execution-discipline.md`（修改）
- **预估行数**: ~80 行（替换"长驻进程控制"段 ~15 行 + 新增 detach 模式 ~45 行 + 新增输出最小化 ~20 行）
- **改动内容**:
  - **替换**现有"长驻进程控制"段：从"禁止裸长驻 + 短命 sys.exit"改为"detach 模式允许 + timeout 硬约束 + PID 管理"
  - **新增**"输出最小化"段：列出 nmap/msfconsole/sqlmap/gobuster 等工具的输出精简标志
  - **修改**"在线托管平台优先"的优先级：从"优先"改为"目标能出公网时优先；目标在内网时用 detach 本地监听"
- **验证点**:
  - detach 命令模板包含 `timeout -k 5 N setsid nohup ... > log 2>&1 & echo $! > pid`
  - timeout 默认 600 秒、上限 1800 秒明确
  - 输出最小化段有具体工具标志列表
  - 现有的其他段（自主探索规则、系统性卡住恢复等）不被破坏
- **依赖**: 无

### 步骤 5. 新建 agents-rules/sub-agent-orchestration.md

- **文件**: `agents-rules/sub-agent-orchestration.md`（新建）
- **预估行数**: ~120 行
- **改动内容**: 借鉴 PentAGI team_specialists + delegation_rules
  - 3 个工种定义（searcher/coder/attacker）—— 照抄 PentAGI 的 6 工种，去掉 installer/memorist/adviser（用其他机制替代）
  - 每个工种的 skills / use_cases / 各领域具体方法
  - 调度规则（照抄 PentAGI delegation_rules，适配中文）
  - 委派策略（何时该委派、何时不该）
  - 领域内 Refiner 规则（子 agent 报告新发现 → 主 agent 追加子任务）
  - 子 agent 报告格式（`<discovered_surfaces>` / `<unsolved_challenges>`）
- **验证点**:
  - 3 个工种定义清晰，每个有 skills/use_cases/方法
  - 调度规则可操作（不是泛化口号）
  - 委派策略有明确的"何时委派/何时不委派"判断
  - 领域内 Refiner 有具体的报告格式定义
  - 可被 `{{buwai-rule:sub-agent-orchestration}}` 引用
- **依赖**: 无

### 步骤 6. 修改 agents-rules/cross-agent-delegation.md — 扩展领域内委派

- **文件**: `agents-rules/cross-agent-delegation.md`（修改）
- **预估行数**: ~40 行修改（现有 15 行 → 扩展到 ~55 行）
- **改动内容**:
  - 现有内容（跨领域委派给 crypto-analysis）保留
  - 新增"领域内委派"段：引用 `{{buwai-rule:sub-agent-orchestration}}`
  - 说明跨领域委派和领域内委派的区别
- **验证点**:
  - 现有的跨领域委派表不丢失
  - 新增的领域内委派引用了 sub-agent-orchestration 规则
  - 两类委派的区别清晰
- **依赖**: 步骤 5

### 步骤 7. 扩充 binary-analysis/scripts/detect_env.py — 加渗透工具检测

- **文件**: `binary-analysis/scripts/detect_env.py`（修改）
- **预估行数**: ~60 行新增（在 EXTERNAL_TOOLS 列表加 7 个工具条目）
- **改动内容**: 在 `EXTERNAL_TOOLS` 列表加入：
  - nmap（agents=["web-analysis"], `brew install nmap`）
  - sqlmap（agents=["web-analysis"], `brew install sqlmap`）
  - gobuster（agents=["web-analysis"], `brew install gobuster`）
  - ffuf（agents=["web-analysis"], `brew install ffuf`）
  - hydra（agents=["web-analysis"], `brew install hydra`）
  - nikto（agents=["web-analysis"], `brew install nikto`）
  - mitmproxy（agents=["web-analysis", "mobile-analysis"], `brew install mitmproxy`）
- **验证点**:
  - `python -c "compile(open('detect_env.py').read(), 'detect_env.py', 'exec')"` 语法检查通过
  - `$PYTHON_CMD detect_env.py --check-preinstall web-analysis` 能检测到新工具（存在的显示 available，不存在的显示 unavailable + install_hint）
  - 不破坏现有的 IDA/apktool/jadx/adb 检测
- **依赖**: 无

### 步骤 8. 新增 binary-analysis/scripts/sploitus_search.py

- **文件**: `binary-analysis/scripts/sploitus_search.py`（新建）
- **预估行数**: ~50 行
- **改动内容**: Sploitus 搜索脚本
  - 输入：搜索关键词（命令行参数）
  - 调用 `https://sploitus.com/search` API
  - 输出：JSON 格式（标题、链接、类型、日期）
  - 错误处理：网络失败、速率限制（HTTP 499）、超时
- **验证点**:
  - `$PYTHON_CMD sploitus_search.py --help` 显示用法
  - `$PYTHON_CMD sploitus_search.py "Apache 2.4.49"` 返回 JSON 结果（需要网络）
  - 无网络时优雅返回错误（不崩溃）
  - `registry.json` 有 `sploitus_search` 条目（name/file/description/params/example_call 字段完整）
- **依赖**: 无

### 步骤 9. 新建 web_render_server.py 基础（HTTP server + 浏览器生命周期 + 基础渲染）

- **文件**: `binary-analysis/scripts/web_render_server.py`（新建，第一批）
- **预估行数**: ~150 行
- **改动内容**:
  - Python HTTP server（基于 `http.server`，不引入 Flask 等框架）
  - Playwright 浏览器生命周期管理（启动时 launch chromium + new_context）
  - 基础 API 端点：
    - `GET /health` — 健康检查（返回服务状态 + 浏览器是否存活）
    - `POST /render` — 渲染页面返回 markdown/text/html（参数：url, format, timeout, wait_selector）
    - `POST /screenshot` — 截图（参数：url, path, full_page, timeout）
  - 所有操作共享同一个 browser context（cookie/session 自动保持）
  - 浏览器崩溃时自动重启（try-except 包裹 + 重新 launch）
  - JSON 请求/响应格式
  - 命令行参数：`--port`（默认 8888）、`--host`（默认 127.0.0.1）
- **验证点**:
  - `python -c "compile(open('web_render_server.py').read(), 'web_render_server.py', 'exec')"` 语法检查通过
  - 启动服务后 `curl http://localhost:8888/health` 返回 `{"status":"ok","browser":true}`
  - `curl -s http://localhost:8888/render -d '{"url":"https://example.com","format":"markdown"}'` 返回页面内容
  - `curl -s http://localhost:8888/screenshot -d '{"url":"https://example.com","path":"/tmp/test.jpg"}'` 生成截图
  - `registry.json` 有 `web_render_server` 条目（在步骤 11 完成后注册，包含所有 API 端点说明）
- **依赖**: 无

### 步骤 10. 扩展 web_render_server.py 交互 API（/navigate + /click + /type + /submit + /content）

- **文件**: `binary-analysis/scripts/web_render_server.py`（追加）
- **预估行数**: ~100 行
- **改动内容**: 在步骤 9 的基础上追加交互 API 端点
  - `POST /navigate` — 导航到 URL（参数：url, timeout, wait_until）
  - `POST /click` — 点击元素（参数：selector）
  - `POST /type` — 输入文本（参数：selector, text）
  - `POST /submit` — 提交表单（参数：selector 或自动找最近的 form）
  - `POST /content` — 获取当前页面内容（参数：format=markdown/text/html/dom）
  - 交互操作的错误处理（元素未找到、超时、导航失败）
  - 保持步骤 9 的 context 共享特性
- **验证点**:
  - 语法检查通过
  - 多步骤操作测试：`/navigate` → `/type` → `/click` → `/content` 能完成登录并获取认证后页面
  - cookie 在 `/navigate` 调用间自动保持（认证后访问受限页面不被重定向）
  - 错误处理：`/click` 不存在的选择器 → 返回 `{"success":false,"error":"..."}` 而非崩溃
- **依赖**: 步骤 9

### 步骤 11. 扩展 web_render_server.py 会话管理（/execute + /cookies + /reset）

- **文件**: `binary-analysis/scripts/web_render_server.py`（追加）
- **预估行数**: ~80 行
- **改动内容**: 在步骤 10 的基础上追加会话管理 API
  - `POST /execute` — 在当前页面执行 JavaScript（参数：script，返回执行结果）
  - `GET /cookies` — 获取当前所有 cookie
  - `POST /cookies` — 设置 cookie（参数：name, value, domain, path）
  - `POST /reset` — 重置 context（关闭当前 context + 创建新的，清空所有状态）
- **验证点**:
  - 语法检查通过
  - `/execute` 测试：`curl -s http://localhost:8888/execute -d '{"script":"return document.title"}'` 返回页面标题
  - `/cookies` 测试：登录后 `GET /cookies` 能拿到 session cookie
  - `/reset` 测试：reset 后 `GET /cookies` 返回空数组，`/navigate` 到受限页面被重定向
- **依赖**: 步骤 10

### 步骤 12. 新增 binary-analysis/scripts/start_browser_server.sh

- **文件**: `binary-analysis/scripts/start_browser_server.sh`（新建）
- **预估行数**: ~30 行
- **改动内容**: 启动持久浏览器服务（detach 模式）
  - 检测服务是否已在运行（`curl -s http://localhost:8888/health`）
  - 如果已在运行 → 输出服务地址，跳过启动
  - 如果未运行 → 用 detach 模式启动：`setsid timeout -k 5 3600 $PYTHON_CMD $SHARED_DIR/scripts/web_render_server.py --port 8888 > $TASK_DIR/browser_server.log 2>&1 &`
  - PID 写入 `$TASK_DIR/browser_server.pid`
  - 等待服务可用（轮询 `/health`，最多 15 秒）
  - 输出服务地址：`http://localhost:8888`
- **验证点**:
  - `bash start_browser_server.sh` 启动后，`curl http://localhost:8888/health` 返回 ok
  - `$TASK_DIR/browser_server.pid` 存在且 PID 有效
  - `kill $(cat $TASK_DIR/browser_server.pid)` 能正常关闭
  - 已有服务在运行时，脚本检测到并跳过（不重复启动）
  - `registry.json` 有 `start_browser_server` 条目
- **依赖**: 步骤 11（web_render_server.py 功能完整）

### 步骤 13. 修改 plugins/security-analysis.ts — 加 detach 违规检测

- **文件**: `plugins/security-analysis.ts`（修改）
- **预估行数**: ~50 行 TS 代码新增
- **改动内容**: 在 `tool.execute.before` 钩子加 detach 违规检测
  - 用正则 `/[^&]&\s*$/` 或 `/[^&]&\s/` 检测后台命令（匹配 `cmd &` 但不匹配 `cmd && cmd2`）
  - 如果是后台命令且没有 `timeout` 包装 → 拒绝执行，返回提示："后台命令必须用 timeout 包装：`setsid timeout -k 5 N cmd > log 2>&1 & echo $! > pid`"
  - 如果是后台命令且没有 PID 写入（`echo $!`）→ 拒绝执行，返回提示
  - 用 `debugLog` 记录每次检测（便于排查）
- **验证点**:
  - `node --check` 语法检查通过
  - 模拟测试：bash 命令 `nc -lvp 4444 &`（无 timeout）→ 被拒绝
  - 模拟测试：bash 命令 `setsid timeout -k 5 600 nc -lvp 4444 > log 2>&1 & echo $! > pid` → 通过
  - 非后台命令（如 `ls -la`）→ 不受影响
- **依赖**: 无

### 步骤 14. 更新各 agent prompt — 引用新规则

- **文件**: 5 个分析 agent prompt（修改）
  - `agents/binary-analysis.md`
  - `agents/mobile-analysis.md`
  - `agents/web-analysis.md`
  - `agents/ai-security-analysis.md`
  - `agents/crypto-analysis.md`
  - （`agents/security-coordinator.md` 不涉及，本次不改 coordinator）
- **预估行数**: 每个文件 ~5 行新增（加引用），共 ~25 行
- **改动内容**: 在每个分析 agent 的 prompt 中，在现有 `{{buwai-rule:xxx}}` 引用附近，新增引用：
  - `{{buwai-rule:scope-control}}`
  - `{{buwai-rule:authorization-frame}}`
  - `{{buwai-rule:language-policy}}`
  - `{{buwai-rule:sub-agent-orchestration}}`
  - （execution-discipline 已经被引用，detach 和输出最小化自动生效）
- **验证点**:
  - 每个 agent prompt 的展开后行数 < 450（Phase 4.5 检查）
  - `{{buwai-rule:xxx}}` 占位符在 agents-rules/ 目录有对应文件
  - 各 agent 的核心规则（分析框架、知识库索引）不被破坏
- **依赖**: 步骤 1-5

### 步骤 15. 更新 web-rendering.md — 浏览器服务 API 使用说明

- **文件**: `binary-analysis/knowledge-base/web-rendering.md`（修改）
- **预估行数**: ~80 行修改（追加新段，保留现有 web_render.py 说明作为降级方案）
- **改动内容**:
  - 新增"浏览器自动化服务"段（web_render_server.py）
  - API 端点完整说明（/render /navigate /click /type /submit /screenshot /execute /cookies /content /reset /health）
  - 典型使用场景（认证后渗透、多步骤攻击链、XSS 验证、CSRF 模拟）
  - 启动→使用→清理完整流程
  - 与 web_render.py 的关系（服务是主方案，web_render.py 是降级方案）
- **验证点**:
  - 人工读一遍确认自包含性
  - 包含完整的启动→使用→清理流程
  - API 端点说明覆盖步骤 9-11 的所有端点
  - 典型场景有具体的 curl 命令示例
- **依赖**: 步骤 9-12

---

## §4 验收标准

### 4.1 功能验收（逐项）

| # | 验收项 | 验证方法 | 通过标准 |
|---|--------|---------|---------|
| 1 | detach 模式 | execution-discipline.md 包含 detach 命令模板 + timeout 硬约束 | 模板格式：`timeout -k 5 N setsid nohup ... > log 2>&1 & echo $! > pid` |
| 2 | Plugin detach 检测 | 模拟后台命令无 timeout → 应被拒绝 | 无 timeout 的后台命令被拒绝 + 返回提示 |
| 3 | scope control | scope-control.md 包含操作前检查清单 + scope 判断维度 | 有人工可读的检查步骤 + 域名后缀/服务名/公网域名分类 |
| 4 | 授权框架 | authorization-frame.md 包含统一中文授权声明 | 有明确的"已授权、不犹豫"声明 + 与安全红线的关系 |
| 5 | 输出最小化 | execution-discipline.md 包含输出精简标志列表 | 列出 nmap/msfconsole/sqlmap/gobuster 等工具的 -q/--open/--batch 标志 |
| 6 | 渗透工具检测 | `detect_env.py --check-preinstall web-analysis` | 能检测 nmap/sqlmap/gobuster/ffuf/hydra/nikto/mitmproxy |
| 7 | 语言策略 | language-policy.md 包含双语通道分类 | 明确技术通道（英文）和沟通通道（中文）的字段分类 |
| 8 | 多 agent 协作 | sub-agent-orchestration.md 包含 3 工种 + 调度规则 + 委派策略 | searcher/coder/attacker 定义清晰 + 有何时委派的判断 |
| 9 | Sploitus 集成 | `sploitus_search.py "test"` 返回 JSON | 返回搜索结果或优雅的错误（不崩溃） |
| 10 | 浏览器自动化服务 | `start_browser_server.sh` 启动后 curl API 可用 | `/health` 返回 ok + `/render` 返回内容 + `/navigate`+`/type`+`/click` 能完成登录 |
| 10a | 会话保持 | 登录后访问受限页面 | cookie 自动保持，不被重定向 |
| 10b | JS 执行 | `/execute` 返回结果 | 能在页面上下文执行 JS 并返回结果 |
| 11 | agent prompt 引用 | 各 agent prompt 包含新规则引用 | `{{buwai-rule:scope-control}}` 等 4 个引用存在 |

### 4.2 回归验收

| 验收项 | 验证方法 | 通过标准 |
|--------|---------|---------|
| 现有规则不被破坏 | 读修改后的 execution-discipline.md | "自主探索规则"/"系统性卡住恢复"/"已知方案处理策略"等段保留 |
| 现有检测不被破坏 | `detect_env.py --check-preinstall binary-analysis` | IDA/apktool/jadx/adb 检测正常 |
| web_render.py 保留 | web_render.py 文件不被删除 | 作为降级方案保留 |
| 浏览器服务不破坏 web_render.py | web_render.py 仍可独立使用 | 不依赖 web_render_server.py |
| Plugin 现有功能 | Plugin 语法检查 + 现有 hook 行为 | tool.execute.before 现有的时间线记录功能保留 |
| agent prompt 行数 | 各 agent prompt 展开后行数 | < 450 行（Phase 4.5 检查） |

### 4.3 架构验收

| 验收项 | 通过标准 |
|--------|---------|
| 依赖方向 | 不违反 agents-rules → agent prompt → 知识库 的依赖方向 |
| 无循环依赖 | agents-rules 文件之间不互相引用（各自独立） |
| 无 docs/ 引用 | 新增文件不引用 docs/ 目录 |
| 文件放置 | 新增文件在正确位置（agents-rules/ 或 binary-analysis/scripts/） |
| 片段引用机制 | 新增的 agents-rules 通过 `{{buwai-rule:xxx}}` 被 agent prompt 引用 |

---

## §5 与现有需求文档的关系

### 不冲突的需求文档

| 现有需求 | 关系 |
|---------|------|
| `2026-05-03-playwright-web-render.md` | 本次步骤 9-12 是它的进化（从一次性渲染升级为常驻浏览器自动化服务），不冲突 |
| `2026-05-23-enforce-no-ask-user.md` | 本次步骤 2（授权框架）是它的强化（从"不问用户"到"已授权、不犹豫"），互补 |
| `2026-05-24-autonomous-exploration.md` | 本次步骤 5（多 agent 协作）是它的扩展（从单 agent 自主到多 agent 协作），互补 |
| `2026-06-27-coordinator-routing-decision-tree.md` | 本次不涉及 coordinator，不冲突 |

### 后续衔接（阶段 2 准备）

阶段 1 的多 agent 协作规则（步骤 5）为阶段 2 的完整协作栈做铺垫：
- 阶段 1 定义了工种和调度规则（prompt 层面）
- 阶段 2 加入 vector store / Graphiti / 持久化子 agent（基础设施层面）
- 两者结合才是完整的多 agent 协作能力

---

## 附录：PentAGI 调研关键发现

### PentAGI 的 detach 机制（terminal.go 第 216-237 行）

```go
if detach {
    detachedCtx := context.WithoutCancel(ctx)  // 脱离请求 ctx
    go func() {
        output, err := t.getExecResult(detachedCtx, createResp.ID, timeout)
        resultChan <- execResult{output: output, err: err}
    }()
    select {
    case <-time.After(defaultQuickCheckTimeout):  // 500ms
        return "Command started in background (still running)"
    }
}
```

**PentAGI 的进程死亡保证**：docker container 销毁（`RemoveContainer`）。
**OpenSecurity 的等价**：Unix `timeout -k 5` 命令（内核级 SIGKILL 保证）。

### PentAGI 的工种定义（primary_agent.tmpl）

6 个工种：searcher / pentester / developer / adviser / memorist / installer。
**OpenSecurity 微调为 3 个**：searcher / coder / attacker（去掉 installer/memorist/adviser，用其他机制替代）。

### PentAGI 的调度规则（primary_agent.tmpl delegation_rules）

- 仅当专家明显更适合时才委派
- 委派时提供完整上下文
- 验证并整合专家结果
- 维护跨委派的任务连贯性

**OpenSecurity 照搬这些规则**，适配中文 + 结合现有 loop-control（失败 2 次切换）。

### PentAGI 的真实进程清理机制

不是 timeout（context timeout 只关闭读取端不杀进程），是 **container 销毁**。
OpenSecurity 没有 container，用 `timeout -k 5` 命令替代——这是内核级保证，比 PentAGI 的 context timeout 更硬。
