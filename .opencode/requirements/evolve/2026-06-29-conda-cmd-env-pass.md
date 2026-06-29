# 进化需求：detect_env.py conda 安装提示使用全路径

## §1 背景与目标

### 来源

复盘 `detect_env.py` 的 `--check-preinstall` 模式：当 crypto-analysis agent 的预装依赖 sage 未安装时，脚本通过 `_build_install_cmd()` 生成安装提示。当前提示写的是裸名 `conda`，但用户环境中 conda 安装在 `~/miniforge3/Scripts/conda.exe` 且**不在 PATH** 中。用户复制提示后无法执行。

### 痛点

1. `venv.ts` 的 `findConda()` 已找到 conda 全路径（`C:\Users\87354\miniforge3\Scripts\conda.exe`），但该路径未传给 `detect_env.py`
2. `detect_env.py` 的 `_build_install_cmd()` 硬编码 `conda`，在 conda 不在 PATH 的环境下生成的提示无效
3. 用户在 Windows 上还需要 `.exe` 后缀（由全路径自然解决）

### 目标

1. `detect_env.py` 的 conda 安装提示使用 Plugin 已找到的 conda 全路径
2. 若 `CONDA_CMD` 环境变量未设置，回退到裸名 `conda`（兼容直接调用场景）

### 效果

- 用户复制 install_hint 后**直接可执行**（含全路径）
- 向后兼容：无 `$CONDA_CMD` 时行为不变

## §2 技术方案

### 2.1 venv.ts — 新增 `getCondaCmd()` 导出

在 `ensureCondaEnvPython()` 中已调用 `findConda()` 找到 conda 路径，将其缓存到模块变量 `cachedCondaCmd`。新增导出函数 `getCondaCmd()`：

```
let cachedCondaCmd: string | null = null;

export function getCondaCmd(): string | null {
  if (cachedCondaCmd !== null) return cachedCondaCmd;
  cachedCondaCmd = findConda();
  return cachedCondaCmd;
}
```

`ensureCondaEnvPython()` 内部在调用 `findConda()` 后同步设置 `cachedCondaCmd`，确保 `getPythonCmd()` 调用后 `getCondaCmd()` 不用再重复执行 `findConda()`。

### 2.2 spawn.ts — RunProcessOptions 增加 env 字段

```typescript
export interface RunProcessOptions {
  timeout?: number;
  /** 额外的环境变量，会合并到默认 env（process.env + UTF-8 配置）之上 */
  env?: Record<string, string>;
}
```

`runProcess()` 在构建 env 时合并 `options.env`（调用方变量优先级高于默认变量）。

### 2.3 security-analysis.ts — 注入并传递 CONDA_CMD

**shell.env hook**: 增加 `$CONDA_CMD` 注入（与 `$PYTHON_CMD` 并列）：

```typescript
const condaCmd = getCondaCmd();
if (condaCmd) {
  output.env.CONDA_CMD = condaCmd;
}
```

**checkPreinstall()**: 将 `$CONDA_CMD` 传给子进程：

```typescript
const condaCmd = getCondaCmd();
const r = await runProcess(pythonCmd, [detectEnv, "--check-preinstall", agent], {
  timeout: 8000,
  env: condaCmd ? { CONDA_CMD: condaCmd } : undefined,
});
```

### 2.4 detect_env.py — 读取 CONDA_CMD 环境变量

```python
def _build_install_cmd(info):
    installer = info.get("installer", "pip")
    if installer == "conda":
        name = info.get("conda_name") or info["pip_name"]
        conda_cmd = os.environ.get("CONDA_CMD", "conda")
        return f"{conda_cmd} install -p '{sys.prefix}' -y {name}"
    return f"{sys.executable} -m pip install {info['pip_name']}"
```

## §3 实现规范

### §3.1 实施步骤拆分

| 步骤 | 文件 | 描述 | 预估行数 | 验证点 | 依赖 |
|------|------|------|----------|--------|------|
| 1 | `venv.ts` | `ensureCondaEnvPython()` 内部缓存 conda 路径；新增 `getCondaCmd()` 导出 | ~12 | 语法检查 `node --check` + `getCondaCmd()` 被正确导出 | 无 |
| 2 | `spawn.ts` | `RunProcessOptions` 增加 `env` 字段；`runProcess()` 合并 `options.env` | ~8 | 语法检查 | 无 |
| 3 | `security-analysis.ts` | import 加 `getCondaCmd`；`shell.env` 注入 `$CONDA_CMD`；`checkPreinstall` 传递 env | ~10 | 语法检查 + grep 确认 `getCondaCmd` 已 import 且被正确引用 | 1, 2 |
| 4 | `detect_env.py` | `_build_install_cmd()` 读取 `$CONDA_CMD` | ~3 | `python -c "compile(...)"` 语法检查 | 无 |

### 编码规则

- 所有改动遵循现有代码风格
- `.ts` 文件：`node --check` 语法校验
- `.py` 文件：`python -c "compile(...)"` 语法校验
- 无新增依赖

## §4 验收标准

### 功能验收

1. `getCondaCmd()` 返回 conda 全路径（如 `C:\Users\87354\miniforge3\Scripts\conda.exe`）或 null
2. Agent 侧 `$CONDA_CMD` 环境变量已注入（可通过 `echo $CONDA_CMD` 验证）
3. `detect_env.py --check-preinstall crypto-analysis` 在 sage 未安装时输出的 install_hint 使用全路径
4. `$CONDA_CMD` 未设置时，回退到裸名 `conda`（向后兼容）

### 回归验收

1. `detect_env.py` 其他功能不受影响（包检测、编译器检测、IDA 检测）
2. 非 crypto-analysis agent 不受影响
3. `checkPreinstall()` 对已安装 sage 的环境仍返回 `{ ready: true }`

### 架构验收

1. 不违反依赖方向（`venv.ts` → `security-analysis.ts` 方向正确）
2. `spawn.ts` 新增 `env` 字段为可选，不改现有调用方
3. 不引入循环依赖

## §5 与现有需求文档的关系

本需求是 `2026-06-28-conda-venv-migration.md` 的补充完善——迁移到 conda env 后，`detect_env.py` 的安装提示应传递 conda 全路径而非裸名。不与该文档冲突。
