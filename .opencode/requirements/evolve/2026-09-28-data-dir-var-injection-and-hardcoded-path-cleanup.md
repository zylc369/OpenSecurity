# 2026-09-28 数据根目录变量化（$DATA_DIR 注入）与硬编码路径清理

> 状态：已实施（Phase 6 审计通过）| 入口：用户指令（`~/bw-security-analysis/` 不得直接出现在运行时文档；应像 `$TASK_DIR` 一样注入；全仓同类一次性改掉）
> 审计依据：全仓 `grep -rn 'bw-security-analysis'`（排除 .git）→ 按"运行时文档 / 插件代码 / 脚本工具 / 控制台代码 / 权限配置 / 测试夹具 / 人类文档与历史记录"七类分拣
> 关联：`2026-09-27-cookie-jar-kb-and-attribution-command.md`（其命令草稿随机更新，v3：路径改 `$DATA_DIR`）
> 实施进度与 as-built：`progress-2026-09-28-data-dir-var-injection.md`
> as-built：23 处替换全落地；插件注入经新进程端到端验证（bash `$DATA_DIR` + 环境信息段行）；命令回归产出完整报告；复扫仅剩 §2.4 例外清单所列
> 修订 v2（命名升级）：对外变量名改为 `$OPENSECURITY_HOME`（兼容读旧名 `DATA_DIR`）；本文所述 `$DATA_DIR` 注入面与文档引用被 `2026-09-28-opensecurity-home-var-rename.md` 取代
> 修订 v3：兼容别名亦已撤除——全面统一（含内部标识符/通道/测试），见 `2026-09-28-opensecurity-home-full-rename.md`

## §1 背景与目标

**来源痛点**：
1. `commands/analysis-attribution.md` 直接写入 `~/bw-security-analysis/workspace/` 与 `~/bw-security-analysis/db/knowledge/knowledge.db`——该路径可被 `DATA_DIR` 环境变量覆盖（TS `constants.ts`、Python `config_manager` 双侧均已支持），写死值在覆盖场景/异构机器上失效。
2. 全仓同类分拣结果：**应改 23 处**（运行时文档 11 处 + 退役机制同批 3 处 + 插件代码 3 处 + 脚本/控制台代码 6 处）；**例外 7 类**（见 §2.4，含完整残余清单）。
3. 机制结论：`$TASK_DIR`/`$ROOT_TASK_DIR`/`$WORDLISTS_DIR` 已有"env section 展示 + shell.env 注入"先例；`$DATA_DIR` 常量已存在但**未注入 agent env**，导致文档无法引用。

**目标**：① 插件 `buildEnvSection` 展示 `$DATA_DIR`、`shell.env` 注入 `DATA_DIR`；② 全部运行时文档改用 `$DATA_DIR/...`；③ 配套代码的硬编码改为 env 优先（与现代常量）或修正；④ 例外项写明理由留档。

**明确不做**：改权限 frontmatter 模式（opencode 静态匹配不支持变量，vendor 证据 `permission/index.ts:179-182` 仅展开 `~`/`$HOME`）；改人类文档/历史记录的默认值说明；改测试夹具的刻意真实路径；改二进制产物。

## §2 技术方案

### 2.1 插件注入（`plugins/security-analysis.ts`，高风险类）

**buildEnvSection**（`$SHARED_DIR` 行后 +1 行）：

```ts
    // 数据根目录（workspace/db/logs/bin/wordlists 共同根; 与 shell.env 注入保持一致）
    envSection += `- 数据根目录 ($DATA_DIR): 完整路径是 \`${DATA_DIR}\`。内含 workspace/（任务目录所在）、db/knowledge/（记忆库 SQLite）、logs/（运行日志）、bin/（外部工具）、wordlists/。引用这些资源时一律写 \`$DATA_DIR/xxx\`，不要写死路径\n`;
```

**shell.env**（`output.env.SHARED_DIR = SHARED_DIR;` 后 +1 行，无条件注入——路径约定恒定，同 `$WORDLISTS_DIR`）：

```ts
        output.env.DATA_DIR = DATA_DIR;
