# Windows Shellcode Loader 组合生成 — 组件模型与免杀设计空间

> 已有 shellcode、需要生成目标环境可运行的 Loader 时加载。4 组件正交组合模型。
> CTF pwn 场景（Linux ELF 利用）见 `pwn-methodology.md`——本文件是 Windows 攻防/evasion 领域。

## 触发条件

- 拿到 shellcode（msfvenom/CS/自写）需要封装为独立可执行文件
- 目标有 AV/EDR，需要变换 loader 特征
- 需要理解/分析他人 loader 的组件构成

## §1 组合模型

**Loader = Storage × Allocator × Copier × Executor**（15×14×9×47 = 85 组件组合空间）。

最小模板（C）:
```c
unsigned char sc[] = {...};
LPVOID addr = VirtualAlloc(NULL, sizeof(sc), MEM_COMMIT|MEM_RESERVE, PAGE_EXECUTE_READWRITE);
memcpy(addr, sc, sizeof(sc));
((void(*)())addr)();
```
编译: `x86_64-w64-mingw32-gcc -o loader.exe loader.c`（C++ 用 g++）; Rust 用 `cargo build --release --target x86_64-pc-windows-gnu`（windows crate 的 VirtualAlloc + `ptr::copy_nonoverlapping` + `mem::transmute`）。

## §2 Storage（15 种）

载体: 内部嵌入 / PE 资源段（加密资源段变种）/ 远程 URL 下载 / 本地文件 / 注册表值 / **NTFS ADS**（file:stream，dir 不显示）。

编码伪装（静态特征消除）:
| 编码 | 运行时还原 |
|---|---|
| UUID（每 16B 一个）| `UuidFromStringA` 循环写入目标区 |
| IPv4（每 4B 点分串）| `inet_addr` / `RtlIpv4StringToAddressA` |
| MAC（每 6B）| `RtlEthernetStringToAddressA` |
| Word List（每 B 一个单词）| 查表映射 |
| Base64 / Huffman / RSA 加密 | 常规解码/解密 |

效果: 静态扫描只看到"UUID 数组/IP 列表"，无连续 shellcode 字节特征。

## §3 Allocator（14 种）

| 分配器 | 关键调用 | 对抗点 |
|---|---|---|
| VirtualAlloc（基线）| PAGE_EXECUTE_READWRITE | EDR 重点监控 |
| HeapCreate | HEAP_CREATE_ENABLE_EXECUTE | 绕 VirtualAlloc 监控 |
| NtAllocateVirtualMemory | 直接 NT API | 绕 kernel32 hook |
| **Indirect Syscall** | 内联 syscall + 运行时取号 | 绕 ntdll 断点 + 直接 syscall 检测 |
| **Mockingjay** | 写入系统 DLL 自带的 RWX section | **零分配行为**（无任何 allocate 调用）|
| NtMapViewOfSection / Section / 文件映射 | section 对象映射 | 内存来源不同 |
| LargePage / DripLoader 延迟分片 | — | 路径/时序差异 |
| VirtualAllocEx | 远程进程 | 注入场景 |

## §4 Copier（9 种）

memcpy / RtlMoveMemory / RtlCopyMemory / 循环字节复制 / NtWriteVirtualMemory / WriteProcessMemory / Indirect Syscall Copier——与 Allocator 对称换层。

## §5 Executor（47 种）

**回调族**（shellcode 地址当回调参数传入）:
- 窗口/显示: EnumWindows、EnumChildWindows、EnumDesktops、EnumDesktopWindows、EnumDisplayMonitors、EnumFontFamilies
- 区域: EnumSystemLocales、EnumCalendarInfo、EnumDateFormats
- 加密: CertEnumSystemStore、CryptEnumOIDInfo
- 文件/安装: CopyFileEx、SetupCommitFileQueueW、ImageGetDigestStream
- 其他: FlsAlloc、LdrEnumerateLoadedModules、InitOnceExecuteOnce

**其他族**: APC（QueueUserAPC+SleepEx / EarlyBird 挂起注入 / NtQueueApcThreadEx）/ Fiber（ConvertThreadToFiber+CreateFiber）/ Timer（CreateTimerQueueTimer、SetTimer）/ 线程（CreateThread、CreateRemoteThread、NtCreateThreadEx、RtlCreateUserThread、SetThreadContext 劫持、EtwpCreateEtwThread）/ **VEH**（AddVectoredExceptionHandler 指向 shellcode 主动触发异常）/ **Module Stomping**（写入合法 DLL .text 区执行）。

## §6 选型原则

1. 每换一个组件即改变静态/行为特征——检测对抗中按"分配→写入→执行"三层逐级换
2. EDR 检测面分层: usermode hook（用 NT API/Indirect Syscall 层）→ 直接 syscall 检测（用回调族/Mockingjay）→ 栈回溯特征（回调栈 vs 线程栈选择）
3. 组合多样性优先于单点"最强"组件——签名扫描对组合空间无覆盖能力

## §6a Windows 漏洞利用三件套

**SEH 溢出链**（32 位 PE、SafeSEH 关）: 溢出盖 SEH handler=`add esp,0xe10;ret` 从异常上下文迁 ROP → 链首 30×ret-slide 吸收崩溃偏移漂移 → **pushad ROP**: 预载 8 寄存器后一条 pushad 按 STDCALL 顺序压出完整 VirtualAlloc(addr,1,0x1000,0x40) 帧（免稀有 mov [esp+N] gadget）→ jmp esp 执行栈 shellcode。**IAT 相对解析**: 目标函数不在 IAT 时读在库函数（如 TlsAlloc）IAT 值+偏移差。0x40 等 null 常量用 `pop eax 大值; sub eax` 构造。线程型服务 shell 存活: CREATE_NEW_PROCESS_GROUP|DETACHED_PROCESS 启动器（mingw 编译）。

**CFG 绕过**: Control Flow Guard 只验间接调用目标是合法函数入口、不验哪个——msvcrt system() 合法，覆写函数指针/vtable 为 system+控第一参即 RCE。输入过滤禁空格: cmd.exe 逗号等价空格（`type,flag.txt`）、`^` 转义、`&` 链命令。

**SeDebugPrivilege**（shell 落地后）: `whoami /priv` 见 SeDebugPrivilege（Disabled 也行）→ meterpreter `migrate -N winlogon.exe` 注入 SYSTEM 进程直接提权。

## §7 关联文件

- `$SHARED_DIR/knowledge-base/pwn-methodology.md` — Linux pwn（shellcode 生成 msfvenom 见其 §5）
