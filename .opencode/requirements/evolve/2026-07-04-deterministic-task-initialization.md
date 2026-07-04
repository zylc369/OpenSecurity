# 需求文档: 任务初始化确定化（从概率执行到 Plugin 强制执行）

## §1 背景与目标

**来源**: 2026-07-04 与用户讨论（`docs/进化/进化-通过程序进行任务初始化.md`）。

当前任务初始化（创建任务目录 + 环境检测）是**概率性执行**——靠 AI 读 `agents-rules/task-initialization.md` 片段 + Read `knowledge-base/task-initialization.md` 后"自觉"执行。AI 偶尔跳过 → `$TASK_DIR` 为空 → 后续所有依赖它的规则失效。

**目标**:
1. 把任务初始化的两步（`create_task_dir.py` + `detect_env.py`）从"AI 自觉执行"改为"Plugin 在 `chat.message` hook 中确定性执行"
2. 判定方式：`getTaskDir(sessionID)` 返回 null = 初次执行 → 自动初始化；非 null = 已初始化 → 跳过
3. 合并 `detect_env.py` 的两次调用（`--check-preinstall` + `--output`）为一次，返回良好的错误信息
4. 删除 `agents-rules/task-initialization.md` + `knowledge-base/task-initialization.md` 两个文档（共 88 行），以及 5 个 agent prompt 中的 `{{buwai-rule:task-initialization}}` 片段引用
5. `--max-duration` 参数：默认 6 小时由 Plugin 自动初始化；用户口头指定时长时，AI 调用新增的 `update_max_duration.py` 脚本更新（方案 C）

**预期收益**（四维度量）:
- **上下文**: 5 个 agent 各移除 21 行片段引用 + 不再需要 Read 67 行知识库 = 每会话省 ~88 行
- **轮次**: AI 不再需要"先执行初始化 → 反馈 → 再分析"，每任务省 1-2 轮
- **速度**: Plugin 同步执行 ~3-5 秒，替代 AI 读文档+执行两步的 30-60 秒
- **准确度**: 消除"AI 偶尔跳过初始化"导致的 `$TASK_DIR` 为空、`env.json` 缺失类故障

**不兼容声明**: 初始化行为从"AI 执行"变为"Plugin 执行"。现有 agent prompt 中的"阶段 0"段落和两个初始化文档直接删除，不做迁移。Coordinator 子 session 行为维持现状（共用父 TASK_DIR，不自动创建）。

## §2 技术方案

### 2.1 整体流程对比

**改进前**（概率执行）:
```
chat.message → checkPreinstall (仅预装检查)
AI 读 prompt 片段 → AI 跑 create_task_dir.py → AI 跑 detect_env.py --output → AI 开始分析
```

**改进后**（确定执行）:
```
chat.message → checkEnvironment:
  1. ensurePythonCmd (现有)
  2. ensureTaskDir (新增, 仅根 session) → getTaskDir 为空时 spawn create_task_dir.py
  3. runDetectEnv (合并) → spawn detect_env.py --agent <name> --output <task_dir>/env.json
  任一步失败 → reportErrorAndAbort (现有模式复用)
AI 直接开始分析 (不再有"阶段 0")
```

### 2.2 Plugin checkEnvironment 重构

`checkEnvironment(agent, sessionID)` 重构为三步序列：

```ts
async function checkEnvironment(agent, sessionID): Promise<EnvironmentCheckResult> {
  // Step 1: PythonCmd 就绪（现有逻辑）
  const pythonCmd = getPythonCmd();
  if (!pythonCmd) return { ready: false, message: getCondaInstallHint() };

  // Step 2: 任务目录初始化（新增）— 仅根 session
  const session = ctx.sessionManager.get(sessionID);
  const isRootSession = !session?.parentSessionID;
  if (isRootSession) {
    const taskDir = getTaskDir(sessionID);
    if (!taskDir) {
      const r = await ensureTaskDir(pythonCmd, sessionID);
      if (!r.ready) return r;
    }
  }

  // Step 3: 环境检测（合并 preinstall + 全量）
  return await runDetectEnv(agent, pythonCmd, sessionID);
}
```

**新增函数**:

```ts
// 确保 TASK_DIR 存在（根 session 首次消息时调用）
async function ensureTaskDir(pythonCmd, sessionID): Promise<EnvironmentCheckResult> {
  const script = join(SHARED_DIR, "scripts", "create_task_dir.py");
  const r = await runProcess(pythonCmd, [script], {
    timeout: 10000,
    env: { OPENCODE_ROOT, SESSION_ID: sessionID },  // create_task_dir.py 从 SESSION_ID 读
  });
  debugLog(`ensureTaskDir: status=${r.status} stdout=${(r.stdout||"").trim()}`, sessionID);
  if (r.error || r.status !== 0) {
    return { ready: false, message: `[任务目录创建失败] ${r.error?.message || r.stderr || "退出码 " + r.status}` };
  }
  // 映射文件已写入，getTaskDir 现在能读到（null 不缓存，无需 clear）
  const taskDir = getTaskDir(sessionID);
  if (!taskDir) {
    return { ready: false, message: `[任务目录创建失败] create_task_dir.py 执行完成但映射未注册` };
  }
  return { ready: true, message: "" };
}

// 合并的环境检测（替代 checkPreinstall）
async function runDetectEnv(agent, pythonCmd, sessionID): Promise<EnvironmentCheckResult> {
  const detectEnv = join(SHARED_DIR, "scripts", "detect_env.py");
  const taskDir = getTaskDir(sessionID);
  const args = [detectEnv, "--agent", agent];
  if (taskDir) args.push("--output", join(taskDir, "env.json"));
  const childEnv: Record<string, string> = { OPENCODE_ROOT };
  const condaCmd = getCondaCmd();
  if (condaCmd) childEnv.CONDA_CMD = condaCmd;
  const r = await runProcess(pythonCmd, args, { timeout: 30000, env: childEnv });
  debugLog(`runDetectEnv: agent=${agent} status=${r.status} ...`, sessionID);
  if (r.error) return { ready: false, message: `[环境检测失败] ${r.error.message}` };
  let result: { success?: boolean; errors?: any[] };
  try { result = JSON.parse(r.stdout); }
  catch (e) { return { ready: false, message: `[环境检测失败] 输出非合法 JSON: ${(e as Error).message}` }; }
  if (result.success !== true) {
    const errs = Array.isArray(result.errors) ? result.errors : [];
    const hints = errs.map(e => typeof e === "string" ? e : (e.install_hint || e.package || "")).filter(Boolean).join("\n");
    return { ready: false, message: hints ? `[环境检测未通过]\n${hints}` : "[环境检测未通过] 未知错误" };
  }
  return { ready: true, message: "" };
}
```

**删除**: `checkPreinstall` 函数（逻辑并入 `runDetectEnv`）。

**Coordinator 子 session 处理**: `ensureTaskDir` 只对根 session（`!parentSessionID`）触发。子 session 共用父 TASK_DIR（由 Coordinator AI 通过 prompt 文字传递），Plugin 不干预——维持现状。

### 2.3 detect_env.py 合并 preinstall 检查

**现状**: 两个独立模式
- `--check-preinstall <agent>`: 仅查 preinstall 依赖，输出 `{success, errors}`，不缓存
- 默认模式（`--output`/`--force`）: 全量检测（compiler/packages/ida_pro/tools），写 cache，不查 preinstall

**合并方案**: 默认模式新增 `--agent <name>` 参数，传了则在全量检测后额外跑 `_check_preinstall(agent)`，errors 合并。

```python
# main() 改造
parser.add_argument("--agent", metavar="AGENT", help="当前 agent 名，用于 preinstall 检查")
args = parser.parse_args()

# --check-preinstall 模式保留（向后兼容，Plugin 不再用）
if args.check_preinstall:
    result = _check_preinstall(args.check_preinstall)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return

# 默认模式（全量检测）
cached = _load_cache(force=args.force)
if cached and not args.force:
    result = {"success": True, "data": cached, "errors": []}
else:
    result = run_detection(skip_install=args.skip_install)

# 合并 preinstall 检查（新增）
if args.agent:
    preinstall_result = _check_preinstall(args.agent)
    if not preinstall_result["success"]:
        result["errors"].extend(preinstall_result["errors"])
        result["success"] = False
```

**success 语义**: `success = (全量 errors 为空) AND (--agent 传了时 preinstall errors 为空)`。

**缓存策略不变**: 全量检测仍 24h 缓存；preinstall 不缓存（每次实时查）。命中缓存时 data 用缓存，但 preinstall 仍实时跑。

**错误信息质量**: `errors` 数组每项含 `install_hint`（preinstall 缺失）或字符串（全量检测失败），Plugin 的 `runDetectEnv` 统一格式化为给用户看的消息。

### 2.4 create_task_dir.py 幂等化

