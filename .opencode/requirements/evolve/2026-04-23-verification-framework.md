# 需求文档: 结果验证框架重构

## §1 背景与目标

**来源**: TencentPediyKeygenMe2 分析会话复盘。AI 在 GUI 验证上卡住 3 次、给出错误结果 5+ 次、反复从零写 Frida 脚本全部失败。

**痛点**:
- P1: Agent 不用现有 gui_verify.py（245行），反而两次从零写 Frida JS 脚本全部失败
- P2: gui_verify.py 默认控件 ID 硬编码（1000/1001/1002），没有探测能力
- P3: gui_verify.py 只能通过 MessageBox 关键词判断成功失败，不通用
- P4: Agent prompt 缺少验证决策树，导致验证方案选择无序
- P5: 验证方案只考虑了 GUI 程序，没有覆盖命令行程序和 DLL
- P6: Hook 注入参数 + Hook 读取结果这个通用能力分散在多个知识库中，没有收口

**目标**: 建立完整的结果验证体系——覆盖所有程序类型（GUI/CLI/DLL），有清晰的决策树指引，有可靠的工具支撑。

**预期收益**: 验证失败轮次从 3-5 轮降到 0-1 轮；消除"卡在 GUI"和"作弊式验证"两类高频问题。

## §2 技术方案

### 方案概览

| 方案 | 改动文件 | 核心内容 |
|------|---------|---------|
| A: gui_verify.py 增强 | `scripts/gui_verify.py` | 新增 --discover/--hook-inject/--hook-result 模式 |
| B: 验证决策树 | `agents/binary-analysis.md` + `plugins/security-analysis.ts` + 新建 `knowledge-base/verification-patterns.md` | 替换现有"结果验证"章节，新增知识库 |
| C: Hook 能力收口 | `knowledge-base/verification-patterns.md` | Hook 注入参数 + Hook 读取结果的完整方案 |
| D: 经验文档更新 | `knowledge-base/dynamic-analysis.md` + `dynamic-analysis-frida.md` + `crypto-validation-patterns.md` | GUI 验证卡住的典型场景与对策 |
| E: 验证函数直接调用 | `knowledge-base/verification-patterns.md` | Unicorn/ctypes 的使用条件和限制 |

---

### 方案 A: gui_verify.py 增强

**改动文件**: `.opencode/binary-analysis/scripts/gui_verify.py`

**改动文件**: `.opencode/binary-analysis/scripts/registry.json`

#### A1: 新增 --discover 模式

**功能**: 启动目标程序，枚举主窗口的所有子控件，输出控件 ID、类型、类名、当前文本。

**参数**: `--discover`（复用 --exe 和 --timeout，**不需要** --username/--license）

**参数必填矩阵**（四个模式的参数要求）:

| 参数 | discover | standard | hook-inject | hook-result | hook-inject + hook-result |
|------|----------|----------|-------------|-------------|---------------------------|
| --exe | 必填 | 必填 | 必填 | 必填 | 必填 |
| --username | 不需要 | 必填 | 不需要 | 必填 | 不需要 |
| --license | 不需要 | 必填 | 不需要 | 必填 | 不需要 |
| --output | 可选 | 可选 | 可选 | 可选 | 可选 |
| --timeout | 可选 | 可选 | 可选 | 可选 | 可选 |
| --edit1-id | 不需要 | 可选 | 不需要 | 可选 | 不需要 |
| --edit2-id | 不需要 | 可选 | 不需要 | 可选 | 不需要 |
| --button-id | 不需要 | 可选 | 可选 | 可选 | 可选 |
| --observe-rounds | 不需要 | 可选 | 可选 | 可选 | 可选 |
| --discover | ✓ | | | | |
| --hook-inject | | | ✓ | | ✓ |
| --hook-result | | | | ✓ | ✓ |
| --hook-func-addr | | | 必填 | | 必填 |
| --hook-inputs / --hook-inputs-file | | | 必填（二选一） | | 必填（二选一） |
| --hook-trigger-addr | | | 可选 | | 可选 |
| --hook-compare-addr | | | | 必填（可多次） | 必填（可多次） |
| --hook-compare-type | | | | 可选（auto） | 可选（auto） |
| --hook-calling-convention | | | 可选（仅 B/C） | | 可选（仅 B/C） |

**互斥规则**: `--discover` 与 `--hook-inject`/`--hook-result` 互斥。`--hook-inject` 和 `--hook-result` **可以组合使用**（同时注入参数 + 读取比较结果，适用于 GUI 无法输入也无法读取结果的场景）。无模式标志时为标准模式。

**条件依赖**: hook-inject + hook-result 组合模式下，必须提供 `--hook-trigger-addr` 或 `--button-id`（至少一个）来触发验证执行。仅 hook-inject 单独模式下，触发方式默认为点击按钮（需要主窗口和按钮控件）。使用 `--hook-trigger-addr` 的分支下可指定 `--hook-calling-convention`。

**实现**: 将 `--username`/`--license` 改为 optional（`required=False`），在参数校验阶段检查：
- 标准模式下缺少 --username/--license → 报错
- discover 模式下传入 hook 专用参数（--hook-func-addr 等）→ 忽略并打印警告 "discover 模式不使用 hook 参数，已忽略"
- hook 模式下传入 --discover → 报互斥错误

