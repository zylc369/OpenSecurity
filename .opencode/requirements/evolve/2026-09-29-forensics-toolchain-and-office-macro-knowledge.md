# 需求: 取证工具链修复与 Office 宏知识补齐（binwalk 死包拆除 / oletools 入清单 / rg 供给 / KB·prompt 分诊）

> 状态: 已实施（2026-09-29，§6 实施结果与证据）
> 日期: 2026-09-29
> 来源: 2026-09-29 取证任务复盘——环境审计发现 binwalk 一跑即崩、oletools 不在依赖清单、rg 缺失、Office 宏知识与主流程分诊缺口

## §1 背景与目标

**痛点（复盘结论，均有工具取证）**:

1. **binwalk 供给链三层损坏**：任何调用直接 `ModuleNotFoundError: No module named 'binwalk.core'`——venv 装的是 PyPI 死包 `binwalk 2.1.0`（`site-packages/binwalk/` 仅含 `__init__.py`）；`detect_py_deps.py` 仍把它列为依赖；`detect_tools.py` 配方 `PkgToolRecipe(name="binwalk")` 的 `pkg_brew`/`pkg_linux` 均为空（mac 按类语义回落 docker，而 brew 现已有可用 3.1.0）；检测项名 `binwalk-full`（ext）与配方名 `binwalk` 不一致（改名残留）。4 个知识库文件以 `$(dirname $PYTHON_CMD)/binwalk` 形式引用（共 6 处），`toolbox-design.md` 备注也提及 pip 版——均指向坏包。forensics/固件/隐写任务必踩。
2. **oletools 不在依赖清单**：Office 宏文档分析（olevba/oleid/pcodedmp）依赖 oletools；py_deps 清单 70 条、工具层均无 oletools 痕迹，任务中临时安装（浪费轮次），环境重建后能力消失。
3. **rg 缺失但指引要求使用**：Bash 工具指引明确要求多文件检索用 `rg`；环境无 rg（detect_tools 无痕迹、`$OPENSECURITY_HOME/bin` 82 工具中无）——任务中实际踩到 `command not found`。
4. **KB 缺口（malware-analysis.md §8a）**: 缺 Office 宏实战技法（`-EncodedCommand` UTF-16LE 解码、pcodedmp 防 VBA stomping、`*.invalid` 判读、穷尽载体排查清单）；索引行触发词缺可观察形态。
5. **主流程缺非 PE 分诊（binary-analysis.md）**: 阶段 A 写死 idat 流水线，全文无非 PE/ELF 目标的处理说明——Office/PDF/pcap/镜像目标会误入 idat。

**目标**:

- binwalk 三层一致（依赖清单/安装配方/检测项）且 mac 原生可用（brew 3.1.0），linux 走 apt（v2），brew 失败自动回落 docker；
- oletools 入唯一依赖清单；新增旧死包拆除机制（防已装环境残留遮蔽 PM 版本）；
- rg 纳入工具层（官方 ReleaseRecipe）；
- KB 与 prompt 补齐 Office 宏取证知识与非 PE 分诊；prompt **净增 0 行**（展开行数维持 <450）。

## §2 技术方案

### §2.1 binwalk 供给链修复

- **拆除死包**：从 `detect_py_deps.PYTHON_PACKAGES` 移除 `PyPkgField(binwalk)`；已装过旧包的环境做一次性 `pip uninstall -y binwalk`（venv/bin 先于 /opt/homebrew/bin，残留死包会遮蔽 PM 版本并使配方安装被误跳过——`_install_pkgtool` 先 `shutil.which` 后安装）。**修订**: 不保留常驻自动拆除代码（理由与复验见 §6 修订记录）。
- **PM 原生**：`PkgToolRecipe(name="binwalk", pkg_brew="binwalk", pkg_linux="binwalk")`。mac=brew（stable 3.1.0，Rust 版，已实测签名扫描+提取可用）；linux=apt（Debian/Ubuntu/Kali 仓库均有 binwalk——Kali 现为 2.4.3+dfsg1，v2 线；Phase 0 手动清单提示）；brew 失败自动回落 docker（类内置行为，无需额外代码）。
- **检测项统一**：`_auto("binwalk-full", _BIN, ...)` → `_auto("binwalk", _BIN, "固件/嵌入文件签名扫描与提取", ["--version"])`；`binwalk-full` 名称全仓清零（口径与测试豁免见 §4）。
- **v3 CLI 实测口径**（mac 原生）：可用 `-e/--extract`、`-M/--matryoshka`（递归）、`-C/--directory <dir>`、`-E/--entropy`、`-a/--search-all`、`-x/-y` 签名过滤、`-l/--log`；**无 v2 的 `--dd`/`--carve`**（`--carve` 仅 master 未发布）。提取产物路径 `<dir>/<file>.extracted/<offset>/...`；gzip、zip 样例提取成功。
- **KB 调用口径**：统一写 `binwalk`（PATH 解析；只用 v2/v3 共有 flag）：`binwalk -e <file>`、递归 `binwalk -M -e <file>`、指定输出 `binwalk -e -C out <file>`；`--dd=".*"` 用法删除（改为 `-e` 口径；需全量 magic 雕刻时用 foremost）。

