# 需求文档: 环境依赖强制检测与虚拟环境隔离

## §1 背景与目标

**来源**: 用户提出的 4 个环境依赖问题（E1-E4）。

**痛点**:
- E1: 阶段 0 环境检测可被 AI 跳过
- E2: 依赖安装失败不阻塞后续流程，AI 可能在缺工具时继续分析导致反复失败
- E3: 包安装到全局 Python，无隔离，跨机器一致性差
- E4: Agent prompt 中的 python3/python 调用未统一到 venv

**目标**: 需要第三方包的脚本通过专用 venv 运行；环境检测不可跳过；依赖缺失时阻塞并提示用户。

**预期收益**: 减少缺工具时的试错轮次（2-3 轮 → 0 轮），提高跨机器移植一致性。

## §2 技术方案

### A1: 修改 Agent prompt — 强制环境检测

**改动文件**: `.opencode/agents/binary-analysis.md`

将"阶段 0：环境检测（首次使用时）"改为"阶段 0：环境检测（每次分析前、强制）"。

核心规则变更:
1. 标题从"首次使用时"改为"强制（每次分析前）"
2. 新增规则: `success: false → 必须停下来告知用户，列出缺失工具的安装命令，禁止继续分析`
3. 新增规则: `未看到环境信息注入 → 必须先执行环境检测，禁止跳过`
4. env_cache.json 缓存仍为 24 小时（不重复检测），但即使有缓存，Agent 也必须确认 env_cache.json 存在且 `success: true`

### A2: 修改 detect_env.py — 阻塞式安装 + venv 支持

**改动文件**: `.opencode/binary-analysis/scripts/detect_env.py`

#### venv 机制

新增 `_ensure_venv()` 函数:

```python
VENV_DIR = os.path.join(CACHE_DIR, ".venv")

def _ensure_venv():
    """确保 venv 存在。返回 venv 的 python 路径，None 表示创建失败。"""
    if os.name == "nt":
        python_bin = os.path.join(VENV_DIR, "Scripts", "python.exe")
    else:
        python_bin = os.path.join(VENV_DIR, "bin", "python")
    
    if os.path.isfile(python_bin):
        return python_bin
    
    print(f"[*] 正在创建虚拟环境: {VENV_DIR}")
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", VENV_DIR],
            check=True, timeout=120
        )
        print(f"[+] 虚拟环境创建成功")
        return python_bin
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"[!] 创建虚拟环境失败: {e}", file=sys.stderr)
        print(f"[!] 请手动创建: {sys.executable} -m venv {VENV_DIR}", file=sys.stderr)
        return None
```

**重要**: `detect_env.py` 始终用系统 Python 运行（`python3`/`python`），不通过 venv。它负责创建 venv 并在其中安装/检测包。

#### 包检测变更

`_detect_package` 改为通过 venv 的 Python 子进程检测（而非当前进程 `__import__`），因为 detect_env.py 用系统 Python 运行但包在 venv 中:

```python
def _detect_package(name, venv_python):
    try:
        result = subprocess.run(
            [venv_python, "-c", f"import {name}; print(__import__(name).__version__)"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return {"available": True, "version": result.stdout.strip()}
    except (subprocess.TimeoutExpired, OSError):
        pass
    return {"available": False, "version": None}
```

#### 安装流程

1. `_ensure_venv()` 创建 venv（如不存在），失败则返回 `success: false`
2. 用 venv 的 Python 自动执行 `pip install`（保留自动安装）
3. 自动安装失败 → 打印手动安装命令 → 标记为不可用
4. 全部必需包检测完成后，如有缺失的必需包 → 返回 `success: false` 并列出安装命令

#### 新增 BA_PYTHON 概念

`detect_env.py` 成功后，在输出 JSON 中新增 `venv_python` 字段:

```json
{
  "success": true,
  "data": {
    "compiler": {...},
    "packages": {...},
    "venv_python": "/home/user/bw-security-analysis/.venv/bin/python"
  }
}
```

### A3: 修改 Agent prompt + templates.md — 统一使用 $BA_PYTHON

**改动文件**: `.opencode/agents/binary-analysis.md`, `.opencode/binary-analysis/knowledge-base/templates.md`

**两类 Python 调用的区分（关键）**:

| 调用类型 | 使用变量 | 说明 |
|---------|---------|------|
| 内联 Python 一行命令（预检查、路径计算、TASK_DIR 创建） | `python3`/`python` | 不需要第三方包，在 venv 创建前就可能执行 |
| 运行独立脚本文件（gui_verify.py、Unicorn 脚本、Frida 脚本） | `$BA_PYTHON` | 需要 capstone/unicorn/gmpy2/frida |
| 运行 detect_env.py | `python3`/`python` | detect_env.py 本身创建 venv，不能用 $BA_PYTHON |
| 运行 idat + IDAPython 脚本 | `$IDAT` | IDA 内置 Python，独立环境 |