```

**debugLog**（shell.env 汇总行）+` DATA_DIR=${DATA_DIR}`。

`DATA_DIR` 已在文件 import 列表中（security-analysis.ts:9），无需新增 import。

### 2.2 运行时文档替换清单（11 处）

| # | 文件:行 | 原文（字面量） | 改为 |
|---|---------|---------------|------|
| 1 | `commands/analysis-attribution.md:15` | `取 `~/bw-security-analysis/workspace/` 最新任务目录` | ``取 `$DATA_DIR/workspace/` 最新任务目录`` |
| 2 | `commands/analysis-attribution.md:31` | ``直读 `~/bw-security-analysis/db/knowledge/knowledge.db` `` | ``直读 `$DATA_DIR/db/knowledge/knowledge.db` `` |
| 3 | `commands/analysis-attribution.md:54` | ``位于项目外（`~/bw-security-analysis/`）`` | ``位于数据根目录（`$DATA_DIR`，项目外）——该变量由 Plugin 注入（见环境信息段）`` |
| 4 | `commands/health-check.md:44` | ``socket = `~/bw-security-analysis/opensecurity-control.sock` `` | ``socket = `$DATA_DIR/opensecurity-control.sock` `` |
| 5 | `commands/health-check.md:52` | ``（`~/bw-security-analysis/logs/<agent>.log` `` | ``（`$DATA_DIR/logs/<agent>.log` `` |
| 6 | `commands/gui-interact-pc.md:7` | ``创建 `~/bw-security-analysis/workspace/gui_<timestamp>/` `` | ``创建 `$DATA_DIR/workspace/gui_<timestamp>/` `` |
| 7 | `agents-rules/output-format.md:14` | `- 任务目录: ~/bw-security-analysis/workspace/<task_id>/` | `- 任务目录: $TASK_DIR` |
| 8 | `agents-rules/execution-discipline.md:16` | ``workspace 根目录（`~/bw-security-analysis/workspace/`）`` | ``workspace 根目录（`$DATA_DIR/workspace/`）`` |
| 9 | `agents/security-analysis-evolve.md:50` | ``（默认 `~/bw-security-analysis/db/knowledge/knowledge.db`）`` | ``（`$DATA_DIR/db/knowledge/knowledge.db`）`` |
| 10 | `security-analysis-evolve/knowledge-base/retrospective-methodology.md:64` | ``（默认 `~/bw-security-analysis/db/knowledge/knowledge.db`）`` | ``（`$DATA_DIR/db/knowledge/knowledge.db`）`` |
| 11 | `binary-analysis/knowledge-base/pwn-methodology.md:325` | `不在 ~/bw-security-analysis/bin` | `不在 $DATA_DIR/bin` |

**同批修正（退役机制残留，规则 8 §0.6）**：
- `binary-analysis/knowledge-base/opencode-plugin-debugging.md:79`：端口文件 `.opencode-control.port` 已随 IPC 改造退役 → 改为（冒烟命令已实测可用，HTTP 200 status=ok）：

```
1. 控制台是否运行？
   → IPC 通道: macOS/Linux 为 $DATA_DIR/opensecurity-control.sock；Windows 为 \\.\pipe\opensecurity-control-482964
   → 冒烟: curl --unix-socket "$DATA_DIR/opensecurity-control.sock" http://localhost/health 应返回 200（status=ok）
```

- `binary-analysis/knowledge-base/macos-process-crash-triage.md:84`：日志三角 `` `~/bw-security-analysis/logs/{control.log, ...}` `` → `` `$DATA_DIR/logs/{control.log, ...}` ``
- `binary-analysis/knowledge-base/macos-process-crash-triage.md:89`：重启命令的 `$HOME/bw-security-analysis` / `<DATA_DIR>` 混用 → 统一：

```bash
cd <项目根> && nohup env OPENCODE_ROOT=<项目 .opencode 路径> \
  DATA_DIR="$DATA_DIR" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  "$DATA_DIR/.venv/bin/python" "$OPENCODE_ROOT/control/backend/server.py" \
  >> "$DATA_DIR/logs/control-stdout.log" 2>> "$DATA_DIR/logs/control-stderr.log" & disown
