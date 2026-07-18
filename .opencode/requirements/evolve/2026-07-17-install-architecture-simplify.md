# install 架构简化：conda/venv 逻辑收口到 detect_env.py

## §1 背景与目标

### 来源痛点

conda 检测 + venv 创建逻辑分散在三处，维护成本高：

| 位置 | 语言 | 行数 | 逻辑 |
|---|---|---|---|
| install.sh | bash | ~80 行 | conda 检测 + venv 创建 + 调 detect_env.py |
| install.ps1 | PowerShell | ~70 行 | 同上，不同语法 |
| venv.ts | TypeScript | ~184 行 | conda 检测 + venv 创建 + Python 验证 |

三套逻辑行为可能不一致（路径候选、错误处理、超时值），修一个 bug 要改三处。

### 改进目标

- conda 检测 + venv 创建只保留一份（Python，跨平台）
- shell 脚本缩减到 ~10 行（只找 python3 → exec detect_env.py install）
- venv.ts 缩减到 ~30 行（只检查 venv 是否存在，不创建）
- 单一职责：install.sh/detect_env.py = 安装器，venv.ts = 消费者

### 预期收益

| 维度 | 改进前 | 改进后 |
|---|---|---|
| conda/venv 逻辑份数 | 3 份（bash + PS + TS） | 1 份（Python） |
| install.sh 行数 | ~80 | ~10 |
| install.ps1 行数 | ~70 | ~10 |
| venv.ts 行数 | ~184 | ~30 |
| 跨平台一致性 | 可能不一致 | 同一份 Python，天然一致 |

## §2 技术方案

### 2.1 新架构

```
install.sh/ps1（~10 行 shell）
  → 找 python3 → exec detect_env.py install

detect_env.py install（Python，跨平台）
  → bootstrap: 不在 venv 里 → 搜 conda → 创建 venv → 重启自己（os.execv / subprocess）
  → 在 venv 里 → pip install + playwright + 外部工具 + events MCP

venv.ts（~30 行 TypeScript）
  → findVenvPython() 只检查存在，不创建
  → 不存在 → 返回 "请运行安装脚本"

checkEnvironment
  → getPythonCmd() = null → "请运行安装脚本"
```

### 2.2 detect_env.py install 新增 bootstrap

```
启动时检查：
  sys.executable 是否 == ~/bw-security-analysis/.venv/bin/python（或 Windows .venv/Scripts/python.exe）
  ├─ 是 → 跳到原有 install 流程
  └─ 否 → bootstrap:
        1. 搜 conda（shutil.which + 常见路径，跨平台）
        2. conda 不存在 → 打印安装指引 + sys.exit(1)
        3. conda 存在 → conda create -p VENV_DIR python=3.13 -y
        4. 校验 venv Python 可执行文件存在（防中断残留）
        5. 重启自己：
           Unix  → os.execv(venv_python, [venv_python, __file__, "install"])
           Win   → subprocess.run([venv_python, __file__, "install"]) + sys.exit(returncode)
```

### 2.3 venv.ts 简化

删除：
- `findConda()` — conda 检测（移到 detect_env.py）
- `verifyConda()` — conda 验证
- `ensureCondaEnvPython()` — venv 创建
- `cachedCondaCmd` — conda 缓存

保留：
- `verifyPython()` — Python 可用性验证
- `findVenvPython()` — 检查 venv Python 是否存在

新增：
- `getInstallHint()` — 返回安装脚本路径提示（替代 `getCondaInstallHint()`）

### 2.4 install.sh / install.ps1 简化

只做一件事：找 python3 → 执行 detect_env.py install。

### 2.5 env-check.ts 清理

删除 `getCondaCmd()` 调用和 `CONDA_CMD` 环境变量传递。detect_env.py 自己找 conda。

### 2.6 checkEnvironment 改动

`getCondaInstallHint()` → `getInstallHint()`（指向 install.sh 而非 miniforge 官网）。