**输出格式**:
```json
{
  "mode": "discover",
  "controls": [
    {"id": 1000, "class": "Edit", "type": "edit", "text": ""},
    {"id": 1001, "class": "Edit", "type": "edit", "text": ""},
    {"id": 1002, "class": "Button", "type": "button", "text": "Verify"}
  ],
  "suggested_args": "--edit1-id 1000 --edit2-id 1001 --button-id 1002",
  "notes": []
}
```

**实现要点**:
- 用 `EnumChildWindows` 遍历主窗口所有子控件
- 读取类名用 `GetClassNameW`，识别 Edit/Button/Static/ComboBox
- 按类型分组，自动推荐 edit1/edit2/button 的 ID。启发式规则：
  - Edit 控件：按 ID 从小到大排序，前 2 个分别推荐为 edit1（用户名）和 edit2（license）
  - Button 控件：优先推荐文本包含"verify/check/ok/submit/确认/验证"的按钮；若无文本匹配则取 ID 最小的
  - 若 Edit 超过 2 个，在输出中新增 `"notes"` 数组字段提示（如 `"notes": ["检测到 5 个 Edit 控件，请根据实际用途选择"]`），不将提示嵌入 suggested_args 字符串
- `--discover` 模式只做探测，不输入不点击。找到主窗口后 3-5 秒内完成枚举（总体超时仍由 --timeout 控制）

#### A2: 新增 --hook-inject 模式

**功能**: 不通过 GUI 控件输入，而是在验证函数入口用 Frida Hook 修改参数。

**参数**: 
- `--hook-inject` 启用此模式
- `--hook-func-addr <hex>` 验证函数地址（如 0x401000）
- `--hook-inputs <json>` 要注入的参数，格式: `[{"arg": 0, "type": "str", "value": "KCTF"}, {"arg": 1, "type": "str", "value": "XXXX"}]`
- `--hook-inputs-file <path>` 从 JSON 文件读取参数（替代 --hook-inputs，避免命令行 JSON 转义问题）
- `--hook-calling-convention <conv>` 调用约定（可选，默认 auto）：`cdecl`/`stdcall`/`fastcall`/`auto`。auto 模式下 x86 默认 cdecl，x64 默认 Win64/fastcall。仅在 Branch B/C（使用 trigger-addr 手动调用验证函数）时需要
- `--hook-trigger-addr <hex>` 触发验证的地址（可选）。用于验证函数不会被正常 GUI 操作自动调用的场景：在此地址设断点，断点命中时手动调用验证函数。实现方式为 Frida `Interceptor.attach(trigger_addr, { onEnter: function() { call target_func(injected_args) } })`

**实现流程**（根据是否有 --hook-trigger-addr 分支）:

分支 A（默认，无 --hook-trigger-addr）:
Frida spawn(挂起) → attach → Hook 验证函数修改参数 → resume → 等待主窗口 → 点击按钮触发 → 读取结果（若含 --hook-result 则读 compare_results，否则回落到 A4 多维行为观察 observations） → 清理
注意：未提供 --button-id 时，复用 discover 模式的按钮检测启发式规则（文本匹配 verify/check/ok/submit）

分支 B（有 --hook-trigger-addr）:
Frida spawn(挂起) → attach → Hook 验证函数修改参数 → 在 trigger-addr 设断点并手动调用验证函数 → resume → 读取结果（若含 --hook-result 则读 compare_results，否则回落到 A4 多维行为观察 observations，轮询在 trigger-addr 触发后开始） → 清理

分支 C（--hook-inject + --hook-result 组合模式）:
Frida spawn(挂起) → attach → 先设 compare hook（hook-result）→ 再设 inject hook（hook-inject）→ resume → 触发验证（用 Branch A 的按钮点击或 Branch B 的 trigger-addr）→ 同时读取 compare_results 和 observations → 清理
Branch A/B 的触发方式在组合模式下同样适用，具体取决于是否提供 --hook-trigger-addr

**前提**: 需要 frida 包（通过 `$BA_PYTHON` 运行）。错误处理层级：
1. frida 包未安装 → 输出 `{"success": false, "error": "frida 未安装，请运行: $BA_PYTHON -m pip install frida"}` 并退出
2. frida spawn 失败（目标 exe 不存在/权限不足/架构不匹配） → 输出 `{"success": false, "error": "Frida spawn 失败: <原因>。请检查目标程序路径和架构"}` 并退出
3. frida 已安装但 attach 失败（反调试/权限/架构不匹配） → 输出 `{"success": false, "error": "Frida attach 失败: <原因>。建议：1. 检查目标程序架构 2. 尝试以管理员权限运行 3. 切换到 IDA 调试器"}` 并退出
4. Hook 脚本加载失败 → 输出 `{"success": false, "error": "Hook 脚本加载失败: <原因>"}` 并退出

#### A3: 新增 --hook-result 模式

**功能**: 不依赖 MessageBox 判断结果，而是在比较逻辑处 Hook 读取比较操作数和结果。

**参数**:
- `--hook-result` 启用此模式
- `--hook-compare-addr <hex>` 比较指令/函数的地址（如 0x401200）。**可多次指定**以 Hook 多个比较点
- `--hook-compare-type <type>` 比较类型: `memcmp`/`strcmp`/`custom`（默认 auto）。auto 模式的检测逻辑：先查目标地址是否为已知导入函数（memcmp/strcmp），是则用对应类型；否则按 custom 处理（读取两个操作数的内存）

