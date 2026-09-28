# 2026-09-28 变量规范名升级：$OPENSECURITY_HOME（兼容别名 DATA_DIR）

> 状态：已实施（Phase 6 审计通过）| 入口：用户评审（`数据根目录 ($DATA_DIR)` 描述与命名"看不出干嘛的"）→ 用户选定 `OPENSECURITY_HOME`
> 来源：`2026-09-28-data-dir-var-injection-and-hardcoded-path-cleanup.md` 的命名修订（其注入面与文档引用被本文件取代）
> 实施进度与 as-built：`progress-2026-09-28-opensecurity-home-var-rename.md`
> as-built：注入面与 9 文件 16 处文档全部改名；读侧 7 文件兼容链就位（三态实测：新名优先/旧名回退/默认）；内部通道零改动；新进程端到端通过（注入/环境信息段/命令回归）
> 修订 v2（同日，用户决策）：撤除兼容别名、全面统一（含内部标识符/进程间通道/测试/plist 键）——本文 §2.2/§2.4 的兼容设计被 `2026-09-28-opensecurity-home-full-rename.md` 取代

## §1 背景与目标

**来源痛点**：
1. 评审指出两处缺陷：① 描述"数据根目录"只列内容不说用途（谁的数据、什么时候用）；② 名字 `DATA_DIR` 无归属、与 `$OPENCODE_ROOT`/`$TASK_DIR` 等并排看不出身份。
2. 调查结论：`DATA_DIR` 同时是跨子系统配置键（控制台 Bootstrap/launchd/插件 spawn env/MCP 通道/13+ 测试沙箱）——**硬全量改名 = 破坏配置接口 + 大量测试改造**。

**用户决策**：规范名用 **`OPENSECURITY_HOME`**（理由：`X_HOME` 惯例契合"运行时数据与工具的家"；避开与既有 `$OPENCODE_ROOT` 及同名仓库目录 `OpenSecurity` 的 ROOT 歧义）。

**目标**：① Agent 注入面与文档统一 `$OPENSECURITY_HOME`，描述回答"谁的数据、装什么、怎么用"；② 读侧 `新名 || 旧名 || 默认值` 兼容，零测试改动、零配置破坏；③ 内部进程通道维持 `DATA_DIR`（值传递语义，非对外接口）。

**明确不做**：改内部常量名（TS/Python 的 `DATA_DIR` 标识符保留）；改内部通道键（`buildSpawnEnv`/`mcp-manager`/launchd plist 写入键）；全量测试改造。

## §2 技术方案

### 2.1 插件（`plugins`，高风险类）

**constants.ts 读链**（27-31 行）：

```ts
// DATA_DIR 支持环境变量覆盖（与控制台 config.py 对等）。
// 规范名 OPENSECURITY_HOME；DATA_DIR 为兼容别名（旧配置/测试沙箱仍可用）。
// 默认 ~/bw-security-analysis（生产环境用户路径）。
// 测试可通过 OPENSECURITY_HOME=/tmp/xxx（或 DATA_DIR）隔离。
export const DATA_DIR =
  process.env.OPENSECURITY_HOME ||
  process.env.DATA_DIR ||
  join(homedir(), "bw-security-analysis");
```

**env section 文案**（`security-analysis.ts` 原 364 行，行数不变）：

```ts
    // OpenSecurity 主目录（运行时数据与工具所在; 与 shell.env 注入保持一致）
    envSection += `- OpenSecurity 主目录 ($OPENSECURITY_HOME): 完整路径是 \`${DATA_DIR}\`。它是本体系全部运行时数据与工具的存放根：workspace/（所有任务目录，$TASK_DIR 在其中；找历史任务目录从这里找）、db/knowledge/knowledge.db（记忆库）、logs/（运行日志）、bin/ 与 wordlists/（外部工具与字典）。命令和文档引用这些资源时一律拼 \`$OPENSECURITY_HOME/...\`，不要写死路径\n`;
