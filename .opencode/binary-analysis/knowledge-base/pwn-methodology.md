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
heap_key = leaked_fd >> 12  # 通常为 0
```

### 步骤 6：落点选择
按 glibc 版本查 §3 决策树，选择劫持目标（hook/IO_FILE/exit_funcs/_rtld_global/TLS）。
详细伪造模板见 `pwn-heap-methodology.md`。

### 步骤 7：触发执行
```bash
one_gadget <libc.so>                 # 找 one_gadget（约束条件需满足）
```
- one_gadget 约束不满足 → 换 `system("/bin/sh")` 或栈迁移 ROP
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
| Canary | 栈溢出被检测 | 泄漏 canary / 爆破（fork 进程）/ TLS 覆盖法 |
| NX/DEP | 不可执行 shellcode | ROP / ret2libc / ret2csu |
| ASLR | 地址随机化 | 信息泄漏（unsorted bin / 格式化字符串） |
| seccomp(ORW) | 禁 execve | open→read→write 链；禁 open 则 openat / memfd_create |
| FORTIFY | 限制危险函数 | 换等价函数绕过 |
| **内核** SMEP | 内核不可执行用户页 | 内核 ROP / 栈迁移 / pt_regs 做内核 ROP |
| **内核** SMAP | 内核不可读用户页 | copy_from/to_user / msg_msg 等内核内数据 |
| **内核** KPTI | 隔离页表 | swapgs_restore 跳板返回用户态 |
| **内核** KASLR | 内核地址随机 | 结构体函数指针泄漏（tty_struct 等） |
| CET/Shadow Stack | 返回地址校验 | 改函数指针而非返回地址 / 合法栈帧 |
| CFI(kCFI/RFP) | 间接调用类型校验 | 同签名合法目标 / 非函数指针落点 |
| ARM PAC | 指针带签名 | 签名重用 / 已签指针直接用 |
| ARM MTE | 内存染色标签 | 概率爆破 / tag 旁路 |

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
# 绕过: 泄漏堆地址得到 pos>>12（通常首次为0），或 safe_link_double_protect 无泄漏法
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

## §5 工具链

| 工具 | 用途 | 安装 | 关键用法 |
|------|------|------|---------|
| pwntools | exploit 框架 | `pip install pwntools` | `context.update(arch='amd64', os='linux')` / `remote()` / `process()` / `cyclic_find()` |
| pwndbg | gdb 插件（堆查看） | `git clone https://github.com/pwndbg/pwndbg && cd pwndbg && ./setup.sh` | `heap` / `tcache` / `vis_heap_chunks` / `io` / `tls` |
| one_gadget | 找 libc one_gadget | `gem install one_gadget` | `one_gadget <libc.so>` |
| ROPgadget | 找 ROP gadget | `pip install ROPgadget` | `ROPgadget --binary <binary> --re "pop rdi"` |
| patchelf | 改 rpath/interpreter | `brew install patchelf` | `patchelf --set-interpreter <ld> --set-rpath <dir> <binary>` |
| glibc-all-in-one | 下各版本 libc/ld | `git clone https://github.com/matrix1001/glibc-all-in-one` | `./update_list.sh` → `./download <id>` |
| how2heap | 堆技术 PoC 库 | `git clone --recursive https://github.com/shellphish/how2heap` | 按 glibc 版本目录查找对应 PoC |
| seccomp-tools | 分析 seccomp 规则 | `gem install seccomp-tools` | `seccomp-tools dump ./<binary>` |
| LibcSearcher | 由偏移反查 libc | `git clone https://github.com/lieanu/LibcSearcher` | 或在线 libc.rip / libc.blukat.me |
| angr | 符号执行/约束求解 | `pip install angr` | 详见 `$SHARED_DIR/knowledge-base/angr-exploration.md`（如已有） |

> pwndbg vs gef：二选一勿同时加载（命令冲突）。pwndbg 堆查看更强（默认首选），gef 多架构支持更好。

**pwntools 调试模式**：
```python
context.terminal = ['tmux', 'splitw', '-h']  # 配合 gdb.attach
p = process('./binary')
gdb.attach(p, 'b *0x401234\nc')  # 设断点并继续
p.interactive()
```

## §6 关联文件

- `$SHARED_DIR/knowledge-base/pwn-heap-methodology.md` — 堆利用详解：House of Apple/Cat/Water/Tangerine 伪造模板、safe-linking 绕过、原语速查
- `$SHARED_DIR/knowledge-base/pwn-kernel-methodology.md` — 内核利用详解：结构体泄漏表、msg_msg/Dirty PageTable、竞态窗口扩大、cross-cache
- `$SHARED_DIR/knowledge-base/analysis-planning.md` — 通用分析规划流程
