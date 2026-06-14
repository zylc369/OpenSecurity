# 需求文档: CRACKME3 复盘改进 — 进程 Patch 工具 + PowerShell 修复 + 分析流程优化

## §1 背景与目标

**来源**: CRACKME3 (CORE CrackMe v2.0) 逆向分析复盘。用户确认的 5 个改进方案（3 个推荐做 + 2 个可选做）。

**痛点**（按浪费排序）:
1. 动态分析缺乏可复用工具 — 22 个手写 ctypes 脚本（~4000 行）重复相同的 OpenProcess/VirtualProtectEx/WriteProcessMemory 样板代码
2. query.py 在 Windows PowerShell 下 3 次执行失败 — Agent 使用 bash 语法导致环境变量未传递
3. gui_verify.py hook 模式能力不足 — 无法满足 code cave 注入 + 值捕获 + 进程暂停的复合场景
4. MD5 hash 计算错误 1 次 — 假设 MD5 是标准算法，未先验证假设就深入分析
5. crypto signal 检测太弱 — 只检测 hex table/base64 table，未识别 MD5 init 常量
6. initial_analysis 噪声字符串 — 加壳二进制返回 200 条乱码字符串浪费上下文

**目标**:
- 方案 A: 新增 `process_patch.py` 通用进程 patch 工具，覆盖 P0+P2
- 方案 B: 修复 Agent prompt 的 PowerShell 执行模板，覆盖 P1
- 方案 C: 在分析流程中增加"先验证假设"规则，覆盖 P3
- 方案 D: 增强 crypto signal 检测，覆盖 P4
- 方案 E: 加壳二进制字符串降噪，覆盖 P5

**预期收益**:
- 上下文: 22 个手写脚本 → 3-5 次工具调用（-85%）
- 轮次: ~80 轮浪费 → ~10 轮（-87%）
- 速度: 省去 20+ 次脚本生成/调试（~25 分钟）
- 准确度: 减少级联错误（假设验证 + 工具化减少手写 bug）

## §2 技术方案

### 方案 A: process_patch.py

**架构位置**: `.opencode/binary-analysis/scripts/process_patch.py`（独立 Python 工具，通过 `$BA_PYTHON` 运行，不依赖 IDA）

**核心设计**: 将 CRACKME3 中重复 10+ 次的进程管理/内存操作/信号同步模式提取为命令行工具。Agent 只需提供 patch 点地址和新字节，code cave 机器码，无需写 OpenProcess/VirtualProtectEx 等样板。

**命令行接口**:

```
process_patch.py --exe TARGET [--window-title TITLE] \
  [--patch ADDR:HEXBYTES] ... \
  [--write-data ADDR:HEXBYTES] ... \
  [--write-code ADDR:HEXBYTES] ... \
  [--capture ADDR:SIZE] ... \
  [--signal ADDR:VALUE] \
  [--trigger ACTION:PARAM] \
  [--timeout SEC] \
  --output RESULT.json
```

**参数说明**:

| 参数 | 必填 | 说明 |
|------|------|------|
| `--exe` | 是 | 目标可执行文件路径 |
| `--window-title` | 否 | 查找窗口的标题子串（默认用 exe 文件名） |
| `--patch ADDR:HEXBYTES` | 否 | 在指定地址写入补丁字节（自动 VirtualProtectEx），可多次使用 |
| `--write-data ADDR:HEXBYTES` | 否 | 在指定地址写入数据字节（同 patch，语义区分） |
| `--write-code ADDR:HEXBYTES` | 否 | 在指定地址写入代码字节（额外 FlushInstructionCache），可多次使用 |
| `--capture ADDR:SIZE` | 否 | 捕获指定地址和大小的内存数据（十六进制），可多次使用 |
| `--signal ADDR:VALUE` | 否 | 信号地址和期望值（轮询等待），如 `0x42248C:DEADBEEF` |
| `--trigger ACTION:PARAM` | 否 | 触发动作。支持: `click:CTRL_ID`（BM_CLICK 到控件）、`message:CTRL_ID:MSG_ID` |
| `--timeout` | 否 | 信号等待超时（秒），默认 15 |
| `--settle` | 否 | 触发后等待时间（秒），默认 2 |
| `--output` | 是 | 输出 JSON 路径 |

**输出格式**:

```json
{
  "success": true,
  "pid": 12345,
  "patches_applied": ["0x40234C:EB", "0x402259:E9XXXXXX909090"],
  "captures": {
    "0x422480": {"hex": "0D15B8BA2C8F3057...", "size": 16}
  },
  "signal_received": true,
  "error": null
}
```

