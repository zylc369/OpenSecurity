# 进化需求：venv 迁移到 conda + 环境检测收口

## §1 背景与目标

### 来源

crypto-analysis agent 需要 SageMath，但 `pip install sagemath-standard` 在 macOS 上编译失败（缺 pkg-config/gmp/mpfr 等构建依赖）。用户决定将 `~/bw-security-analysis/.venv` 从 `python -m venv` 创建改为 `conda create -p` 创建，利用 conda 的预编译 sage 包。

### 痛点

1. pip 路线无法安装 sage（编译地狱），crypto-analysis agent 的格/Coppersmith/ECC 攻击无法执行
2. 环境检测逻辑分散（chat.message 里直接调 checkPreinstall，没有统一收口）
3. venv.ts 在模块顶层立即执行 `ensureVenvPython()`，conda 不存在时 Plugin 直接加载失败，用户看到的是"Plugin 未加载"而非友好提示

### 目标

1. `~/bw-security-analysis/.venv` 改用 `conda create -p` 创建（路径不变，PYTHON_CMD 不变）
2. venv.ts 改为惰性缓存函数 `getPythonCmd()`，不在模块顶层执行
3. chat.message 调用新的 `checkEnvironment()` 统一环境检测函数（含 conda 检测 + preinstall 检测）
4. detect_env.py 的包安装改为配置驱动（`installer` 字段），sage 声明 `installer: "conda"`
5. pip 在 conda env 里照常工作——除 sage 外所有包安装方式不变

### 效果

- sage 可通过 `conda install sage` 安装（预编译，无需编译依赖）
- conda 不存在时用户得到友好提示（而非 Plugin 崩溃）
- 环境检测逻辑收口到单一函数，后续扩展只改一处
- 包安装逻辑配置驱动，新增 conda 包只改配置不改代码

## §2 技术方案

### 核心变更概览

```
venv.ts:
  - 删除: export const PYTHON_CMD = ensureVenvPython()  (模块顶层执行)
  - 删除: findSystemPython()                             (不再需要系统 Python)
  - 新增: findConda()                                    (跨平台检测 conda)
  - 新增: getPythonCmd(): string | null                  (惰性 + 缓存)
    - 已缓存 → 直接返回
    - findVenvPython() 成功 → 缓存 + 返回（conda env 的 python 在同一路径）
    - findConda() 失败 → 返回 null
    - conda create -p → findVenvPython() → 缓存 + 返回

security-analysis.ts:
  - 新增: checkEnvironment(agent, sessionID): EnvironmentCheckResult
    - 调 getPythonCmd()，null → 报"conda 未安装"
    - 调 checkPreinstall(agent)，不 ready → 报预装缺失
  - chat.message: checkPreinstall → checkEnvironment
  - 所有 PYTHON_CMD 引用 → getPythonCmd() 调用

detect_env.py:
  - 新增: _build_install_cmd(info) — 配置驱动的安装命令生成
  - REQUIRED_PACKAGES sage 条目: 加 installer/conda_name 字段
  - _check_preinstall 的 install_hint 生成: 硬编码 pip → 调 _build_install_cmd(info)
```

### 关键设计决策

**为什么 conda env 和 venv 的 python 检测路径相同？**

conda env 的文件结构与 venv 完全一致：
- Linux/macOS: `<env_dir>/bin/python`
- Windows: `<env_dir>/Scripts/python.exe`

`conda create -p ~/bw-security-analysis/.venv` 创建的 python 在 `findVenvPython()` 已有的候选路径里。因此 `findVenvPython()` 和 `verifyPython()` **不用改**，只有创建步骤从 `python -m venv` 改为 `conda create -p`。

**为什么 pip 引用不需要全改？**

conda env 自带 pip。`sys.executable -m pip install xxx` 在 conda env 里照常工作。只有 sage 需要 `conda install`（因为 pip 编译失败），其余包继续用 pip。通过 `installer` 配置字段声明每个包的安装器，代码通用读取。

**Python 版本选择**

`conda create -p` 指定 `python=3.13`（conda 解析为最新的 3.13.x 补丁版本）。3.13 比 3.14 更经实战检验，对本工具链（C 扩展为主）无性能差异。

### 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `plugins/lib/venv.ts` | 重写 | ensureVenvPython → getPythonCmd（惰性缓存）；findSystemPython → findConda；创建命令 python -m venv → conda create -p |
| `plugins/security-analysis.ts` | 修改 | 新增 checkEnvironment；chat.message 调 checkEnvironment；PYTHON_CMD → getPythonCmd()（6 处引用） |
| `binary-analysis/scripts/detect_env.py` | 修改 | 新增 _build_install_cmd；sage 条目加 installer/conda_name；_check_preinstall 调 _build_install_cmd |
| `docs/项目介绍/新机器配置指南.md` | 修改 | 加 miniforge 前置步骤；sage 安装从 pip 改 conda |
| `crypto-analysis/knowledge-base/crypto-methodology.md` | 修改 | sage 安装命令从 pip 改 conda |