**问题**: Coordinator 场景下，Plugin 的 `ensureTaskDir` 和 Coordinator agent prompt 的命令可能双重触发。现有 `create()` 每次都新建目录 + 覆盖映射 → 产生孤儿目录 + TASK_DIR 漂移。

**修复**: `create()` 开头检查 sessionID 是否已有映射，有则直接返回已有目录。

```python
def create(max_duration_hours=DEFAULT_MAX_DURATION_HOURS):
    session_id = os.environ.get("SESSION_ID", "")
    # 幂等：sessionID 已有映射则直接返回已有目录
    if session_id:
        mapping_file = os.path.join(TASK_SESSIONS, f"{session_id}.json")
        if os.path.isfile(mapping_file):
            with open(mapping_file) as f:
                existing = json.load(f)
                existing_dir = existing.get("task_dir", "")
                if existing_dir and os.path.isdir(existing_dir):
                    print(existing_dir)
                    return
    # 首次创建（现有逻辑）
    ...
```

这也修复了 `knowledge-base/task-initialization.md` L21 声称"幂等"但代码不幂有的文档/代码矛盾。

### 2.5 update_max_duration.py 新增

**场景**: 用户口头指定分析时长（如"分析 2 小时"），AI 识别后调用此脚本更新 `.persistence.json`。

**位置**: `$SHARED_DIR/scripts/update_max_duration.py`（通用层，所有 agent 可用）。

**接口**:
```
$PYTHON_CMD "$SHARED_DIR/scripts/update_max_duration.py" --max-duration 2
```
- `--max-duration`: 浮点数，单位小时，范围 (0, 24]，超出范围钳位到默认 6
- 从 `$TASK_DIR` 环境变量读任务目录（Plugin shell.env 已注入）
- 读 `$TASK_DIR/.persistence.json`，更新 `max_duration_hours` 字段，写回
- `.persistence.json` 不存在时报错退出（说明 Plugin 初始化未完成）

**agent prompt 提示**: 5 个单 agent prompt 在删除"阶段 0"后，补充一行极简说明（见 §3.1 步骤 6）。

### 2.6 文档/片段清理

| 删除项 | 原因 |
|--------|------|
| `agents-rules/task-initialization.md` | 片段不再被引用，逻辑移入 Plugin |
| `binary-analysis/knowledge-base/task-initialization.md` | 逻辑移入 Plugin，不再需要 AI Read |
| 5 个 agent 的 `{{buwai-rule:task-initialization}}` 引用 + "阶段 0" 段落 | Plugin 已自动执行 |
| Coordinator 的 "0.1 创建父任务目录" 命令 | Plugin ensureTaskDir 已自动创建 |

## §3 实现规范

### 改动范围表

| 文件 | 改动类型 | 影响级别 |
|------|---------|---------|
| `binary-analysis/scripts/create_task_dir.py` | 幂等化（开头加映射检查） | 低 |
| `binary-analysis/scripts/detect_env.py` | 新增 `--agent` 参数，默认模式合并 preinstall | 中（所有 agent 依赖） |
| `binary-analysis/scripts/update_max_duration.py` | 新建 | 低 |
| `plugins/security-analysis.ts` | 重构 checkEnvironment，删 checkPreinstall | 高（所有 agent 环境注入） |
| `agents/binary-analysis.md` | 删"阶段 0" + 补极简说明 | 中 |
| `agents/mobile-analysis.md` | 同上 | 中 |
| `agents/web-analysis.md` | 同上 | 中 |
| `agents/crypto-analysis.md` | 同上 | 中 |
| `agents/ai-security-analysis.md` | 同上 | 中 |
| `agents/security-coordinator.md` | 删"0.1 创建父任务目录" | 中 |
| `agents-rules/task-initialization.md` | 删除文件 | 低 |
| `binary-analysis/knowledge-base/task-initialization.md` | 删除文件 | 低 |

### §3.1 实施步骤拆分

**步骤 1. create_task_dir.py 幂等化**
- 文件: `binary-analysis/scripts/create_task_dir.py`
- 改动: `create()` 函数开头加 sessionID 映射检查（见 §2.4），已存在则 print 已有目录并 return
- 预估行数: ~12 行新增
- 验证点: `compile` 通过；设 `SESSION_ID=test123` 连跑两次，第二次输出与第一次相同，`.task_sessions/test123.json` 的 task_dir 不变
- 依赖: 无