### §2.2 oletools 与旧包拆除

- `PYTHON_PACKAGES` 新增：`PyPkgField(name="oletools", pip_name="oletools", agents=["binary-analysis"], description="Office 宏文档分析与 VBA stomping 校验（olevba/oleid/pcodedmp; malware-analysis）")`。
- 检测/一键安装链路自动纳入（scan 走 `find_spec` + `importlib.metadata`；`/api/install` 白名单来自 `one_click_installable()`）。
- 旧包一次性卸载（不保留常驻自动拆除机制）——修订说明见 §2.1 / §6。

### §2.3 ripgrep 供给

- `ReleaseRecipe(name="rg", repo="BurntSushi/ripgrep", plats={…}, bins=["rg"], excl="sha256,.deb,.rpm")`：

| 平台 | 关键词（逗号分隔的 AND 组，组内 `|` 为 OR） |
|---|---|
| darwin-arm64 | `apple-darwin,aarch64` |
| darwin-amd64 | `apple-darwin,x86_64` |
| linux-amd64 | `unknown-linux,x86_64` |
| linux-arm64 | `unknown-linux,aarch64` |
| win-amd64 | `pc-windows-msvc,x86_64` |
| win-arm64 | `pc-windows-msvc,aarch64` |

- `excl` 必须含 `sha256`：上游 release 每个产物附 `.tar.gz.sha256`，不带排除会被 raw 分支当成二进制写入 `rg`（静默错误）。
- 检测项：`_auto("rg", ["binary-analysis", "web-analysis", "mobile-analysis", "crypto-analysis", "ai-security-analysis"], "多文件文本搜索（Bash 工具指引的 rg）", ["--version"])`。
- 产物落 `$OPENSECURITY_HOME/bin/rg`（agent PATH 内，venv 之后解析）。

### §2.4 知识库更新

| 文件 | 改动 |
|---|---|
| `forensics-methodology.md` | ① carving 命令 2 行改 v3 口径（`-e` / `-e -C`；去 `--dd`）；② 工具表 binwalk 行路径改 `binwalk`；③ 分诊表新增 Office 宏行（指向 `malware-analysis.md` §8a） |
| `windows-forensics.md` | `$(dirname $PYTHON_CMD)/binwalk` → `binwalk`（1 处） |
| `steganography-forensics.md` | 同上（1 处） |
| `disk-memory-forensics.md` | 同上（1 处） |
| `control/docker/toolbox-design.md` | binwalk 行备注更新：pip 版拆除；mac=brew v3；容器版=v2 完整版兜底 |
| `malware-analysis.md` | §8a 扩充 6 条要点（见下）；索引行触发词在 prompt 侧同步 |

§8a 扩充要点（按知识编写规范，无来源叙事、具体可执行）：① pptm/docm/xlsm=zip，宏在 `ppt|word|xl/vbaProject.bin`；② `olevba` 提取源码并自动标注 Suspicious/IOC；③ `-EncodedCommand` base64 一律 UTF-16LE 解码（判别：raw 中 `\x00` 占比高 / `24 00` 开头）；④ `pcodedmp` 防 VBA stomping（p-code `LitStr` 与源码逐字对照；console script 调用，不能 `python -m`）；⑤ `*.invalid` 为 RFC 2606 保留域，不联网复现，载荷/flag 在宏常量里；⑥ 穷尽载体排查（字面 flag 扫描 / 嵌入 PE·ZIP / 图片 IEND·EOI 尾部 / ZIP comment·EOCD / 残留文本框提示）。

