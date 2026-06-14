# 结果验证完整方案

> AI 编排器在需要验证分析结果时按需加载。

## 触发条件

分析结果（license/key/password）需要验证时。

---

## 完整验证决策树

```
第一步：能否定位到验证函数？
├─ 能 → 函数是否"干净"（纯计算，不调系统 API，无 SEH）？
│       ├─ 是 → Unicorn 模拟原函数（方案 E1）
│       └─ 否 → Q: 程序类型？
│               ├─ DLL → ctypes 加载调用（方案 E2）
│               ├─ CLI EXE → Hook 注入参数 + Hook 读返回值（方案 C1）
│               │           （Hook 可精确控制参数和读取返回值，subprocess 仅能传命令行参数，无法精确验证）
│               └─ GUI EXE → Hook 注入参数 + Hook 读返回值（方案 C1）
└─ 不能 → Q: 程序类型？
        ├─ 命令行程序 → subprocess 运行，传参，读 stdout/退出码（方案 E3）
        ├─ DLL → 枚举导出函数 + ctypes 逐个调用（方案 E4）
        └─ GUI 程序 → 视觉驱动 GUI 自动化（首选）
                      ├─ 截图 → MCP 定位控件 → 键鼠操作 → 截图读结果
                      ├─ MCP 连续 2 次超时或不可用 → 降级 gui_verify.py
                      │   ├─ 控件 ID 未知 → --discover
                      │   ├─ 标准操作 → 默认模式
                      │   ├─ 输入不进去 → --hook-inject
                      │   ├─ 读不出结果 → --hook-result
                      │   └─ 全部失败 → Patch 排除法 → 用户人工确认
                      └─ 全部失败 → Patch 排除法 → 用户人工确认
```

判断验证成功/失败的分层方案:
- **第一层（首选）**: Hook 验证函数返回值/比较逻辑 — 代码层面，100% 可靠
- **第二层（后备）**: 观察程序多维行为（新窗口/文本变化/退出码），原样报告由 AI 判断

---

## 方案 E1: Unicorn 模拟原函数

**适用**: 已定位验证函数 + 函数"干净"（纯计算，不调系统 API，无 SEH）

### 实现要点

1. 从 IDA 数据库提取函数代码和所需段数据，加载到 Unicorn
2. 设置栈空间（默认 1MB）
3. 写入测试数据到数据区
4. 按调用约定设置参数（cdecl: 栈上；thiscall: ECX + 栈上；x64: RCX/RDX/R8/R9 + 栈上）
5. 执行并读取返回值（EAX/RAX）

### 常见陷阱

| 陷阱 | 说明 |
|------|------|
| 地址映射不一致 | IDA 数据库地址 ≠ Unicorn 映射地址，需要对齐 |
| 未处理系统调用 | 模拟不包含 OS API（malloc/printf 等），遇到时需手动 hook 返回值 |
| 浮点指令 | Unicorn 默认不映射浮点寄存器，需要时手动映射 |
| SEH | 遇到 SEH 时 Unicorn 无法处理，应切换到 Hook 方案（方案 C1） |
| 函数边界判断 | `emu_start` 的结束地址不一定是下一条指令，用 `emu_stop()` 在 hook 中手动停止更可靠 |

### 模板

详见 `unicorn-templates.md`。

---

## 方案 E2: ctypes 加载调用（DLL）

**适用**: 已定位验证函数 + 函数不干净 + 程序类型为 DLL

DLL 天然支持进程内加载，ctypes 比 Hook 更简单可靠（无需 spawn/attach/message 循环）。

### 实现要点

```python
import ctypes

dll = ctypes.CDLL(path)       # __cdecl
# 或 dll = ctypes.windll(path)  # __stdcall

func = dll.validate
func.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
func.restype = ctypes.c_int

result = func(b"username", b"license_key")
```

### 注意事项

- DLL 可能有依赖缺失（`LoadLibrary` 失败），需捕获 `OSError`
- 32-bit DLL 无法在 64-bit Python 中加载，需匹配架构
- 设置 `argtypes` 和 `restype` 确保调用约定正确

### 回退链

ctypes 加载调用 → Hook inject/result（Frida 模板，见方案 C1）→ 用户确认

---

## 方案 E3: 命令行程序验证

**适用**: 未定位验证函数 + 程序类型为命令行

### 实现要点

```python
import subprocess

# 传参方式 1：命令行参数
result = subprocess.run(
    [exe_path, "username", "license_key"],
    capture_output=True, text=True, timeout=30
)

# 传参方式 2：stdin
result = subprocess.run(
    [exe_path],
    input="username\nlicense_key\n",
    capture_output=True, text=True, timeout=30
)

# 判断
if result.returncode == 0 and "success" in result.stdout.lower():
    print("验证通过")
```

### 成功判断

- 退出码 0 + stdout 包含成功关键词 → 通过
- 退出码非 0 或 stdout 包含错误关键词 → 失败
- stdout 无明确关键词 → 需要进一步分析

### 回退链

subprocess 读 stdout → Hook inject/result（Frida 模板，见方案 C1）→ Patch 排除法 → 用户确认

---

## 方案 E4: DLL 导出函数调用

**适用**: 未定位验证函数 + 程序类型为 DLL

### 实现要点

1. **枚举导出函数**: 用 `query.py exports` 或 Python `pefile` 库
2. **识别验证函数**: 函数名含 validate/verify/check/serial/license
3. **逐个调用**: 用 ctypes 传入测试参数，观察返回值

