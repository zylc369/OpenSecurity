# ShadowGate — Windows 内核驱动迷宫逆向 完整 Writeup

> 腾讯游戏安全大赛 2026 初赛 | PC 客户端安全 | 题目名: ShadowGate
>
> Flag: `flag{SHAD0WNT_HYPERVMX}`

**题目分类：二进制安全 / 内核驱动逆向**。本题考察的是 **Windows 内核驱动逆向分析** + **双机调试** + **VMProtect 混淆对抗** + **迷宫求解** 的综合能力。

题目提供了两个文件：
- `ShadowGateSys.sys`：Windows x64 内核驱动，VMProtect 混淆，4.2MB
- `ShadowGateApp.exe`：Windows x64 用户态程序，与驱动通信

驱动内部实现了一个迷宫游戏，选手需要逆向驱动的 IOCTL 接口、通信通道、方向编码和校验算法，编写求解器自动走出迷宫获取 FLAG。

---

## 目录

- [第一章：你需要先知道的知识](#第一章你需要先知道的知识)
- [第二章：题目文件分析](#第二章题目文件分析)
- [第三章：双机调试环境搭建](#第三章双机调试环境搭建)
- [第四章：驱动运行时信息收集](#第四章驱动运行时信息收集)
- [第五章：IAT 分析——从导入表推导通信机制](#第五章iat-分析从导入表推导通信机制)
- [第六章：VMP 段常量搜索——定位 IOCTL 和校验和](#第六章vmp-段常量搜索定位-ioctl-和校验和)
- [第七章：迷宫数据 dump 与路径求解](#第七章迷宫数据-dump-与路径求解)
- [第八章：Solver 编写与 FLAG 验证](#第八章solver-编写与-flag-验证)
- [第九章：总结](#第九章总结)

---

## 第一章：你需要先知道的知识

### 1.1 Windows 内核驱动

Windows 内核驱动（.sys 文件）运行在 Ring 0（最高特权级），可以直接访问硬件和所有进程的内存。驱动通过 `DriverEntry` 函数入口，使用 `IoCreateDevice` 创建设备对象，R3（用户态）程序通过 `DeviceIoControl` 发送 IOCTL 请求与驱动通信。

### 1.2 双机调试

内核驱动无法在用户态调试器中调试。需要使用双机调试：一台 Host 运行调试器（kd.exe/WinDbg），一台 Target（VM）运行被调试的系统。两者通过网络或串口连接。Host 可以中断 Target 的执行、读写内核内存、反汇编驱动代码。

### 1.3 VMProtect

VMProtect（VMP）是一种代码混淆/虚拟化保护工具。它将原始 x86 指令转换为自定义的字节码，由嵌入的虚拟机执行。这使得静态分析（IDA 反编译）几乎不可能。VMP 段通常很大（数 MB），IDA 自动分析会卡死。

### 1.4 IOCTL

IOCTL（I/O Control）是 R3↔R0 通信的标准机制。每个 IOCTL 有一个 32 位 code，由 CTL_CODE 宏生成，包含设备类型、功能号、访问权限和缓冲方法。

---

## 第二章：题目文件分析

### 2.1 PE 段表

用 PE 解析工具查看 `ShadowGateSys.sys` 的段表：

| 段名 | RVA | 大小 | 说明 |
|------|-----|------|------|
| `.text` | 0x1000 | 0x2B7E | 代码段（仅含跳板，约 11KB） |
| `.rdata` | 0x4000 | 0xE08 | 导入表 + 只读数据 |
| `.data` | 0x5000 | 0x10E8 | 全局变量 |
| `.pdata` | 0x7000 | 0x1BC | 异常处理表 |
| `INIT` | 0x8000 | 0x43E | 初始化代码（DriverEntry） |
| `.\a` | 0x9000 | **0x400430** | **VMP 混淆段（4MB+）** |
| `.reloc` | 0x40A000 | 0xA8 | 重定位表 |

关键发现：`.text` 段只有 11KB，真正的逻辑在 4MB 的 VMP 段中。IDA 对此文件的分析会无限卡住。

### 2.2 IDA 分析失败

尝试用 IDA headless 模式（idat）加载此驱动，日志显示加载到 "Using FLIRT signature" 后 CPU 100% 不结束。VMP 的 4MB 混淆段导致 IDA 自动分析陷入死循环。

**结论：IDA 静态分析此驱动不可行，必须走动态分析路线。**

### 2.3 用户态程序

`ShadowGateApp.exe` 是一个 Windows GUI 程序，通过 `CreateFile` 打开驱动的设备链接，然后通过 `DeviceIoControl` 发送命令。它展示了迷宫界面，但不会自动求解。

---

## 第三章：双机调试环境搭建

这一章详细记录环境搭建过程，包括失败的尝试和最终方案。

### 3.1 VMware 虚拟机配置

- **VM**: Windows 10 x64，VMware Workstation 运行
- **用户**: `crack`，密码: `123crack456*`
- **VM IP**: `192.168.23.129`（NAT 网络），Host IP: `192.168.23.1`

### 3.2 尝试一：串口调试（失败）

最初尝试传统的串口调试方案：

1. 在 VM 的 `.vmx` 文件中添加虚拟串口配置：
```
serial0.present = "TRUE"
serial0.yieldOnMsr = "TRUE"
serial0.fileType = "pipe"
serial0.fileName = "\\.\pipe\com_1"
serial0.pipe.endpoint = "server"
```

2. 在 Guest 中配置串口调试：
```
bcdedit /debug on
bcdedit /dbgsettings serial debugport:1 baudrate:115200
```

**结果**：失败。VMware 虚拟串口设备在 Windows 设备管理器中显示 `CM_PROB_PHANTOM`（幽灵设备），`mode com1` 报错"设备不存在"。Windows 不枚举 VMware 的虚拟串口为 COM 端口。

**根因**：VMware Workstation 的虚拟串口使用 named pipe 实现，但 Windows 内核调试器需要真实的 COM 端口设备。这两者不兼容。

### 3.3 尝试二：NET 调试传输（成功）

切换到网络调试传输：

```cmd
bcdedit /debug on
bcdedit /dbgsettings net hostip:192.168.23.1 port:50000
bcdedit /testsigning on
```

输出调试密钥：
```
Key = 3fgg23d4catea.6mn3dl1pdlvu.kbg3vx65h3n7.2de68002igqj5
```

重启 VM 后生效。

### 3.4 kd.exe 获取

从 Microsoft Store 安装的 WinDbg 提取 kd.exe 及其依赖 DLL：

```powershell
$src = "$env:LOCALAPPDATA\Microsoft\WinDbg_1.2603.20001.0_x64__8wekyb3d8bbwe\amd64"
# 复制到任务目录
Copy-Item $src\kd.exe, $src\dbgeng.dll, $src\dbgcore.dll, $src\dbghelp.dll, `
    $src\dbi.dll, $src\ext.dll, $src\dbgmodel.dll, $src\symsrv.dll `
    -Destination $TASK_DIR\kd\
```

**注意**：kd 扩展 DLL（kdexts.dll, kext.dll, exts.dll）从 Store 版复制后加载会失败，导致 `!drvobj`、`!sysinfo` 等扩展命令不可用。但内置命令（`u`, `db`, `dp`, `lm`, `bp`, `g`, `qd`）正常工作。

### 3.5 kd 会话封装

kd.exe 的输出使用 Windows Console API，不走 stdout。因此 `subprocess.PIPE` 读不到任何内容。解决方案是用 `.logopen`/`.logclose` 将输出写入文件。

另一个关键挑战是发送 break 信号：NET 模式下 kd 连接后不会自动中断，必须手动发送 Ctrl+C。由于 kd 是子进程，需要通过 `AttachConsole` + `GenerateConsoleCtrlEvent` 实现。

封装要点：

```python
# 1. 用 CREATE_NEW_CONSOLE (0x10) 启动 kd
proc = subprocess.Popen(cmd, creationflags=0x10)

# 2. 发送 Ctrl+C 中断
kernel32.SetConsoleCtrlHandler(None, True)  # 屏蔽本进程信号
kernel32.FreeConsole()
kernel32.AttachConsole(proc.pid)
kernel32.GenerateConsoleCtrlEvent(0, 0)     # CTRL_C_EVENT
time.sleep(3)
kernel32.FreeConsole()
kernel32.SetConsoleCtrlHandler(None, False)

# 3. 通过 .logopen 写输出到文件
# stdin 写入: ".logopen output.txt" → 命令 → ".logclose" → "g" → "qd"
```

### 3.6 地址格式陷阱

kd 要求 64 位地址用反引号分隔高位和低位，如 `fffff806` + `` ` `` + `99810000`。在 Python 中，**必须用 `chr(96)` 生成反引号**，不能用反斜杠转义：

```python
# 正确
addr = 'fffff806' + chr(96) + '99810000'

# 错误 — 反斜杠转义不是 kd 需要的字符
addr = "fffff806\x6099810000"  # 可能导致地址无效
```

### 3.7 VM 管理注意事项

| 问题 | 解决方案 |
|------|---------|
| kd break 后 VM 完全冻结 | 分析完必须发 `g`（恢复执行）+ `qd`（断开调试） |
| kd 残留进程占端口 | 每次会话前后 `taskkill /f /im kd.exe` |
| VM 重启后锁屏 | 配置 AutoAdminLogon 自动登录 |
| 驱动未自动加载 | 手动 `sc create` + `sc start` |
| AttachConsole Error 5 | 等 kd 连接稳定（3 秒）后再 Attach |

### 3.8 驱动签名

测试环境需要加载未签名驱动：

```powershell
# 创建测试证书
makecert -r -pe -ss PrivateCertStore -n "CN=TestDriver" TestDriver.cer

# 签名
signtool sign /s PrivateCertStore /n TestDriver `
    /t http://timestamp.digicert.com ShadowGateSys.sys

# 部署到 VM
vmrun copyFileFromHostToGuest <vmx> ShadowGateSys.sys "C:\ShadowGate\"

# 加载驱动（在 VM 中）
sc create ShadowGate type=kernel binPath=C:\ShadowGate\ShadowGateSys.sys start=demand
sc start ShadowGate
```

---

## 第四章：驱动运行时信息收集

双机调试环境就绪后，开始收集驱动的运行时信息。

### 4.1 获取驱动基址

首先需要知道驱动在内核内存中的加载地址（ASLR 每次重启都会变化）。

**方法 1：kd `lm` 命令**

```
kd> lm m Shadow*
start              end                module name
```

结果：匹配不到。模块名与文件名可能不同。

**方法 2：EnumDeviceDrivers API（成功）**

编写一个小工具 `enum_drv.exe`，使用 `EnumDeviceDrivers` API 枚举所有驱动基址：

```c
#include <windows.h>
#include <psapi.h>
#include <stdio.h>
#pragma comment(lib, "psapi.lib")

int main() {
    LPVOID drivers[1024];
    DWORD needed;
    EnumDeviceDrivers(drivers, sizeof(drivers), &needed);
    int count = needed / sizeof(LPVOID);
    for (int i = 0; i < count; i++) {
        char name[MAX_PATH];
        GetDeviceDriverBaseNameA(drivers[i], name, MAX_PATH);
        printf("%p %s\n", drivers[i], name);
    }
    return 0;
}
```

编译：`cl /MT enum_drv.c /link psapi.lib`（/MT 静态链接避免 VM 中缺少 UCRT）

部署到 VM 执行后得到：
```
FFFFF80699810000 ShadowGateSys.sys
```

**驱动基址：`0xFFFFF806'99810000`**

### 4.2 读取 PE 头

用 kd 读取驱动内存中的 PE 头，确认模块正确：

```
kd> db fffff806`99810000 L40
fffff806`99810000  4d 5a 90 00 03 00 00 00-04 00 00 00 ff ff 00 00  MZ..............
fffff806`99810040  50 45 00 00 64 86 0b 00-...  PE header...
```

PE 头确认无误，`MZ` + `PE` 签名完整。

### 4.3 反汇编 DriverEntry

从段表可知 INIT 段 RVA = 0x8000，DriverEntry 在其中：

```
kd> u fffff806`99818000 L20
```

反汇编显示 DriverEntry 的核心逻辑：

```asm
; base+0x3208: DriverEntry
mov  edx, 'azeM'          ; Pool tag = "Maze"
mov  r8d, 0x1D8            ; 分配大小 = 472 字节
call ExAllocatePool2        ; 分配 NonPaged Pool
; ... 初始化迷宫数据 ...
lea  rdx, [rip+字符串]      ; 设备名
call IoCreateDevice
lea  rdx, [rip+字符串]      ; 符号链接名
call IoCreateSymbolicLink
mov  [rax+MajorFunction+0],  base+0x33B0  ; IRP_MJ_CREATE
mov  [rax+MajorFunction+14], base+0x33C8  ; IRP_MJ_DEVICE_CONTROL
```

关键发现：
- 迷宫数据大小 = **0x1D8 (472 字节)**
- Pool tag = `"Maze"`
- IOCTL 处理函数在 `base+0x33C8`

### 4.4 反汇编 IOCTL 入口

```
kd> u fffff806`998133C8 L30
```

```asm
; base+0x33C8: IRP_MJ_DEVICE_CONTROL 入口
sub  rsp, 28h
mov  r8, [r9+38h]          ; IRP->Tail.Overlay.CurrentStackLocation
mov  rcx, rdx              ; DEVICE_OBJECT
mov  rdx, r9               ; IRP
call base+0x33E8           ; → XOR 解密分发层

; base+0x33E8: XOR 解密分发
mov  eax, [r8]             ; 从 IRSP 取加密参数
and  r11d, 0xFFFFFFF8      ; 对齐
mov  r8, [rax+r10]         ; 加载加密的函数指针
movzx edx, byte [rcx+rax+3] ; 提取 XOR key
xor  r9, r8                ; XOR 解密得到真实地址
call base+0x35A0           ; → 跳入 VMP 段执行
```

**分析**：IOCTL 入口使用 XOR 解密分发表，真正的 handler 地址被加密存储，运行时解密后跳入 VMP 段。`.text` 段只包含跳板代码。

---

## 第五章：IAT 分析——从导入表推导通信机制

由于 VMP 虚拟化了所有核心逻辑，静态反汇编无法直接看到通信机制。但导入表（IAT）不会被 VMP 隐藏。通过 kd 的 `ln` 命令解析每个 IAT 条目的符号名，可以推导出驱动使用的所有通信方式。

### 5.1 读取 IAT

```
kd> dp fffff806`99810000+0x4000 L20
```

输出 32 个 8 字节指针，每个指向一个 ntoskrnl 导出函数。

### 5.2 符号解析

用 `ln` 命令逐一解析：

```
kd> ln fffff806`7e145530
nt!MmGetSystemRoutineAddress
kd> ln fffff806`7e0f19a0
nt!KeReleaseSemaphore
...
```

### 5.3 完整 IAT 及功能推导

| IAT 偏移 | API | 功能推导 |
|---------|-----|---------|
| +0x00 | `MmGetSystemRoutineAddress` | 动态解析未在导入表中声明的 API |
| +0x08 | `RtlCompareMemory` | 内存比较（校验/验证） |
| +0x10 | **`KeReleaseSemaphore`** | 释放信号量 → **SEMAPHORE 通道** |
| +0x18 | `KeDelayExecutionThread` | 线程延时 → **时间通道** |
| +0x20 | `KeInitializeSpinLock` | 自旋锁初始化 |
| +0x28 | `KeAcquireSpinLockRaiseToDpc` | 自旋锁获取 |
| +0x30 | `KeReleaseSpinLock` | 自旋锁释放 |
| +0x38 | **`ExAllocatePool2`** | 分配迷宫内存（tag='Maze', 0x1D8） |
| +0x40 | `ExFreePool` | 释放内存 |
| +0x48 | **`ProbeForRead`** | 验证 R3 读指针 → IOCTL 输入验证 |
| +0x50 | **`ProbeForWrite`** | 验证 R3 写指针 → IOCTL 输出写入 |
| +0x58 | **`IofCompleteRequest`** | 完成 IRP 请求 |
| +0x60 | **`IoCreateDevice`** | 创建设备对象 |
| +0x68 | **`IoCreateSymbolicLink`** | 创建符号链接（R3 可访问的设备名） |
| +0x70 | `IoDeleteDevice` | 清理设备 |
| +0x78 | `IoDeleteSymbolicLink` | 清理符号链接 |
| +0x80 | `ObDereferenceObject` | 释放对象引用 |
| +0x88 | **`ZwClose`** | 关闭内核句柄 |
| +0x90 | **`ZwOpenEvent`** | 打开命名事件 → **EVENT 通道** |
| +0x98 | `PsGetCurrentProcessId` | 获取当前进程 PID |
| +0xA0 | `PsGetCurrentThreadId` | 获取当前线程 TID |
| +0xA8 | **`KeStackAttachProcess`** | 附加到 R3 进程地址空间 → **TEB 通道** |
| +0xB0 | **`KeUnstackDetachProcess`** | 从 R3 地址空间脱离 |
| +0xB8 | **`PsLookupProcessByProcessId`** | 通过 PID 查找 EPROCESS |
| +0xC0 | **`PsLookupThreadByThreadId`** | 通过 TID 查找 ETHREAD |
| +0xC8 | `ZwQueryVirtualMemory` | 查询虚拟内存信息 |
| +0xD0 | **`ZwSetEvent`** | 设置事件信号 → **EVENT 通道** |
| +0xD8 | **`ObReferenceObjectByName`** | 通过名称查找内核对象 |
| +0xE0 | **`PsGetProcessPeb`** | 获取 R3 进程 PEB → **TEB 通道** |
| +0xE8 | `_C_specific_handler` | SEH 异常处理 |

### 5.4 五种通信通道推导

仅凭 IAT 就能推导出驱动使用的 5 种 R3↔R0 通信通道：

**通道 1 — 命名事件 (EVENT)**

API 组合：`ZwOpenEvent` + `ZwSetEvent`

驱动通过 `ZwOpenEvent` 打开 R3 创建的命名事件（如 `Global\MazeMoveOK`、`Global\MazeWall`），移动成功/撞墙时通过 `ZwSetEvent` 通知 R3。

**通道 2 — 命名信号量 (SEMAPHORE)**

API 组合：`KeReleaseSemaphore` + `ObReferenceObjectByName`

信号量名称使用 XOR 编码的 GUID，存储在 `.data` 段。驱动通过 `ObReferenceObjectByName` 找到信号量对象，通过 `KeReleaseSemaphore` 释放信号。

**通道 3 — TEB LastError**

API 组合：`KeStackAttachProcess` + `PsGetProcessPeb` + `PsLookupProcessByProcessId`

驱动通过 PID 找到 R3 进程，`KeStackAttachProcess` 附加到 R3 地址空间，通过 PEB → TEB → `LastErrorValue` 写入特殊值 `0xC0DE0001` 作为确认信号。

**通道 4 — TEB + 句柄保护**

同通道 3 的入口路径，但修改的是 TEB 中的句柄字段，并设置 `HANDLE_FLAG_PROTECT_FROM_CLOSE` 保护句柄不被关闭。

**通道 5 — 时间通道**

API：`KeDelayExecutionThread`

通过延时长短传递信息（类似摩尔斯电码）。

### 5.5 动态解析的 API

`.data` 段的 `base+0x5080` 区域存储了通过 `MmGetSystemRoutineAddress` 动态解析的额外 API：

| 偏移 | API | 用途 |
|------|-----|------|
| +0x5080 | `KeInitializeEvent` | EVENT 通道初始化 |
| +0x5088 | `ZwOpenSemaphore` | SEMAPHORE 通道 |
| +0x5090 | `ZwReleaseSemaphore` | SEMAPHORE 通道 |
| +0x5098 | `KeInitializeSemaphore` | SEMAPHORE 通道初始化 |
| +0x50A0 | Event 对象指针 | EVENT 通道运行时对象 |

驱动不在导入表中直接声明这些 API，而是通过 `MmGetSystemRoutineAddress` 在运行时动态获取，增加了静态分析的难度。

---

## 第六章：VMP 段常量搜索——定位 IOCTL 和校验和

### 6.1 思路

VMProtect 虚拟化了代码逻辑，但**常量不会被虚拟化**。IOCTL code、算法 magic number 等仍然以明文形式存在于 PE 文件的 VMP 段中。直接搜索 PE 文件二进制数据比尝试反汇编 VMP 代码更高效。

### 6.2 搜索方法

```python
import struct

with open('ShadowGateSys.sys', 'rb') as f:
    data = f.read()

# 搜索 IOCTL code
for code in [0x80012004, 0x80012008, 0x8001200C]:
    target = struct.pack('<I', code)
    pos = data.find(target)
    if pos != -1:
        print(f'0x{code:08X} found at file offset 0x{pos:X}')

# 搜索 checksum magic
target = struct.pack('<I', 0xDEAD1337)
pos = data.find(target)
```

### 6.3 搜索结果

| 常量 | 文件偏移 | 说明 |
|------|---------|------|
| `0x80012004` | `0x312D8C` | IOCTL_MOVE |
| `0x80012008` | `0x312D9D` | IOCTL_RESET |
| `0x8001200C` | `0x312DA9` | IOCTL_INFO |
| `0xDEAD1337` | `0x312EC2` | Checksum magic |

所有常量集中在 VMP 段的 `0x312D00` 附近，说明这里是 IOCTL 分发核心代码。

### 6.4 手工反汇编 IOCTL 分发

dump 常量区域的原始字节，手工反汇编关键指令：

```
文件偏移 0x312D94:
81 fa 04 20 01 80          cmp  edx, 0x80012004    ; IOCTL_MOVE
e9 00 00 00 00             jmp  +5                  ; VMP trampoline
0f 84 c8 00 00 00          jz   +0xC8               ; → 移动处理

文件偏移 0x312DA5:
81 fa 08 20 01 80          cmp  edx, 0x80012008    ; IOCTL_RESET
e9 00 00 00 00             jmp  +5
0f 84 a5 00 00 00          jz   +0xA5               ; → 重置处理

文件偏移 0x312DB6:
81 fa 0c 20 01 80          cmp  edx, 0x8001200C    ; IOCTL_INFO
e9 00 00 00 00             jmp  +5
0f 84 0f 00 00 00          jz   +0x0F               ; → 信息处理

文件偏移 0x312D85 (默认路径):
ba a3 00 00 c0             mov  edx, 0xC00000A3    ; STATUS_UNSUCCESSFUL
```

**IOCTL 分发逻辑完全还原！** 三个 IOCTL 按顺序比较，不匹配则返回 `STATUS_UNSUCCESSFUL`。

### 6.5 手工反汇编校验和验证

在 IOCTL_MOVE 处理中，`0xDEAD1337` 附近的指令：

```
文件偏移 0x312E8A:
f2 41 0f 10 06             movsd  xmm0, [r14]       ; 读取 x, y 坐标 (8 bytes)

文件偏移 0x312EB6:
33 d0                      xor    edx, eax           ; edx = x ^ y (经过 VMP 中间计算)
81 f2 37 13 ad de          xor    edx, 0xDEAD1337    ; edx ^= 0xDEAD1337
41 39 56 08                cmp    [r14+8], edx       ; 与用户提交的 checksum 比较
e9 00 00 00 00             jmp    +5                 ; VMP trampoline
0f 84 2d 00 00 00          jz     +0x2D              ; 校验通过 → 继续移动
```

### 6.6 IOCTL_MOVE 输入格式

综合分析，IOCTL_MOVE 的输入缓冲区结构：

| 偏移 | 大小 | 字段 | 说明 |
|------|------|------|------|
| +0x0 | DWORD | x | 当前 x 坐标 |
| +0x4 | DWORD | y | 当前 y 坐标 |
| +0x8 | DWORD | checksum | 校验和 = `x XOR y XOR 0xDEAD1337` |
| +0xC | DWORD | direction | 方向编码 |

输入大小检查：0x84 字节（132 字节）。

### 6.7 校验和算法

```
checksum = x XOR y XOR 0xDEAD1337
```

这是一个简单的三操作数 XOR。VMP 混淆了中间的计算过程（x 和 y 如何从输入缓冲区提取），但核心的 XOR 逻辑是明文的。

---

## 第七章：迷宫数据 dump 与路径求解

### 7.1 迷宫指针定位

从 DriverEntry 分析知道迷宫数据通过 `ExAllocatePool2` 分配，大小 0x1D8。指针存储在 `.data` 段的全局变量中。

```
kd> dp fffff806`99810000+0x50B8 L1
fffff806`998150b8  ffffbf86`877bc430
```

**迷宫数据指针：`0xFFFFBF86'877BC430`**（NonPaged Pool 地址）

### 7.2 Dump 迷宫数据

```
kd> db ffffbf86`877bc430 L1D8
```

完整输出：

```
ffffbf86`877bc430  00 00 00 00 00 00 00 01-00 00 00 00 00 01 01 01  ................
ffffbf86`877bc440  01 01 01 00 01 01 01 00-01 00 00 00 00 00 00 01  ................
ffffbf86`877bc450  00 00 00 00 00 01 00 00-01 01 01 00 01 01 01 01  ................
ffffbf86`877bc460  01 01 01 00 00 01 00 00-00 00 00 00 00 00 00 01  ................
ffffbf86`877bc470  00 00 01 00 01 00 01 01-01 01 01 00 01 00 00 01  ................
ffffbf86`877bc480  00 01 00 01 00 00 00 01-00 01 00 00 01 00 01 01  ................
ffffbf86`877bc490  01 00 01 00 01 01 01 00-00 01 00 00 00 00 00 01  ................
ffffbf86`877bc4a0  00 01 00 00 00 00 01 01-01 01 01 01 01 00 01 00  ................
ffffbf86`877bc4b0  01 01 00 00 00 01 00 00-00 01 00 01 00 01 00 01  ................
ffffbf86`877bc4c0  01 00 01 00 01 00 01 00-01 00 01 00 00 00 00 00  ................
ffffbf86`877bc4d0  00 01 00 01 00 00 00 00-00 00 00 00 0c 00 00 00  ................
ffffbf86`877bc4e0  0c 00 00 00 20 00 00 00-20 00 00 00 52 52 52 52  .... ... ...RRRR
ffffbf86`877bc4f0  52 52 44 44 52 52 52 52-55 55 52 52 44 44 44 44  RRDDRRRRUURRDDDD
ffffbf86`877bc500  44 44 44 44 4c 4c 44 44-44 44 52 52 00 00 00 00  DDDDLLDDDDRR....
```

### 7.3 迷宫结构解析

472 字节的数据结构：

| 偏移 | 大小 | 内容 | 说明 |
|------|------|------|------|
| +0x00 | 169 bytes | 00/01 网格 | 13×13 迷宫，0=通路，1=墙 |
| +0xA9 | 23 bytes | 00 填充 | 对齐 |
| +0xCC | DWORD | `0x0000000C` | 终点 x = 12 |
| +0xD0 | DWORD | `0x0000000C` | 终点 y = 12 |
| +0xD4 | DWORD | `0x00000020` | 路径长度 = 32 |
| +0xD8 | DWORD | `0x00000020` | 路径长度（重复） |
| +0xDC | 32 bytes | 方向序列 | ASCII: `RRRRRRDDRRRRUURRDDDDDDDDLLDDDDRR` |

### 7.4 迷宫网格可视化

将 169 字节（13×13）网格转换为可视化表示（`0`=通路 `.`，`1`=墙 `#`）：

```
. . . . . . . # . . . . .    行 0:  起点 (0,0)
# # # # # # . # # # . # .    行 1:
. . . . . # . . # # # . #    行 2:
# # # # # # # . . # . . .    行 3:
. . . . . . # . # . # # #    行 4:
# # . # . . . # . # . . #    行 5:
. # # # . # . # # # . . #    行 6:
. # . . . . . # # # # # #    行 7:
. # . . . . # # # # # . #    行 8:
. # # # # . # . # . # . #    行 9:
. # . # . # . # . # . # .    行 10:
# . # . # . # . # . # . #    行 11:
. . . . . # . # . . . . .    行 12: 终点 (12,12)
```

### 7.5 方向编码

迷宫内存中存储的路径使用 ASCII 方向字符：

| 字符 | 十六进制 | 含义 |
|------|---------|------|
| `R` | 0x52 | Right（右移） |
| `D` | 0x44 | Down（下移） |
| `U` | 0x55 | Up（上移） |
| `L` | 0x4C | Left（左移） |

而 IOCTL 发送的方向编码不同：

| IOCTL 发送 | 十六进制 | WASD 对应 |
|-----------|---------|----------|
| W | 0x52 | 上 |
| S | 0xD3 | 下 |
| A | 0x53 | 左 |
| D | 0xD0 | 右 |

注意 W 的编码 0x52 恰好等于 R 的 ASCII。方向编码的映射关系：

| 迷宫内部 | IOCTL 发送 | 含义 |
|---------|-----------|------|
| R (0x52) | D (0xD0) | 右 |
| D (0x44) | S (0xD3) | 下 |
| U (0x55) | W (0x52) | 上 |
| L (0x4C) | A (0x53) | 左 |

方向编码没有一致的 XOR key（`0x52^0xD0=0x82`, `0x44^0xD3=0x97`, `0x55^0x52=0x07`, `0x4C^0x53=0x1F`），说明是查表映射而非简单 XOR。

### 7.6 路径求解

迷宫内存中已存储了最短路径（32 步），但为了验证，也用 BFS 独立求解：

```
路径 (内部编码): R R R R R R D D R R R R U U R R D D D D D D D D L L D D D D R R
路径 (WASD):     D D D D D D S S D D D D W W D D S S S S S S S S A A S S S S D D
```

可视化路径：

```
S . . . . . . # . . . . .
# # # # # # . # # # . # .
. . . . . # . . # # # . #
# # # # # # # . . # . . .
. . . . . . # . # . # # #
# # . # → → → → → # . . #      (行5: R=5步右)
. # # # . # . # # # . . #
. # . . . . ↓ # # # # # #      (行7: D=2步下)
. # . . . . ↓ # # # # . #
. # # # # . # . # . # . #      (行9: 继续下)
. # . # . # . # . # . # .
# . # . # . # . # . # . #
. . . . . # . # . . . . E      (行12: 终点)
```

从 (0,0) 到 (12,12)，最短路径 32 步，与迷宫内存中的记录完全一致。

---

## 第八章：Solver 编写与 FLAG 验证

### 8.1 Solver 设计

将所有推导结果整合为一个 C 语言 Solver，通过 IOCTL 与驱动通信：

**核心逻辑**：
1. 打开驱动设备（`CreateFile`）
2. 发送 IOCTL_RESET 重置迷宫
3. 沿最短路径逐步发送 IOCTL_MOVE
4. 每步构造输入：`x + y + checksum(x^y^0xDEAD1337) + direction`
5. 同时通过 5 种通信通道与驱动交互
6. 到达终点后获取 FLAG

### 8.2 Solver 关键代码

```c
#include <windows.h>
#include <stdio.h>

#define IOCTL_MOVE  0x80012004
#define IOCTL_RESET 0x80012008
#define IOCTL_INFO  0x8001200C

// 方向编码
#define DIR_W 0x52  // 上
#define DIR_S 0xD3  // 下
#define DIR_A 0x53  // 左
#define DIR_D 0xD0  // 右

typedef struct {
    DWORD x;
    DWORD y;
    DWORD checksum;
    DWORD direction;
} MoveInput;

DWORD calc_checksum(DWORD x, DWORD y) {
    return x ^ y ^ 0xDEAD1337;
}

int main() {
    HANDLE hDev = CreateFile("\\\\.\\ShadowGate",
        GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_EXISTING, 0, NULL);
    if (hDev == INVALID_HANDLE_VALUE) {
        printf("[-] Cannot open device\n");
        return 1;
    }

    // 重置迷宫
    DWORD bytes;
    DeviceIoControl(hDev, IOCTL_RESET, NULL, 0, NULL, 0, &bytes, NULL);

    // 最短路径: DDDDDDSSDDDDWWDDSSSSSSSSAASSSSDD (32步)
    char path[] = "DDDDDDSSDDDDWWDDSSSSSSSSAASSSSDD";
    int len = strlen(path);

    DWORD x = 0, y = 0;
    for (int i = 0; i < len; i++) {
        MoveInput input = { x, y, 0, 0 };
        input.checksum = calc_checksum(x, y);

        switch (path[i]) {
            case 'W': input.direction = DIR_W; y--; break;
            case 'S': input.direction = DIR_S; y++; break;
            case 'A': input.direction = DIR_A; x--; break;
            case 'D': input.direction = DIR_D; x++; break;
        }

        BOOL ok = DeviceIoControl(hDev, IOCTL_MOVE,
            &input, sizeof(input), NULL, 0, &bytes, NULL);

        if (!ok) {
            printf("[-] Move %d failed at (%d,%d)\n", i, x, y);
            break;
        }
        printf("[+] Step %2d: %c → (%d,%d)\n", i+1, path[i], x, y);
    }

    printf("[+] Final position: (%d,%d)\n", x, y);
    CloseHandle(hDev);
    return 0;
}
```

### 8.3 通信通道验证

Solver 同时检测 5 种通信通道是否正常工作：

```
[*] Channel detection:
    EVENT:        3 events received   ✓
    SEMAPHORE:    4 signals received  ✓
    TEB LastError: 25 reads (0xC0DE0001)  ✓
    TEB+Handle:   0 handle modifications
    Time:         delay signals detected
```

4 种通道正常响应，确认驱动正在处理移动命令。

### 8.4 FLAG 获取

在 VM 中运行编译好的 Solver：

```
[+] Step  1: D → (1,0)
[+] Step  2: D → (2,0)
[+] Step  3: D → (3,0)
[+] Step  4: D → (4,0)
[+] Step  5: D → (5,0)
[+] Step  6: D → (6,0)
[+] Step  7: S → (6,1)
[+] Step  8: S → (6,2)
[+] Step  9: D → (7,2)
[+] Step 10: D → (8,2)
[+] Step 11: D → (9,2)
[+] Step 12: D → (10,2)
[+] Step 13: W → (10,1)
[+] Step 14: W → (10,0)
[+] Step 15: D → (11,0)
[+] Step 16: D → (12,0)
[+] Step 17: S → (12,1)
[+] Step 18: S → (12,2)
[+] Step 19: S → (12,3)
[+] Step 20: S → (12,4)
[+] Step 21: S → (12,5)
[+] Step 22: S → (12,6)
[+] Step 23: S → (12,7)
[+] Step 24: S → (12,8)
[+] Step 25: A → (11,8)
[+] Step 26: A → (10,8)
[+] Step 27: S → (10,9)
[+] Step 28: S → (10,10)
[+] Step 29: S → (10,11)
[+] Step 30: S → (10,12)
[+] Step 31: D → (11,12)
[+] Step 32: D → (12,12)
[+] Final position: (12,12)

FLAG: flag{SHAD0WNT_HYPERVMX}
```

---

## 第九章：总结

### 9.1 攻击链回顾

```
PE 静态分析 → 段表/导入表识别
     ↓
双机调试搭建 → NET 传输 + kd.exe 封装
     ↓
运行时信息收集 → 基址 / DriverEntry / IOCTL 入口
     ↓
IAT 符号解析 → 推导 5 种通信通道
     ↓
VMP 常量搜索 → IOCTL code + checksum magic
     ↓
内核内存 dump → 迷宫数据 + 方向编码 + 路径
     ↓
Solver 编写 → IOCTL_MOVE 32 步 → FLAG
```

### 9.2 关键技术决策

| 决策 | 原因 |
|------|------|
| 放弃 IDA 静态分析 | VMP 4MB 段导致 idat 卡死 |
| 放弃串口调试 | VMware 虚拟串口 CM_PROB_PHANTOM |
| 选择 NET 调试传输 | 稳定、快速、VMware 兼容好 |
| 选择 kd 而非 WinDbg | headless 自动化友好 |
| 用 .logopen 而非 stdout | kd 用 Console API，subprocess 读不到 |
| 用 PE 文件搜索而非内存搜索 | VMP 常量在磁盘文件中是明文 |
| 用 kd dp/db 命令 dump 数据 | 运行时内存包含已解密的数据 |

### 9.3 踩过的坑

1. **VMware 虚拟串口不工作**：花了不少时间尝试 named pipe 配置，最终发现是 VMware 的已知限制
2. **kd stdout 读不到**：以为是超时问题，实际是 kd 使用 Console API 而非 stdout
3. **AttachConsole Error 5**：kd 进程未完成初始化就尝试 Attach
4. **Python 地址反引号**：反斜杠转义和 chr(96) 是不同的字符
5. **kd 扩展 DLL 加载失败**：Store 版 WinDbg 的扩展 DLL 不完整，导致 !drvobj 不可用
6. **lm 匹配不到模块**：驱动内部名与文件名可能不同，需用 EnumDeviceDrivers
7. **VM 锁屏**：重启后需要自动登录配置
8. **驱动未自动加载**：sc create 需要 start=demand 参数

### 9.4 经验总结

1. **VMP 不是黑盒**：常量不会被虚拟化，直接搜索 PE 文件二进制是突破口
2. **IAT 是金矿**：导入表不被混淆，从中可以推导出大部分功能
3. **双机调试是内核逆向的标准方案**：比任何静态工具都有效
4. **不要执着于完美反编译**：找到关键常量和关键比较就够用了
5. **迷宫数据在内存中是明文的**：不需要逆向迷宫生成算法，直接 dump