**输出格式**（含 observations 后备维度，`success` 字段与其他模式一致）:
```json
{
  "success": true,
  "mode": "hook_result",
  "compare_results": [
    {
      "addr": "0x401200",
      "op1_hex": "a1 b2 c3 ...",
      "op2_hex": "a1 b2 c3 ...",
      "match": true
    }
  ],
  "verification_passed": true,
  "confidence": "high",
  "aggregation_rule": "all",
  "observations": {
    "new_windows": [],
    "title_changed": false,
    "static_texts": [],
    "exit_code": null,
    "process_running": true
  }
}
```

当 `compare_results` 为空（比较点未命中）时，Agent 根据 `observations` 的原始数据判断。

**前提**: 同 A2，需要 frida。

#### A4: 增强结果判断（多维度行为观察）

**问题**: 当前只通过 MessageBox 关键词判断，很多程序不弹 MessageBox（如 TencentPediyKeygenMe2 点击 Verify 无反应）。

**新增观察维度**（按可靠性排序）:

| 维度 | 实现方式 | 可靠性 |
|------|---------|-------|
| Hook 比较结果 | --hook-result 模式 | 高（代码层面） |
| 新窗口出现 | EnumWindows 检测新窗口（不限 MessageBox） | 中 |
| 主窗口标题变化 | 定时 GetWindowTextW 比对 | 中 |
| 主窗口内容变化 | EnumChildWindows 重读所有 Static 控件文本 | 中 |
| 进程退出码 | WaitForExit + 读取退出码 | 低（大多程序不退出） |
| 进程状态 | 是否仍在运行 / 是否崩溃 | 低 |

**实现**: 默认模式（非 --discover）下，点击按钮后串行轮询多个观察维度（每 0.5 秒检查一次，默认 5 轮共 2.5 秒，可通过 `--observe-rounds` 参数调整），综合判断。不使用多线程以降低复杂度。

**输出格式变更**: 在原有基础上增加 `mode` 和 `observations` 字段:
```json
{
  "success": true,
  "mode": "standard",
  "verification_passed": null,
  "observations": {
    "new_windows": ["Congratulations!"],
    "title_changed": false,
    "static_texts": ["Correct!", "Well done!"],
    "exit_code": null,
    "process_running": true
  },
  "message": "检测到新窗口: Congratulations!",
  "suggestion": "AI 应根据 observations 判断验证是否通过"
}
```

当 `verification_passed` 为 `null` 时，Agent 根据 `observations` 的原始数据自行判断。

**confidence 字段定义**:
- `"high"`: Hook 比较结果完全匹配，或 MessageBox/新窗口明确包含成功/失败关键词
- `"medium"`: 部分比较点匹配，或仅有窗口标题/文本变化等间接证据
- `"low"`: 仅观察到进程状态变化（如崩溃/退出），无法确认是否与验证相关

**退出码语义**:
- `verification_passed == true` → 进程退出码 0
- `verification_passed == false` → 进程退出码 1
- `verification_passed == null` → 进程退出码 0（脚本成功执行，但结果待定，由 Agent 根据 observations 判断）
- `success == false`（脚本自身出错）→ 进程退出码 2

#### A5: registry.json 更新

```json
{
  "name": "gui_verify",
  "file": "gui_verify.py",
  "description": "Win32 GUI 自动化验证脚本：支持控件探测(--discover)、标准 GUI 操作、Hook 注入参数(--hook-inject)、Hook 读取结果(--hook-result)、多维度行为观察",
  "params": ["--exe", "--username", "--license", "--output", "--timeout", "--edit1-id", "--edit2-id", "--button-id", "--discover", "--hook-inject", "--hook-func-addr", "--hook-inputs", "--hook-inputs-file", "--hook-trigger-addr", "--hook-calling-convention", "--hook-result", "--hook-compare-addr", "--hook-compare-type", "--observe-rounds"],
  "example_call": "$BA_PYTHON $SCRIPTS_DIR/scripts/gui_verify.py --exe TARGET.EXE --username test --license XXXX --output result.json",
  "added_at": "2026-04-23",
  "verified": false
}
```

---

### 方案 B: 验证决策树

**改动文件**: 
- `.opencode/agents/binary-analysis.md` — 替换"结果验证"章节
- `.opencode/plugins/security-analysis.ts` — 更新 COMPACT_RULES
- `.opencode/binary-analysis/knowledge-base/verification-patterns.md` — **新建**

#### B1: Agent prompt 变更

将 `binary-analysis.md` 的"结果验证"章节（编辑前第 231-243 行）替换为以下内容（含完整两层决策树，不依赖知识库即可做基本决策）:

```markdown
## 结果验证（强制）

生成的分析结果（如 license、key、password）必须经过验证才能报告给用户。

**完整方案模板见 `$SCRIPTS_DIR/knowledge-base/verification-patterns.md`。**

### 验证决策树

```
第一步：能否定位到验证函数？
├─ 能 → 函数是否"干净"（纯计算，不调系统 API，无 SEH）？
│       ├─ 是 → Unicorn 模拟原函数
│       └─ 否 → Hook 注入参数 + Hook 读返回值
│               （DLL 例外：直接 ctypes 加载调用，更简单可靠）
└─ 不能 → 程序类型？
        ├─ 命令行 → subprocess 传参，读 stdout/退出码
        ├─ DLL → 枚举导出函数 + ctypes 逐个调用
        └─ GUI → gui_verify.py
                  ├─ 控件 ID 未知 → --discover
                  ├─ 标准操作 → 默认模式
                  ├─ 输入不进去 → --hook-inject
                  ├─ 读不出结果 → --hook-result
                  └─ 全部失败 → Patch 排除法 → 用户人工确认
```

**核心禁令**:
- **绝对禁止**用自己重实现代码验证自己重实现结果（作弊式验证）
- 验证优先用 Hook 读返回值（代码层面 100% 可靠），后备观察程序多维行为（原样报告由 AI 判断）
```

GUI 验证脚本小节更新（替换 `binary-analysis.md` 的 `### GUI 验证脚本` 小节，编辑前位于第 317-321 行；注意：行号基于编辑前文件状态，第一处替换会偏移此行号，建议按节标题定位）:
```markdown
### GUI 验证脚本

```bash
# 标准模式
"$BA_PYTHON" "$SCRIPTS_DIR/scripts/gui_verify.py" --exe <TARGET> --username <USER> --license <LICENSE> --output "$TASK_DIR/gui_result.json"

# 控件探测（ID 未知时先探测）
"$BA_PYTHON" "$SCRIPTS_DIR/scripts/gui_verify.py" --exe <TARGET> --discover --output "$TASK_DIR/discover.json"

# Hook 注入（GUI 输入不进去时）
# 推荐：将参数写入 JSON 文件，避免命令行转义问题（Windows/通用）
"$BA_PYTHON" "$SCRIPTS_DIR/scripts/gui_verify.py" --exe <TARGET> --hook-inject --hook-func-addr 0x401000 --hook-inputs-file "$TASK_DIR/inputs.json" --output "$TASK_DIR/result.json"

# Hook 读取结果（读不出结果时）
"$BA_PYTHON" "$SCRIPTS_DIR/scripts/gui_verify.py" --exe <TARGET> --username <USER> --license <LICENSE> --hook-result --hook-compare-addr 0x401200 --output "$TASK_DIR/result.json"
```
```

#### B2: Plugin COMPACT_RULES 更新

在 `security-analysis.ts` 的 COMPACT_RULES 中替换第 ① 条（条数不变，允许单条适度扩展以包含决策树摘要）:

```
① 禁止作弊式验证 — 定位验证函数→能定位: 干净用Unicorn/复杂用Hook; 不能定位→CLI用subprocess/DLL用ctypes/GUI用gui_verify.py。详见 knowledge-base/verification-patterns.md
```

#### B3: 新建 verification-patterns.md

完整的验证决策树知识库文件，内容见方案 C+E 的合并（在同一个文件中）。

#### B4: 知识库索引更新

在 `binary-analysis.md` 的知识库索引表中新增一行:

```markdown
| `verification-patterns.md` | 需要验证分析结果（license/key/password） |
```

#### B5: frida-hook-templates.md 头部新增引用

在 `frida-hook-templates.md` 文件头新增:

```markdown
> 验证结果的完整决策树见 `verification-patterns.md`。本文件提供通用的 Hook 模板。
```

---

### 方案 C+E: 验证知识库（verification-patterns.md）

**新建文件**: `.opencode/binary-analysis/knowledge-base/verification-patterns.md`

此文件合并方案 C（Hook 能力收口）和方案 E（验证函数直接调用），作为验证体系的完整知识库。

**与现有知识库的关系**:
- `frida-hook-templates.md` — **保留原文件**，在文件头新增引用指向本文档。本文档的"Hook 模板"章节提供验证专用模板（参数修改 + 比较结果读取），不重复 frida-hook-templates.md 的通用模板
- `crypto-validation-patterns.md` "验证策略"章节 — 精简为引用，指向本文档
- `dynamic-analysis.md` + `dynamic-analysis-frida.md` — GUI 策略章节保留（含 IDA/Frida 特定实现），新增交叉引用指向本文档

#### 文件结构

