# 需求文档: BinaryAnalysis Agent 全面审查修复

## §1 背景与目标

**来源**: Phase 0 复盘分析，对 BinaryAnalysis Agent 的全面审查。

**痛点**:
- M1/M3: `$SCRIPTS_DIR` 和 `$IDAT` 变量从未赋值，所有 idat 调用会失败
- M2: Windows 上 `python3` 不存在，需每次手动替换
- M4: Agent 不支持 `$ARGUMENTS` 模板变量，prompt 中的表述误导 AI
- M6: 缺少新机器配置步骤文档
- P2: classify_scene 不检测 frida 可用性
- P4: debug_dump.py 仅支持 PE，ELF/Mach-O 无法 dump
- P5: frida_unpack.py 引用路径使用脆弱的相对路径
- 动态分析评估: 缺少 Unicorn 模拟和 Frida Hook 的完整可运行模板

**预期收益**: 减少 Agent 在变量赋值和跨平台适配上的试错轮次，提高移植性和覆盖面。

## §2 技术方案

### R1: Agent prompt 添加变量赋值指引

**改动文件**: `.opencode/agents/binary-analysis.md`

在"运行环境"章节之后、"参数解析规则"之前，新增"变量初始化"章节。

Agent prompt 中的实际文本（直接写入 binary-analysis.md）:

    ## 变量初始化（每轮对话首次执行前）

    从 Plugin 注入的环境信息中提取关键路径。如果环境信息段包含 `脚本目录 ($SCRIPTS_DIR): <路径>` 和 `IDA Pro: <路径>`，
    直接使用这些值赋值。如果环境信息未注入，从 config.json 读取。

    **Linux/macOS (bash)**:

        SCRIPTS_DIR=<从环境信息中提取的脚本目录路径>
        IDAT=$(python3 -c "
        import os, sys, json
        c = json.load(open(os.path.expanduser('~/bw-security-analysis/config.json')))
        p = c.get('ida_path','')
        for n in ['idat','idat.exe']:
            f = os.path.join(p, n)
            if os.path.isfile(f):
                print(f); break
        else:
            print(''); sys.exit(1)
        ")

    **Windows (PowerShell)**:

        $SCRIPTS_DIR = "<从环境信息中提取的脚本目录路径>"
        $IDAT = python -c "import os,sys,json; c=json.load(open(os.path.expanduser('~/bw-security-analysis/config.json'))); p=c.get('ida_path',''); [print(os.path.join(p,n)) or None for n in ['idat.exe','idat'] if os.path.isfile(os.path.join(p,n))][:1] or sys.exit(1)"

    **验证**: 变量赋值后执行 `echo $SCRIPTS_DIR` / `echo $IDAT`（PowerShell 用 `echo $SCRIPTS_DIR` / `echo $IDAT`）确认非空。

注意: bash 模板使用 `python3`（仅 Linux/macOS），Windows 统一使用 PowerShell 模板（使用 `python`）。

### R2: templates.md 添加 Windows PowerShell 命令模板

**改动文件**: `.opencode/binary-analysis/knowledge-base/templates.md`

在现有 bash 模板之后，新增 PowerShell 替代模板。覆盖：
- 预检查脚本
- TASK_DIR 创建
- idat 调用（查询/更新/初始分析/沉淀脚本）

### R3: 新机器配置步骤文档

**改动文件**: 新增 `.opencode/commands/security-analysis-docs/setup-guide.md`

端到端步骤：(1) clone 仓库 (2) 初始化子模块 (3) 安装依赖 (4) 运行 detect_env.py (5) 创建 config.json (6) 在 OpenCode 中选择 Agent。

### O1: 修复 $ARGUMENTS 表述

**改动文件**: `.opencode/agents/binary-analysis.md`

将"参数解析规则"章节中的 `用户输入：$ARGUMENTS` 替换为:

    **用户输入**：从对话消息中获取用户的原始输入。

### O2: classify_scene 检测 frida 可用性

**改动文件**: `.opencode/binary-analysis/_analysis.py`

在 `classify_scene()` 的 GUI 场景中，检查 frida 是否可用。新增参数 `packages` 传入 detect_env 检测结果。

**数据流方案**: initial_analysis.py 通过环境变量 `IDA_ENV_JSON` 读取 detect_env 的缓存文件路径，解析后传入 `classify_scene()` 的 `packages` 参数。如果 `IDA_ENV_JSON` 未设置，则 `packages=None`（向后兼容）。

**函数签名变更**:
```python
def classify_scene(packer_info, strings, import_names, architecture, file_type, packages=None):
```

`packages` 是 detect_env.py 输出的 `data.packages` 字典。访问时使用防御性访问: `packages.get("frida", {}).get("available", False)`。

当 frida 不可用时，GUI 场景的推荐操作中添加 `"frida_available": false` 标记，Agent 可据此跳过 Frida 方案。

**initial_analysis.py 同步修改**: 在 `_main()` 中读取 `IDA_ENV_JSON` 环境变量，解析 packages 后传入 `classify_scene()`。

### O3: 新增 Unicorn 模拟脚本模板

**改动文件**: 新增 `.opencode/binary-analysis/knowledge-base/unicorn-templates.md`

内容：
- 完整的 Unicorn 模拟 IDAPython 脚本（可作为沉淀脚本通过 idat headless 运行）
- 完整的纯 Python Unicorn 模拟脚本（不依赖 IDA 运行时）
- 覆盖 x86/x86_64 架构
- 包含从 IDA 数据库提取二进制数据的模板

### O4: 新增 Frida Hook 脚本模板

**改动文件**: 新增 `.opencode/binary-analysis/knowledge-base/frida-hook-templates.md`

内容：
- Frida Hook 完整 Python + JS 脚本模板
- 参数拦截、返回值读取、内存读取的通用模板
- 进程清理模板
- Frida 16/17 兼容写法

### O5: debug_dump.py 增加 ELF dump 支持

**改动文件**: `.opencode/binary-analysis/scripts/debug_dump.py`

新增 `_dump_elf_segments()` 和 `_rebuild_elf()` 函数。通过 `ida_ida.inf_get_filetype()` 判断文件类型: PE 走原有 PE dump 分支，ELF 走新增 ELF dump 分支。

**DumpHook.dbg_run_to() 流程变更**:
1. 先调用 `ida_ida.inf_get_filetype()` 判断文件类型
2. PE: 保持原有 `_detect_image_base()` + `_dump_segments_from_pe()` + `_rebuild_pe()` 流程不变
3. ELF: 调用 `_dump_elf_segments()`（从 IDA 段数据库读取）+ `_rebuild_elf()`

**ELF dump 策略**: 遍历 IDA 段数据库读取所有段数据 → 写入新 ELF 文件（ELF header + program headers + 段数据）。

**输出路径**: 复用 `IDA_PE_OUTPUT` 环境变量（改名为语义上的"dump 输出路径"），根据文件类型自动调整扩展名（PE → .pe，ELF → .elf）。

**本轮仅覆盖 ELF，Mach-O 留待后续**（Mach-O 需要不同的 segment 加载逻辑，复杂度较高）。

### O6: registry.json verified 标记

**改动文件**: `.opencode/binary-analysis/scripts/registry.json`

由于端到端测试无法在本轮执行（需要真实 .i64 文件 + idat），保持 `verified: false`，但在 description 中添加"需要端到端验证"标注。

**决策**: 不做 verified 改标。仅更新 registry.json 的描述: debug_dump 描述改为"dump 内存段并重建可执行文件（PE/ELF）"，标记 `verified: false`。

### O7: frida_unpack.py 引用改为基于项目根目录

**改动文件**: `.opencode/binary-analysis/knowledge-base/packer-handling.md` 和 `.opencode/binary-analysis/knowledge-base/dynamic-analysis-frida.md`

`frida_unpack.py` 已迁移到 `$SHARED_DIR/scripts/frida_unpack.py`（与其他 binary-analysis 脚本同级），直接用 `$SHARED_DIR/scripts/frida_unpack.py` 引用即可。

## §3 实现规范

### 改动范围表

| 文件 | 改动类型 | 影响范围 | 风险等级 |
|------|---------|---------|---------|
| `.opencode/agents/binary-analysis.md` | 修改 | Agent 行为 | 高 |
| `.opencode/binary-analysis/knowledge-base/templates.md` | 修改 | 命令构造 | 中 |
| `.opencode/commands/security-analysis-docs/setup-guide.md` | 新增 | 文档 | 低 |
| `.opencode/binary-analysis/_analysis.py` | 修改 | 场景分类 | 中 |
| `.opencode/binary-analysis/scripts/initial_analysis.py` | 修改 | 初始分析 | 中 |
| `.opencode/binary-analysis/knowledge-base/unicorn-templates.md` | 新增 | 知识库 | 低 |
| `.opencode/binary-analysis/knowledge-base/frida-hook-templates.md` | 新增 | 知识库 | 低 |
| `.opencode/binary-analysis/scripts/debug_dump.py` | 修改 | 脱壳 dump | 中 |
| `.opencode/binary-analysis/knowledge-base/packer-handling.md` | 修改 | 脱壳策略 | 低 |
| `.opencode/binary-analysis/knowledge-base/dynamic-analysis-frida.md` | 修改 | Frida 策略 | 低 |
| `.opencode/binary-analysis/scripts/registry.json` | 修改 | 注册表 | 低 |

### 编码规则

- IDAPython 脚本遵循 `knowledge-base/idapython-conventions.md`
- 知识库文档自包含，不依赖主 prompt 上下文
- 路径使用相对路径或基于 `$SCRIPTS_DIR` 的路径
- 新增函数不改变现有函数签名（除 O2 的 `packages` 参数有默认值）
- O2 中 packages 访问必须使用防御性访问: `packages.get("frida", {}).get("available", False)`

## §4 验收标准

### 功能验收

- [ ] Agent prompt 包含变量初始化指引，`$SCRIPTS_DIR` 和 `$IDAT` 有明确的赋值方法
- [ ] templates.md 包含 Windows PowerShell 替代命令模板
- [ ] setup-guide.md 覆盖从零配置的完整步骤
- [ ] `$ARGUMENTS` 表述已修正为"从对话消息中获取用户的原始输入"
- [ ] `classify_scene()` 接受 `packages` 参数且向后兼容（防御性访问）
- [ ] `initial_analysis.py` 通过 `IDA_ENV_JSON` 读取 detect_env 缓存并传入 `classify_scene()`
- [ ] unicorn-templates.md 包含可运行的完整模板
- [ ] frida-hook-templates.md 包含可运行的完整模板
- [ ] debug_dump.py 支持 ELF 格式 dump（仅 ELF，Mach-O 不在本轮范围）
- [ ] frida_unpack.py 引用路径不再使用脆弱的相对路径（packer-handling.md 和 dynamic-analysis-frida.md 都已更新）

### 回归验收

- [ ] Agent prompt 行数 < 450（Phase 4.5 检查）
- [ ] `_analysis.py` 的 `classify_scene()` 默认参数（无 packages）行为不变
- [ ] `initial_analysis.py` 调用 `classify_scene()` 不受影响（无 `IDA_ENV_JSON` 时行为不变）
- [ ] 知识库索引表更新（binary-analysis.md 中引用新增的 unicorn-templates.md 和 frida-hook-templates.md）
- [ ] README.md 更新

### 架构验收

- [ ] 依赖方向不变: `_base.py ← _utils.py ← _analysis.py ← query.py / update.py / scripts/*.py`
- [ ] 新增知识库文件在 knowledge-base 目录下
- [ ] setup-guide.md 在 security-analysis-docs 目录下

## §5 与现有需求文档的关系

- 本文档独立于之前的两轮需求文档（plugin-and-architecture-improvements.md、knowledge-and-ops-improvements.md）
- 前两轮的改动已全部完成，本文档是第三轮进化
- O5 的 debug_dump.py 改动基于第一轮创建的原始文件
