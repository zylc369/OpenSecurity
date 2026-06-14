# 动态分析策略 — IDA 调试器（首选）

> AI 编排器在需要动态分析时通过 Read 工具按需加载。
> 本文档为动态分析首选方案。IDA 调试器失败时切换到 `dynamic-analysis-frida.md`。

## 触发条件

1. **动态脱壳**：阶段 2.5 定位到 OEP 后，需要 dump 解壳后的内存
2. **算法验证**：静态分析推导出算法后，需要用实际输入/输出对比验证
3. **运行时数据追踪**：需要追踪特定函数的参数、返回值、内存状态
4. **GUI 程序交互**：需要向 GUI 控件输入数据并读取结果

## 方案选择

| 方案 | 优先级 | 适用场景 | 前置条件 |
|------|--------|---------|---------|
| IDA 内置调试器 | **首选** | 本地可执行文件、脱壳、断点追踪、算法验证 | 无（IDA 自带） |
| Frida | 后备 | IDA 调试器失败（强反调试）、需要注入远程进程 | pip install frida |
| 双机调试 (kd) | 第三梯队 | Windows 内核驱动（.sys）逆向 | VM + kd.exe + NET 传输 |

**优先使用 IDA 内置调试器**。仅当 IDA 调试器不可用或失败时，才切换到后备方案：
- 读取 `$SHARED_DIR/knowledge-base/dynamic-analysis-frida.md`
- **目标是内核驱动时**：读取 `$SHARED_DIR/knowledge-base/kernel-driver-analysis.md`

---

## GUI 程序分析策略（优先级排序）

> **以下策略按优先级排序，优先使用高优先级方法。低优先级方法是高优先级失败后的回退方案。**
> **GUI 交互经验在本文档和 `dynamic-analysis-frida.md` 中保持一致。**
> **验证结果时的完整决策树见 `verification-patterns.md`。**

### 策略 0（最先尝试）：定位验证函数

在尝试任何 GUI 操作之前，先通过静态分析（decompile/xrefs/strings）定位验证函数。
一旦定位到，直接走"直接调用路径"（Hook 注入参数 + Hook 读返回值），避免 GUI 操作。

**常见验证函数定位方法**:
1. strings 追踪: 找 "Correct"/"Wrong"/"Success" 等字符串 → xrefs_to → 找到引用函数
2. imports 追踪: 找 GetDlgItemTextA/GetWindowTextA → 谁调用它们 → 追踪到验证逻辑
3. Button 点击回调: 找 WM_COMMAND 处理 → BN_CLICKED 分支 → 追踪到验证函数

### 策略 1（首选）：Hook 比较逻辑地址

**原理**：绕过整个 GUI 交互流程，直接 hook 程序内部的比较/验证函数。

**适用条件**：已定位到比较函数的地址（通过 decompile/xrefs/strings 追踪）

**实现方式 — Code Cave 代码注入**：

在 `.text` 段的零填充区域（code cave）写入 shellcode，修改比较点处的指令跳转到 shellcode：

```python
import ida_bytes
import ida_dbg
import struct

def inject_code_cave(target_addr, cave_addr, hook_code_bytes):
    ida_bytes.put_bytes(cave_addr, hook_code_bytes)
    jmp_rel = cave_addr - (target_addr + 5)
    jmp_bytes = b"\xE9" + struct.pack("<i", jmp_rel)
    ida_bytes.put_bytes(target_addr, jmp_bytes)
```

**关键经验**：
- Code cave 地址选择：`.text` 段末尾的零填充区域（通常可用 `read_data` bytes 模式扫描找空区域）
- 32-bit 进程注入时注意地址范围（32-bit 地址 < 0x80000000）
- 注入的代码执行完后需要跳回原流程或直接退出

**优势**：不依赖 GUI 控件、不受 WoW64 断点限制、不依赖 Windows 消息机制

### 策略 2：GUI 自动化（Win32 API）

**适用条件**：无法定位比较逻辑，或需要通过 GUI 触发特定流程

**关键经验（已验证）**：

#### 编辑控件文本设置

⚠ **`SetDlgItemTextA` 对 MFC 编辑控件可能不生效**（调用返回成功但控件内容未更新，WM_GETTEXTLENGTH 返回 0）。

**正确做法**：用 `SendMessage(WM_SETTEXT)` 直接发到编辑控件句柄：

```python
import ctypes
user32 = ctypes.windll.user32

WM_SETTEXT = 0x000C
hwnd_edit = user32.GetDlgItem(hwnd_dialog, control_id)
user32.SendMessageA(hwnd_edit, WM_SETTEXT, 0, text_buffer)
```

**验证方法**：设置后用 `GetWindowTextLengthA` 或 `WM_GETTEXTLENGTH` 检查控件实际内容。

#### 触发按钮点击

**正确做法**：用 `PostMessageA` 发送 `WM_COMMAND`（异步，不阻塞）：

```python
WM_COMMAND = 0x0111
user32.PostMessageA(hwnd_dialog, WM_COMMAND, btn_id, hwnd_btn)
```