**步骤 2. detect_env.py 合并 preinstall（新增 --agent 参数 + stdout 纯净化）**
- 文件: `binary-analysis/scripts/detect_env.py`
- 改动:
  - **stdout 纯净化（前置必做）**: 将 `run_detection()` 和 `main()` 中所有进度日志 `print("[*]/[+]/[!] ...")` 改为打到 stderr（`print(..., file=sys.stderr)`）。**原因**: 默认模式的 stdout 现混了进度日志和最终 JSON，Plugin 合并后需 `JSON.parse(stdout)`，混合输出会导致解析失败。`--check-preinstall` 模式已是纯 JSON（用 `_warn` 打 stderr），不受影响。stdout 最终只保留：`main()` 末尾的 `print(output_json)`（无 --output 时）或完全不输出（有 --output 时，JSON 写文件）
  - argparse 加 `--agent` 参数
  - `main()` 默认模式在全量检测后，若传了 `--agent` 则跑 `_check_preinstall(agent)` 合并 errors；`--check-preinstall` 模式保留不动（向后兼容）
- 预估行数: ~45 行修改（进度日志迁移 ~20 + --agent 逻辑 ~25）
- 验证点:
  - `compile` 通过
  - `detect_env.py --agent binary-analysis --force` 的 stdout 是**合法 JSON**（`python -c "import json,sys; json.load(sys.stdin)"` 能解析），进度日志只出现在 stderr
  - JSON 含 preinstall 结果（IDA 未配时 success=false + errors 含 install_hint）
  - `detect_env.py --check-preinstall binary-analysis` 仍正常（向后兼容）
- 依赖: 无

**步骤 3. update_max_duration.py 新增**
- 文件: `binary-analysis/scripts/update_max_duration.py`（新建）
- 改动: 从 `$TASK_DIR` 读 `.persistence.json`，更新 `max_duration_hours`；范围校验 (0,24]，超范围钳位 6；文件不存在时报错退出
- 预估行数: ~55 行
- 验证点: `compile` 通过；先跑 create_task_dir.py，再跑 `update_max_duration.py --max-duration 2`，确认 `.persistence.json` 的 `max_duration_hours` 变为 2.0
- 依赖: 无

**步骤 4. security-analysis.ts: checkEnvironment 重构**
- 文件: `plugins/security-analysis.ts`
- 改动:
  - 新增 `ensureTaskDir(pythonCmd, sessionID)` 函数（见 §2.2）
  - 新增 `runDetectEnv(agent, pythonCmd, sessionID)` 函数（见 §2.2）
  - 重构 `checkEnvironment`: ensurePythonCmd → ensureTaskDir（仅根 session）→ runDetectEnv
  - 删除 `checkPreinstall` 函数（L264-316，逻辑并入 runDetectEnv）
- 预估行数: ~85 行修改（删 ~50 + 加 ~80，净增 ~30）
- 验证点: `node --check security-analysis.ts` 通过；`rg "checkPreinstall" plugins/` 返回 0
- 依赖: 步骤 2（detect_env.py --agent 接口就绪）

**步骤 5. 删除初始化文档 + 片段文件**
- 文件:
  - 删除 `agents-rules/task-initialization.md`
  - 删除 `binary-analysis/knowledge-base/task-initialization.md`
- 验证点: 两个文件不存在
- 依赖: 无（与步骤 6 同时进行更安全，避免中间态 agent 引用不存在的片段）

**步骤 6. agent prompt 清理（6 个文件）**
- 文件: `binary-analysis.md`、`mobile-analysis.md`、`web-analysis.md`、`crypto-analysis.md`、`ai-security-analysis.md`、`security-coordinator.md`
- 改动:
  - 5 个单 agent: 删除 `## 阶段 0：任务初始化（强制）` 整段（含 `{{buwai-rule:task-initialization}}` 和前后的 `---` 分隔线）；在"分析执行框架"标题下补充 1-2 行极简说明：
    ```
    > 任务目录（$TASK_DIR）和环境检测由 Plugin 自动完成，开箱即用。用户口头指定分析时长时，执行：
    > `$PYTHON_CMD "$SHARED_DIR/scripts/update_max_duration.py" --max-duration <小时数>`
    ```
  - Coordinator: 删除 "0.1 创建父任务目录" 小节（Plugin ensureTaskDir 已自动创建）；保留 "0.2 变量初始化" 作为变量说明
