# 需求文档: 创建 web-analysis Agent

## §1 背景与目标

### 背景

在 CyberGame 2026 (SK-CERT) 的 `future.js` Web Cache Poisoning 题目分析中（详见 `docs/解题报告/Web/futurejs-writeup.md`，1752 行），暴露出当前安全分析体系缺少 Web 安全分析能力：

- 当前体系只有 binary-analysis（IDA Pro 逆向）和 mobile-analysis（APK/IPA），没有 Web 安全分析 agent
- Web 安全分析涉及完全不同的技术栈：HTTP 协议、缓存机制、XSS/SSRF/SQLi、Web 框架源码审计
- 分析 futurejs 时，binary-analysis 的框架（围绕 IDA 数据库设计）完全不适用

### 目标

创建 `web-analysis` Agent，使体系具备 Web 安全分析能力：

1. 专门的 Web 安全分析框架（信息收集 → 攻击面枚举 → 漏洞分析 → 利用验证）
2. Web 安全知识库（漏洞模式、框架安全、黑盒方法论）
3. 与现有 Plugin 集成（session 管理、环境注入、占位符展开）

### 预期收益

- 上下文: Web 分析时不加载 IDA 相关 prompt，减少无效上下文 ~30%
- 轮次: 有专门方法论引导，减少方向性迷茫（futurejs 试了 10+ 种方向）
- 速度: 按框架执行比随机探索更快
- 准确度: 有方法论和知识库引导，避免遗漏关键攻击面

---

## §2 技术方案

### 2.1 架构中的位置

```
.opencode/
├── agents/
│   ├── binary-analysis.md        # 已有
│   ├── mobile-analysis.md        # 已有
│   ├── security-analysis-evolve.md  # 已有
│   └── web-analysis.md           # ← 新增（Agent prompt）
├── web-analysis/                 # ← 新增（Agent 专属目录）
│   ├── knowledge-base/           # 知识库（按需加载）
│   │   ├── web-methodology.md    # Web 安全分析方法论
│   │   ├── web-vulnerabilities.md # Web 漏洞模式速查
│   │   └── cache-poisoning.md    # Web Cache Poisoning 专题
│   └── README.md                 # 目录说明
├── binary-analysis/              # 已有（共享目录 $SHARED_DIR）
└── plugins/
    └── security-analysis.ts      # 修改：注册 web-analysis
```

**归属判定（按规则 4）**:
- `web-methodology.md`（Web 安全方法论）: 通用分析知识 → web-analysis/
- `web-vulnerabilities.md`（漏洞模式）: Web 特有 → web-analysis/
- `cache-poisoning.md`（缓存投毒专题）: 从 futurejs writeup 沉淀 → web-analysis/
- `web_render.py`: 已在 binary-analysis/scripts/ 中，通过 $SHARED_DIR 共享

**依赖方向**: web-analysis 可引用 $SHARED_DIR（binary-analysis/）的通用工具（如 web_render.py），不可反向依赖。

### 2.2 Agent Prompt 设计

基于 binary-analysis.md 和 mobile-analysis.md 的结构模式，web-analysis.md 包含以下段落：

| 段落 | 内容 | 行数估计 |
|------|------|---------|
| frontmatter | description, mode: primary, buwai-extension-id: web-analysis | ~8 |
| 角色 | Web 安全分析编排器职责说明 | ~10 |
| 运行环境 | {{buwai-rule:running-environment}} | ~3（展开后） |
| 变量初始化 | {{buwai-rule:variable-initialization}}（去掉 $IDAT, $BA_PYTHON） | ~10 |
| 参数解析 | URL 或源码目录识别 | ~8 |
| 阶段 0 任务初始化 | {{buwai-rule:task-initialization}} | ~7（展开后） |
| 分析执行框架 | 阶段 A（信息收集）+ 阶段 B（攻击规划）+ 阶段 C（执行监控） | ~60 |
| Web 分析核心原则 | 6 条核心原则 | ~15 |
| 工具清单 | curl、浏览器 DevTools、源码阅读、Docker 分析 | ~20 |
| 知识库索引 | 3 个知识库文档的触发条件表 | ~15 |
| 输出格式 | {{buwai-rule:output-format}} + 专属补充 | ~15 |
| 后续交互 | 变量丢失自愈 | ~10 |
| 任务存档 | {{buwai-rule:task-archive}} | ~1 |
| 安全规则 | 不发送恶意请求到生产环境等 | ~5 |
| **总计** | | **~185** |