**禁止** `SendMessageA(BM_CLICK)` — 同步调用，如果按钮处理弹出 MessageBox 会阻塞。

#### 读取结果

按钮点击后程序可能弹出 MessageBox。用 `EnumWindows` 遍历 `#32770`（Dialog）窗口读取标题。

### 策略 3（最后手段）：手动交互 + 断点读取

**适用条件**：自动化方法全部失败

**方法**：
1. IDA 调试器启动程序，GUI 正常显示
2. 在目标函数设断点
3. 手动在 GUI 中输入数据并操作
4. 断点命中后读取寄存器和内存

---

## IDA 内置调试器

### 核心优势

- 零额外依赖（IDA 自带调试器模块）
- dump 后数据直接在 IDA 内，无需重新加载
- 使用标准 OS 调试 API（Windows: Win32 Debug API, Linux: ptrace），不被反 Frida 检测
- 可在 idat headless 模式下运行（`idat -A -S<script>`）

### 已知限制

- **WoW64 调试限制**：64-bit 环境调试 32-bit 进程时，硬件断点和 INT3 断点可能不工作。遇到时切换到 code cave 注入方式
- **反调试检测**：部分壳使用 `IsDebuggerPresent`、`NtQueryInformationProcess` 等检测调试器。遇到时切换到 Frida
- **仅限本地**：IDA 调试器只能调试本机进程
- **平台绑定**：Windows 调试器只能调试 Windows 程序

### 事件驱动调试模型（强制）

IDA 调试器使用**事件驱动模型**，而非轮询。核心模式：

```python
import ida_dbg
import ida_ida

class MyHook(ida_dbg.DBG_Hooks):
    def dbg_run_to(self, pid, tid=0, ea=0):
        ida_dbg.refresh_debugger_memory()
        pc = ida_dbg.get_reg_val("EIP")  # 或 "RIP"（64-bit）
        # ... 处理断点命中 ...
        ida_dbg.request_exit_process()
        ida_dbg.run_requests()

    def dbg_process_exit(self, pid, tid, ea, code):
        return 0

def _load_debugger():
    if ida_ida.inf_get_filetype() == ida_ida.f_PE:
        ida_dbg.load_debugger("win32", 0)
    elif ida_ida.inf_get_filetype() == ida_ida.f_ELF:
        ida_dbg.load_debugger("linux", 0)
    elif ida_ida.inf_get_filetype() == ida_ida.f_MACHO:
        ida_dbg.load_debugger("mac", 0)

_load_debugger()
hook = MyHook()
hook.hook()
ida_dbg.run_to(target_addr)

while ida_dbg.get_process_state() != 0:
    ida_dbg.wait_for_next_event(1, 0)

hook.unhook()
```

**关键点**：
- **必须调用 `ida_dbg.load_debugger()`**：根据文件类型加载对应调试器插件
- **使用 `DBG_Hooks` 回调**：不在外部轮询，在回调中处理事件
- **headless 事件循环**：`ida_dbg.wait_for_next_event(1, 0)` 驱动事件
- **在回调中用 `request_*` + `run_requests()`**：如 `request_exit_process()` + `run_requests()`

### 核心 IDAPython 调试 API

| API | 用途 |
|-----|------|
| `ida_dbg.load_debugger(plugin, opts)` | 加载调试器插件（"win32"/"linux"/"mac"） |
| `ida_dbg.run_to(ea)` | 运行到指定地址（启动进程 + 临时断点） |
| `ida_dbg.add_bpt(ea)` | 添加断点 |
| `ida_dbg.del_bpt(ea)` | 删除断点 |
| `ida_dbg.get_reg_val(name)` | 读寄存器（EIP/RIP/EAX/RAX 等） |
| `ida_dbg.set_reg_val(name, val)` | 写寄存器 |
| `ida_dbg.refresh_debugger_memory()` | 刷新内存视图（断点命中后必须调用） |
| `ida_dbg.wait_for_next_event(wf, timeout)` | headless 事件循环驱动 |
| `ida_dbg.DBG_Hooks` | 事件回调基类 |
| `ida_dbg.request_continue_process()` | 请求继续运行 |
| `ida_dbg.request_exit_process()` | 请求终止进程 |

配合 `ida_bytes.get_bytes(ea, size)` 在断点命中时读取任意内存。

### 脱壳场景：debug_dump.py

项目内置 IDA 调试器脱壳脚本：`$SHARED_DIR/scripts/debug_dump.py`

```bash
IDA_OEP_ADDR=0x401000 IDA_OUTPUT="$TASK_DIR/unpacked.exe" \
  "$IDAT" -A -S"$SHARED_DIR/scripts/debug_dump.py" \
  -L"$TASK_DIR/debug_dump.log" "<目标文件>.i64"
```

**功能**：加载调试器 → 运行到 OEP → dump 所有段 → 重建 PE → 写入输出。

**注意**：输出 PE 不含 IAT 重建，仅用于 IDA 加载分析。
