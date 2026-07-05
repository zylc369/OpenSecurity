# 需求文档: 环境检测重构 + 任务目录创建搬 TS

## §1 背景与目标

**来源**: 2026-07-05 与用户讨论，基于 `2026-07-04-deterministic-task-initialization.md` 的后续优化。

`2026-07-04` 把任务初始化搬进 Plugin 后，暴露三个问题：

1. **detect_env.py 在 chat.message 里自动装包**：timeout 60 秒可能不够（playwright 浏览器 200MB），超时后用户不知道卡在哪个包（stderr 被 capture 吞了）
2. **检测不按 agent 过滤**：用 binary-analysis 会报 playwright/bs4 缺失（其实只有 web-analysis 需要）——根因是 PYTHON_PACKAGES 没给包标记 `agents` 字段（dataclass 本来就有这个字段）
3. **create_task_dir.py 逻辑简单但用 Python**：目录创建 + JSON 写入，TS 完全能做，省一次 spawn + Plugin 完全自包含

**目标**:
1. chat.message 走 `--check-preinstall`（只检测不装），timeout 回到 8 秒——不装包就不会慢
2. 所有 Python 包标记 `agents` + 设为 `preinstall=True`，`_check_preinstall(agent)` 自然按 agent 过滤
3. `_check_preinstall` 扩展：检测版本 + 编译器 + IDA + 工具 + 写 env_cache.json + 支持 `all`（Coordinator 用）
4. Coordinator 检测所有子 agent 依赖的并集（`--check-preinstall all`），避免执行中途子 agent 缺包
5. create_task_dir.py 搬 TS（Plugin 新增 `createTaskDir` 函数）
6. runDetectEnv 错误信息拼入 stderr（detect_env 崩溃时用户看到 traceback/进度日志）

**预期收益**（四维度量）:
- **速度**: chat.message 环境检测从可能 60 秒（装包）→ 稳定 2-3 秒（只 find_spec + which）
- **准确度**: 按 agent 过滤，不再报不相关的缺失包；Coordinator 预检所有子 agent 依赖
- **上下文**: 删 create_task_dir.py（1 个文件）；错误信息更精准（只列当前 agent 缺的包）
- **体验**: 首次缺包时用户看到精准清单 + 一键安装命令；装包进度用户手动跑 `--force` 时实时可见

**不兼容声明**: chat.message 不再自动装包。首次搭建缺包时用户手动装（按 hint）或手动跑 `detect_env.py --force`。`--force` 保留自动安装能力（run_detection 仍可用，但所有包标为 preinstall 后 main() 默认改走 _check_preinstall）。

## §2 技术方案

### 2.1 PYTHON_PACKAGES 标记 agents + 全部 preinstall=True

Dependency dataclass 已有 `agents` 字段（空=所有 agent）。当前只有 sage 标记了 agents。给每个包标记正确的 agents + 全部设 `preinstall=True`：

| 包 | agents |
|---|---|
| angr / triton / capstone / unicorn / PIL / pyautogui / pyperclip | binary-analysis |
| z3 / gmpy2 | binary-analysis, crypto-analysis |
| frida | binary-analysis, mobile-analysis |
| playwright / requests | web-analysis, ai-security-analysis |
| markdownify / bs4 / lxml | web-analysis |
| sage | crypto-analysis（已标记） |

### 2.2 _check_preinstall 扩展为完整检测 + 写 cache

当前 `_check_preinstall(agent)` 只检测 preinstall 包的可用性（find_spec），返回 `{success, errors}`。扩展为：

```
_check_preinstall(agent):
  1. 按 agent 过滤 PYTHON_PACKAGES（all = 不过滤）
  2. find_spec 检测 + importlib.metadata.version 收集版本
  3. _detect_compiler() 检测编译器
  4. _detect_ida_pro() 检测 IDA Pro
  5. 按 agent 过滤 EXTERNAL_TOOLS，_resolve_tool + _get_tool_version 检测
  6. 组装 data（compiler/packages/ida_pro/tools）+ _save_cache 写入 env_cache.json
  7. 返回 {success, data, errors}（stdout 输出完整 JSON）
```

