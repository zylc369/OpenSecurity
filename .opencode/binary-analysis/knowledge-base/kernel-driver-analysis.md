# Windows 内核驱动逆向分析 — 双机调试方案

> 当分析目标为 Windows 内核驱动（.sys），且 IDA 静态分析因 VMProtect 等混淆无法推进时，
> 使用双机调试（kd.exe）进行运行时反汇编、内存 dump 和动态追踪。
> 本文档为 IDA 调试器和 Frida 之后的第三梯队方案。

---

## 触发条件

1. 目标是 Windows 内核驱动（.sys 文件）
2. IDA 静态分析受阻：VMProtect/Themida 混淆段导致 idat 自动分析卡死
3. 需要读取驱动运行时数据（全局变量、迷宫/配置等）
4. 需要在运行时反汇编混淆段代码（VMP 段中的常量和逻辑）

---

## 1. 环境搭建

### 1.1 传输方式选择

| 方式 | 配置 | 优点 | 缺点 | 推荐优先级 |
|------|------|------|------|-----------|
| **NET** | `bcdedit /dbgsettings net hostip:<IP> port:<PORT>` | 稳定、速度快、VMware 兼容好 | 需要 host IP | **首选** |
| Serial | VMware 虚拟串口 → named pipe | 传统方案 | VMware 虚拟串口常 `CM_PROB_PHANTOM`，Windows 不枚举 COM | 不推荐 |
| USB | `bcdedit /dbgsettings usb targetname:<NAME>` | 不占网络 | 需要 USB 3.0 xHCI | 备选 |

**首选 NET 传输**。串口在 VMware 中失败率极高（虚拟串口设备不被 Windows 枚举）。

### 1.2 VM 配置步骤

```powershell
# 在 Guest 中执行（以管理员身份）
bcdedit /debug on
bcdedit /dbgsettings net hostip:192.168.23.1 port:50000
bcdedit /testsigning on        # 允许加载测试签名驱动
# 记录输出的密钥，如: 3fgg23d4catea.6mn3dl1pdlvu.kbg3vx65h3n7.2de68002igqj5

# 重启后生效
shutdown /r /t 0
```

### 1.3 Host 端 kd.exe 获取

从 WinDbg Store 版提取 kd.exe 及依赖 DLL：

```powershell
# WinDbg Store 版安装路径（版本号可能不同）
$windbg_dir = "$env:LOCALAPPDATA\Microsoft\WinDbg_1.2603.20001.0_x64__8wekyb3d8bbwe\amd64"

# 必须复制的文件（kd.exe 运行依赖）
kd.exe, dbgeng.dll, dbgcore.dll, dbghelp.dll, dbi.dll, ext.dll, 
dbgmodel.dll, symsrv.dll, srcsrv.dll, symbolengine.dll
```

**注意**：kd 扩展 DLL（kdexts.dll, kext.dll, exts.dll）从 Store 版复制后可能加载失败，导致 `!drvobj` 等扩展命令不可用。但内置命令（`u`, `db`, `dp`, `lm`, `bp`, `g`, `qd`）正常。

### 1.4 测试驱动签名

```powershell
# 创建测试证书
makecert -r -pe -ss PrivateCertStore -n "CN=TestDriver" TestDriver.cer

# 签名驱动
signtool sign /s PrivateCertStore /n TestDriver /t http://timestamp.digicert.com Target.sys

# 将证书和驱动复制到 VM
vmrun copyFileFromHostToGuest <vmx> <local> <guest_path>
# 在 VM 中导入证书到"受信任的根证书颁发机构"
```

---

## 2. kd 会话封装

### 2.1 核心挑战