### §2.5 Agent prompt 更新（净 0 行）

`agents/binary-analysis.md`：

- 阶段 A 触发条件行**行内改写**：补"非 PE/ELF 载体（Office 文档/PDF/pcap/镜像/流量）不走 idat → 按对应知识库文档执行（Office 宏 → `malware-analysis.md` §8a），从阶段 B 继续"。
- 知识库索引 `malware-analysis.md` 行触发词**行内改写**：补 `.docm/.pptm/.xlsm` 可观察形态。
- 行数约束：现展开 449 行（273 行文件 − 7 占位符 + 183 片段行），两处均为行内改写 → 展开行数保持 449 < 450。

## §3 实现规范

### §3.1 实施步骤

1. **detect_py_deps.py：移除 binwalk 死包 + 新增 oletools**
   - 文件: `control/backend/services/detect_py_deps.py`（as-built：−2（binwalk 条目）+2（oletools 条目），净 0）
   - 验证点: `python -c compile`；`detect_py_deps.py scan --json` 断言无 binwalk、oletools 存在且 `available=true`；`install --dry-run` 输出含 oletools 不含 binwalk；`pip show binwalk` 为空（本机一次性卸载，见 §6 修订）
   - 依赖: 无
2. **detect_tools.py：binwalk 配方与检测项修复**
   - 文件: `control/backend/services/detect_tools.py`（约 3 行：配方行 + `_auto` 行）
   - 验证点: `python -c compile`；审计脚本断言 `binwalk` 配方 `pkg_brew=="binwalk"`、`EXTERNAL_TOOLS` 有 `binwalk` 且无 `binwalk-full`、`version_cmd==["--version"]`
   - 依赖: 无
3. **detect_tools.py：rg 配方 + 检测项新增**
   - 文件: `control/backend/services/detect_tools.py`（约 +14 行）
   - 验证点: `python -c compile`；审计脚本断言配方存在、bins==["rg"]、excl 含 sha256、六个平台 `plats` 关键词能匹配上游资产名（对照 15.2.0 资产清单静态样例）
   - 依赖: 无
4. **真机落地验证：binwalk 走新配方 + rg 安装 + 路径真值**
   - 步骤: `pip uninstall -y binwalk` → `brew uninstall binwalk` → `ToolsInstaller.install_tool("binwalk")`（走 brew 分支）→ 校验 `which binwalk`=/opt/homebrew/bin/binwalk、`binwalk --version`=3.1.0、`binwalk -e` 样例提取 → `install_tool("rg")` → `rg --version`、样例检索 → `ToolsScanner` 断言双绿
   - 验证点: 上述命令输出正确；scan_tool available=True；证据记录 progress.md
   - 依赖: 1、2、3
5. **知识库：binwalk 调用口径更新（4 KB + toolbox-design）**
   - 文件: `forensics-methodology.md` / `windows-forensics.md` / `steganography-forensics.md` / `disk-memory-forensics.md` / `control/docker/toolbox-design.md`
   - 验证点: `grep -rn "dirname \$PYTHON_CMD)/binwalk"` 全仓 0 残留（口径见 §4 回归验收注）；命令与 v3 `--help` 一致；编辑后各文件 NUL/控制字节扫描；人工读
   - 依赖: 4（v3 真值）
6. **知识库：malware-analysis.md §8a 扩充**
   - 文件: `binary-analysis/knowledge-base/malware-analysis.md`（约 +9 行）
   - 验证点: 人工读自包含；叙事词（实测/来源/赛事名）grep 清零；NUL 扫描；`olevba`/`pcodedmp` 命令抽样实测可执行
   - 依赖: 无
7. **知识库：forensics-methodology.md 分诊表新增 Office 宏行**
   - 文件: `forensics-methodology.md`（+1 行）
   - 验证点: 表格排版正确；指向目标存在（`malware-analysis.md` §8a）；NUL 扫描
   - 依赖: 6
8. **Agent prompt：binary-analysis.md 分诊 + 索引触发词（净 0 行）**
   - 文件: `agents/binary-analysis.md`（2 处行内改写）
   - 验证点: 展开行数复算 =449（<450）；占位符 7 个展开无残留；人工读核心规则未损
   - 依赖: 无