**agent="all"** 时不做 agent 过滤（检测所有包），用于 Coordinator。

**保留 run_detection**（代码不删），但 main() 的默认/--force 模式改为调 `_check_preinstall("all")`。run_detection 的自动安装逻辑（_install_package 等）不再被 main() 调用——用户如需自动装，手动跑 `detect_env.py --force`（main 走 _check_preinstall("all")，不装，但写 cache）。

> 用户如需"一键安装所有缺失包"：按 errors 里的 install_hint 执行 pip install（_check_preinstall 的 hint 含安装命令）。

### 2.3 createTaskDir 搬 TS

`plugins/lib/task-session.ts` 新增 `createTaskDir(sessionID): string`：

```ts
export function createTaskDir(sessionID: string): string {
  // 幂等：getTaskDirRaw 已有映射且目录存在 → 返回已有
  // 首次：mkdir WORKSPACE_DIR + 时间戳_随机hex 目录名
  //       writeFileSync .task_sessions/{sessionID}.json 映射
  //       writeFileSync .persistence.json（max_duration_hours=6, resume_count=0, last_resume_at=null）
  // 返回 task_dir 路径
}
```

复用已有的 `getTaskDirRaw`（幂等检查）、`WORKSPACE_DIR`/`TASK_SESSIONS_DIR`（constants.ts）。

### 2.4 Plugin runDetectEnv / ensureTaskDir 改造

**ensureTaskDir**: 删除 spawn create_task_dir.py，改为调 `createTaskDir(sessionID)`。签名简化（去掉 pythonCmd 参数——不再 spawn）。

**runDetectEnv**:
- 改调 `--check-preinstall <agent>`（Coordinator 传 `all`）
- timeout 60000 → **8000**（只检测不装，8 秒够）
- 错误信息拼入 stderr（超时/崩溃时用户看到 detect_env 的日志/traceback）

### 2.5 Coordinator 处理

Plugin 的 runDetectEnv 里，如果 `agent === AGENT_SECURITY_COORDINATOR`，传 `--check-preinstall all`（检测所有子 agent 依赖的并集）。

## §3 实现规范

### 改动范围表

| 文件 | 改动类型 | 影响级别 |
|------|---------|---------|
| `binary-analysis/scripts/detect_env.py` | PYTHON_PACKAGES 标记 + _check_preinstall 扩展 + main() 改造 | 高 |
| `plugins/lib/task-session.ts` | 新增 createTaskDir 函数 | 中 |
| `plugins/security-analysis.ts` | ensureTaskDir 改调 createTaskDir + runDetectEnv 改调 --check-preinstall + Coordinator all | 高 |
| `binary-analysis/scripts/create_task_dir.py` | **删除** | — |
| `binary-analysis/scripts/registry.json` | 删 create_task_dir.py 条目 | 低 |
| `binary-analysis/scripts/update_max_duration.py` | docstring 更新（不再引用 create_task_dir.py） | 低 |

### §3.1 实施步骤拆分

**步骤 1. detect_env.py: PYTHON_PACKAGES 标记 agents + 全部 preinstall=True**
- 文件: `binary-analysis/scripts/detect_env.py`
- 改动: 15 个非 preinstall 包加 `preinstall=True` + `agents=[...]`（见 §2.1 表格）
- 预估行数: ~20 行修改
- 验证点: `compile` 通过；`detect_env.py --check-preinstall binary-analysis` 只检测 binary 相关包（不检测 playwright/bs4/lxml）；`--check-preinstall web-analysis` 只检测 web 包（不检测 angr/capstone）
- 依赖: 无

