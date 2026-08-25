# 反调试检测与绕过（Anti-Debugging Bypass）

> 逆向保护类二进制（商业保护器/恶意软件/CTF crackme）时，目标检测调试器导致崩溃/退出/静默失控时加载。反混淆入口见 deobfuscation-selection.md；商业保护器的 VM 分析见 vm-bytecode-reversing.md；恶意软件的 C2 通信/RAT 家族/配置提取/内存检测 → malware-analysis.md。

## 触发条件

- 目标在调试器下运行: 启动即崩 / main 前崩 / 固定点崩 / 随机点崩 / 断点命中即崩 / 调试器静默失控 / 子进程杀父进程
- 静态发现: ptrace / IsDebuggerPresent / NtQuery / rdtsc / GetTickCount / SIGTRAP / INT 2D / TLS 目录项

---

## 1. Linux 检测矩阵（14 种，含可靠性）

| # | 技术 | 检测方法 | 可靠性 | 绕过 |
|---|---|---|---|---|
| L1 | ptrace(PTRACE_TRACEME) | 自附加，已有 tracer 则返回 -1 | 高 | LD_PRELOAD shim `long ptrace(int r,...){return 0;}` / NOP patch / GDB `catch syscall ptrace` + `set $rax=0` |
| L2 | /proc/self/status TracerPid | TracerPid 非零即被调试 | 高 | hook fopen/fread 过滤 / FUSE 覆盖挂载 |
| L3 | /proc/self/maps 扫描 | 找 frida/LD_PRELOAD 特征 | 中 | hook 返回过滤版 / 重命名 agent 库 |
| L4 | rdtsc 时序 | 两点周期差超阈值（cmp 0x1000 级） | 中 | 第二个 rdtsc 后硬件断点改 eax |
| L5 | clock_gettime 时序 | syscall 版时序 | 中 | hook 返回受控值 |
| L6 | signal(SIGTRAP)+raise | 调试器吞信号→handler 未执行 | 高 | GDB `handle SIGTRAP nostop pass` |
| L7 | SIGSTOP/SIGCONT 自发 | 测调试器是否介入 | 低 | 正确转发信号 |
| L8 | fork+ptrace watchdog | 子进程 attach 父进程失败→杀父 | 高 | kill 子 / patch fork / follow-fork-mode |
| L9 | getenv("LD_PRELOAD") | 环境变量 | 低 | unset / hook getenv |
| L10 | getppid() | 父应为 init/shell | 低 | 正常 shell 启动 |
| L11 | /proc/self/exe readlink | 路径与预期不符 | 低 | symlink |
| L12 | 0xCC 扫描 | 扫 .text 中 INT3 字节 | 中 | **只用硬件断点** |
| L13 | prctl(PR_SET_DUMPABLE,0) | 启动后禁 ptrace | 中 | hook prctl 保持 dumpable |
| L14 | personality(ADDR_NO_RANDOMIZE) | ASLR 被禁=调试器特征 | 低 | GDB 不禁 ASLR（set disable-randomization off） |

LD_PRELOAD 一行版:
```bash
echo 'long ptrace(int r, ...) { return 0; }' > /tmp/ap.c
gcc -shared -o /tmp/ap.so /tmp/ap.c && LD_PRELOAD=/tmp/ap.so ./target
```
GDB 环境变量 LINES/COLUMNS 也是检测点。

## 2. Windows PEB 与 NtQuery 族（确定性最高）

PEB 四字段（x64: `mov rax,gs:[0x60]`）:

| 字段 | 偏移 | 调试值 | 正常值 |
|---|---|---|---|
| BeingDebugged | PEB+0x02 | 1 | 0 |
| NtGlobalFlag | PEB+0xBC | 0x70 | 0 |
| ProcessHeap.Flags | Heap+0x40 | 0x40000062 | 0x02 |
| ProcessHeap.ForceFlags | Heap+0x44 | 0x40000060 | 0 |

绕过: 四字段清零（Frida 直接写 PEB 内存）。直接读 PEB 的检测必须 patch 内存，hook API 无效。

NtQueryInformationProcess 三类:

| InfoClass | 值 | 被调试返回 | 陷阱 |
|---|---|---|---|
| ProcessDebugPort | 0x07 | 非零 | — |
| ProcessDebugObjectHandle | 0x1E | 有效句柄 | — |
| ProcessDebugFlags | 0x1F | **0** | **反转语义: 无调试器=1，hook 时返回 1** |

CheckRemoteDebuggerPresent 底层=NtQIP(DebugPort)，hook 底层一并覆盖。IsDebuggerPresent 属 API 层（hook 返 0 即可）。

## 3. Windows 异常/线程/时序族

异常类:
- **INT 2D**: 有调试器→后续字节跳过（int 2dh 后跟 nop，执行路径分歧）。绕过: VEH 处理/NOP patch
- **CloseHandle/NtClose(无效句柄)**: 有调试器抛异常，无则仅返回错误。绕过: VEH / hook NtClose
- **SEH 检测 / VEH 链检查**: 装异常 handler 检查分发路径 / 遍历 VEH 找调试器 handler
- UD2 无效指令异常同族

线程/早期执行:
- **TLS 回调**: 在 main 前执行。断点: WinDbg `sxe ld` / GDB `starti`（停在首个镜像加载处再下 TLS 断点）
- **ThreadHideFromDebugger (0x11)**: NtSetInformationThread 调用后线程对调试器隐身（症状=静默失控）。绕过: hook NtSIT 当 0x11 时 NOP
- **硬件断点检测**: GetThreadContext 读 DR0-DR3 非零。绕过: hook GTC 清零（注意与 0xCC 扫描互斥: 一个要软断点一个要硬断点，组合用 Frida 免断点 hook）
- **内核调试器检测**: NtQuerySystemInformation(SystemKernelDebuggerInformation)。绕过: TitanHide 驱动

时序类四源: QueryPerformanceCounter / GetTickCount(64) / rdtsc / OutputDebugString 时间差（有调试器 ODS 反而快）。多检查点累积漂移→Frida 全源 replace。

低可靠性族: 父进程检查(explorer.exe) / FindWindow("OLLYDBG"/"x64dbg") / 进程名枚举 / **CRC .text 完整性**（patch 存储哈希或 hook CRC 函数）/ BlockInput。

## 4. 多层组合四型

1. **fork+ptrace watchdog**: 子进程 attach 父失败→SIGKILL 父。破解: patch fork / kill watchdog / 双调试器
2. **多进程互检**: 父子互查。破解: 双附加
3. **多检查点累积时序**: 单点 patch 无效。破解: Frida replace 全部时序源
4. **Nanomite (INT3 替换)**: 条件跳转全换 INT3，父进程求值条件 SETREGS。破解: trace 全部 INT3 handler 重建跳转表后 patch。Linux 信号版载体: SIGTRAP(int3)/SIGILL(ud2)/SIGFPE(idiv 0)/SIGSEGV(null 解引用)，真实操作在信号 handler（父进程=真 CPU，log 全部 PTRACE_POKETEXT 序列重建算法）; Windows 版 EXCEPTION_DEBUG_EVENT + 魔数 0x1337BABE/0xDEADC0DE

**pwntools 函数级 patch**（按符号名定位免算偏移）:
```python
elf = ELF('./challenge', checksec=False)
elf.asm(elf.symbols.ptrace, 'ret')     # 整函数→立即返回（无副作用反调试函数最干净）
elf.asm(addr, 'xor eax, eax; ret')     # 强制返回 0
elf.asm(addr, 'mov eax, 1; ret')       # 强制返回 1
elf.save('patched')
```

## 5. 系统化 Bypass 四阶段 + 决策树

```
Phase 1 自动化(~80%): Frida 反反调试脚本群（PEB 清零+时间函数平滑+API 返回值改写）/ LD_PRELOAD(ptrace+时序 shim)
Phase 2 早期执行(+10%): 断 TLS/_init → patch pre-main 检查
Phase 3 自定义(+8%): trace exit/abort 回溯 → Frida hook 残余 → 二进制 patch 持久化
Phase 4 多进程/内核(+2%): 双进程调试 / TitanHide / Qiling 全模拟
```