9. **测试固化：3 个回归用例 + pyright**
   - 文件: `control/backend/tests/test_control.py`（约 +35 行，置于 detect_tools 测试区）
   - 用例: ① `detect_tools: binwalk 检测项与配方一致（回归线）`；② `detect_tools: rg 配方存在且排除 sha256`；③ `detect_py_deps: binwalk 死包已移除 + oletools 在清单`
   - 验证点: 测试运行器无筛选参数——用自制 runner 导入 `tests/test_control.py` 仅执行选定用例（3 新 + 既有 `detect_tools` / CLI deps 相关），不启动 E2E 共享服务；`basedpyright` 对变更文件 UndefinedVariable=0
   - 依赖: 1、2、3
10. **全量回归 + 收尾**
    - 步骤: 按模式 K 纪律跑 test_control 全量（目标 90/90）：停生产 → 全量 → 拉起生产；若当前时段不宜停机，先以定向 runner 收口，全量留待约定窗口；需求文档补 §6 实施结果；progress.md 标记完成
    - 验证点: 全量绿（或失败仅为本变更无关项且记录）；生产恢复可访问
    - 依赖: 全部

### 架构影响图（Phase 4）

```
detect_py_deps.py（唯一清单）
  ├─ scan / --json ──→ env-check.ts（插件自举） + /api/deps + 前端控制台
  ├─ required_packages ──→ install.sh → _run_install（含新增拆除块）
  └─ one_click_installable ──→ /api/install 白名单
detect_tools.py（工具层）
  ├─ EXTERNAL_TOOLS ──→ ToolsScanner → /api/deps + install_hint（agent 侧提示）
  └─ installable_tools ──→ install.sh / install_tool → _install_pkgtool(brew/apt/docker) / _install_release
知识库 4 文件 + toolbox-design.md ←→ agents/binary-analysis.md 索引行（触发词可达性）
tests/test_control.py（回归线）←→ 上述 services 两文件
```

影响方向均为既有单向（services → scan/install → 插件/控制台；prompt → 知识库），无新增反向依赖。

### 改动范围表

| 文件 | 改动 | 预估行数 |
|---|---|---|
| `control/backend/services/detect_py_deps.py` | −binwalk、+oletools | ±0（−2/+2） |
| `control/backend/services/detect_tools.py` | binwalk 配方/检测修复 + rg 配方/检测 | +14 |
| `control/backend/tests/test_control.py` | 3 个回归用例 | +35 |
| `agents/binary-analysis.md` | 分诊 + 触发词（行内改写） | ±0 |
| `binary-analysis/knowledge-base/malware-analysis.md` | §8a 扩充 | +9 |
| `binary-analysis/knowledge-base/forensics-methodology.md` | carving 口径 + 工具表 + 分诊行 | +1 |
| `binary-analysis/knowledge-base/windows-forensics.md` | 路径口径 | ±0 |
| `binary-analysis/knowledge-base/steganography-forensics.md` | 路径口径 | ±0 |
| `binary-analysis/knowledge-base/disk-memory-forensics.md` | 路径口径 | ±0 |
| `control/docker/toolbox-design.md` | binwalk 行备注 | ±0 |

## §4 验收标准

**功能验收**:

- `which binwalk` → `/opt/homebrew/bin/binwalk`；`binwalk --version` → `binwalk 3.1.0`；`binwalk -e` 对 gzip/zip 样例提取成功（产出 `<file>.extracted/<offset>/…`）。
- `which rg` → `$OPENSECURITY_HOME/bin/rg`；`rg --version` → `ripgrep 15.2.0`；对样例目录检索正确。
- `detect_py_deps.py scan`：输出无 binwalk、有 oletools（available）；`/api/deps/binary-analysis` 同口径。
- `ToolsScanner`：binwalk、rg `available=True` 且 version 正确。
- `pip show binwalk` 为空（本机一次性卸载完成；常驻拆除机制经修订移除，见 §6）；`brew uninstall binwalk` 后重跑 `install_tool("binwalk")` 能重新装上（配方路径可复现）。

**回归验收**:

- test_control 全量 90/90（87 存量 + 3 新增；按生产停机纪律执行）。
- `basedpyright` 变更文件 UndefinedVariable=0。
- `agents/binary-analysis.md` 展开行数复算 449 < 450；占位符展开零残留。
- 知识库 grep：`binwalk-full` 全仓 0；`dirname $PYTHON_CMD)/binwalk` 全仓 0。
  注：**全仓口径** = `agents/` + `agents-rules/` + `binary-analysis/knowledge-base/` + `control/`（后端 services + docker 文档 + 前端）；排除 `node_modules`、`__pycache__`（旧 pyc 可能残留字符串）与 `requirements/evolve/`（历史批次档案不追改）；`control/backend/tests/` 允许且**仅允许**"反断言"字面（`"binwalk-full" not in ...` 及其 docstring——回归用例需要该字面），两类之外出现即失败。

**架构验收**:

- 无新增运行时文件（rg/binwalk 产物落既有 `$OPENSECURITY_HOME/bin`，符合工具层归属）；无循环依赖；变更集中在控制台后端唯一清单 + 知识库 + agent prompt 既有结构。

## §5 与现有需求文档的关系

- `progress-2026-09-05-evolve.md`（PM 化批次）：binwalk-full→binwalk 改名终检遗漏（`_auto` 残留一行）——本需求修复该残留并补 v3 口径。
- `E1-portable-matrix.md`：其 "binwalk-full 保留 docker" 判定基于当时 brew 无包；现状 brew 有 3.1.0 → mac 走原生，docker 降为失败回落。E1 作为历史批次档案不追改，以本需求为准。
- `pending-items.md`（E2E 端口隔离，模式 K）：影响本轮全量回归执行方式（生产停机纪律），本需求遵守不扩面。
- `2026-09-29-pyright-introduction.md`：变更 Python 文件沿用其回归线（UndefinedVariable=0）。

## §6 实施结果

**完成于 2026-09-29**（同一工作会话；全部验收过）。

**as-built（git diff 口径）**:

- `detect_py_deps.py` ±0（−2/+2）：移除 binwalk 死包、新增 oletools 条目；常驻拆除块经修订移除（见下）。
- `detect_tools.py` +13/−2：binwalk 配方 `pkg_brew="binwalk"/pkg_linux="binwalk"`；`_auto` 改名 `binwalk`；新增 rg `ReleaseRecipe`（六平台 plats + `excl="sha256,.deb,.rpm"`）+ `_auto("rg", 5 agents)`。
- `test_control.py` +41：3 个回归用例（binwalk 一致线 / rg sha256 排除 / py_deps 清单不变量）。
- `binary-analysis.md` ×2 行内改写（净 0 行）：阶段 A 非 PE/ELF 分诊 + 索引触发词；展开行数 449 保持 < 450。
- KB 5 文件：`forensics-methodology.md`（carving v3 口径 + 工具表 + Office 分诊行）；`malware-analysis.md` §8a 7 要点（+6 行）；`windows-forensics.md`/`steganography-forensics.md`/`disk-memory-forensics.md` 路径口径；`toolbox-design.md` 备注。
- 新增：本需求文档、任务目录 `progress.md`。

**验证证据**:

- 工具链：清场后 `install_tool("binwalk")` → `installed | brew install binwalk`；`install_tool("rg")` → `installed | ripgrep-15.2.0-aarch64-apple-darwin.tar.gz → rg`；`which -a binwalk` = `/opt/homebrew/bin/binwalk`、`rg` = `$OPENSECURITY_HOME/bin/rg`；`binwalk --version`=3.1.0；gzip/zip `-e -C` 提取成功；fake-encrypted zip 经 v3 `-e` 提取成功；`rg -n` 样例检索命中。
- 扫描/接口：`scan --json` 无 binwalk、oletools available 0.60.2；`GET /api/deps/binary-analysis`（重启后）tool binwalk 3.1.0 / rg 15.2.0 / oletools available / `required_missing=[]`。
- 回归：test_control 全量 **90/90**（停生产窗口执行；恢复 pid 75383 / boot_token 4f750781 / health ok）；basedpyright UndefinedVariable=0（总错误 57，无新增；余为存量类型流精确性）。
- 一次性清理（本机）：`Successfully uninstalled binwalk-2.1.0`；brew 3.1.0 原生就绪。
- grep 口径：`binwalk-full` 0 残留（口径内；`tests/test_control.py` 仅存回归反断言 2 处——`not in` 断言与 docstring，属预期）；`dirname $PYTHON_CMD)/binwalk` 0 残留；5 个 KB 文件 NUL/CTRL = 0。

