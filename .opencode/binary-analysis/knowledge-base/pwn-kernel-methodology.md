# Pwn 内核利用方法论 — 结构体泄漏、落点与竞态

> 内核 pwn 详细参考。标准流程见 `$SHARED_DIR/knowledge-base/pwn-methodology.md`。
> 本文件聚焦 Linux 内核漏洞利用（LPE/提权）。用户态堆利用见 `pwn-heap-methodology.md`。

## 触发条件

- 题目提供内核镜像（`bzImage`）+ 文件系统（`rootfs.cpio`/`initramfs.cpio.gz`）+ 启动脚本（`boot.sh`/`run.sh`）
- 或题目描述提到 kernel/driver/LPE/内核模块
- `dmesg` 或驱动源码中看到 `kmalloc`/`copy_from_user`/`ioctl`

## §1 基础设施

### 环境搭建
```bash
# 解包文件系统
mkdir rootfs && cd rootfs
zcat ../rootfs.cpio.gz | cpio -idmv

# 添加 exploit（编译时用对应内核的 gcc + 静态链接）
gcc -static -o exploit exploit.c
# 或 musl-gcc -static -o exploit exploit.c（更小）

# 重新打包
find . | cpio -o --format=newc | gzip > ../rootfs.cpio.gz

# qemu 启动（典型参数）
qemu-system-x86_64 -kernel bzImage -initrd rootfs.cpio.gz \
  -append "console=ttyS0 root=/dev/ram quiet" -nographic -m 128M
# 如需调试加: -s（gdbserver :1234）-S（暂停启动）
```

### 内核符号表
- 有 `/proc/kallsyms`：直接 `cat /proc/kallsyms | grep commit_creds`
- 无（KASLR + 隐藏符号）：需要泄漏内核基址（见 §2）

## §2 结构体泄漏表（KASLR 绕过）

> UAF 块被含函数指针的内核结构体重用 → 读出函数指针 → 计算内核基址。

| 结构体 | 触发方式 | kmalloc slab | 泄漏内容 |
|--------|---------|-------------|---------|
| `tty_struct` | `open("/dev/ptmx")` | 0x2e0 (kmalloc-1024) | `tty_operations` 指针（含 kernel .text 地址） |
| `seq_operations` | `open("/proc/self/stat")` | kmalloc-32 | 4 个函数指针（start/stop/next/show） |
| `msg_msg` | `msgsnd()` | 可变（按消息长度选 slab） | 配合 MSG_COPY 可部分读；改 `m_ts` 越界读 |
| `pipe_buffer` | `pipe()` + `write()` | kmalloc-1024 | `anon_pipe_buf_ops` 指针 |
| `shm_file_data` | `shmat()` | kmalloc-64 | 多个内核指针 |

**泄漏后计算**：
```c
// 假设泄漏了 tty_operations 地址
kernel_base = leaked_addr - known_offset;  // offset 从 /proc/kallsyms 或 vmlinux 获取
```

**KASLR 泄漏全景**: 除结构体函数指针外还有——dmesg（dmesg_restrict=0 时内核打印地址）/ /proc/self/stat wait_channel 字段（版本相关）/ eBPF JIT spray（可预测偏移）/ 已知 module 基址推算 / **9 bit 熵 = 512 位置可爆破**（可持久重连场景）。基址: `kaslr_base = (leak & ~0xfffff) - (vmlinux 符号 & ~0xfffff)`。

## §3 内核落点

### 落点 A：modprobe_path（最简单 LPE）
**场景**: 有内核任意写，`modprobe_path` 未受 CONFIG 保护

**落点 A 三补全**: ① 无泄漏时 **256 次爆破页内偏移**（KASLR 下 modprobe_path 仅 1 字节熵）逐试写路径+触发 ② **STATIC_USERMODEHELPER 检测**: GDB 断 `call_usermodehelper_setup`+触发——未启用: rdi 存 r14 于 +127 使用（透传）; 启用: +122 立即数常量（改写无效→转 core_pattern）③ **core_pattern 定位**（无 KALLSYMS_ALL）: 断 `override_creds` → 崩溃进程 → finish 后 `movzx r13d,[rip+X]` 的数据地址即 core_pattern，覆写 `|/tmp/evil.sh`（首字符 | 管道执行）任意崩溃触发。触发文件首 4 字节须**不可打印**（可打印则内核跳过 request_module）。