**执行流程**:
1. 启动目标进程，等待窗口出现
2. OpenProcess(PROCESS_ALL_ACCESS)
3. 对所有 patch/write_data/write_code 地址执行 VirtualProtectEx(PAGE_EXECUTE_READWRITE)
4. 按顺序执行所有 write_data → write-code → patch
5. 对 write-code 地址额外 FlushInstructionCache
6. 执行 trigger 动作（如 BM_CLICK）
7. 如果指定了 signal: 轮询等待信号值出现（每 0.5s 检查，超时报错）
8. 如果指定了 capture: 读取所有 capture 地址的数据
9. 终止进程，输出 JSON

**平台支持**: 仅 Windows（使用 ctypes + kernel32/user32）。Linux/macOS 可后续扩展。

### 方案 B: 修复 PowerShell 执行模板

**架构位置**: `.opencode/agents/binary-analysis.md`（Agent prompt）

**改动**: 在"工具脚本清单"部分的 query.py 调用示例中，补充 PowerShell 版本模板。在"阶段 A"的 idat 调用示例中同时给出 bash 和 PowerShell 版本。

关键：确保 PowerShell 版本使用 `$env:VAR="value"` + `& "$IDAT"` 语法，并正确处理路径中的空格。

### 方案 C: 先验证假设

**架构位置**: `.opencode/agents/binary-analysis.md`（Agent prompt）

**改动**: 在"阶段 C：执行与监控"的"常见失败模式与切换方向"表格中，增加一条规则：

```
| 假设标准算法但结果不匹配 | 停止推理，先用动态分析捕获实际值，与标准算法输出对比 |
```

并在"逆向分析核心原则"中增加第 6 条：
```
6. **假设必须验证** — 当假设使用了标准算法时，先用已知输入+动态捕获对比，不一致则立即停止基于该假设的推理
```

### 方案 D: 增强 crypto signal 检测

**架构位置**: `.opencode/binary-analysis/_analysis.py`（层 2.5）

**改动**: 在 `classify_scene()` 函数中增强 `crypto_signals` 检测逻辑：

1. 检测 MD5 init 常量: 在字符串中搜索 `0x67452301` 的 hex 表示，或在导入函数中搜索 `MD5`/`md5`
2. 检测 GF(2) 查表特征: 统计连续的非零 DWORD 数据块（≥64 个 DWORD），如果存在 ≥4 个这样的表，标记为 `gf2_tables`
3. 检测 CRC32 表: 搜索标准 CRC32 多项式常量 `0xEDB88320`

具体实现: 在 `classify_scene()` 中，遍历 `import_names` 集合匹配关键词（`MD5`/`SHA`/`AES`/`DES`/`crypt`/`cipher`），遍历 `strings` 列表匹配算法名称关键词（`"md5"`/`"sha"`/`"aes"`/`"des"`/`"rc4"`/`"blowfish"` 等出现在字符串值中）。不尝试匹配 init 常量的数值表示（常量在代码段而非字符串段）。

### 方案 E: 加壳二进制字符串降噪

**架构位置**: `.opencode/binary-analysis/scripts/initial_analysis.py`（scripts 层）

**改动**: 在 `initial_analysis.py` 的 `_main()` 函数中，在 `detect_packer()` 调用之后、`collect_strings()` 调用之前，当 `packer_info["packer_detected"]` 为 `True` 且 `func_count <= 5` 时，将 `max_strings` 从默认 200 限制为 20。需要调整代码顺序：将 `collect_strings()` 调用移到 `detect_packer()` 之后。

同时，在 scene 分类结果中增加 `strings_reduced: true` 标记，告知 Agent 字符串列表被截断的原因。

## §3 实现规范

### 改动范围表

| 文件 | 改动类型 | 预估行数 | 风险级别 |
|------|---------|---------|---------|
| `scripts/process_patch.py` | **新建** | ~200 行 | 低（新文件，无下游） |
| `agents/binary-analysis.md` | 修改 | ~30 行 | 中（影响 AI 编排行为） |
| `_analysis.py` | 修改 | ~25 行 | 高（影响 query.py + initial_analysis.py） |
| `scripts/initial_analysis.py` | 修改 | ~10 行 | 中（影响初始分析输出） |
| `scripts/registry.json` | 修改 | ~10 行 | 低（元数据更新） |

### 编码规则

1. `process_patch.py` 是独立 Python 脚本（不依赖 IDA），通过 `$BA_PYTHON` 运行
2. 遵循现有脚本风格：argparse 参数解析、JSON 输出、中文日志（print）
3. 所有 ctypes 操作需要错误处理（get_last_error）
4. 进程启动后必须有 cleanup（try/finally 中 TerminateProcess）
5. `_analysis.py` 的改动不能破坏现有 `classify_scene()` 的返回格式（只能增加字段）

### §3.1 实施步骤拆分

**步骤 1. 新建 process_patch.py 基础框架**
- 文件: `scripts/process_patch.py`
- 预估行数: ~80 行
- 验证点: `python -c "compile(open('.opencode/binary-analysis/scripts/process_patch.py').read(), 'x', 'exec')"` 语法通过 + `--help` 输出正确
- 依赖: 无