```markdown
# 结果验证完整方案

> AI 编排器在需要验证分析结果时按需加载。

## 触发条件
分析结果（license/key/password）需要验证时。

## 完整验证决策树

第一步：能否定位到验证函数？
  ├─ 能 → "直接调用路径"
  └─ 不能 → "程序运行路径"

### 直接调用路径（已定位验证函数）

Q: 函数是否"干净"（纯计算，不调系统 API，无 SEH）？
  ├─ 是 → Unicorn 模拟（方案 E1）
  └─ 否 → Q: 程序类型？
         ├─ DLL → ctypes 加载调用（方案 E2）
          ├─ CLI EXE → Hook 注入参数 + Hook 读返回值（方案 C1）
             （Hook 可精确控制参数和读取返回值，subprocess 仅能传命令行参数，无法精确验证）
         └─ GUI EXE → Hook 注入参数 + Hook 读返回值（方案 C1）

### 程序运行路径（未定位验证函数）

Q: 程序类型？
  ├─ 命令行程序 → subprocess 运行，传参，读 stdout/退出码（方案 E3）
  ├─ DLL → 枚举导出函数 + ctypes 逐个调用（方案 E4）
  └─ GUI 程序 → gui_verify.py（方案 A）
                  ├─ 控件 ID 未知 → --discover
                  ├─ 标准操作 → 默认模式
                  ├─ 输入不进去 → --hook-inject
                  ├─ 读不出结果 → --hook-result
                  └─ 全部失败 → Patch 排除法 → 用户人工确认

### 方案 E1: Unicorn 模拟
（从 crypto-validation-patterns.md 迁移，内容不变）

### 方案 E2: ctypes 加载调用（DLL）

DLL 天然支持进程内加载，ctypes 比 Hook 更简单可靠（无需 spawn/attach/message 循环）。

**实现要点**:
- `ctypes.CDLL(path)` 加载 DLL，`ctypes.windll` 用于 __stdcall
- 设置 `func.argtypes` 和 `func.restype` 确保调用约定正确
- 注意：DLL 可能有依赖缺失（`LoadLibrary` 失败），需捕获 `OSError`
- 注意：32-bit DLL 无法在 64-bit Python 中加载，需匹配架构
- **回退链**: ctypes 加载调用 → Hook inject/result（Frida 模板）→ 用户确认

### 方案 E3: 命令行程序验证

**实现要点**:
- `subprocess.run([exe, arg1, arg2], capture_output=True, text=True, timeout=30)`
- 成功判断：退出码 0 + stdout 包含成功关键词
- 失败判断：退出码非 0 或 stdout 包含错误关键词
- **回退链**: subprocess 读 stdout → Hook inject/result（Frida 模板）→ Patch 排除法 → 用户确认

### 方案 E4: DLL 导出函数调用

**实现要点**:
- 用 `query.py exports` 或 Python `pefile` 枚举导出函数
- 验证函数识别策略：函数名含 validate/verify/check/serial/license
- 找到候选函数后用 ctypes 逐个调用，传入测试参数
- **回退链**: ctypes 直接调用 → Hook inject/result（Frida 模板）→ 用户确认

### 方案 C1: Hook 注入 + Hook 读取（通用核心方案）
（收口自 dynamic-analysis.md + dynamic-analysis-frida.md + frida-hook-templates.md）

判断验证成功/失败的分层方案:
- 第一层（首选）: Hook 验证函数返回值/比较逻辑
- 第二层（后备）: 观察程序多维行为（新窗口/文本变化/退出码），原样报告由 AI 判断

### Hook 注入参数模板

**GUI EXE**: 直接调用 `gui_verify.py --hook-inject`（预构建脚本）

**CLI EXE / DLL**: 参照 `frida-hook-templates.md` 模板 1 手动编写 Frida 脚本，标准流程:
```
spawn(target) → attach(pid) → script = create_script(hook_code) → load → resume(pid)
→ 触发验证（CLI 自动执行，GUI 需要手动或自动化触发）
→ 读取 Hook 输出的参数/返回值 → cleanup
```
Agent 操作步骤: 读取 `frida-hook-templates.md` → 复制模板 1 → 替换地址和参数 → 保存为临时脚本 → 用 `$BA_PYTHON` 执行

### Hook 读取结果模板

**GUI EXE**: 直接调用 `gui_verify.py --hook-result`（预构建脚本）

**CLI EXE / DLL**: 参照 `frida-hook-templates.md` 模板 3（比较函数 Hook）手动编写，或参照 `verification-patterns.md` 的"方案 C1"章节

### 常见失败与切换

| 失败现象 | 切换方向 |
|---------|---------|
| SetDlgItemTextA 不生效 | 切 SendMessage(WM_SETTEXT) 直接发到控件句柄 |
| Frida spawn 后进程立即崩溃 | 切 IDA 调试器 code cave 注入 |
| Frida attach 失败（反调试） | 切 IDA 调试器，或 Patch 反调试检测 |
| 标准 MD5/hash 结果不匹配 | 切"对比验证"：先确认输入，再逐项检查差异 |
| gui_verify.py 所有模式失败 | 切 Patch 排除法（二分定位）→ 用户人工确认 |
| Unicorn 遇到 SEH 崩溃 | 切 Hook 注入方案（让程序自己跑） |
| ctypes 加载 DLL 失败（依赖缺失） | 用 `Dependencies` 工具检查依赖，或 Hook 方案 |
| 命令行程序无 stdout 输出 | 检查是否读 stderr，或 Hook 验证函数返回值 |
```

---

### 方案 D: 经验文档更新

#### D1: dynamic-analysis.md 更新

在"GUI 程序分析策略"章节增加:

```markdown
### 策略 0（最先尝试）：定位验证函数

在尝试任何 GUI 操作之前，先通过静态分析（decompile/xrefs/strings）定位验证函数。
一旦定位到，直接走"直接调用路径"（Hook 注入参数 + Hook 读返回值），避免 GUI 操作。

**常见验证函数定位方法**:
1. strings 追踪: 找 "Correct"/"Wrong"/"Success" 等字符串 → xrefs_to → 找到引用函数
2. imports 追踪: 找 GetDlgItemTextA/GetWindowTextA → 谁调用它们 → 追踪到验证逻辑
3. Button 点击回调: 找 WM_COMMAND 处理 → BN_CLICKED 分支 → 追踪到验证函数
```