```c
// 1. 泄漏 kernel base，算出 modprobe_path 地址
// 2. 任意写覆盖 modprobe_path 为 "/tmp/x"
// 3. 写提权脚本
system("echo '#!/bin/sh\necho 0 > /proc/sys/kernel/kptr_restrict\nchmod 777 /flag' > /tmp/x");
chmod("/tmp/x", 0777);
// 4. 触发 modprobe（执行未知格式文件）
system("echo -ne '\\xff\\xff\\xff\\xff' > /tmp/bad");
chmod("/tmp/bad", 0777);
system("/tmp/bad");  // 内核调用 modprobe_path → 以 root 执行 /tmp/x
// 5. 读 flag
system("cat /flag");
```

### 落点 B：cred 覆写
**场景**: 能控制函数指针调用（如 commit_creds/prepare_kernel_cred 可达）

```c
// 经典 ROP/函数指针调用链
commit_creds(prepare_kernel_cred(0));  // 当前进程提权到 root
// 然后返回用户态（需正确处理 KPTI）
```

### 落点 C：Dirty PageTable（PTE 劫持）
**场景**: 页级 UAF

```
原理: 页级 UAF → PTE 页回收 → 改 PTE 物理页号指向任意物理页
步骤:
  1. 制造 page-level UAF（通过 cross-cache 回收到 PCP 分配器）
  2. 喷射 PTE 页占位（大量 mmap 使内核分配页表页）
  3. 改写 PTE 项: 修改物理页号字段指向目标物理地址
  4. 通过该 PTE 映射的虚拟地址读写任意物理内存
  5. 改 creds 或覆盖 suid 二进制
变体: 重叠"匿名页 PTE"与"文件页 PTE"，
  使只读文件映射经匿名侧可写 → 任意文件写
```

**变体详解: PTE overlap 任意文件写**
```
原理: 让一个物理页同时被"匿名映射 PTE 页"和"文件映射 PTE 页"占用
       匿名侧可写、文件侧只读 → 经匿名侧改写 → CPU 置 D bit → munmap 回写文件
步骤:
  1. 喷射匿名映射 PTE 页: mmap 大量 MAP_ANONYMOUS|MAP_SHARED（可写），按 PTE 索引布局
  2. 喷射文件映射 PTE 页: mmap 目标文件（如 /bin/umount）为 PROT_READ|MAP_SHARED（只读）
  3. page-level UAF（经 cross-cache 回收）让一个物理页同时被两类 PTE 页占用
  4. 扫描匿名侧找文件内容特征（如 \x7fELF）→ 发现 overlap
  5. 经匿名侧（可写）改写文件页内容 → 写入 shebang（#!/tmp/.helper\n）指向提权脚本
  6. CPU 自动置 D(dirty) bit → munmap 时内核写回文件 → 只读文件被永久覆写
  7. 触发: 让目标 suid 二进制（如 /bin/umount）被执行 → 走 shebang → 提权
优势: 比 Dirty Pagetable 改地址字段更简单；内存效率高（同一文件反复 mmap 只占一个物理页）
注: 用 read syscall 写内存而非直接写（UAF 时不知哪个 PTE 被改，直接写只读页会 SIGSEGV，read 返回 -1 不崩溃）
```

### 落点 D：Dirty Pageflags（PTE flag 翻转，比 PageTable 更简单）
**场景**: 有页级 UAF，但不需要改 PTE 地址字段，只需翻转 flags

```
原理: 不覆写 PTE 的物理地址（Dirty Pagetable 做法），而是翻转 PTE 的 flags 位
关键 flags:
  - R/W (Read/Write): 0=只读, 1=可写
  - U/S (User/Supervisor): 0=仅内核, 1=用户态可访问
  - P (Present): 0=触发缺页, 1=在内存中
  - XD (Execute Disable): 1=禁止执行

攻击步骤:
  1. 目标文件（如 /etc/passwd）被 mmap 为只读（R/W=0）
  2. 页级 UAF → PTE 页回收 → 喷射占位
  3. 翻转该文件 PTE 的 R/W 位: 0→1
  4. 写入修改 → CPU 自动设置 D (Dirty) bit
  5. munmap 时内核看到 D bit → 认为页被修改 → 写回文件 → 只读文件被覆写
优势: 只翻转一个 bit，比改地址字段更简单、更不容易触发检测
```