**不修改**：
- detect_env.py 的 `_install_package`（只处理 pip 包；preinstall 包如 sage 不走自动安装，由 `_check_preinstall` 生成 hint 让用户手动装。`_install_package` 和 `_build_install_cmd` 职责不同：前者实际执行安装（subprocess），后者生成给用户看的命令字符串（hint））
- detect_env.py 的 `_detect_package`（find_spec 检测逻辑不变）
- 所有脚本里的 "请运行 pip install xxx" 提示（在 conda env 里仍正确）
- detect_env.py 的 REQUIRED_PACKAGES 中除 sage 外的条目（pip 安装不变）

### 架构影响

- **venv.ts**：从模块顶层常量变为惰性函数。PYTHON_CMD 不再在 Plugin 加载时确定，而是在首次 chat.message 时确定（有缓存）。后续 hook 调 getPythonCmd() 拿到的是缓存值。
- **security-analysis.ts**：环境检测收口到 checkEnvironment。chat.message 是 LLM 调用前最早的 awaited hook，这里防住后续 hook 不会在环境缺失时执行。
- **detect_env.py**：配置驱动的安装命令生成，`_build_install_cmd(info)` 根据 `installer` 字段选择安装器，新增 installer 类型只需在 `_build_install_cmd` 加分支 + REQUIRED_PACKAGES 加字段。

## §3 实现规范

### 编码规则

1. `getPythonCmd()` 返回 `string | null`。null 表示 conda 不可用且 env 不存在。一旦成功初始化，缓存非 null 值，后续调用直接返回。
2. `checkEnvironment()` 是 chat.message 里唯一的环境检测入口，返回 `{ready: boolean, message: string}`。
3. detect_env.py 的 `_build_install_cmd(info)` 根据 `info.get("installer", "pip")` 选择安装器，不硬编码包名。
4. conda 检测跨平台：先查 PATH（`conda --version`），再查常见安装路径（miniforge3/miniconda3）。
5. conda 创建命令：`conda create -p "<VENV_DIR>" python=3.13 -y`（`-y` 跳过确认）。

### §3.1 实施步骤拆分

#### 步骤 1. venv.ts — conda 检测 + 惰性缓存函数

- **文件**: `plugins/lib/venv.ts`
- **预估行数**: ~80 行（重写大部分文件）
- **改动**:
  1. 删除 `findSystemPython()` 函数（不再需要系统 Python 创建 venv）
  2. 新增 `findConda(): string | null` 函数：
     - 先试 PATH 里的 `conda`（`conda --version` 验证）
     - 再试常见安装路径（跨平台）：
       - macOS/Linux: `~/miniforge3/bin/conda`、`~/miniconda3/bin/conda`、`/opt/miniforge3/bin/conda`
       - Windows: `%USERPROFILE%\miniforge3\Scripts\conda.exe`、`%USERPROFILE%\miniconda3\Scripts\conda.exe`
     - 每个候选用 `verifyPython` 同款模式验证（执行 `conda --version`）
     - 都不可用 → 返回 null
  3. 将 `ensureVenvPython()` 重写为 `ensureCondaEnvPython(): string | null`：
     - 第 1 步：`findVenvPython()`（现有函数，不用改——conda env 的 python 在同一路径）
     - 第 2 步：env 不存在 → `findConda()`，返回 null 则整体返回 null（不 throw）
     - 第 3 步：`conda create -p "<VENV_DIR>" python=3.13 -y`（timeout 300000ms = 5 分钟）
     - 第 4 步：创建后 `findVenvPython()` 验证
     - 失败返回 null（不 throw）
  4. 删除模块级 `export const PYTHON_CMD = ensureVenvPython();`
  5. 新增模块级 `let cachedPythonCmd: string | null = null;`
  6. 新增 `export function getPythonCmd(): string | null`：
     - `if (cachedPythonCmd) return cachedPythonCmd;`
     - `cachedPythonCmd = ensureCondaEnvPython();`
     - `return cachedPythonCmd;`
   7. 新增 `export function getCondaInstallHint(): string`：返回平台相关的 miniforge 安装指引，供 checkEnvironment 使用。使用 `process.platform` 判断平台，只显示对应平台的命令。消息模板：
      ```
      [环境未就绪] conda 未安装，无法创建 Python 虚拟环境。请先安装 Miniforge：
      - macOS: brew install --cask miniforge
      - Linux: 参考 https://github.com/conda-forge/miniforge#download
      - Windows: 从 https://github.com/conda-forge/miniforge#download 下载安装包

      安装后重启终端，重新发送消息。
      ```