- 预估行数: ~35 行修改（分散在 6 个文件，每文件删 ~5-8 行 + 加 ~2 行）
- 验证点: `rg "buwai-rule:task-initialization" .opencode/agents/` 返回 0；各 agent prompt 展开后 < 450 行；Coordinator prompt 不再含 `create_task_dir.py` 命令
- 依赖: 步骤 4（Plugin 已自动初始化）+ 步骤 5（片段文件已删）

**步骤 7. 端到端验证**
- 验证点:
  1. **新 session 首次消息**: opencode 启动新 session 发消息 → 检查 Plugin 日志含 `ensureTaskDir` + `runDetectEnv` 调用 → `~/bw-security-analysis/workspace/` 下生成新 TASK_DIR + `.task_sessions/<sid>.json` 映射 + `$TASK_DIR/env.json`
  2. **不重复初始化**: 同一 session 再发消息 → Plugin 日志显示 `getTaskDir` 命中、跳过 ensureTaskDir
  3. **幂等性**: 手动跑两次 `SESSION_ID=<sid> create_task_dir.py`，第二次输出与第一次相同
  4. **Coordinator 子 session**: Coordinator 父 session 自动初始化；子 session 不触发 ensureTaskDir（Plugin 日志显示 parentSessionID 非空，跳过）
  5. **detect_env 合并**: `detect_env.py --agent mobile-analysis` 输出含 apktool/jadx/adb 的 preinstall 检查结果
  6. **update_max_duration**: 跑 `update_max_duration.py --max-duration 3`，确认 `.persistence.json` 更新
  7. **故障路径**: 模拟 IDA 未配（清空 `.ai_env` 的 IDA_PRO_HOME），新 session 发消息 → Plugin abort 并显示 install_hint
- 依赖: 步骤 1-6

## §4 验收标准

### 功能验收
- [ ] Plugin 在 `chat.message` 中对根 session 自动执行 create_task_dir.py + detect_env.py（日志可证）
- [ ] AI 不再执行任何"阶段 0：任务初始化"步骤（agent prompt 中无此段落）
- [ ] `getTaskDir(sessionID)` 返回 null 时触发初始化，非 null 时跳过
- [ ] Coordinator 子 session（有 parentSessionID）不触发 ensureTaskDir
- [ ] `create_task_dir.py` 幂等：同一 sessionID 重复执行不新建目录
- [ ] `detect_env.py --agent <name>` 合并全量检测 + preinstall 检查，errors 含 install_hint
- [ ] `update_max_duration.py --max-duration <H>` 正确更新 `.persistence.json`
- [ ] 初始化失败时（如 IDA 未配），Plugin 调 `reportErrorAndAbort` 终止并显示 install_hint

### 回归验收
- [ ] create_task_dir.py / detect_env.py / update_max_duration.py `compile` 通过
- [ ] security-analysis.ts `node --check` 通过
- [ ] `detect_env.py --check-preinstall <agent>` 仍正常（向后兼容）
- [ ] detect_env.py 默认模式（不带 --agent）仍正常（全量检测，不查 preinstall）
- [ ] 6 个 agent prompt 展开后 < 450 行
- [ ] 现有 session（已有 TASK_DIR）发消息不重复创建

### 架构验收
- [ ] 依赖方向: Plugin → scripts/*.py（单向），scripts 不反向引用 Plugin
- [ ] 无循环依赖
- [ ] 任务初始化逻辑单一来源（Plugin checkEnvironment），不再散落 prompt + 文档
- [ ] detect_env.py 两种模式（--check-preinstall 向后兼容 + --agent 合并）共存无冲突

## §5 与现有需求文档的关系

- `2026-04-22-environment-dependency-hardening.md`: 建立了 env_cache.json + checkPreinstall 机制。本需求合并 checkPreinstall 到 runDetectEnv，env_cache.json 结构不变（仍由 detect_env.py 写入）
- `2026-04-28-task-dir-persistence.md`: 建立了 create_task_dir.py + .persistence.json 机制。本需求复用该机制，新增幂等化 + Plugin 自动调用，脚本接口不变
- `2026-05-03-agent-prompt-snippets.md`: 建立了 `{{buwai-rule:xxx}}` 片段机制。本需求删除 task-initialization 片段的引用和文件（片段机制本身保留，其他片段不受影响）
- `2026-07-02-config-json-elimination.md`: 建立了 detect_env.py 的 Dependency dataclass + EXTERNAL_TOOLS registry + --check-preinstall 模式。本需求在 --check-preinstall 基础上新增 --agent 合并模式，dataclass 结构不变