**步骤 2. detect_env.py: _check_preinstall 扩展（版本收集 + 编译器/IDA/工具检测 + 写 cache + 支持 all）**
- 文件: `binary-analysis/scripts/detect_env.py`
- 改动:
  - `_check_preinstall` 函数重构：Python 包检测改用 find_spec + `importlib.metadata.version`（收集版本到 packages dict）；新增编译器检测（调 `_detect_compiler`）；新增 IDA Pro 检测（调 `_detect_ida_pro`）；外部工具检测（调 `_resolve_tool` + `_get_tool_version`，按 agent 过滤）；组装 data + `_save_cache`；支持 `agent == "all"`（不做 agent 过滤）
  - hint 生成逻辑抽为 `_build_install_hint(dep)` 辅助函数（从现有 _check_preinstall 内联代码提取）
  - IDA Pro 缺失时报 install_hint（从 EXTERNAL_TOOLS 的 dep 获取）
  - 返回值改为 `{success, data, errors}`（含 data，供 stdout 输出）
- 预估行数: ~80 行修改（_check_preinstall 从 ~40 行扩展到 ~90 行 + _build_install_hint ~15 行）
- 验证点:
  - `compile` 通过
  - `detect_env.py --check-preinstall binary-analysis` stdout 含完整 data（compiler/packages/ida_pro/tools）+ env_cache.json 更新
  - `detect_env.py --check-preinstall all` 检测所有包（不做 agent 过滤）
  - `detect_env.py --check-preinstall web-analysis` 检测 playwright/requests/bs4/lxml/markdownify
- 依赖: 步骤 1

**步骤 3. detect_env.py: main() 默认/--force 模式改走 _check_preinstall + 删除 --agent 参数**
- 文件: `binary-analysis/scripts/detect_env.py`
- 改动:
  - main() 的默认模式（非 --check-preinstall）：缓存命中时用缓存；未命中/--force 时调 `_check_preinstall("all")`（替代 `run_detection`）
  - `run_detection` 函数保留（不删除），但不再被 main() 调用
  - 删除 `--agent` 参数（上次进化 2026-07-04 新增，本次改调 --check-preinstall 后无消费者：Plugin 不再用、agent prompt 不带、知识库不带）
- 预估行数: ~25 行修改
- 验证点: `compile` 通过；`detect_env.py --force` 输出完整 JSON（含 data）；`detect_env.py`（默认模式，缓存命中）用缓存；`detect_env.py --agent x` 报错（参数已删）
- 依赖: 步骤 2

**步骤 4. task-session.ts: 新增 createTaskDir 函数**
- 文件: `plugins/lib/task-session.ts`
- 改动: 新增 `createTaskDir(sessionID): string`（幂等检查 via getTaskDirRaw + 目录创建 + 映射注册 + persistence.json 初始化）
- 预估行数: ~35 行新增
- 验证点: `node --check task-session.ts` 通过
- 依赖: 无（与步骤 1-3 并行）

**步骤 5. security-analysis.ts: ensureTaskDir + runDetectEnv 改造**
- 文件: `plugins/security-analysis.ts`
- 改动:
  - `ensureTaskDir`: 删除 spawn create_task_dir.py（runProcess 调用），改为调 `createTaskDir(sessionID)`（同步 TS 调用）；签名去掉 pythonCmd 参数；try/catch 包裹（createTaskDir 可能抛 fs 异常）
  - `runDetectEnv`: 改调 `detect_env.py --check-preinstall <agent>`（agent == coordinator 时传 `all`）；timeout 60000 → 8000；错误信息拼入 stderr（`r.error` / JSON.parse 失败 / success=false 三条路径都拼 stderr 尾部 300 字符）
  - `checkEnvironment` 里 ensureTaskDir 调用去掉 pythonCmd 参数
- 预估行数: ~55 行修改
- 验证点: `node --check security-analysis.ts` 通过
- 依赖: 步骤 2（detect_env --check-preinstall 就绪）+ 步骤 4（createTaskDir 就绪）