> 展开后行数（含所有 {{buwai-rule:}} 片段）≈ 185 行，远低于 450 行阈值。

### 2.3 Agent Prompt 核心差异（与 binary/mobile 对比）

| 维度 | binary-analysis | mobile-analysis | web-analysis |
|------|----------------|-----------------|-------------|
| 输入 | IDA 数据库路径 | APK/IPA 文件 | URL 或源码目录 |
| 阶段 A 信息收集 | idat initial_analysis.py | apktool/jadx/unzip | 框架识别/路由枚举/攻击面 |
| 阶段 B 分析规划 | 场景模板 | 多路径决策树 | 漏洞类型决策树 |
| 核心原则 | 找关键点/绕过优先 | 跨层追踪/静态+动态 | 攻击面优先/配置即代码 |
| 变量 | $IDAT, $BA_PYTHON | （同 binary） | 不需要 $IDAT/$BA_PYTHON |

### 2.4 Plugin 修改

修改 `security-analysis.ts`，最小改动：

1. 添加 `AGENT_WEB_ANALYSIS` 常量
2. 将其加入 `PRIMARY_AGENTS` 数组
3. 在 `getCompactionContext` 中添加 web-analysis 的压缩保留状态

### 2.5 知识库文档设计

#### web-methodology.md（Web 安全分析方法论）

内容来源: futurejs writeup 第十三、十四章的方法论总结 + 通用 Web 安全分析方法

结构:
- 白盒分析流程（有源码）
- 黑盒分析流程（无源码）
- 源码审计优先级
- 框架源码审计方法（关键: futurejs 的突破就在框架源码中）
- 攻击链构造方法

#### web-vulnerabilities.md（Web 漏洞模式速查）

内容来源: OWASP Top 10 + CTF 常见漏洞类型

结构:
- 注入类（XSS/SQLi/SSRF/CRLF）
- 认证/会话类（Cookie 安全/JWT/CORS/CSRF）
- 缓存类（Web Cache Poisoning/Cache Deception）
- 文件类（LFI/RFI/文件上传）
- 逻辑类（IDOR/条件竞争）

#### cache-poisoning.md（Web Cache Poisoning 专题）

内容来源: futurejs writeup 的完整攻击链

结构:
- 缓存投毒原理
- 缓存键分析
- Vary 头绕过
- 组合利用（缓存投毒 + XSS）
- 防御措施

### 2.6 变量初始化差异

web-analysis 不需要 `$IDAT`（不使用 IDA Pro）和 `$BA_PYTHON`（不需要 venv Python），但需要：

| 变量 | 来源 | 说明 |
|------|------|------|
| `$AGENT_DIR` | 环境信息"Agent 目录" | web-analysis/ 目录 |
| `$SHARED_DIR` | 环境信息"共享目录" | binary-analysis/（含 web_render.py） |
| `$TASK_DIR` | 任务初始化 | 任务工作目录 |

变量初始化段直接使用 {{buwai-rule:variable-initialization}} 片段（与 mobile-analysis 一致），但在"参数解析"段之后追加 Web 专属变量说明：只用 $AGENT_DIR、$SHARED_DIR、$TASK_DIR，不依赖 $IDAT 和 $BA_PYTHON。

---

## §3 实现规范

### 3.0 改动范围表

| 文件 | 操作 | 预估行数 | 说明 |
|------|------|---------|------|
| `agents/web-analysis.md` | 新增 | ~185 | Agent prompt |
| `web-analysis/knowledge-base/web-methodology.md` | 新增 | ~120 | Web 安全方法论 |
| `web-analysis/knowledge-base/web-vulnerabilities.md` | 新增 | ~150 | 漏洞模式速查 |
| `web-analysis/knowledge-base/cache-poisoning.md` | 新增 | ~100 | 缓存投毒专题 |
| `web-analysis/README.md` | 新增 | ~15 | 目录说明 |
| `plugins/security-analysis.ts` | 修改 | ~15 行改动 | 注册 web-analysis |

### 3.1 实施步骤拆分

**步骤 1. 创建 web-analysis 目录结构**
  - 文件: 创建 `web-analysis/`、`web-analysis/knowledge-base/` 目录，创建 `web-analysis/README.md`
  - 预估行数: ~15 行
  - 验证点: 目录存在，README.md 可读
  - 依赖: 无

