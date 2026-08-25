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

**校验逻辑分析三原则**:
1. **比较方向判定**（动手前先判）: `transform(输入)==存储目标` → 逆算法/Z3 求解; `transform(存储目标)==输入` → 免逆向，直接对存储数据应用变换即得答案
2. **Memory Dumping**: transform 复杂但可运行时——最终比较处断点 + 任意等长输入 → 断点处 dump 程序计算的期望值（x/s $rsi）
3. **Decoy 检测**: 多个比较目标+多个成功消息=假 flag 序列，断点设**最终**比较，数比较次数取最后一个

**XOR 场景操作化**（混淆器免疫）: 混淆器 bury 逐字节 XOR 循环（obfy 类不透明谓词墙）时不 unwind——断终点 `strcmp(expected, enc(input))`，GDB commands 块自动 dump RDI/RSI 双操作数; 喂已知明文 "AAAA..." 记录 computed_A[i]，则 `key[i]=computed_A[i]^'A'`、正确输入 `=expected[i]^key[i]`。独立性验证: 输入翻一字节确认 computed 只动一字节。混淆器再厚，终点必须等于固定串——一跑泄漏 keystream、二跑换算合法输入。

**memcmp 计数 oracle**: LD_PRELOAD 把 memcmp 换成返回前缀匹配数的版本（`for i<n: if s1[i]==s2[i] cnt++ else break; return cnt`）——二值验证变逐字节计数 oracle; GDB 断 memcmp 后读返回值=前缀匹配数，逐位置换字符找计数+1 者。判定: 验证走 memcmp/strcmp 且前缀逐比较（返回非 0 语义不破坏）。与上文「XOR 场景操作化」互补——那边从双操作数泄漏期望值，这边利用程序自身的匹配计数反馈。

**Levenshtein 编辑距离 oracle**: oracle 返回编辑距离时三步恢复——①空串定长; ②逐字符发 `c*length`，distance=length-count 揪出存在字符及数量; ③一半存在/一半不存在二分定位。反馈越连续信息泄漏越多（存在性+数量+位置梯度）。通用: 任何 boolean 比较器（regex 匹配/时延/HTTP 状态码）经 2 的幂加减都坍缩为二分全值 oracle。

**位级验证器刮取**: 验证按位分解（每 flag 位一次 `call functionN`，读 `flag[offset]>>bit&1` 调不透明函数比常量）时不反编译 wrapper——PEDA `current_inst(rip)[1]` 当廉价反汇编器单步刮取: 解析 call 前 `sar imm`（bit index）/`add imm`（byte offset），call 前读 edi、ni 后读 eax，`ret==arg` 投票 bit=0 否则 1，`set $eax=0` 中和继续。任何 `f_i(bit_i)==const_i` 结构都是黑盒 oracle——不需要理解 f_i。

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

---

## 调试器选型（Windows 用户态）

主力就是 IDA（$IDAT 已配置）+ Frida（AI 无头主力）。两者覆盖用户态全部场景: IDA 调试器支持符号断点（bp kernel32.CreateFileW）、条件断点、内存监视，脚本化走 idat + IDAPython; Frida 负责 hook/改返回值/dump 内存/反反调试（IsDebuggerPresent/NtQueryInformationProcess 返回值改写+PEB 清零，hook 群一个脚本全包）; 内存 dump 用项目脚本 process_patch.py。

### lldb（macOS/iOS 主调试器）

macOS（Mach-O）/iOS/Swift/ObjC 首选。速查: `breakpoint set -r "check.*"` 正则断点批量 hook 校验函数族; `image list` 读 PIE 的 ASLR slide; `register write rax 0` 改寄存器; `dis -n main` 反汇编。Python 脚本化: frame.FindRegister("rdi").GetValueAsUnsigned() + process.ReadCStringFromMemory() 读参数，`command script add` 注册自定义命令——API 比 GDB 结构化。

### r2frida（r2 界面 + Frida 注入）