验证闭环: bypass 后在 ExitProcess/exit/_exit 设断点——意外命中=漏网检查→从 exit 回溯。

症状→根因决策树:
| 症状 | 根因 | 动作 |
|---|---|---|
| main 前崩 | TLS 回调 | 开 TLS 断点 |
| 启动即崩 | TRACEME / PEB | LD_PRELOAD / Frida PEB 清零 |
| 固定点崩 | API 检查 | hook 返回值 |
| 随机点崩 | 时序 | hook rdtsc/QPC |
| 断点命中即崩 | INT 2D / SIGTRAP | VEH / nostop pass |
| 静默失控 | HideFromDebugger | hook NtSIT |
| 子进程杀父 | fork watchdog | patch fork / kill child |

## 6. 工具矩阵与保护器画像

| 检测类 | GDB | WinDbg | Frida | Qiling |
|---|---|---|---|---|---|
| ptrace 自附加 | catch syscall | N/A | N/A | hook 返 0 | 模拟 |
| PEB/NtQuery | N/A | 自动 | 手动 eb | hook | 模拟 |
| rdtsc | 改寄存器 | 欺骗 QPC | 手动 | replace 块 | 模拟 |
| INT 2D/INT3 | handle signal | VEH/自动 | 异常处理 | 替换指令 | 模拟 |
| TLS 回调 | starti | Break on TLS | sxe ld | 早期注入 | 模拟 |
| HideFromDebugger | N/A | 自动 NOP | 手动 | hook NtSIT | 模拟 |
| fork watchdog | follow-fork | N/A | N/A | hook fork | 双模拟 |
| 0xCC 扫描 | 硬件断点 | 硬件断点 | 硬件断点 | 免断点 | 模拟 |

反反调试覆盖清单（Frida 脚本逐项 hook）: PEB 三字段+NtQueryInformationProcess 全类+NtSetInformationThread(HideFromDebugger)+GetTickCount/QPC 时间平滑——一个脚本全包。

保护器画像: VMProtect(PEB+时序+驱动级→TitanHide+Frida hook 群) / Themida(多层 PEB+SEH+时序→Frida+逐项 patch) / Enigma(IsDebuggerPresent+CRC→Frida 改返回值+patch 哈希) / 恶意软件自定义(Frida+Qiling)。Qiling 全模拟是终极兜底（无真实调试器特征）。

## 7. 恶意软件环境检查（anti-sandbox/anti-VM）与 Ghidra 修补）

反调试之外的另一族检测（拖时间/查虚拟机/查环境）:

| 检查 | 类型 | Patch |
|---|---|---|
| sleep(150) | 反沙箱 | 立即数改 1 |
| /proc/cpuinfo "hypervisor" | 反 VM | JNZ 翻 JZ |
| "VMware"/"VirtualBox" 字符串 | 反 VM | JNZ 翻 JZ |
| 风扇数/硬件检查 | 反 VM | JLE 翻 JGE |
| getpwuid 用户名 / hostname | 环境 | 比较翻转 |
| LD_PRELOAD 检查 | 反 hook | 跳过检查 |

Ghidra 修补: 点指令 → Ctrl+Shift+G 改 opcode（JNZ 0x75 ↔ JZ 0x74）→ 立即数直接改操作数 → 按 O 导出 "Original File" → chmod +x。服务端汇报型: 采集函数里的字符串地址/格式串一并 patch。顺序: 先反调试（否则验证不了后续 patch）→ sleep → 环境检查。

## 8. Linux Bypass 补集

- **直接 syscall 盲区**: 内联 `asm("syscall")` 不经 libc → LD_PRELOAD 无效。对付: GDB `catch syscall 101`（按号拦）+设 $rax=0，或 patch。yama: `echo 0 > /proc/sys/kernel/yama/ptrace_scope`
- **mount namespace 隔离 /proc 检查**（比 FUSE 轻）: `unshare -m bash -c 'mount --bind /dev/null /proc/self/status && ./binary'`; GDB 内 `b fopen; set {char[20]} $rdi="/dev/null"`
- **alarm(N) 自杀型**: `handle SIGALRM ignore` 或 patch alarm
- 信号族: SIGTRAP→nostop pass / SIGALRM→ignore / SIGSEGV→nostop pass