## §3 实现规范

### 改动范围表

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `binary-analysis/scripts/detect_env.py` | 修改 | install 子命令新增 bootstrap 逻辑 |
| `plugins/lib/venv.ts` | 重构 | 删除 conda 相关，只保留 venv 检查 |
| `plugins/lib/env-check.ts` | 修改 | 删除 CONDA_CMD 传递 |
| `plugins/security-analysis.ts` | 修改 | `getCondaInstallHint()` → `getInstallHint()` |
| `install.sh` | 重写 | 缩减到 ~10 行 |
| `install.ps1` | 重写 | 缩减到 ~10 行 |

### §3.1 实施步骤拆分

**步骤 1. detect_env.py install 新增 bootstrap**
- 文件: detect_env.py
- 预估行数: ~60 行（bootstrap 函数 + 跨平台 conda 搜索 + execv/subprocess 重启）
- 验证点: `python3 detect_env.py install` 在非 venv 环境下自动创建 venv 并重启；venv 已存在时跳过 bootstrap
- 依赖: 无

**步骤 2. venv.ts 简化**
- 文件: venv.ts
- 预估行数: 删除 ~150 行，新增 ~15 行，净删除 ~135 行
- 验证点: bun bundle 成功；`getPythonCmd()` 返回 venv Python 或 null；`getInstallHint()` 返回安装脚本路径
- 依赖: 无

**步骤 3. env-check.ts + security-analysis.ts 清理**
- 文件: env-check.ts, security-analysis.ts
- 预估行数: ~10 行（删 CONDA_CMD 传递 + 改 getCondaInstallHint → getInstallHint）
- 验证点: bun bundle 成功；无 getCondaCmd / getCondaInstallHint 引用
- 依赖: 步骤 2

**步骤 4. install.sh / install.ps1 重写**
- 文件: install.sh, install.ps1
- 预估行数: 各 ~10 行
- 验证点: bash -n install.sh；语法正确；不再有 conda/venv 逻辑
- 依赖: 步骤 1

**步骤 5. 文档引用清理**
- 文件: 引用 install.sh/ps1 旧流程的文档
- 预估行数: ~5 行
- 验证点: grep 确认无残留旧引用
- 依赖: 步骤 4

## §4 验收标准

### 功能验收

| 验收项 | 验证方式 |
|---|---|
| `python3 detect_env.py install` 从系统 Python 自动 bootstrap 到 venv | 运行后 `sys.executable` 是 venv Python |
| venv 已存在时跳过 bootstrap | 日志无 conda create |
| conda 不存在时打印指引并退出 | 无 conda 时 sys.exit(1) + 指引 |
| `getPythonCmd()` 仍返回 venv Python 或 null | venv 存在 → 返回路径；不存在 → null |
| `getInstallHint()` 返回 install.sh 路径 | 消息含 `bash ".../install.sh"` |
| install.sh 只有找 python + exec detect_env.py | grep 确认无 conda/venv |
| env-check.ts 不再传 CONDA_CMD | grep 确认 |

### 回归验收

| 验收项 | 验证方式 |
|---|---|
| check-preinstall 正常工作 | detect_env.py check-preinstall all 成功 |
| shell.env 注入 PYTHON_CMD 正常 | venv 存在时 PYTHON_CMD 有值 |
| MCP 注册正常 | venv 存在时 McpManager 正常 |

### 架构验收

| 验收项 | 验证方式 |
|---|---|
| conda 检测只在 detect_env.py | grep 确认 venv.ts 和 install.sh 无 findConda/conda |
| venv 创建只在 detect_env.py | grep 确认 venv.ts 和 install.sh 无 conda create |

## §5 与现有需求文档的关系

- `2026-07-15-detect-env-subcommand-refactor.md` — detect_env 子命令重构，本文档是其 install 子命令的扩展
- `2026-07-17-events-writer-daemon.md` — events writer daemon，无冲突