## §4 msg_msg 任意读写

**核心**: msg_msg 头部有 `m_ts`（消息大小）和 `next`（指向 msg_msgseg 数据段）。

```
任意读:
  1. msgsnd 申请 msg_msg（可控制 size 选 kmalloc slab）
  2. UAF 改大 m_ts → 越界读邻居 slab 泄漏
  3. 伪造 next 指针 → 任意地址读
  4. msgrcv 配合 MSG_COPY 实现无破坏读

任意写:
  配合 pipe_buffer / sk_buff（含有 write 函数指针的 ops）实现
```

## §5 竞态窗口扩大法（userfaultfd 替代）

> 现代 kernel 题 `userfaultfd` 普遍被禁用（需 `CAP_SYS_PTRACE`）。以下是替代方案。

| 方法 | 原理 | 适用场景 |
|------|------|---------|
| **FUSE** | 用户态 FUSE 文件系统阻塞内核 `read`，stall `copy_from_user` | 能触发内核读用户态数据 |
| **MADV_DONTNEED + 并发 mprotect** | MADV_DONTNEED 清 PTE 使每页缺页；另一线程疯狂 mprotect 翻转权限争抢 mmap_lock，把毫秒级窗口拖到数十秒 | 长遍历（哈希/check）中的竞态 |
| **io_uring** | 异步 IO stall | 内核 ≥ 5.1 且未禁 io_uring |
| **fallocate** | `fallocate(FALLOC_FL_PUNCH_HOLE)` 延迟 | 特定文件操作竞态 |
| **SIGALRM + 多线程** | 在 io 操作中插入可中断点 | 简单竞态 |

### MADV_DONTNEED + mprotect 详解
```c
// 线程 A: 疯狂翻转权限
while (racing) {
    mprotect(page, PAGE_SIZE, PROT_READ);
    mprotect(page, PAGE_SIZE, PROT_READ | PROT_WRITE);
    usleep(1);
}
// 主线程: MADV_DONTNEED 使 PTE 失效
madvise(page, PAGE_SIZE, MADV_DONTNEED);
// 线程 B: 触发长遍历（使缺页重试，拖住内核）
// → 在窗口内竞态触发漏洞
```

**机制（为什么有效）**——单独任一操作都不够，slowdown 来自两者交互:
1. `MADV_DONTNEED` 经 `zap_page_range_single`（madvise.c:845）清掉 PTE
2. 遍历大虚拟地址区时每页触发 page fault（fault-heavy）
3. `mprotect` 线程反复获取 `mmap_write_lock`（mprotect.c:740）并重写 VMA/PTE
4. fault 路径在 page-table 和 mmap 锁上争用，反复 retry（memory.c:3305）
5. 调 `usleep` 可把窗口从几毫秒拉到数十秒

> 关键: `MADV_DONTNEED` 使遍历 fault-heavy，`mprotect` 使这些 fault 昂贵——缺一不可。目标线程需被迫 walk 大虚拟地址范围（如哈希/check 遍历）。

## §6 cross-cache 攻击（跨 slab 缓存）

**场景**: 独立 slab 缓存（`SLAB_NO_MERGE`）的 UAF 只能拿到同类对象，需要跨类型重用。

**阈值计算（为什么单 CPU 不够）**:
- `objs_per_slab`（每 slab 对象数）和 `cpu_partial`（每 CPU partial 保留阈值）决定何时触发 `discard_slab`
- 例: `objs_per_slab=56`, `cpu_partial=120` → 每 CPU partial 保留 `ceil(120*2/56)=5` slabs
- 单 CPU 分配 N 个对象只能 touch `ceil(N/56)` slabs（如 N=128 → 3 slabs），远不够触发 discard_slab

**跨 CPU 积累法**:
```
原理: 把独立缓存的页归还 buddy allocator，再用别的 slab（msg_msg/pipe/PTE 页）回收该页
步骤（cross-CPU 法）:
  1. sched_setaffinity 绑定 CPU0 分配、CPU1 释放
  2. CPU0 分配建 slab（消耗 CPU0 当前 slab），CPU1 free 把页挂入 CPU1 partial
     （关键: 不同 CPU free 时，SLUB 把页挂入 free 方 CPU 的 partial，而非回收给分配方）
  3. 重复此模式 → CPU0 持续建新 slab，CPU1 partial 积累
  4. CPU1 partial 满后推 node partial → node partial 满后才 discard_slab → 页回 buddy/PCP
  5. 喷射目标结构体（msg_msg/pipe/PTE 页）回收该页
  6. UAF 块与目标结构体重叠 → 读写目标内容
```