**步骤 2. 创建 web-analysis Agent prompt**
  - 文件: `agents/web-analysis.md`
  - 预估行数: ~185 行
  - 验证点: frontmatter 格式正确（mode: primary, buwai-extension-id: web-analysis）；包含完整段落（角色、参数解析、阶段 A/B/C、核心原则、工具清单、知识库索引、输出格式、安全规则）；占位符 {{buwai-rule:xxx}} 使用正确；展开后 < 450 行（展开行数 = .md 行数 - 占位符行数 + 各片段文件行数之和）
  - 依赖: 无

**步骤 3. 创建知识库: web-methodology.md**
  - 文件: `web-analysis/knowledge-base/web-methodology.md`
  - 预估行数: ~120 行
  - 验证点: 自包含（不依赖主 prompt 上下文即可理解）；包含白盒/黑盒分析流程；包含框架源码审计方法
  - 依赖: 无

**步骤 4. 创建知识库: web-vulnerabilities.md**
  - 文件: `web-analysis/knowledge-base/web-vulnerabilities.md`
  - 预估行数: ~150 行
  - 验证点: 自包含；覆盖 OWASP Top 10 主要类型；每个漏洞类型有识别方法 + 利用思路
  - 依赖: 无

**步骤 5. 创建知识库: cache-poisoning.md**
  - 文件: `web-analysis/knowledge-base/cache-poisoning.md`
  - 预估行数: ~100 行
  - 验证点: 自包含；包含缓存投毒原理、缓存键分析、Vary 绕过、组合利用、防御
  - 依赖: 无

**步骤 6. 修改 Plugin: 注册 web-analysis**
  - 文件: `plugins/security-analysis.ts`
  - 预估行数: ~15 行改动
  - 验证点: `node --check security-analysis.ts` 语法通过；`AGENT_WEB_ANALYSIS` 常量存在；`PRIMARY_AGENTS` 包含 `"web-analysis"`；`getCompactionContext` 包含 web-analysis 分支
  - 依赖: 无

**步骤 7. 端到端验证**
  - 文件: 所有新增/修改文件
  - 预估行数: 0 行（验证步骤，不写代码）
  - 验证点: agent prompt 展开后 < 450 行；所有知识库文件自包含；Plugin 语法正确；agent prompt 引用路径使用 $OPENCODE_ROOT 变量
  - 依赖: 步骤 1-6 全部完成

---

## §4 验收标准

### 功能验收

- [ ] `web-analysis.md` frontmatter 包含 `mode: primary` 和 `buwai-extension-id: web-analysis`
- [ ] Agent prompt 包含完整段落：角色、参数解析、阶段 A（信息收集）、阶段 B（攻击规划）、阶段 C（执行监控）、核心原则、工具清单、知识库索引、输出格式、安全规则
- [ ] 变量初始化段不引用 $IDAT 和 $BA_PYTHON
- [ ] 阶段 A 信息收集包含：框架识别、路由枚举、中间件识别、攻击面枚举
- [ ] 阶段 B 包含漏洞类型决策树（读取 `web-methodology.md`）
- [ ] 知识库索引表列出 3 个文档及其触发条件
- [ ] 3 个知识库文件全部自包含
- [ ] Plugin 中 `PRIMARY_AGENTS` 包含 `"web-analysis"`
- [ ] Plugin 中 `getCompactionContext` 有 web-analysis 分支

### 回归验收

- [ ] binary-analysis.md 无任何改动
- [ ] mobile-analysis.md 无任何改动
- [ ] security-analysis-evolve.md 无任何改动
- [ ] Plugin 对 binary-analysis 和 mobile-analysis 的行为不变（`PRIMARY_AGENTS` 扩展不影响已有逻辑）

### 架构验收

- [ ] web-analysis/ 可引用 $SHARED_DIR，$SHARED_DIR 不引用 web-analysis/（单向依赖）
- [ ] 所有知识库文件路径使用 $OPENCODE_ROOT 变量
- [ ] agent prompt 展开后 < 450 行

---

## §5 与现有需求文档的关系

- 本次需求独立于所有已有需求文档
- 不依赖任何未完成的进化任务
- 与 `2026-05-03-agent-prompt-snippets.md`（共享片段机制）互补：web-analysis 复用 agents-rules/ 下的片段
- 与 `2026-05-05-long-document-editing-strategy.md`（长文档编辑策略）互补：知识库文档用 Edit 创建