```

### 2.3 配套代码修正（3 处 + 插件消息 2 处）

| # | 文件 | 现状 | 改为 |
|---|------|------|------|
| C1 | `plugins/lib/env-check.ts:111` | 消息内字面量 `~/bw-security-analysis/logs/plugin_debug.log` | `${DEFAULT_LOG}`（新增 import 自 `./constants`） |
| C2 | `plugins/lib/env-check.ts:228` | 消息内字面量 `~/bw-security-analysis/logs/` | `${LOGS_DIR}` |
| C3 | `plugins/security-analysis.ts:1224` | 注释 `+ ~/bw-security-analysis/bin` | `+ $DATA_DIR/bin` |
| C4 | `tools/clean_databases.py:19` | `Path.home() / "bw-security-analysis" / ...` | `DATA_DIR = os.environ.get("DATA_DIR") or str(Path.home() / "bw-security-analysis")`；`KNOWLEDGE_DB = Path(DATA_DIR) / "db" / "knowledge" / "knowledge.db"` |
| C5 | `control/backend/services/detect_tools.py:42` | `CACHE_DIR = os.path.expanduser("~/bw-security-analysis")` | `CACHE_DIR = os.environ.get("DATA_DIR") or os.path.expanduser("~/bw-security-analysis")`（env 优先，缺省回退不变） |
| C6 | `control/backend/services/detect_py_deps.py:35` | 同上 | 同上 |
| C7 | `control/backend/services/detect_tools.py:1206-1221` | wrapper 模板 `WL_MSYS="$HOME/bw-security-analysis/wordlists"`；配套死代码行 `_rw_add envwl "$ToolsEnv.WORDLISTS_DIR" ...`（`ToolsEnv` 非真实 env 变量，空转） | `WL_MSYS="{WL_DIR}"` + 生成处 `.replace("{WL_DIR}", ToolsEnv.WORDLISTS_DIR)`；删除死代码 `envwl` 行并更正上方多形态匹配注释 |
| C8 | `control/backend/services/detect_tools.py:12` | docstring `自动安装产物落 ~/bw-security-analysis/bin` | `自动安装产物落 $DATA_DIR/bin` |

### 2.4 例外清单（不改 + 理由）

| 类别 | 位置 | 理由 |
|------|------|------|
| 权限 frontmatter | `agents/{web,binary,mobile,ai-security,crypto}-analysis.md`、`fresh-eyes/searcher/memorist/security-analysis-evolve.md` 的 `external_directory: ~/bw-security-analysis/**: allow` | opencode 权限 pattern 静态匹配，仅展开 `~/`、`$HOME`（vendor `permission/index.ts:179-182`），不支持自定义变量；DATA_DIR 覆盖时该目录降级为交互放行，功能不破坏 |
| 默认值定义（单一来源） | `plugins/lib/constants.ts:30-31`、`control/backend/services/config_manager.py:75` | 两侧各自的规范默认值定义点（env 可覆盖）；改默认值属另一决策 |
| 测试夹具 | `control/backend/tests/test_integration.py:33`（REAL_VENV_DIR 刻意指向真实 venv）、`plugins/tests/test-control.ts:27-29`（防误删真实数据的守卫） | 刻意为之的测试语义 |
| 已合规（env 优先） | `mcp-servers/control_url.py:38`、`control/frontend/vite.config.ts:13`、`control/backend/tests/test_e2e_real.py:34`、本轮改造后的 `tools/clean_databases.py:19` 与 `detect_tools/detect_py_deps` 的 `or <默认值>` 回退行 | 已是 `os.environ.get("DATA_DIR") / process.env.DATA_DIR ??` 形态（含缺省回退默认值） |
| 标签非路径 | `config_manager.py:301` `# bw-security-analysis 环境变量配置`、`test_control.py:415` 断言 | 是配置文件标题标签，不是文件系统路径 |
| 外围测试/评估脚本 | `test/**`（knowledge/mcp_events/control 等约 15 文件，各 1 处） | 对本机真实部署做集成/质量评估的脚本（DB/venv 指向部署实例），非 agent 运行时；如需沙箱感知可另行批量处理 |
| 人类文档与历史记录 | `README*.md`、`CONTRIBUTING*.md`、`.opencode/binary-analysis/README.md`、`.github/**`、`docs/**`、`requirements/evolve/**`（含本需求文档）、`control/docker/toolbox-design.md`、`plugins/tests/win-pipe-probe.ts` 等 | 面向人类的默认值说明（必要时附 `DATA_DIR` 覆盖方法）与历史记录；非 agent 运行时指令 |

**加分项（例外说明补丁）**：`docs/contributing/add-new-agent.md` 权限模板处 +1 行注记，说明权限 pattern 不支持变量、DATA_DIR 覆盖时需手动同步。

### 2.5 架构影响图

```
plugins/security-analysis.ts ──buildEnvSection +1 行 / shell.env 注入 DATA_DIR──→ 全部识别 agent 的系统提示与 bash env
plugins/lib/env-check.ts ──2 处消息改常量引用──→ 自身（无行为变更，仅文案）
agents-rules/{output-format,execution-discipline}.md ──片段展开──→ 各消费 agent（行数不变）
commands/{analysis-attribution,health-check,gui-interact-pc}.md ──用户按需触发──→ 自身
agents/security-analysis-evolve.md + evolve KB + binary KB ×3 ──文本替换──→ 自身
control/backend/services/{detect_tools,detect_py_deps}.py + tools/clean_databases.py ──CACHE_DIR/env 优先──→ 控制台/工具链（缺省行为不变）
Plugin 其余机制零改动（文件不变、展开机制不变）
```

### 2.6 Phase 4.5 预算校验

| 项 | 变化 | 红线 |
|----|------|------|
| 5 个分析 agent 展开行数 | 不变（428/449/407/416/320；output-format/execution-discipline 为同行替换） | <450 ✓ |
| 系统提示环境信息段 | +1 行（`$DATA_DIR` 行，动态注入，非 prompt 文件） | — |
| evolve prompt 行数 | 不变（1 行替换） | <450 ✓ |

### 2.7 关键技术决策

- **变量选 `$DATA_DIR` 而非新造名**：TS/Python 两侧已是规范名（env 可覆盖），零新增概念；`workspace/`、`db/` 子路径由文档拼接。
- **注入位置对齐 `$WORDLISTS_DIR` 先例**（env section 展示 + shell.env 无条件注入）。
- **console Python 侧也做 env 优先**：`buildSpawnEnv` 已向子进程注入 `DATA_DIR`（沙箱/覆盖一致性），`detect_tools/detect_py_deps` 的模块级常量此前忽略它，属实现不一致；缺省回退保持现状。
- **wrapper 用生成期替换而非运行时 `$HOME`**：`{WL_DIR}` 替换值来自 `ToolsEnv.WORDLISTS_DIR`（已 env 优先），随实际数据目录走。
- **权限 frontmatter 例外留档**（技术限制 + 降级行为说明），并在 `add-new-agent.md` 补注记。

## §3 实现规范

### 3.1 实施步骤

**S1. 插件注入（security-analysis.ts）**
- 文件：`plugins/security-analysis.ts` | 预估：+3 行 / 1 行注释替换 | 依赖：无
- 验证点：① `grep '$DATA_DIR' plugins/security-analysis.ts` 命中 envSection 与 shell.env；② `grep 'output.env.DATA_DIR'` 命中；③ `bun build plugins/security-analysis.ts --target=bun --outfile=<tmp>` 零错误；④ debugLog 含 DATA_DIR

**S2. 插件消息与常量（env-check.ts）**
- 文件：`plugins/lib/env-check.ts` | 预估：+1 import / 2 行替换 | 依赖：无
- 验证点：① import 行存在且与 constants 导出一致；② 2 处字面量零残留；③ bun build 零错误

**S3. 运行时文档批次一（commands）**
- 文件：`commands/analysis-attribution.md`、`commands/health-check.md`、`commands/gui-interact-pc.md` | 预估：6 行替换 | 依赖：无
- 验证点：① `grep -rn 'bw-security-analysis' commands/` = 0；② 三文件行数不变；③ 命令草稿（旧需求文档 §2.3）在 S8 同步后 diff 为零

**S4. 运行时文档批次二（rules + evolve prompt）**
- 文件：`agents-rules/output-format.md`、`agents-rules/execution-discipline.md`、`agents/security-analysis-evolve.md` | 预估：3 行替换 | 依赖：无
- 验证点：① 3 文件字面量零残留；② 5 agent 展开行数复算不变；③ evolve 展开行数不变

**S5. 知识库批次（含退役机制修正）**
- 文件：`binary-analysis/knowledge-base/{opencode-plugin-debugging,macos-process-crash-triage,pwn-methodology}.md`、`security-analysis-evolve/knowledge-base/retrospective-methodology.md` | 预估：4 文件 6 处 | 依赖：无
- 验证点：① 四文件字面量零残留；② IPC 冒烟命令先实测通过再落盘（`curl --unix-socket .../opensecurity-control.sock http://localhost/health`）；③ 引号/`$DATA_DIR` 形态通读

**S6. 代码批次（tools + console + wrapper）**
- 文件：`tools/clean_databases.py`、`control/backend/services/detect_tools.py`、`control/backend/services/detect_py_deps.py` | 预估：+8/-3 行 | 依赖：无
- 验证点：① 三文件 `py_compile` 通过，仅剩 env 优先回退默认值表达式（非裸硬编码）；② `DATA_DIR=/tmp/ddtest` 导入验证：`ToolsEnv.CACHE_DIR`、`detect_py_deps.CACHE_DIR`、`KNOWLEDGE_DB` 均指向沙箱；不设 DATA_DIR 时回退默认；③ wrapper 模板渲染：`{WL_DIR}` 无残留、`WL_MSYS` 为实际路径、`envwl` 死代码已删；④ 控制台测试 `tests/test_control.py`：87 passed（1 个 collection error 为既有问题，见 §5）

**S7. 端到端验证（插件热加载 + 命令回归）**
- 文件：无（检查） | 依赖：S1-S6
- 要点：嵌套 `opencode run`（新进程加载新插件）→ 要求输出版权 env section 的 `$DATA_DIR` 行 + `bash echo $DATA_DIR`；再跑一次 `/analysis-attribution <task-dir>` 确认命令在新变量形态下可用
- 验证点：① env section 含"数据根目录 ($DATA_DIR)"；② bash `$DATA_DIR` 非空且与常量一致；③ 命令产出报告含新路径引用（原文残留 0）；④ plugin 无加载错误（检查嵌套会话输出/日志）

**S8. 全仓复扫与文档同步**
- 文件：新需求文档、旧需求文档（v3 修订）、progress、`docs/contributing/add-new-agent.md`（注记 +1 行） | 依赖：S1-S7
- 验证点：① 全仓复扫 `bw-security-analysis`：运行时/插件/脚本类别 0 残留，其余仅剩 §2.4 例外；② 旧文档命令草稿 == 命令文件（diff 零）；③ progress as-built 完整

### 3.2 编码规则

- 文档引用统一 `$DATA_DIR/...`；无引号场景与既有 `$TASK_DIR` 风格一致
- Python env 读取统一 `os.environ.get("DATA_DIR") or <fallback>`（勿用 `os.environ["DATA_DIR"]` 直取）
- 不改任何默认值（`~/bw-security-analysis` 仅允许存在于"默认值定义/人类文档/历史记录/测试夹具"）

## §4 验收标准

**功能验收**：`$DATA_DIR` 在 env section 展示 + shell.env 注入；23 处替换全部落地（明细 §2.2/§2.3）；IPC 冒烟命令可用；`DATA_DIR` 覆盖时三条 Python 路径与 wrapper 均跟随。
**回归验收**：5 agent 展开行数不变；占位符 7×5 不变；插件/命令语法检查零错误；控制台测试子集通过；旧命令文档草稿与实现一致；无任何 `PYTHON_CMD`/`WORDLISTS_DIR` 等既有注入行为变更。
**架构验收**：改动落位 `plugins/`、`commands/`、`agents-rules/`、`agents/`、方向 `knowledge-base/`、`control/backend/services/`、`tools/`；零新文件归属争议；例外清单留档。

## §5 与现有需求文档的关系

- **承接**：用户 2026-09-28 指令（源于 `2026-09-27-cookie-jar-kb-and-attribution-command.md` 交付物的路径硬编码问题）。
- **同步更新**：该文档 §2.3 命令草稿（v3：`$DATA_DIR` 替换 + 权限注记措辞）与 header 修订记录；保持"草稿 == 已实现"核验方法。
- **并行**：`2026-09-27-gopher-ssrf-tooling-and-knowledge.md` 等无交集。
- **范围外观察**：① 人类文档（README/docs）与权限 frontmatter 的 DATA_DIR 覆盖体验（覆盖时需手动补权限 pattern）——如需治理可另立需求；② 既有测试瑕疵：`control/backend/tests/test_control.py:75` 助手函数 `def test(name)` 被 pytest 误收集为用例（fixture 'name' not found，恒报 1 collection error），与本次改动无关，建议后续改名为非 `test` 前缀。