## §7 mitigations 绕过组合

| 缓解 | 绕过 |
|------|------|
| KASLR | §2 结构体函数指针泄漏 + 全景（dmesg/wait_channel/9bit 爆破）|
| SMEP（不可执行用户页） | 内核 ROP / 栈迁移 / pt_regs 中的用户栈做 ROP。细化: **CR4 翻转**（<4.15: pop rcx + mov cr4,rcx 清 bit20, 0x1006f0→0x6f0, 后可 ret2usr; ≥4.15 CR4 pinning 封堵）/ JIT 代码（eBPF）/ shellcode 写内核页。栈迁移 gadget: `xchg eax,esp;ret`（低 32 位 mmap）/ `push rdi;pop rsp`（RDI=被劫持函数第一参常受控）|
| SMAP（不可读用户页） | `copy_from/to_user` / msg_msg 等内核内数据。细化: 伪结构必须内核堆喷射放置 / **stac;clac gadget** 临时开用户访问 / pipe-userfaultfd 分段送数据 |
| KPTI（隔离页表） | `swapgs_restore_regs_and_return_to_usermode` 跳板。**栈布局**: `tramp + p64(0)×2(padding) + 五元组[RIP][CS=0x33][RFLAGS][RSP][SS=0x2b]`; 替代——signal handler 法（exploit 前注册，提权后触发 fault，handler 以 root 运行）|
| FG-KASLR（函数粒度随机） | **.data/.rodata/percpu/异常表不随机**——modprobe_path/core_pattern 仍 base+固定偏移可打（首选 data-only）; 或泄漏对象函数指针逐个去随机化 / module JIT gadget。**__ksymtab 法**: ksymtab 段不随机化且条目存相对偏移（kernel_symbol{value_offset,name_offset}）——真实地址=&entry+value_offset; 两阶段 ROP: 一段读 4B 偏移（pop rax+mov eax,[rax]）→KPTI trampoline 回用户态算→二段用真实地址重入。未随机化早期 .text（≤~0x400dc6，含 swapgs_restore）gadget 直接用; ropr 地址过滤筛选 |
| kCFI（函数指针类型校验） | 同签名合法目标（如 commit_creds 与同类函数）|
| CFI 严苛时 | 改用非函数指针落点（modprobe_path / Dirty PageTable / 任意文件写）|
| STATIC_USERMODEHELPER | modprobe_path 锁死 → 转 **core_pattern** 或 cred 直写 |
| RANDSTRUCT（结构体偏移随机） | 任意读按特征（指针值/已知字段）推断实际布局; 或打未覆盖结构体 |
| Lockdown LSM | 需先内核代码执行——抬门槛不改链主体; `cat /proc/config.gz` 逐项确认缓解在位 |

**返回用户态**（绕 KPTI）:
```c
// 不能直接 ret 到用户态函数（KPTI 隔离）
// 用 swapgs_restore_regs_and_return_to_usermode + offset
// 或 modprobe_path 路径（无需切态）
// 完整三法与栈布局见 §7 KPTI 行
```

## §7a SLUB 堆喷射与对象表

**SLUB 加固**: `SLAB_FREELIST_RANDOM`（分配顺序随机化，影响喷射确定性）/ `SLAB_FREELIST_HARDENED`（`stored_fp = ptr ^ rand ^ &stored_fp`，同 safe-linking 思路）。

**喷射四步**: 定位目标 cache → 预喷射排空 free → 触发漏洞 → 同 size 补占。

**喷射原语族**:
| 原语 | 特性 |
|---|---|
| **setxattr** | 任意大小+内容 kmalloc 临时缓冲（copy 后 free）; 配 userfaultfd 暂停在 alloc-free 之间做稳定竞态 |
| **sk_buff** | sendto 喷 payload 全控、recvfrom 读回验证、网络时序配竞态 |
| **msg_msg** | 大小灵活+MSG_COPY 无破坏读+**驻留不 free**（setxattr 立即 free 需竞态才驻留）|