templates.md 中只有 gui_verify.py、Unicorn 脚本、Frida 脚本的调用替换为 `$BA_PYTHON`。其余保持 `python3`/`python`。

变量初始化章节新增（**移到阶段 0 detect_env.py 成功之后**）:

bash:
```bash
# 阶段 0 成功后，从 env_cache.json 提取 BA_PYTHON
BA_PYTHON=$(python3 -c "
import json, os, sys
cache_path = os.path.expanduser('~/bw-security-analysis/env_cache.json')
if os.path.isfile(cache_path):
    cache = json.load(open(cache_path))
    print(cache.get('data', {}).get('venv_python', 'python3'))
else:
    print('python3')
")
```

PowerShell:
```powershell
$BA_PYTHON = python -c "import json,os,sys; p=os.path.expanduser('~/bw-security-analysis/env_cache.json'); print(json.load(open(p)).get('data',{}).get('venv_python','python')) if os.path.isfile(p) else print('python')"
```

### A4: 修改 Plugin — 注入 BA_PYTHON

**改动文件**: `.opencode/plugins/security-analysis.ts`

`system.transform` hook 注入 `BA_PYTHON` 路径:

```javascript
if (envData?.data?.venv_python) {
  envSection += `- BA_PYTHON: ${envData.data.venv_python}\n`;
}
```

### A5: 更新 setup-guide.md

**改动文件**: `.opencode/commands/security-analysis-docs/setup-guide.md`

步骤 4（环境检测）更新: 说明 venv 会自动创建在 `~/bw-security-analysis/.venv`。

### A6: 更新 environment-setup.md

**改动文件**: `.opencode/binary-analysis/environment-setup.md`

说明 venv 策略和手动安装命令格式（`~/bw-security-analysis/.venv/bin/pip install xxx`）。

## §3 实现规范

### 改动范围表

| 文件 | 改动类型 | 影响范围 | 风险等级 |
|------|---------|---------|---------|
| `.opencode/agents/binary-analysis.md` | 修改 | Agent 行为 | 高 |
| `.opencode/binary-analysis/scripts/detect_env.py` | 修改 | 环境检测 | 高 |
| `.opencode/plugins/security-analysis.ts` | 修改 | 环境信息注入 | 中 |
| `.opencode/binary-analysis/knowledge-base/templates.md` | 修改 | 命令模板 | 中 |
| `.opencode/commands/security-analysis-docs/setup-guide.md` | 修改 | 文档 | 低 |
| `.opencode/binary-analysis/environment-setup.md` | 修改 | 文档 | 低 |

### 编码规则

- `detect_env.py` 仍是纯 Python 脚本，不依赖 IDA 运行时
- venv 创建使用 `sys.executable -m venv`（用全局 Python 创建 venv）
- 包安装使用 venv 的 pip（`VENV_DIR/bin/python -m pip install`）
- 所有路径使用 `os.path.expanduser` 确保跨平台

## §4 验收标准

### 功能验收

- [ ] Agent prompt 阶段 0 标记为"强制"，不可跳过
- [ ] Agent prompt 明确: `success: false` → 必须停下来告知用户
- [ ] `detect_env.py` 始终用系统 Python 运行（不用 $BA_PYTHON）
- [ ] `detect_env.py` 自动创建 venv，创建失败时返回 `success: false` 并给出手动命令
- [ ] `_detect_package` 通过 venv Python 子进程检测（非 `__import__`）
- [ ] `detect_env.py` 保留自动安装（用 venv pip），安装失败标记为不可用
- [ ] 必需包缺失时返回 `success: false` 并列出安装命令
- [ ] `detect_env.py` 输出 `venv_python` 字段
- [ ] Plugin 注入 `BA_PYTHON` 路径
- [ ] templates.md 中独立脚本调用使用 `$BA_PYTHON`（内联 Python 一行命令保持 `python3`/`python`）
- [ ] `$BA_PYTHON` 赋值在阶段 0 成功之后执行（env_cache.json 不存在时回退到 `python3`/`python`）

### 回归验收

- [ ] Agent prompt 行数 < 450
- [ ] `detect_env.py --force` 能正常创建 venv 并检测环境
- [ ] `detect_env.py` 缓存机制不变（24h TTL）
- [ ] IDAPython 脚本（query.py、update.py）不受影响（它们通过 idat 运行，不经过 venv）
- [ ] setup-guide.md 更新

### 架构验收

- [ ] venv 位于 `~/bw-security-analysis/.venv`（数据目录，不提交 git）
- [ ] 依赖方向不变: `_base.py ← _utils.py ← _analysis.py ← query.py / update.py / scripts/*.py`

## §5 与现有需求文档的关系

- 本文档是第四轮进化
- 与第三轮（comprehensive-review-fixes.md）的 R1 变量初始化方案叠加: 在原有 `$SCRIPTS_DIR`/`$IDAT` 基础上新增 `$BA_PYTHON`
- 第三轮的 O2（classify_scene packages 参数）依赖 env_cache.json，本轮改动不影响