| 挑战 | 原因 | 解决方案 |
|------|------|---------|
| kd 输出不可从 stdout 读 | kd 使用控制台 I/O，不是 stdout | 用 `.logopen`/`.logclose` 写文件 |
| 发送 break 信号 | NET 模式不自动 break | `AttachConsole` + `GenerateConsoleCtrlEvent(CTRL_C)` |
| 地址格式 | kd 用反引号 `` ` `` 分隔高位 | Python 中用 `chr(96)` 拼接 |
| 进程残留 | kd 异常退出后端口被占用 | 每次会话前后 `taskkill /f /im kd.exe` |
| VM 冻结 | kd break 后 VM 完全冻结 | 分析完必须 `g` 恢复 + `qd` 断开 |

### 2.2 kd_helper.py 封装模式

```python
import subprocess, time, os, ctypes

class KDSession:
    """kd.exe 双机调试会话封装"""
    
    def __init__(self, kd_path, port=50000, key=None, log_dir=None):
        self.kd_path = kd_path
        self.port = port
        self.key = key
        self.log_file = os.path.join(log_dir, 'kd_log.txt') if log_dir else None
    
    def _start_kd(self):
        """启动 kd 子进程 (CREATE_NEW_CONSOLE)"""
        cmd = [self.kd_path, f'-k net:port={self.port},key={self.key}']
        # 必须用 CREATE_NEW_CONSOLE (0x10)，否则 AttachConsole 失败
        self.proc = subprocess.Popen(cmd, creationflags=0x10,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(3)  # 等待连接
    
    def _send_break(self):
        """通过 AttachConsole + Ctrl+C 发送 break"""
        ctypes.windll.kernel32.SetConsoleCtrlHandler(None, True)  # 屏蔽本进程
        ctypes.windll.kernel32.FreeConsole()
        ctypes.windll.kernel32.AttachConsole(self.proc.pid)
        ctypes.windll.kernel32.GenerateConsoleCtrlEvent(0, 0)  # CTRL_C_EVENT
        time.sleep(3)
        ctypes.windll.kernel32.FreeConsole()
        ctypes.windll.kernel32.SetConsoleCtrlHandler(None, False)
    
    def exec_commands(self, commands, cmd_delay=3):
        """执行命令列表，返回输出文本"""
        self._start_kd()
        self._send_break()
        
        # 构建命令序列: 打开日志 → 执行命令 → 关闭日志 → 恢复 VM → 断开
        all_cmds = [f'.logopen "{self.log_file}"'] + commands + ['.logclose', 'g', 'qd']
        
        # 逐行写入 kd 的 stdin
        for cmd in all_cmds:
            self.proc.stdin.write(cmd + '\n')
            self.proc.stdin.flush()
            time.sleep(cmd_delay if cmd not in ('g', 'qd', f'.logopen "{self.log_file}"', '.logclose') else 1)
        
        # 等待 kd 进程结束
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        
        # 读取日志输出
        if self.log_file and os.path.isfile(self.log_file):
            with open(self.log_file, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
        return ''
    
    def cleanup(self):
        """清理残留 kd 进程"""
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.kill()
        except Exception:
            pass
        # 确保没有残留 kd 进程占用端口
        subprocess.run('taskkill /f /im kd.exe', shell=True, capture_output=True)
```

### 2.3 地址格式

kd 要求地址用反引号 `` ` `` 分隔高位和低位：

```python
def kd_addr(addr_hex):
    """格式化地址为 kd 格式: fffff806`99810000"""
    return addr_hex[:8] + chr(96) + addr_hex[8:]
```

**禁止** 用反斜杠转义（`\`` ），kd 不认。

---

## 3. 驱动运行时分析流程

### 3.1 获取驱动基址

```python
# 方法1: kd 命令
commands = ['lm m Shadow*']  # 模糊匹配模块名

# 方法2: 如果 lm 匹配不到（模块名可能不同），编译枚举工具部署到 VM
# 用 EnumDeviceDrivers() API 枚举所有驱动基址
# 编译: cl /MT enum_drv.c → 部署到 VM → vmrun runProgramInGuest
```

**经验**：`lm m <name>` 对某些驱动匹配不到（内部 PE 名与文件名不同）。`EnumDeviceDrivers` API 更可靠。

### 3.2 反汇编驱动代码

```python
base = kd_addr('fffff80699810000')  # 替换为实际基址
commands = [
    f'u {base}+0x33C8 L40',  # 反汇编 IOCTL 入口
]
```

### 3.3 读取内存

```python
# 读取指针
commands = [f'dp {base}+0x50B8 L1']  # 读迷宫指针

# 读取数据块
commands = [f'db {maze_ptr} L1D8']  # dump 472 字节迷宫数据

# 读取 DWORD 数组 (IAT)
commands = [f'dp {base}+0x4000 L20']  # 读 32 个指针
```

### 3.4 符号解析

```python
# 用 ln 命令将地址解析为符号名
commands = [f'ln fffff806{chr(96)}7e145530']
# 输出: nt!MmGetSystemRoutineAddress
```

---

## 4. VMProtect 混淆驱动分析方法

### 4.1 问题

VMProtect 将原始代码虚拟化到 `.(\a` 段（通常 4MB+），IDA 自动分析会无限卡住。

### 4.2 解决策略

| 策略 | 方法 | 适用场景 |
|------|------|---------|
| **PE 文件常量搜索** | `struct.pack('<I', value)` + `data.find()` 搜索文件二进制 | 找 IOCTL code、magic 常量、算法参数 |
| **运行时反汇编** | kd `u` 命令反汇编运行时代码（已解压） | 看 .text 段非混淆部分 |
| **运行时内存 dump** | kd `db`/`dp` 读全局变量和数据 | 读迷宫、配置、编码表 |
| **间接调用追踪** | 分析 XOR 解密分发表 | 理解 .text→VMP 调用链 |

### 4.3 PE 文件常量搜索模板

```python
import struct

with open(pe_path, 'rb') as f:
    data = f.read()

# 搜索 DWORD 常量
target = struct.pack('<I', 0xDEAD1337)
pos = data.find(target)
if pos != -1:
    # dump 上下文
    context = data[pos-32:pos+48]
    # 手工反汇编关键指令
```

**关键**：VMP 段中的常量（IOCTL code、magic number、算法参数）**不会被虚拟化**，它们以明文形式存在于 PE 文件中。搜索文件比搜索内存更可靠。

### 4.4 XOR 解密分发表分析

VMProtect 驱动的 .text 段通常有一个 XOR 解密层：

```asm
; base+0x33E8: IOCTL 入口
mov eax, [r8]              ; 从 IRSP 取加密参数
and r11d, 0xFFFFFFF8       ; 对齐
mov r8, [rax+r10]          ; 加载加密函数指针
movzx edx, byte [rcx+rax+3] ; 提取 XOR key
xor r9, r8                 ; XOR 解密得到真实地址
call base+0x35A0           ; → 跳入 VMP 段执行
```

**分析路径**：`.text` 入口 → 提取加密指针 → XOR 解密 → 调用 VMP 段。VMP 段内才是真正的逻辑。

---

## 5. 常见坑和解决方案

### 5.1 VMware 串口不工作

**现象**：VMware 添加虚拟串口后，Windows 设备管理器显示 `CM_PROB_PHANTOM`，`mode com1` 报错。

**原因**：VMware 虚拟串口设备不被 Windows PnP 枚举。

**解决**：切换到 NET 传输（`bcdedit /dbgsettings net`）。

### 5.2 kd 扩展命令不可用

**现象**：`!drvobj`, `!sysinfo`, `!devnode` 等扩展命令报错。

**原因**：从 WinDbg Store 版复制的扩展 DLL 不完整。

**解决**：改用内置命令：
- `lm m <pattern>` 替代 `!drvobj`（枚举模块）
- `u <addr>` 反汇编（替代 `!disasm`）
- `dp/db/dd` 读内存（替代 `!address`）

### 5.3 kd 连接后 VM 冻结

**现象**：kd break 后 VM 完全无响应，`vmrun runProgramInGuest` 超时。

**原因**：内核调试 break 会冻结整个 VM。

**解决**：分析完必须执行 `g`（恢复执行）+ `qd`（断开调试）。

### 5.4 kd 输出读不到

**现象**：`subprocess.PIPE` 读 stdout 为空。

**原因**：kd 使用 Windows Console API（`WriteConsoleOutput`），不走 stdout。

**解决**：用 `.logopen <file>` 将输出重定向到文件，分析完用 `.logclose`。

### 5.5 AttachConsole 失败 (Error 5)

**现象**：`AttachConsole(kd_pid)` 返回 Access Denied。

**原因**：kd 进程尚未完成控制台初始化。

**解决**：等待 kd 连接稳定（`sleep(3)`）后再 AttachConsole。

### 5.6 Python 地址反引号

**现象**：kd 命令 `dp fffff806\`99810000` 报语法错误。

**原因**：Python 反斜杠转义 `` \` `` 不是 kd 需要的反引号。

**解决**：用 `chr(96)` 生成反引号字符。

```python
# 正确
addr = 'fffff806' + chr(96) + '99810000'

# 错误
addr = 'fffff806`99810000'  # Python 可能解析异常
```

### 5.7 VM 重启后锁屏

**现象**：VM 重启后停在锁屏界面，`vmrun runProgramInGuest` 无法执行。

**解决**：配置自动登录：
```
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v AutoAdminLogon /t REG_SZ /d 1
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v DefaultUserName /t REG_SZ /d crack
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v DefaultPassword /t REG_SZ /d <password>
```

### 5.8 驱动未自动加载

**现象**：VM 重启后驱动不存在。

**解决**：手动加载：
```cmd
sc create <name> type=kernel binPath=<path> start=demand
sc start <name>
```

---

## 6. IOCTL 分析技巧

### 6.1 从 IAT 推导通信机制

内核驱动的 IAT（导入地址表）直接暴露其功能：

| API 组合 | 推导的通信机制 |
|---------|-------------|
| `ZwOpenEvent` + `ZwSetEvent` | 命名事件通信 |
| `KeReleaseSemaphore` | 命名信号量通信 |
| `KeStackAttachProcess` + `PsGetProcessPeb` | 访问 R3 进程的 PEB/TEB |
| `ObReferenceObjectByName` | 通过名称查找内核对象 |
| `ProbeForRead` + `ProbeForWrite` | 验证 R3 指针（IOCTL 输入输出） |
| `IofCompleteRequest` | IRP 处理完成 |

### 6.2 IOCTL Code 搜索

从 PE 文件 VMP 段搜索 IOCTL code：

```python
# CTL_CODE 宏: DeviceType(16bit) | Access(2bit) | Function(12bit) | Method(2bit)
# 常见格式: 0x8001xxxx
for code in [0x80012004, 0x80012008, 0x8001200C]:
    target = struct.pack('<I', code)
    pos = data.find(target)
    if pos != -1:
        # 找到后 dump 上下文，手工反汇编 cmp 指令
```

### 6.3 Checksum 算法定位

在 VMP 段搜索特征常量（如 `0xDEAD1337`），然后反推上下文：

```
xor edx, eax           ; x ^ y
xor edx, 0xDEAD1337    ; ^ magic
cmp [r14+8], edx       ; verify checksum
```

---

## 7. 工具部署清单

| 工具 | 用途 | 来源 |
|------|------|------|
| `enum_drv.exe` | 枚举驱动基址 | 编译: `cl /MT enum_drv.c`（/MT 静态链接避免 UCRT 依赖） |
| `kd_helper.py` | kd 会话封装 | 纯 Python，见 §2.2 模板 |
| `test_sign.bat` | 测试签名驱动 | makecert + signtool |
| `detect_kernel_debug_env.py` | 双机调试环境自动检测 | `$SHARED_DIR/scripts/detect_kernel_debug_env.py --output env.json` |
| `vm_login.py` | VM 登录管理（密码安全隔离） | `$SHARED_DIR/scripts/vm_login.py --login/--status/--encrypt-password` |

**编译注意**：部署到 VM 的工具必须用 `/MT` 静态链接，VM 中可能缺少 UCRT 运行时。