**对象大小表**（x86-64，版本相关）: seq_operations/shm_file_data 0x20→kmalloc-32; msg_msg 0x30+数据→64~4096; subprocess_info 0x60→96; timerfd_ctx 0x68→128; sk_buff head ~0xE0→专用; **cred 0xA8→cred_jar 专用（须 cross-cache）**; file 0x100→filp 专用; tty_struct 0x2B8/0x2e0→1024; pipe_buffer×16 0x280→1024; poll_list 0x10+变长。

**原语→目标选择**: 控制 RIP → pipe_buffer(ops)/seq_operations（open /proc/self/stat 分配，改 start，read 触发，rdi=seq_file）; 任意读 → msg_msg 改 m_ts/next; 任意写 → msg_msg+msgrcv 回收; KASLR 泄漏 → pipe_buffer 读 ops。**tty_struct kROP 两阶段**（，顺序写 ≥0x200B 全结构内自包含）: +0x00 magic=0x5401/+0x08 dev=`pop rsp` gadget/+0x10 driver=结构+0x170（须有效堆指针）/+0x18 ops=结构+0x50（假 vtable ioctl 槽=leave gadget）/+0x170 真 ROP——ioctl→leave（RBP 指结构）→RSP 落 +0x08→ret pop rsp→弹 driver 迁 +0x170。捷径: `push rdx;...;pop rsp` gadget + ioctl 第 3 参全控一步迁栈。**ioctl 寄存器 AAW**: cmd→部分控 RBX/RCX/RSI、arg→全控 RDX/R8/R12——假 vtable 放 `mov [rdx],esi;ret` 逐 4B 写 modprobe_path。

## §7b DirtyPipe（CVE-2022-0847）

新建 pipe 的 pipe_buffer flags 残留 `PIPE_BUF_FLAG_CAN_MERGE`（未初始化清除）→ `splice()` 把文件页挂 pipe 后带该标志 → 后续 write **直接覆写文件页缓存**（含只读文件，改动不落盘但提权足够）。
要点: 目标文件须可读（splice 前提）; 从 offset+1 开始覆写（首字节不可改）; 典型改 /etc/passwd 或 SUID 二进制后半段。影响 Linux 5.8-5.16.11/5.15.25/5.10.102。与 DirtyCow 同效（绕文件权限写）不同理（标志残留 vs 竞态）。

## §7c 两个非常规内核写原语

**I/O 端口 hypercall 三层链**（user→kernel→hypervisor）: hypervisor 陷阱端口 0x8000-0x80FF 当 syscall 分发（`out dx,eax`; dx=0x8000+syscall 号、eax=参数指针）。内核限制用户态直呼但**内核态代码可直接 poke**——用户态 GOT 覆写弹到内核 gadget → 内核态 out 直达 VMM。hypervisor 只接受内核内存中的字符串时: 先故意失败的 open() 让内核缓冲持路径再传址。规则: 多 ring 层叠先映射"数据住哪 vs 代码在哪跑"; VMM 陷阱端口/MMIO 区是变相 hypercall 且常缺参数消毒。

**ACPI DSDT 注入**: 攻击者可控 ACPI 表时——AML 在内核保护生效前以**直接物理内存访问**运行: `OperationRegion(PWDN, SystemMemory, 物理地址, 长度)`+Field 写 = 超强内核写原语（patch commit_creds 序言，任意 setuid 即提权）。识别: 启动流程加载用户提供 DSDT/SSDT。

## §7d set_fs(KERNEL_DS) 未恢复——CVE-2015-8966

ARM fcntl64 路径 set_fs(KERNEL_DS) 未恢复 USER_DS → 该线程 copy_from/to_user 不再做地址域检查（传内核地址直接拷贝）。**pipe 当安全 shim 外带**: 直读 MMU 敏感区会 panic——fork 子进程触发 bug 后 `write(pipe_w,(void*)kernel_addr,N)`，父进程 read 管道收回内核内存; 泄漏 cred 后原地改 uid/gid/euid/egid=0。审计: 任何 set_fs 调用对的全部提前 return 路径是否恢复 USER_DS（4.25+ 已整体移除 set_fs）。
**错误路径触发法**: debug 函数 filp_open 失败提前 return 不恢复——mkdir 把目标路径做成目录即触发 -EISDIR。**syscall 表改写用法**: pipe 中转 write/read 把 syscall_table+100/101 槽改为 prepare_kernel_cred/commit_creds → syscall(100,0)+syscall(101,ret) 提权（免 ROP 免 cred 定位）。