**执行偏差（如实记录）**:

- 步骤 7 的分诊行编辑随步骤 5 同文件批次落地（编辑动作合并；步骤 7 验证点独立执行）——progress.md 已记录。
- 调研期先装 brew binwalk 作为 v3 真值来源；步骤 4 以 `uninstall → install_tool` 重装复现配方路径（未走"第一次安装"路径的原始形态，属等价复现）。
- pyright 错误总量 58 → 57（存量计数演进，与本轮无因果）。

**修订记录**: **修订 1（用户 review 反馈，同日）**: 移除 `_LEGACY_REMOVALS` 常驻自动拆除块——一次性历史清理不值当常驻代码，且覆盖不完整（单工具安装路径 `install --tool` 不经过该块）；现实环境仅本机（已一次性卸载完成）。测试同步去掉该断言（`test_detect_py_deps_list_invariants` 保留"死包不在清单 / oletools 在清单"两条不变量）；旧环境迁移说明由本节"一次性清理"承载。**复验（修订后终态）**: test_control 全量 **90/90**（停生产窗口执行；恢复 pid 56273 / boot_token be9fd598 / health ok）、`scan` 无 binwalk / oletools available、basedpyright UndefinedVariable=0、`_LEGACY_REMOVALS` 代码引用清零。

**决策附注（pip 渠道为何移除——防未来重复评估）**:

- PyPI `binwalk`：唯一版本 2.1.0（2015-01），包内容缺 `binwalk.core`——**全平台** import 即崩；pip 渠道从未提供过可用的 binwalk。
- 官方 v2（Python）从未发布到 PyPI；从 GitHub 源码 `pip install git+…@v2.3.4` 在本环境 Python 3.13 实测失败（`No module named 'imp'`，该模块 py3.12 起被移除）。
- 官方 v3（Rust）：GitHub releases **全部 0 预编译资产**（无法走 rg 式 ReleaseRecipe 便携分发）；官方渠道即 brew/apt/cargo/源码。
- 第三方 PyPI `binwalk3`（zacharyflint）：仓库已 404、单版本 wheel 仅捆绑 Windows 自编译二进制，mac/linux 分支退化为 `shutil.which("binwalk")`（要求系统已装）——不构成 pip 跨平台方案，且供应链风险高。
- 结论：mac=brew v3 / linux=apt v2 / win=docker 兜底是当前"每平台可用且来路可信"的唯一组合；跨平台覆盖从 0（全平台坏包）升至全平台有解。
- **Windows 具体路由**: docker wrapper（系统全平台策略的一部分——40+ 工具在 win 走 docker：5 个显式 DockerRecipe + 16 个无 mac/linux 包的 PkgToolRecipe；上游 README 亦将 docker 列为最省事的安装法）；Windows 无原生包（Chocolatey 无、上游无预编译资产、pip 死路）。可选增强 = 自编译 v3 入库 `PrebuiltRecipe`（需 Windows 构建机 + 实机验证）。Windows 分支整体未实机验证（`pending-items` #5），wrapper 状态解析检查点已补录。

**验证边界（如实）**: 本轮的实机验证全部在 **macOS(arm64)** 完成（工具链/接口/90 用例/pyright 均此一平台）。**Linux（apt 路径）与 Windows（docker 路径）未在任何实机执行**——Linux 侧已核仓库包存在性（Debian/Ubuntu/Kali 均有；Kali=2.4.3+dfsg1）并做两层补充验证：① Kali 容器内 apt 版 binwalk（v2 线）实测 `-e -C` 提取可用（产物 `_<file>.extracted/`；v2 不支持 `--version`，版本显示为空、不影响可用性判定）；② 安装器 linux 分支进程内模拟通过（`需手动安装: sudo apt install -y binwalk`）。整机安装流未实机。Windows 侧 docker 目标核验（分支模拟 → `opensecurity/toolbox-core` 容器）通过，但 wrapper 实机执行未验证，wrapper 状态解析疑点已补录 `pending-items` #5。macOS Intel 同渠道（brew）未实机。

**待后续**: 无新增挂起项。全量回归所需的"停生产"纪律源自 `pending-items` 模式 K（E2E 端口隔离未根治），本轮遵守未扩面。