**注意**: binary-analysis.md 阶段 C 的"常见失败模式与切换方向"表与 verification-patterns.md 的"常见失败与切换"表存在部分重叠。不删除 prompt 中的表（Agent 首先看到 prompt，不一定会加载知识库），但在 verification-patterns.md 表中标注"与 prompt 失败表互补"以明确关系。

#### D2: dynamic-analysis-frida.md 更新

在开头增加交叉引用:

```markdown
> 验证结果时的完整决策树见 `verification-patterns.md`。
> Hook 注入参数和 Hook 读取结果的模板见 `verification-patterns.md` 的"方案 C1"章节。
```

#### D3: crypto-validation-patterns.md 更新

将"验证策略"章节（编辑前第 218-314 行，建议按节标题"## 验证策略（强制）"定位）的详细内容迁移到 `verification-patterns.md`，原位保留精简引用:

```markdown
### 验证策略

> 完整的验证决策树、方案模板和判断标准见 `verification-patterns.md`。
> 本节保留核心原则：

1. 先定位验证函数 → 能定位走直接调用，不能定位走程序运行
2. **绝对禁止**作弊式验证
3. 验证优先用 Hook 读返回值（代码层面），后备观察程序多维行为
```

---

## §3 实现规范

### 改动范围表

| 文件 | 改动类型 | 方案 | 影响范围 |
|------|---------|------|---------|
| `scripts/gui_verify.py` | **大改** | A | 新增 3 个模式 + 多维观察，预计新增 ~450 行 |
| `scripts/registry.json` | 新增条目 | A | 新增 gui_verify 条目（现有 registry 无此条目） |
| `agents/binary-analysis.md` | **中改** | B | 替换"结果验证"章节（~12行→~20行），更新 GUI 脚本小节 |
| `plugins/security-analysis.ts` | 小改 | B | 更新 COMPACT_RULES 第 ① 条 |
| `knowledge-base/verification-patterns.md` | **新建** | C+E | 完整验证知识库，预计 ~350 行 |
| `knowledge-base/dynamic-analysis.md` | 小改 | D | 新增"策略 0"章节 |
| `knowledge-base/dynamic-analysis-frida.md` | 小改 | D | 新增交叉引用 |
| `knowledge-base/crypto-validation-patterns.md` | 中改 | D | "验证策略"章节精简，引用新知识库 |
| `knowledge-base/frida-hook-templates.md` | 小改 | B | 文件头新增引用 |

### 编码规则

1. gui_verify.py 的 Hook 功能（--hook-inject/--hook-result）必须检测 frida 可用性，不可用时给出明确错误提示
2. gui_verify.py 的 --discover 模式不依赖 frida，仅用 Win32 API
3. verification-patterns.md 必须自包含（不依赖主 prompt 上下文即可理解）
4. 知识库文件中使用相对路径引用其他知识库（如 `$SCRIPTS_DIR/knowledge-base/xxx.md`）

### 执行顺序

```
1. 新建 verification-patterns.md（方案 C+E，其他文件依赖它）
2. 更新 crypto-validation-patterns.md（方案 D3，依赖步骤 1）
3. 更新 dynamic-analysis.md（方案 D1）
4. 更新 dynamic-analysis-frida.md（方案 D2）
5. 更新 frida-hook-templates.md 头部引用（方案 B5）
6. 改造 gui_verify.py（方案 A，独立）
7. 更新 registry.json（方案 A，依赖步骤 6）
8. 更新 binary-analysis.md（方案 B1+B4，依赖步骤 1 和 6）
9. 更新 security-analysis.ts（方案 B2，依赖步骤 1）
```

## §4 验收标准

### 功能验收

| 编号 | 验收项 | 验证方法 |
|------|--------|---------|
| F1 | gui_verify.py --discover 能输出控件列表 | 用任意 Win32 对话框程序测试 |
| F2 | gui_verify.py 默认模式增加多维观察 | 用不弹 MessageBox 的程序测试，确认 observations 字段 |
| F3 | gui_verify.py --hook-inject 能注入参数 | 需要 frida 环境 + 已知验证函数地址的程序 |
| F4 | gui_verify.py --hook-result 能读取比较结果 | 需要 frida 环境 + 已知比较地址的程序 |
| F5 | Agent prompt 的验证决策树清晰可执行 | 人工审阅 |
| F6 | verification-patterns.md 自包含可理解 | 不读主 prompt 的情况下能理解全部内容 |
| F7 | 三个知识库文档（dynamic/crypto/verification）无冲突 | 交叉审阅 |

### 回归验收

| 编号 | 验收项 |
|------|--------|
| R1 | gui_verify.py 标准模式（不带新参数）行为与改造前一致 |
| R2 | Agent prompt 总行数 < 450 行 |
| R3 | COMPACT_RULES 仍为 12 条，单条允许适度扩展（不超过原来的 3 倍） |

### 架构验收

| 编号 | 验收项 |
|------|--------|
| A1 | gui_verify.py 不引入 IDA 运行时依赖（纯 Python 脚本）|
| A2 | verification-patterns.md 不与 crypto-validation-patterns.md 的"验证策略"章节内容重复（后者精简为引用）|
| A3 | 依赖方向合规：知识库文件之间只做引用，不产生循环依赖 |

## §5 与现有需求文档的关系