- **验证点**: `node --check venv.ts` 语法通过；`getPythonCmd` 是命名导出，无 `PYTHON_CMD` 常量导出

#### 步骤 2. security-analysis.ts — checkEnvironment + 更新 PYTHON_CMD 引用

- **文件**: `plugins/security-analysis.ts`
- **预估行数**: ~60 行
- **依赖**: 步骤 1
- **改动**:
  1. import: `PYTHON_CMD` → `getPythonCmd, getCondaInstallHint`
  2. 新增 `checkEnvironment(agent: string, sessionID: string): EnvironmentCheckResult` 函数（类型 `PreinstallResult` 重命名为 `EnvironmentCheckResult`，语义更准确）：
     ```typescript
     type EnvironmentCheckResult = { ready: boolean; message: string };
     
     function checkEnvironment(agent: string, sessionID: string): EnvironmentCheckResult {
       const pythonCmd = getPythonCmd();
       if (!pythonCmd) {
         return { ready: false, message: getCondaInstallHint() };
       }
       return checkPreinstall(agent, sessionID);
     }
     ```
  3. `type PreinstallResult` → `type EnvironmentCheckResult`（类型定义重命名 + checkPreinstall 函数返回类型同步改名）
  4. chat.message: `checkPreinstall(agent, sessionID)` → `checkEnvironment(agent, sessionID)`
  5. checkPreinstall 内部: `spawnSync(PYTHON_CMD, ...)` → `const pc = getPythonCmd(); if (!pc) return {ready:false, ...}; spawnSync(pc, ...)`（防御性 null 检查——checkEnvironment 已保证非 null，此处仅兜底）
  6. buildEnvSection: `${PYTHON_CMD}` → `${getPythonCmd() ?? "未初始化"}`
  7. shell.env: `output.env.PYTHON_CMD = PYTHON_CMD` → `const pc = getPythonCmd(); if (pc) output.env.PYTHON_CMD = pc;`
  8. Plugin 加载日志: `debugLog("  PYTHON_CMD: ${PYTHON_CMD}")` → `debugLog("  PYTHON_CMD: ${getPythonCmd() ?? "未初始化"}")`（注意：此时可能返回 null，因为惰性）
  9. shell.env 日志: `PYTHON_CMD=${PYTHON_CMD}` → `PYTHON_CMD=${getPythonCmd() ?? "未初始化"}`
- **验证点**: `node --check security-analysis.ts` 语法通过；grep 确认无 `PYTHON_CMD`（常量）引用

#### 步骤 3. detect_env.py — 配置驱动的安装命令

- **文件**: `binary-analysis/scripts/detect_env.py`
- **预估行数**: ~30 行
- **改动**:
  1. REQUIRED_PACKAGES 的 sage 条目加字段：
     ```python
     "sage": {
         "required": False,
         "pip_name": "sagemath-standard",
         "conda_name": "sage",
         "agents": ["crypto-analysis"],
         "preinstall": True,
         "installer": "conda",
     },
     ```
  2. 新增 `_build_install_cmd(info)` 函数：
     ```python
     def _build_install_cmd(info):
         """根据 info 的 installer 字段生成安装命令（配置驱动，不硬编码包名）。"""
         installer = info.get("installer", "pip")
         if installer == "conda":
             name = info.get("conda_name") or info["pip_name"]
             return f"conda install -p '{sys.prefix}' {name}"
         return f"{sys.executable} -m pip install {info['pip_name']}"
     ```
  3. `_check_preinstall` 中生成 install_cmd 的行：
     - 原: `install_cmd = f"{sys.executable} -m pip install {info['pip_name']}"`
     - 改: `install_cmd = _build_install_cmd(info)`
  4. `_check_preinstall` 中生成 install_hint 的描述行：
     - 原: `preinstall_desc_part1 = f"预装依赖 {name}（pip: {info['pip_name']}）未安装"`
     - 改: 去掉硬编码 "pip:"，改为通用描述 `f"预装依赖 {name}（{info.get('installer', 'pip')}: {info.get('conda_name') or info['pip_name']}）未安装"`
- **验证点**: `python -c "compile(open('detect_env.py').read(), 'detect_env.py', 'exec')"` 通过；`python detect_env.py --check-preinstall crypto-analysis` 输出的 install_hint 含 `conda install` 而非 `pip install`

#### 步骤 4. 新机器配置指南 — miniforge 前置 + conda 安装步骤