```

**shell.env 注入**：`output.env.DATA_DIR = DATA_DIR;` → `output.env.OPENSECURITY_HOME = DATA_DIR;`（+上方注释）；debugLog 汇总行标签同步；1227 行注释 `$DATA_DIR/bin` → `$OPENSECURITY_HOME/bin`；启动日志 847 行标签改 `OPENSECURITY_HOME`。

### 2.2 读侧兼容（`新名 || 旧名 || 默认值`，各 1 行）

| # | 文件:行 | 现状 |
|---|---------|------|
| R1 | `control/backend/services/config_manager.py:71,194` | `DATA_DIR_ENV="DATA_DIR"`；读取点 `os.environ.get(b.DATA_DIR_ENV, b.DEFAULT_DATA_DIR)` → `DATA_DIR_ENV="OPENSECURITY_HOME"` + `DATA_DIR_COMPAT_ENV="DATA_DIR"` + 链式读取；类 docstring（4、64-67 行）同步提及兼容名 |
| R2 | `control/backend/services/detect_tools.py:42` | `os.environ.get("DATA_DIR") or ...` |
| R3 | `control/backend/services/detect_py_deps.py:35` | 同上 |
| R4 | `mcp-servers/control_url.py:38` | `os.environ.get("DATA_DIR", ...)` |
| R5 | `tools/clean_databases.py:19` | `os.environ.get("DATA_DIR") or ...` |
| R6 | `control/frontend/vite.config.ts:13` | `process.env.DATA_DIR ?? ...` |
| R7 | `control/backend/tests/test_e2e_real.py:34` | `os.environ.get("DATA_DIR", ...)` |

### 2.3 文档改名（9 文件 16 处，`$DATA_DIR` → `$OPENSECURITY_HOME`）

`agents/security-analysis-evolve.md:50`；`agents-rules/execution-discipline.md:16`；`commands/gui-interact-pc.md:7`、`commands/health-check.md:44,52`、`commands/analysis-attribution.md:15,31,54`（54 行措辞"数据根目录"→"数据主目录"）；`binary-analysis/knowledge-base/opencode-plugin-debugging.md:79,80`、`macos-process-crash-triage.md:84,89-91`（重启命令改 `OPENSECURITY_HOME="$OPENSECURITY_HOME"` 与 `$OPENSECURITY_HOME/...` 路径）、`pwn-methodology.md:325`；`security-analysis-evolve/knowledge-base/retrospective-methodology.md:64`。

### 2.4 内部通道声明（不改）

`plugins/lib/control-manager.ts`（`buildSpawnEnv` 注入 `DATA_DIR`）、`plugins/lib/mcp-manager.ts`（MCP 子进程 env）、`launchd_setup.py`（plist 键）维持旧键：**值为已解析数据目录的传递通道**，与对外配置名无关；控制台/MCP 读取侧均兼容新名（R1-R4）。

### 2.5 架构影响图

```
plugins/lib/constants.ts ──读链 新||旧||默认──→ DATA_DIR 常量（下游不变）
plugins/security-analysis.ts ──env section 行替换 + shell.env 注入 OPENSECURITY_HOME──→ 全部识别 agent
7 个读侧文件 ──各 +1 行兼容链──→ 控制台/工具/MCP（旧名保持可用）
9 个运行时文档 ──$DATA_DIR→$OPENSECURITY_HOME──→ 命令/规则/KB/evolve prompt
内部通道（control-manager/mcp-manager/launchd） ──DATA_DIR 键──→ 零改动
旧文档留痕：2026-09-27-cookie-jar 命令草稿 v4 同步；2026-09-28-data-dir 加修订注记
```

### 2.6 Phase 4.5 预算校验

| 项 | 变化 | 红线 |
|----|------|------|
| 5 个分析 agent 展开行数 | 不变（428/449/407/416/320；均为同行替换） | <450 ✓ |
| 系统提示环境信息段 | 行数不变（1 行替换） | — |
| evolve prompt | 行数不变 | <450 ✓ |

### 2.7 关键技术决策

- **规范名 `OPENSECURITY_HOME`**：与既有 `$OPENSECURITY_FLOW_ID` 同前缀；`X_HOME`（CARGO_HOME/RUSTUP_HOME 族）表明"数据与工具的家"；避开仓库同名目录带来的 `OPEN*_ROOT` 歧义。
- **兼容设计**：读侧链式（新||旧），测试/旧配置零改动；注入面与文档只出现新名（旧名静默别名）。
- **内部通道不动**：键名 `DATA_DIR` 仅在进程间传递已解析值，非对外接口；避免 13+ 测试与 plist 改造。
- **记录留痕**：命令文档（v4）保持"草稿==实现"；前一需求文档加修订注记指向本文件。

## §3 实现规范

### 3.1 实施步骤

**S1. 插件读链与注入（constants.ts + security-analysis.ts）**
- 文件：`plugins/lib/constants.ts`、`plugins/security-analysis.ts` | 预估：+5/-3 行 | 依赖：无
- 验证点：① `bun build` 两文件零错误；② 链式读取三态测试（新名优先/旧名回退/默认）；③ `security-analysis.ts` 内 `OPENSECURITY_HOME` 命中 5 处（env 行/注入行/启动日志/汇总日志/注释）+ `constants.ts` 读链就位

**S2. 读侧兼容（R1-R7）**
- 文件：7 个 | 预估：+8/-7 行 | 依赖：无
- 验证点：① 三文件 `py_compile` + 沙箱三态导入（OPENSECURITY_HOME only / DATA_DIR only / 缺省）；② `test_control.py` 回归（旧名沙箱路径仍隔离）；③ 残留扫描：这 7 文件旧名仅出现在兼容链中

**S3. 运行时文档改名（9 文件 16 处）**
- 文件：见 §2.3 | 预估：16 行替换 | 依赖：无
- 验证点：① 运行时目录（agents/commands/rules/KB）`$DATA_DIR` 零命中、`$OPENSECURITY_HOME` 命中数与清单一致；② 5 agent 展开行数复算不变；③ 旧标签"数据根目录 ($DATA_DIR)"零残留

**S4. 记录同步（命令文档 v4 + 前一需求文档注记）**
- 文件：`2026-09-27-cookie-jar-kb-and-attribution-command.md`（3 行 + v4 注）、`2026-09-28-data-dir-var-injection-and-hardcoded-path-cleanup.md`（修订注记） | 依赖：S3
- 验证点：① 命令草稿==命令文件（diff 零）；② 注记指向本文件

**S5. 端到端验证（新进程）**
- 文件：无（检查） | 依赖：S1-S4
- 验证点：① 新进程 evolve 会话：bash `echo $OPENSECURITY_HOME` 非空 + 环境信息段"OpenSecurity 主目录"行逐字吻合；② `/analysis-attribution` 命令回归产出完整报告；③ 环境信息段只列新名（无 `$DATA_DIR` 行）

**S6. 全仓复扫与收尾**
- 文件：需求/进度文档、`docs/contributing/add-new-agent.md` 注记更新（"数据根目录被 `DATA_DIR` 覆盖时…" → "数据主目录被 `OPENSECURITY_HOME`/兼容名 `DATA_DIR` 覆盖时…"） | 依赖：S1-S5
- 验证点：① 全仓 `\$DATA_DIR` 仅剩记录与兼容链/内部通道（逐类清单）；② `bw-security-analysis` 字面量维持上轮例外态；③ 进度 as-built 完整

### 3.2 编码规则

- 读侧统一 `新名 or 旧名 or 默认` 形态（Python）/`??` 链（TS）
- 注入面与运行时文档只写新名；旧名只出现在兼容代码与记录
- 不动内部通道键；不动既有测试

## §4 验收标准

**功能验收**：`$OPENSECURITY_HOME` 在 env section 展示且描述可读（归属/内容/用法三要素）；shell.env 注入新名；7 读侧文件兼容链就位；13 处文档改名完成；命令回归通过。
**回归验收**：5 agent 展开行数不变；占位符 7×5；`test_control.py` 通过（旧名沙箱零改动）；内部通道零改动（control-manager/mcp-manager/launchd 未触碰）；插件/命令语法零错误。
**架构验收**：改动落位 `plugins/`、`control/backend/services/`、`mcp-servers/`、`tools/`、`commands/`、`agents-rules/`、方向 `knowledge-base/`；记录留痕完整。

## §5 与现有需求文档的关系

- **承接**：`2026-09-28-data-dir-var-injection-and-hardcoded-path-cleanup.md`（该文的注入面与文档引用被本文件取代；其"硬编码清理"结论仍有效）。
- **同步**：`2026-09-27-cookie-jar-kb-and-attribution-command.md` v4（命令草稿改名）。
- **并行**：无交集。
- **范围外观察**：若未来要将内部通道键也升级为 `OPENSECURITY_HOME`，需连带改造 13+ 测试与 launchd plist（本次明确不做）。