`r2 frida://spawn/./binary` 附加; `\dt strcmp` 跟踪调用、`\ii/\il` 列导入/模块、`\dm` 内存映射。适合 r2 工作流内做动态跟踪，省写 Frida JS。

### libSegFault.so 无调试器兜底（version-sensitive）

`LD_PRELOAD=libSegFault.so ./target` 崩溃即打印全寄存器+backtrace+内存映射到 stderr——gdb 不可用/被检测时拿 shellcode 入口寄存器快照（常见 RAX→缓冲、RDI→0）。**版本限定**: glibc ≥2.35 已移除（官方 2022-01 移除，进程内捕 SIGSEGV 不安全）; 替代 systemd-coredump/coredumpctl 或外部 libsegfault 项目。

### rr 逆向调试

`rr record ./binary` 录制 + `rr replay` 回放（GDB 界面+反向命令）: `reverse-continue`/`reverse-stepi`/`reverse-next` 反向执行、`checkpoint`+`restart 1` 存档回跳。单步错过关键时刻时反向回去免重跑——反调试破坏状态/竞态/不可重现环境尤其宝贵。

## 调试自动化: r2pipe 循环爆破与 GDB one-liner

r2pipe 驱动 radare2 调试模式做逐字符 oracle 爆破（改寄存器→重启→跑→判输出循环）:
```python
import r2pipe
r2 = r2pipe.open('./binary', flags=['-d'])
r2.cmd('aaa'); r2.cmd('db 0x401234')
for char in range(256):
    r2.cmd('ood')             # 重启调试进程（恢复初始状态）
    r2.cmd(f'dr eax={char}')  # 直接改寄存器当输入
    if 'correct' in r2.cmd('dc'): print(chr(char))
```

GDB one-liner 适合固定断点单跑（`start` 先跑 main 强制解析 PIE 基址，之后可用相对断点）:
```bash
gdb -ex 'start' -ex 'b *main+0x198' -ex 'run' ./binary
```
选型: 固定断点验证用 GDB -ex 链; 循环改值爆破用 r2pipe。

**输出函数断点批量提取**（绕人工延时）: 逐字符输出+usleep/忙等延时的程序——字符在延时前已在参数寄存器，断输出函数+commands 块自动打印，毫秒拿全:
```gdb
set logging file flag.log; set logging on
break putchar
commands
  silent
  printf "%c", $rdi      # ARM=$r0; RISC-V/MIPS=$a0; write 调用看 fd=1 缓冲指针
  continue
end
run
```

## 无调试器运行时监视（恶意样本行为分析）
- 系统调用/库: `strace -f -e trace=network,file -o trace.log ./malware` / `ltrace -f`
- 三路并行监视: `tcpdump -i any -w traffic.pcap`（网络）+ `inotifywait -m -r /tmp /var/tmp --format '%T %w%f %e' --timefmt '%H:%M:%S'`（落盘）+ `watch -n 1 'ps aux | grep mal'`（进程）——隔离环境（VM 快照/容器）中同时开
- 运行时内存字符串: `pid=$(pgrep mal); cat /proc/$pid/mem 2>/dev/null | strings | grep -i flag`——解密后的明文（C2 域名/key）只存在于运行内存; 或 `gdb -p $pid -batch -ex 'dump memory dump.bin 0x400000 0x500000'`

`gdb -batch -x script.gdb ./crackme && cat flag.log`。反调试检测软件断点的场景换 hbreak。

**位置编码+ZF 监控一次跑恢复**: 喂 `input[i]=i`（\x00\x01\x02...），GDB 单步全程监控 `$eflags>>6&1`（ZF）——比较命中即期望值等于该位编码值，此时 `x/1i rip-5` 取比较立即数=期望值，一跑映射全部位置。适用逐位置比较+分支结构; 位置编码技巧同用于 ILP 约束提取（angr 文件 §6）标定涉及位置。与黑盒改位法互补: 黑盒逐位多跑（改一位看一位变化），白盒单步一跑全收。