| 现有需求 | 关系 |
|---------|------|
| `2026-04-22-environment-dependency-hardening.md` | 本需求的 Hook 功能依赖 venv 中的 frida 包，环境检测由该需求保障 |
| `2026-04-22-comprehensive-review-fixes.md` | 无直接关系 |
| `2026-04-22-knowledge-and-ops-improvements.md` | 无直接关系 |
| `2026-04-22-plugin-and-architecture-improvements.md` | 本需求修改 Plugin 的 COMPACT_RULES，与该需求的 Plugin 改动不冲突 |

## §6 审计修复记录

第一轮审计发现 15 个问题（4 高 / 8 中 / 3 低），以下为修复情况:

| 问题 | 严重级 | 修复方式 |
|------|--------|---------|
| --discover 与 required 参数冲突 | 高 | A1 新增参数互斥设计说明，`--discover` 模式下 --username/--license 为 optional |
| 完整决策树未进 prompt | 高 | B1 替换文本改为包含完整两层决策树（缩进格式），不再仅是结论摘要 |
| CLI 无预构建 Hook 工具 | 高 | Hook 模板章节明确 GUI 用预构建脚本、CLI/DLL 用模板手动实现，给出 Agent 操作步骤 |
| frida-hook-templates.md 去向不明 | 高 | 方案 C+E 明确"保留原文件 + 新增引用"，不迁移不删除 |
| CLI/DLL 无回退链 | 中 | E3/E4 新增回退链（subprocess/ctypes → Hook → Patch → 用户确认） |
| 验证逻辑 4 处重复 | 中 | 收口为 prompt（决策树）+ verification-patterns.md（完整方案）两级定义，其他处只引用 |
| DLL 用 ctypes 不用 Hook 看似矛盾 | 中 | 决策树 DLL 分支新增注释"DLL 天然支持进程内加载，ctypes 更简单可靠" |
| --discover "3-5 秒"歧义 | 中 | 修正为"找到主窗口后 3-5 秒内完成枚举，总体超时由 --timeout 控制" |
| 多维观察复杂度被低估 | 中 | 改为串行轮询方案（非多线程），行数预估修正为 ~450 |
| E2/E4 无实现细节 | 中 | 新增 ctypes 加载要点、DLL 依赖/架构注意事项、导出函数识别策略 |
| GUI 策略在两个知识库重复 | 中 | 本次不解决已有重复（风险可控），D1/D2 新增交叉引用指向统一方案 |
| registry.json 用词"更新"不准确 | 中 | 改为"新增条目" |
| --hook-inputs JSON 转义易出错 | 低 | 新增 --hook-inputs-file 参数，支持从文件读取 |
| verification-patterns.md 行数偏低 | 低 | 修正为 ~350 行 |
| 作弊式验证禁令多处重复 | 低 | 保留重复（核心禁令值得强化），但统一措辞 |

第 1.5 轮审计发现 13 个问题（1 高 / 7 中 / 5 低），以下为修复情况:

| 问题 | 严重级 | 修复方式 |
|------|--------|---------|
| 四模式参数必填矩阵缺失 | 高 | A1 新增完整参数必填矩阵表格，明确各模式需要的参数 |
| --hook-trigger-addr 用途不明 | 中 | 补充具体实现方式（Frida Interceptor.attach + 手动调用） |
| discover 控件推荐启发式规则不足 | 中 | 新增启发式规则（Edit 按 ID 排序、Button 按文本匹配） |
| prompt 决策树 GUI 分支缺兜底 | 中 | 新增"全部失败 → Patch 排除法 → 用户人工确认" |
| GUI 脚本小节替换位置无行号 | 中 | 标注替换 binary-analysis.md 第 317-321 行 |
| registry.json params 不完整 | 中 | 补充全部参数（从 7 个扩展到 18 个） |
| "常见失败与切换"仅占位符 | 中 | 填充 8 条具体失败模式与切换方向 |
| Frida attach 失败处理缺失 | 中 | A2 新增 3 层错误处理（包未安装/attach失败/脚本失败） |
| "互斥组"术语不准确 | 低 | 改用"参数必填矩阵"表述，明确用条件校验而非 argparse 互斥组 |
| --hook-compare-type auto 未解释 | 低 | 补充 auto 检测逻辑（查导入表 → 判断类型） |
| confidence 字段取值未定义 | 低 | 补充 high/medium/low 的含义说明 |
| "3-5 轮"无确定值 | 低 | 改为"默认 5 轮，可通过 --observe-rounds 调整" |
| compare_results 数组与单地址矛盾 | 低 | --hook-compare-addr 改为可多次指定 |

第 2 轮审计发现 4 个问题（1 高 / 2 中 / 1 低），以下为修复情况:

| 问题 | 严重级 | 修复方式 |
|------|--------|---------|
| 参数矩阵仍缺 5 个参数 | 高 | 矩阵补充 edit1/edit2/button-id、hook-trigger-addr、observe-rounds；新增"hook-inject + hook-result"组合列 |
| hook-inject 与 hook-result 互斥不合理 | 中 | 互斥规则改为：discover 与 hook-inject/hook-result 互斥；hook-inject 和 hook-result 可组合使用 |
| 多比较地址聚合规则未定义 | 中 | 输出格式新增 aggregation_rule 字段，默认 "all"（全部匹配才算通过） |
| hook-result 输出缺 observations | 低 | A3 输出格式新增 observations 字段，当 compare_results 为空时作为后备 |