**步骤 2. 实现 process_patch.py 核心逻辑（进程管理 + patch + capture）**
- 文件: `scripts/process_patch.py`
- 预估行数: ~120 行（在步骤 1 基础上增加）
- 验证点: 用 CRACKME3_packed.EXE 测试（如果存在）: `--exe CRACKME3_packed.EXE --window-title "CRACKME" --patch 0x40234C:EB --capture 0x402000:16 --output result.json`，确认 JSON 输出包含 `patches_applied` 和 `captures` 字段
- 依赖: 步骤 1

**步骤 3. 更新 registry.json**
- 文件: `scripts/registry.json`
- 预估行数: ~10 行
- 验证点: `python -c "import json; json.load(open('.opencode/binary-analysis/scripts/registry.json'))"` 通过
- 依赖: 步骤 2

**步骤 4. 修复 Agent prompt — PowerShell 模板**
- 文件: `agents/binary-analysis.md`
- 预估行数: ~15 行
- 验证点: 人工检查 PowerShell 模板语法正确，`$env:VAR` 语法和 `& "$IDAT"` 引号处理无误
- 依赖: 无

**步骤 5. 修复 Agent prompt — 先验证假设规则**
- 文件: `agents/binary-analysis.md`
- 预估行数: ~10 行
- 验证点: 人工检查新增规则内容完整、位置正确
- 依赖: 无

**步骤 6. 增强 crypto signal 检测**
- 文件: `_analysis.py`
- 预估行数: ~25 行
- 验证点: `python -c "compile(open('.opencode/binary-analysis/_analysis.py').read(), 'x', 'exec')"` 通过（注意：运行时需要 IDA 模块，此处仅语法检查）
- 依赖: 无

**步骤 7. 加壳二进制字符串降噪**
- 文件: `scripts/initial_analysis.py`
- 预估行数: ~10 行
- 验证点: `python -c "compile(open('.opencode/binary-analysis/scripts/initial_analysis.py').read(), 'x', 'exec')"` 通过
- 依赖: 无

**步骤 8. Agent prompt 增加 process_patch 工具描述**
- 文件: `agents/binary-analysis.md`
- 预估行数: ~15 行
- 验证点: 人工检查工具描述与 registry.json 一致，参数说明完整
- 依赖: 步骤 3

## §4 验收标准

### 功能验收

- [ ] `process_patch.py --help` 输出完整的参数说明
- [ ] `process_patch.py --exe <TARGET> --output result.json` 能启动进程并输出 JSON（无 patch 时仅做进程管理）
- [ ] `process_patch.py --exe <TARGET> --patch 0xADDR:EB --output result.json` 成功写入单字节补丁
- [ ] `process_patch.py --exe <TARGET> --capture 0xADDR:16 --output result.json` 成功读取 16 字节数据
- [ ] `process_patch.py --exe <TARGET> --signal 0xADDR:DEADBEEF --timeout 5 --output result.json` 超时后正确报错
- [ ] `process_patch.py` 执行后目标进程被正确终止（无残留）
- [ ] Agent prompt 包含 PowerShell 版本的 query.py 和 initial_analysis.py 调用模板
- [ ] Agent prompt 包含"先验证假设"规则（核心原则第 6 条 + 失败模式表新增条目）
- [ ] `_analysis.py` 的 `classify_scene()` 能检测 MD5 init 常量和 GF(2) 查表特征
- [ ] `initial_analysis.py` 在加壳二进制上将字符串限制为 20 条

### 回归验收

- [ ] query.py 的全部 13 种查询类型不受影响（_analysis.py 的 `classify_scene()` 只增加字段，不修改现有字段）
- [ ] initial_analysis.py 的 JSON 输出格式兼容（`strings_reduced` 为新增字段）
- [ ] Agent prompt 行数 < 500 行（当前 464 行 + ~30 行 - ~5 行优化 = ~489 行）

### 架构验收

- [ ] `process_patch.py` 不依赖 IDAPython 模块（纯 ctypes）
- [ ] `_analysis.py` 的改动不引入新的依赖（只使用已有的 `import_names` 和 `strings` 参数）
- [ ] 依赖方向合规: process_patch.py 无层间依赖；_analysis.py 的改动不影响 _utils.py 或 _base.py

## §5 与现有需求文档的关系

- **2026-04-24-gui-visual-automation.md**: process_patch.py 是 gui_verify.py 的补充而非替代。gui_verify.py 处理标准 GUI 验证，process_patch.py 处理底层进程 patch 场景。gui-automation.md 的降级策略增加 process_patch.py 作为 gui_verify.py 之后的下一级降级。
- **2026-04-23-verification-framework.md**: process_patch.py 扩展了验证手段，填补了"Hook 注入 + 值捕获"的空白。
- 其他文档: 无直接冲突。