- **文件**: `docs/项目介绍/新机器配置指南.md`
- **预估行数**: ~50 行
- **改动**:
  1. "前置条件"段：删除 "Python 3.8+ 已安装"，改为 "Miniforge 已安装（提供 conda + Python）"
  2. "步骤 2. Python 依赖"段：更新说明为"Plugin 首次加载时通过 conda 创建虚拟环境（`~/bw-security-analysis/.venv`）"
  3. 手动安装命令的 venv python 路径不变（conda env 的 python 在同一路径）
  4. "步骤 2.5 SageMath"段重写：
     - 安装命令从 `~/bw-security-analysis/.venv/bin/pip install sagemath-standard` 改为 `conda install -p ~/bw-security-analysis/.venv sage`
     - 删除"不要用 conda 另起环境"的说明（现在就是用 conda）
     - 删除 macOS pip 退路说明（pip 路线已废弃）
     - 说明 conda 提供预编译 sage，无需编译依赖
  5. "常见问题"表：
     - "虚拟环境损坏"行：删除 `python -m venv` 重建说明，改为 `conda create -p ~/bw-security-analysis/.venv python=3.12`
     - 新增"conda 未安装"行：安装 miniforge 的平台命令
- **验证点**: 文件无 `pip install sagemath-standard`；含 miniforge 安装步骤；含 `conda install sage`

#### 步骤 5. crypto-methodology.md — sage 安装命令

- **文件**: `crypto-analysis/knowledge-base/crypto-methodology.md`
- **预估行数**: ~5 行
- **改动**:
  - 第 54 行: `~/bw-security-analysis/.venv/bin/pip install sagemath-standard` → `conda install -p ~/bw-security-analysis/.venv sage`
- **验证点**: 文件无 `pip install sagemath-standard`；含 `conda install sage`

#### 步骤 6. 全量验证

- **文件**: 无代码改动
- **验证点**:
  1. `node --check plugins/lib/venv.ts` 通过
  2. `node --check plugins/security-analysis.ts` 通过
  3. `python -c "compile(open('detect_env.py').read(), 'detect_env.py', 'exec')"` 通过
  4. grep 确认 security-analysis.ts 中无 `PYTHON_CMD`（常量引用，应全改为 `getPythonCmd()` 调用）
  5. grep 确认 venv.ts 中无 `findSystemPython`、无 `python -m venv`、无 `export const PYTHON_CMD`
  6. grep 确认全项目无 `pip install sagemath-standard`（除历史需求文档 `requirements/evolve/` 外）

## §4 验收标准

### 功能验收

- [ ] `getPythonCmd()` 首次调用时检测/创建 conda env，后续调用返回缓存值
- [ ] conda 不存在时 `getPythonCmd()` 返回 null，chat.message 输出友好的 miniforge 安装指引
- [ ] conda env 创建后 `getPythonCmd()` 返回 `~/bw-security-analysis/.venv/bin/python`（或 Windows 对应路径）
- [ ] `checkEnvironment()` 统一了 conda 检测和 preinstall 检测
- [ ] chat.message 调用 `checkEnvironment` 而非直接调 `checkPreinstall`
- [ ] detect_env.py `--check-preinstall crypto-analysis` 输出的 install_hint 含 `conda install -p ... sage`
- [ ] detect_env.py 的 `_build_install_cmd` 根据 `installer` 字段选择安装器（配置驱动）
- [ ] 新机器配置指南含 miniforge 安装步骤 + conda install sage

### 回归验收

- [ ] Plugin 加载成功（不再因 conda 缺失在模块顶层崩溃）
- [ ] 已有 conda env 的机器：`getPythonCmd()` 直接返回缓存路径，不触发重复创建
- [ ] shell.env 正常注入 PYTHON_CMD 环境变量
- [ ] detect_env.py 的自动安装（pip 包）在 conda env 里正常工作
- [ ] 所有非 sage 包仍通过 pip 安装（installer 字段缺省 = pip）
- [ ] 环境信息段正确显示 PYTHON_CMD 路径

### 架构验收

- [ ] venv.ts 不在模块顶层执行 env 创建（惰性 + 缓存）
- [ ] 环境检测收口到 checkEnvironment（单一入口）
- [ ] detect_env.py 安装命令配置驱动（无硬编码包名 if/else）
- [ ] pip 在 conda env 里照常工作（除 sage 外所有包不变）
- [ ] 依赖方向未违反（Plugin → agent → knowledge-base，单向）

## §5 与现有需求文档的关系

- **替代** `2026-05-26-unify-python-cmd-venv.md` 中的 venv 创建方式（`python -m venv` → `conda create -p`），但 `$PYTHON_CMD` 变量名和路径不变
- **继承** `2026-04-22-environment-dependency-hardening.md` 的环境检测理念，并将检测收口到 checkEnvironment
- **修正** `2026-06-27-crypto-analysis-agent.md` 中 sage 安装方式（从 pip 改为 conda）
- **不影响** 其他需求文档中的功能实现