第 3 轮审计发现 6 个问题（3 中 / 3 低），以下为修复情况:

| 问题 | 严重级 | 修复方式 |
|------|--------|---------|
| --observe-rounds 适用范围矛盾 | 中 | 矩阵改为所有非 discover 模式都可选 observe-rounds |
| hook-inject 实现流程无 trigger-addr 分支 | 中 | A2 新增分支 A（默认：点击按钮）和分支 B（有 trigger-addr：手动调用） |
| 组合模式触发机制空白 | 中 | 新增条件依赖：组合模式下必须有 hook-trigger-addr 或 button-id 至少一个 |
| confidence 取值无定义 | 低 | A4 新增 confidence 字段定义（high/medium/low 含义和判定规则） |
| verification_passed=null 时退出码未定义 | 低 | A4 新增退出码语义：null→0（脚本成功、结果待定），false→1，脚本出错→2 |
| E2 缺少回退链 | 低 | E2 新增回退链：ctypes → Hook → 用户确认 |

第 4 轮审计发现 4 个问题（2 中 / 2 低），以下为修复情况:

| 问题 | 严重级 | 修复方式 |
|------|--------|---------|
| 组合模式执行流程空白 | 中 | A2 新增分支 C（组合模式），明确 hook 设置顺序和触发方式 |
| A3 输出缺 success 字段 | 中 | A3 输出格式新增 `"success": true` 字段 |
| hook-inject 未提供 button-id 时行为未定义 | 低 | Branch A 补充：复用 discover 的按钮检测启发式规则 |
| R3 与 B2 存在张力 | 低 | B2 精简措辞；R3 放宽为"单条不超过原来的 3 倍" |

第 5 轮审计发现 5 个问题（2 中 / 3 低），以下为修复情况:

| 问题 | 严重级 | 修复方式 |
|------|--------|---------|
| 分支流程 spawn/启动顺序矛盾 | 中 | 三个分支统一为 spawn(挂起)→attach→hook(s)→resume→等待/触发→读取→清理 |
| hook-inject 独立模式读取结果机制不明 | 中 | Branch A 明确：含 --hook-result 读 compare_results，否则回落到 observations |
| 参数矩阵星号无脚注 | 低 | 删除星号，条件依赖已在"条件依赖"段落中描述 |
| hook-inject 示例不兼容 PowerShell | 低 | 示例改用 --hook-inputs-file |
| discover 模式传入 hook 参数行为未定义 | 低 | 参数校验规则补充：discover 模式忽略 hook 参数并打印警告 |

第 6 轮审计发现 4 个问题（3 中 / 1 低），以下为修复情况:

| 问题 | 严重级 | 修复方式 |
|------|--------|---------|
| prompt 失败表与 verification 失败表重叠 | 中 | D1 新增注释：保留 prompt 表，verification 表标注"与 prompt 互补" |
| Frida spawn 失败无错误处理 | 中 | A2 新增第 2 层错误处理（spawn 失败） |
| Branch B/C 手动调用缺调用约定 | 中 | A2 新增 --hook-calling-convention 参数 |
| 两处行号替换有时序依赖 | 低 | B1 行号标注"编辑前状态"，建议按节标题定位 |

第 7 轮审计发现 2 个问题（1 中 / 1 低），以下为修复情况:

| 问题 | 严重级 | 修复方式 |
|------|--------|---------|
| --hook-calling-convention 未同步到矩阵和 registry | 中 | 矩阵新增行、registry params 从 18→19、条件依赖段落补充 |
| 改动范围表缺 frida-hook-templates.md | 低 | 改动范围表新增一行（小改，方案 B） |

第 8 轮审计发现 2 个问题（1 中 / 1 低），以下为修复情况:

| 问题 | 严重级 | 修复方式 |
|------|--------|---------|
| --button-id 矩阵出现两行且矛盾 | 中 | 合并为单行，hook-inject 列统一为"可选" |
| discover 多 Edit 提示嵌入 JSON 字符串 | 低 | 新增 notes 数组字段，不嵌入 suggested_args |

第 9 轮审计发现 3 个问题（1 中 / 2 低），以下为修复情况:

| 问题 | 严重级 | 修复方式 |
|------|--------|---------|
| B2 路径缺 knowledge-base/ 前缀 | 中 | 改为 knowledge-base/verification-patterns.md |
| D3 行号未标注"编辑前状态" | 低 | 改为按节标题定位，标注"编辑前" |
| CLI 直接调用路径选 Hook 缺解释 | 低 | 新增注释说明 Hook vs subprocess 的优劣 |

第 10 轮审计发现 3 个问题（1 中 / 2 低），以下为修复情况:

| 问题 | 严重级 | 修复方式 |
|------|--------|---------|
| Branch B 无 hook-result 时结果读取不明 | 中 | Branch B 补充与 Branch A 对称的结果读取说明和 observations 轮询时机 |
| 条件依赖前向引用 Branch B/C | 低 | 替换为描述性文字"使用 --hook-trigger-addr 的分支" |
| A4 标准模式输出缺 mode 字段 | 低 | A4 输出格式新增 `"mode": "standard"` |