```python
import pefile

pe = pefile.PE(dll_path)
for export in pe.DIRECTORY_ENTRY_EXPORT.symbols:
    if export.name:
        print(f"  {hex(export.address)}: {export.name.decode()}")
```

### 回退链

ctypes 直接调用 → Hook inject/result（Frida 模板，见方案 C1）→ 用户确认

---

## GUI 视觉驱动方案（首选）

**适用**: 未定位验证函数 + 程序类型为 GUI

### 核心思路

用多模态 LLM（zai-mcp-server）识别截图中的控件位置和文字，用坐标级键鼠操作（pyautogui + pyperclip）模拟人的操作，用截图对比判断操作结果。不依赖控件 API，跨框架通用。

### 操作流程

1. 截图 → MCP 识别控件坐标和文字
2. 键鼠操作（gui_act.py）模拟点击和输入
3. 再截图 → MCP 对比判断结果

详细操作流程见 `$SHARED_DIR/knowledge-base/gui-automation.md`。

### 降级: gui_verify.py（仅当 MCP 不可用时）

触发条件: MCP 连续 2 次超时 或 MCP 服务完全不可用。
一旦降级，每次操作前仍尝试 MCP（1 次），恢复则切回视觉驱动。

---

## 方案 C1: Hook 注入 + Hook 读取（通用核心方案）

**适用**: 已定位验证函数 + 函数不干净（调系统 API、有 SEH）+ 程序类型为 EXE（CLI 或 GUI）

### 核心思路

"程序自己跑自己的代码"比"我们模拟它的代码"更可靠。Hook 方案让程序正常运行，只在关键点拦截。

### Hook 注入参数

**GUI EXE**: 直接调用 `gui_verify.py --hook-inject`（预构建脚本，见 Agent prompt 工具脚本清单）

**CLI EXE / DLL**: 参照 `frida-hook-templates.md` 模板 1 手动编写 Frida 脚本，标准流程:
```
spawn(target) → attach(pid) → script = create_script(hook_code) → load → resume(pid)
→ 触发验证（CLI 自动执行，GUI 需要手动或自动化触发）
→ 读取 Hook 输出的参数/返回值 → cleanup
```

Agent 操作步骤: 读取 `frida-hook-templates.md` → 复制模板 1 → 替换地址和参数 → 保存为临时脚本 → 用 `$PYTHON_CMD` 执行

### Hook 读取结果

**GUI EXE**: 直接调用 `gui_verify.py --hook-result`（预构建脚本）

**CLI EXE / DLL**: 参照 `frida-hook-templates.md` 模板 3（比较函数 Hook）手动编写

### 比较函数 Hook 示例

> 详细的 Hook 模板见 `frida-hook-templates.md` 模板 3（含 memcmp/strcmp 通用 Hook）。
> 以下为验证场景的快速参考：

Hook memcmp 捕获内存比较，在 `onLeave` 中读取两个缓冲区内容和比较结果。
Hook strcmp 捕获字符串比较，在 `onEnter` 中读取两个字符串。
两者都通过 `send()` 将结果传回 Python 端，用于判断验证是否通过。

---

## 常见失败与切换

> 以下失败模式与 Agent prompt 中的"常见失败模式与切换方向"表互补，本表聚焦验证环节。

| 失败现象 | 切换方向 |
|---------|---------|
| SetDlgItemTextA 不生效 | 切 SendMessage(WM_SETTEXT) 直接发到控件句柄 |
| Frida spawn 后进程立即崩溃 | 切 IDA 调试器 code cave 注入 |
| Frida attach 失败（反调试） | 切 IDA 调试器，或 Patch 反调试检测 |
| 标准 MD5/hash 结果不匹配 | 切"对比验证"：先确认输入，再逐项检查差异 |
| gui_verify.py 所有模式失败 | 切 Patch 排除法（二分定位）→ 用户人工确认 |
| Unicorn 遇到 SEH 崩溃 | 切 Hook 注入方案（让程序自己跑） |
| ctypes 加载 DLL 失败（依赖缺失） | 用 Dependencies 工具检查依赖，或 Hook 方案 |
| 命令行程序无 stdout 输出 | 检查是否读 stderr，或 Hook 验证函数返回值 |

---

## Patch 排除法（二分定位）

**适用**: 验证 pipeline 中某个阶段导致失败，需要定位具体失败点。

### 静态 Patch（IDA 数据库修改）

#### 步骤

1. 从 pipeline 末尾开始 patch，每次只 patch 一个检查点
2. 常见 patch 方式：`jnz` → `jz` 或 `jmp`（改 1-2 字节）
3. 找到"patch 后通过"的点 → 该点之前就是真正的失败阶段
4. 找到失败点后恢复原始字节

#### 实现要点

- 用 IDA 的 `read_data bytes` 读取原始字节，保存备份
- 从 pipeline 末尾开始向前逐个 patch
- 每次只 patch 一个检查点
- **必须恢复原始字节**，不保留 patch

### 运行时 Patch（process_patch.py）

当需要 patch 运行中的进程并捕获结果时，使用 `process_patch.py`（替代手写 ctypes 脚本）：

```bash
"$PYTHON_CMD" "$SHARED_DIR/scripts/process_patch.py" \
  --exe TARGET.EXE \
  --patch 0x401234:EB \
  --capture 0x422480:16 \
  --trigger click:1002 \
  --output "$TASK_DIR/patch_result.json"
```

完整参数参考见 `$SHARED_DIR/knowledge-base/process-patch-reference.md`。