**步骤 6. 删除 create_task_dir.py + 更新引用**
- 文件:
  - 删除 `binary-analysis/scripts/create_task_dir.py`
  - `binary-analysis/scripts/registry.json`: 删 create_task_dir.py 条目
  - `binary-analysis/scripts/update_max_duration.py`: docstring "由 create_task_dir.py 创建" → "由 Plugin createTaskDir 创建"
- 预估行数: 删 1 文件 + ~5 行修改
- 验证点: create_task_dir.py 不存在；`rg "create_task_dir" .opencode/`（排除 requirements/evolve）返回 0
- 依赖: 步骤 5

**步骤 7. 端到端验证**
- 验证点:
  1. **按 agent 过滤**: `detect_env.py --check-preinstall binary-analysis` 不检测 playwright/bs4；`--check-preinstall web-analysis` 不检测 angr/capstone
  2. **all 模式**: `--check-preinstall all` 检测所有包
  3. **env_cache 写入**: `--check-preinstall binary-analysis` 后 env_cache.json 含 packages/ida_pro/tools/compiler
  4. **createTaskDir TS**: 新 sessionID 调 createTaskDir → 目录创建 + 映射注册 + persistence.json；重复调返回相同目录（幂等）
  5. **runDetectEnv timeout**: 模拟 Plugin 调 `--check-preinstall binary-analysis`，确认 < 8 秒完成
  6. **错误信息**: stderr 拼入错误消息（模拟 detect_env 崩溃，确认错误消息含 traceback）
  7. **向后兼容**: `detect_env.py --force` 仍正常输出完整 JSON
- 依赖: 步骤 1-6

## §4 验收标准

### 功能验收
- [ ] `--check-preinstall binary-analysis` 只检测 binary 包（angr/capstone/frida/...），不检测 playwright/bs4/lxml
- [ ] `--check-preinstall web-analysis` 只检测 web 包（playwright/requests/bs4/lxml/markdownify）
- [ ] `--check-preinstall all` 检测所有包（Coordinator 用）
- [ ] `_check_preinstall` 写入 env_cache.json（含 compiler/packages/ida_pro/tools）
- [ ] createTaskDir（TS）创建目录 + 映射 + persistence.json，幂等
- [ ] Plugin runDetectEnv 调 `--check-preinstall`，timeout 8000ms
- [ ] Coordinator 传 `--check-preinstall all`
- [ ] 错误信息含 stderr（超时/崩溃时用户看到进度日志/traceback）

### 回归验收
- [ ] detect_env.py `compile` 通过
- [ ] security-analysis.ts / task-session.ts `node --check` 通过
- [ ] `detect_env.py --force` 仍正常输出完整 JSON
- [ ] create_task_dir.py 已删除，无代码引用残留
- [ ] update_max_duration.py 仍正常工作（.persistence.json 格式不变）

### 架构验收
- [ ] 依赖方向: Plugin → detect_env.py（单向）；createTaskDir 在 Plugin 内（不 spawn）
- [ ] 无循环依赖
- [ ] 环境检测单一入口（_check_preinstall），不再 run_detection + _check_preinstall 两套
- [ ] task 目录创建完全在 TS 侧（不依赖 Python 脚本）

## §5 与现有需求文档的关系

- `2026-07-04-deterministic-task-initialization.md`: 本需求是其后续优化。前者建立了 Plugin 自动初始化（ensureTaskDir + runDetectEnv），本需求优化检测策略（--skip-install → --check-preinstall）、按 agent 过滤、createTaskDir 搬 TS
- `2026-07-02-config-json-elimination.md`: 建立了 Dependency dataclass + EXTERNAL_TOOLS registry + _check_preinstall。本需求复用并扩展 _check_preinstall（从只查 preinstall 扩展为完整检测）
- `2026-04-28-task-dir-persistence.md`: 建立了 create_task_dir.py + .persistence.json 机制。本需求将 create_task_dir.py 的逻辑搬入 Plugin TS（createTaskDir），.persistence.json 格式不变