## 9. Anti-VM 特征全景

CPUID: leaf1 ECX bit31=hypervisor; leaf 0x40000000 品牌串（VMwareVMware/Microsoft Hv/KVMKVMKVM/XenVMMXenVMM）; **cpuid 时序**（强制 VM exit，rdtsc 夹逼 delta>500=VM）。MAC OUI: VMware 00:0C:29/00:50:56、VBox 08:00:27、Hyper-V 00:15:5D、Parallels 00:1C:42、QEMU 52:54:00。工件: vm*.sys/vbox*.dll/VMTools 服务/vmtoolsd.exe; Linux dmi product_name+dmesg hypervisor。资源沙箱画像: <2 核/<2GB RAM/<60GB 磁盘（分析机反配 4+8+100）。

## 10. Anti-DBI 检测与反制

Frida 五检测: maps 找 frida/gadget / **connect 127.0.0.1:27042**（默认端口）/ inline hook 检测（libc 函数首字节 0xE9/0xFF）/ 线程名 gmain/gdbus/frida-*（/proc/self/task/*/comm）/ Windows \\.\pipe\frida-*。反制: hook strstr（needle 含 frida 时 retval 置 0）/ early-load gadget / Interceptor.replace 整函数替代 inline。Pin/DynamoRIO: maps 特征（pin-/pinbin/dynamorio/drrun）+ 指令计数时序开销。

## 11. 自哈希 watchdog 破坏型

静态自哈希（CRC .text 检出 0xCC/patch）bypass 五法: 硬件断点/patch 比较/hook 哈希/模拟/快照 diff。**watchdog 破坏型**（循环 CRC 失败时 memset 抹 flag 再退）: kill 线程 / patch sleep 无限 / patch 比较。快照 diff 一次定位多层检查点。审计信号: 哈希调用+size 指向代码段; 纯循环+sleep 线程。

## 12. TF 单步自检与 SIGFPE 代码变异

**TF 自检 cmovz**: `pushf; pop edx; and edx,0x100`（单步陷阱标志）+ cmovz 只在非单步写正确值——stepi 时静默走错路不崩溃。解: `hbreak`（硬件断点无 TF 副作用无 INT3 字节）。一切读 EFLAGS/RFLAGS/DR6 的检查都怕 stepi——一律硬件断点。识别: pushf 后 and 0x100（TF）/0x400（DF）。

**SIGFPE 代码变异**: handler 从 ucontext gregs[REG_RIP] 取址→mprotect .text 可写→变异常量。双盲: 静态（正常路径 FPE 不触发看不到变异）+动态（调试器默认拦 SIGFPE handler 不跑）。分析: `handle SIGFPE nostop noprint pass` + 断 handler + .text 页前后 diff。识别: signal(SIGFPE)+mprotect 共存。

## 13. 信号 handler 反分析族

- **SIGILL 自定义分发**: handler 从 ucontext 取 RIP，把"非法指令"操作数当自定义 opcode 执行后改写 saved RIP 前进（或切 32/64 模式）——handler 即 VM dispatcher。静态全垃圾指令。分析: `handle SIGILL nostop pass` + strace -e signal。识别: 早期 signal(SIGILL/SIGSEGV/SIGTRAP) 注册+大量非法指令
- **SIGFPE 计数侧信道**: 信号驱动验证（除零当分支）时——正确字符产生**更多**信号: `strace -e signal=SIGFPE | grep -c SIGFPE` 逐字符计数爆破。oracle 三型: 看崩溃内容/看 API 调用/数信号次数（本条）

## 14. VEH+CRC 异步防篡改"重算写回"

VEH 在任意异常后异步 CRC 自检（可能覆盖整个 .text），patch 任何字节都被查。四路 bypass: ①硬件断点（字节不变）②NOP AddVectoredExceptionHandler 注册 ③patch CRC 比较本身 ④**重算写回**——改完代码后 binascii.crc32 重算新值 struct.pack 写回期望值偏移，校验自洽（对一切自哈希通用）。