## §7d-2 页级 off-by-one 与 OOM killer

**pgoff off-by-one + 页级堆风水**: `if (vmf->pgoff > page_nr)` 差一字——pages 数组后 8B 被当 struct page 指针多映射一页。布局: 页级堆风水（比对象级可靠——页大+对齐保证）夹隔离 cache 页; 目标文件只读 open+splice() 入 pipe_buffer（首部 struct page 指针）; off-by-one 把只读文件页以 RW 权限重映射用户态 → 覆写 busybox 目标（/sbin/poweroff）root shell，~84.6%（CVE-2023-2008 风格）。
**OOM killer 滥用**: packet socket `setsockopt(PACKET_RX_RING)` 大分配（vzalloc 拆高阶）——**内存记内核账不涨自身 oom_score**（用户态 malloc 无效）→ OOM 杀 rcS/sh → busybox-init 按 inittab `::askfirst:/bin/ash` 重生 root shell。其他内核侧分配路径（netfilter）同理。

## §7d-3 panic CODE 外带与 SLUB freelist 细节

**panic CODE 泄漏**: initramfs（flag 常驻内核内存）+无 KASLR+RIP 控制——`jmp flag地址`，panic 消息 CODE 段打印的指令字节=flag。panic_on_oops=0 时受控 oops 走 dmesg（dmesg 泄漏族的变体）。
**SLUB freelist**: 5.7+ free 指针放对象**中间**（ALIGN(size/2,8)）非 offset 0——块首溢出够不到，邻块溢出/下溢仍可; CONFIG_SLAB_FREELIST_HARDEN: 指针 XOR per-cache random（GDB 查 kmem_cache_cpu freelist 值非内核地址即启用）。
**自定义 binfmt loader**: load_*_binary 在 install_exec_creds **之前**解析攻击者头——① header_offset 未校验 OOB 读 bprm->cred（printk 副信道外带）② `_clear_user(cred+0x10,0x48)` 全零 uid 族 → 提交即 root ③ vm_mmap 控 flags 内核帮忙映射 RWX。审计: header 边界/access_ok/printk 副信道三点。

## §7e eBPF verifier bypass

模式: verifier 寄存器预测 ≠ 硬件行为 → 失步寄存器绕指针算术检查 → map OOB=内核任意读写。
三步（右移失步）: `BPF_RSH reg,64`（verifier=0/runtime=原值——x86 shift 用低 6 位，移 64=移 0）→ `BPF_MUL reg,offset`（verifier 0*off=0 放行/runtime=off）→ `BPF_ADD map_ptr,reg`（越界）。helper 变体: bpf_skb_load_bytes 的 len 验证失步→栈溢出→ROP commit_creds(init_cred)。情报: 内核 changelog 每个 eBPF verifier 补丁=此前有可利用 bug。检查 `/proc/sys/net/core/bpf_jit_enable`。
**eBPF verifier 漏洞完整利用链**: ④ 泄漏 kernel .text——bpf_map 元数据 vtable 指针（KASLR defeat）⑤ 任意读——corrupted btf 指针 + bpf_obj_get_info_by_fd ⑥ 劫持——init_pid_ns radix tree 搜当前 task_struct、map_get_next_key vtable 改 work_for_cpu_fn 执行 commit_creds(&init_cred); ALU sanitizer（Spectre 缓解）靠管理指针 offset 范围过 alu_limit。

**内核审计三细节**: ① ioctl 可改模块全局 MaxBuffer（write 长度检查用它）→ 先抬阈值再溢出 ② tty_struct 劫持: magic(+0x00) 须 0x5401（paranoia 检查）、driver(+0x10) 须有效堆指针、ops(+0x18) 泄漏/劫持双用 ③ kmalloc 头体不匹配（kmalloc(len) 但 memcpy 头 0x40+体 len）→ 溢出覆盖邻 struct file 的 f_op → 假 vtable 经 fd 操作触发（老内核 kmalloc-256; 新内核 filp 专用须 cross-cache §6）。

## §8 关联文件

- `$SHARED_DIR/knowledge-base/pwn-methodology.md` — 标准 8 步流程、mitigations 速查
- `$SHARED_DIR/knowledge-base/pwn-heap-methodology.md` — 用户态堆利用详解
