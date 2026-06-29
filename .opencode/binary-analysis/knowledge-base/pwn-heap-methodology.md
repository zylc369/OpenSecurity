# Pwn 堆利用方法论 — 原语、落点与伪造模板

> 堆利用详细参考。标准 8 步流程见 `$SHARED_DIR/knowledge-base/pwn-methodology.md`。
> 一手 PoC 源码参考: 源文档库 `docs/资料/writeup-sources/pwn/how2heap-*.c`（可编译验证）。

## 触发条件

已定位到堆漏洞（UAF/OOB/DF），需要升级为 RCE。本文件回答："拿到漏洞后怎么构造利用链"。

## §1 漏洞 → 原语升级

| 漏洞类型 | 直接能力 | 升级路径 |
|---------|---------|---------|
| UAF（free 后指针未置空） | 读/写已释放块 | tcache poisoning → 任意地址分配；或 house_of_botcake → 重叠块 |
| OOB（越界读写） | 读/写相邻块 | 改 top chunk size → House of Tangerine；或改邻居 fd → tcache poisoning |
| DF（double free） | 同一块进 freelist 两次 | tcache dup → 任意地址分配 |
| 栈溢出 (BOF) | 覆盖返回地址 | ROP / ret2libc / canary 泄漏 |
| 格式化字符串 | 任意读 + 任意写 | 直接泄漏 libc/栈 → 改 GOT / __malloc_hook（≤2.33） |

**关键转换**：大多数漏洞需要先升级为 **任意写**（写任意值到任意地址），再配合 §4 落点完成 RCE。

## §2 safe-linking 绕过（glibc ≥ 2.32）

glibc 2.32 起 tcache/fastbin 的 fd 经 `(pos >> 12) ^ ptr` 异或保护（pos = fd 字段所在地址）。

### 方法 1：泄漏堆地址（最可靠）
```python
# 泄漏堆地址（从堆指针：unsorted bin 中多 chunk 的 fd/bk、或 UAF 读相邻 free chunk 的指针）
heap_addr = leaked_heap_ptr
key = heap_addr >> 12  # safe-linking key
poisoned_fd = key ^ target_addr  # 构造毒化 fd
```

### 方法 2：double_protect（无泄漏盲绕过）
原理：`(ptr ^ key) ^ key = ptr`，二次保护等于不保护。
- 前提：已控制 tcache metadata（配合 House of Water，§6）
- 限制：写原语需 4-bit 爆破（LSB 有 4 bit 随机性）；有递增能力则无需爆破
- 源码参考: `how2heap-safe_link_double_protect.c`

### 方法 3：解密已毒化的指针
```python
# 从 tcache fd 反推真实地址
real_addr = encrypted_fd ^ (chunk_addr >> 12)
```
- 源码参考: `how2heap-decrypt_safe_linking.c`

## §3 核心堆原语速查

| 原语 | 输入要求 | 输出能力 | 版本边界 | 源码参考 |
|------|---------|---------|---------|---------|
| **tcache_poisoning** | UAF 或能改 tcache fd | 任意地址分配 | 2.26+（2.32+ 需绕 safe-linking） | how2heap-tcache_poisoning.c |
| **large_bin_attack** | 能改 large bin 块的 bk_nextsize | 堆地址写到任意地址 | 2.30+ ⚠**2.42 已补** | how2heap-large_bin_attack.c |
| **house_of_botcake** | UAF + 能 free 同一块两次 | 重叠块（同时 in tcache 和 unsorted） | 通用 | how2heap-house_of_botcake.c |
| **tcache_stashing_unlink** | 能改 smallbin 块的 bk | smallbin 回填 tcache 时劫持 | 2.29+ | how2heap-tcache_stashing_unlink_attack.c |
| **fastbin_reverse_into_tcache** | 能控制 fastbin | fastbin 释放时向 tcache 写堆地址 | 2.26-2.41 ⚠**2.42 已补** | how2heap-fastbin_reverse_into_tcache.c |
| **poison_null_byte** | OOB 能写一个 \0 | off-by-one 制造重叠块 | 通用 | （how2heap 仓库） |

### large_bin_attack 详解（构造任意写的核心原语）
```
前提: 一个块已在 large bin 中，且能改其 bk_nextsize
步骤:
  1. malloc(0x428) 和 malloc(0x418)（同 large bin 但不同 size）
  2. free(p1)，大分配使 p1 入 large bin
  3. 改 p1->bk_nextsize = &target - 0x20
  4. free(p2)，再大分配把 p2（更小）插入
  5. 执行 victim->bk_nextsize->fd_nextsize = victim → target 被写为 p2 地址
结果: target 处被写入一个堆地址（配合 IO_FILE 攻击改 _IO_list_all 等）
注意: glibc 2.42 已修补此路径
```

## §4 glibc 2.34+ 落点伪造模板

> `__malloc_hook`/`__free_hook` 在 2.34 被移除后，以下落点替代。

### 落点 A：House of Apple（IO_FILE wide-data vtable）
**场景**: glibc 2.35-2.39，有任意写 + 能触发 FSOP（exit / _IO_flush_all_lockp）

```
步骤:
  1. 泄漏 libc 基址 + 堆基址
  2. 伪造 _IO_FILE 结构:
     - _flags = 0（绕过检查）
     - _wide_data 指向可控堆块（伪造的 wide_data）
  3. 伪造 wide_data 的 vtable 指向 _IO_wfile_jumps 偏移:
     使 __doallocate 落在 system / one_gadget
  4. 用 large_bin_attack 或任意写改 _IO_list_all 指向伪造的 _IO_FILE
  5. 调用 exit() → 遍历 _IO_list_all → 触发 _IO_wfile_overflow → vtable 调用 → RCE
```

### 落点 B：exit_funcs 劫持
**场景**: 有任意写 + 能触发 exit

```
步骤:
  1. 泄漏 pointer guard（位于 TLS，glibc 2.34+ 偏移固定）
     pwndbg: p/x $fs_base  →  找 pointer guard 偏移
  2. 用 PTR_MANGLE 规则计算目标值:
     mangled = rol((ptr ^ pointer_guard), 17)  # 先异或 pointer_guard，再左旋 17 位
     pwntools: from pwn import *; rol(target ^ key, 17, 64)
  3. 任意写覆盖 __exit_funcs->next 或 initial 的 fn 指针
  4. 触发 exit → 遍历 atexit handler → 执行伪造函数
```

### 落点 C：_rtld_global 劫持（最简单，无加密）
**场景**: 有任意写 + exit 触发，`_dl_rtld_lock_recursive` 可写

```
步骤:
  1. 泄漏 ld.so 基址（_rtld_global 在 ld.so 数据段）
  2. 任意写覆盖 _rtld_global._dl_rtld_lock_recursive = one_gadget / system
  3. 触发 exit → _dl_fini → 调用 _dl_rtld_lock_recursive → RCE
优势: 该指针无 PTR_MANGLE 加密，一次任意写即可劫持
```

## §5 无 free 场景

### House of Tangerine（House of Orange 现代版，无需 free）
**场景**: glibc 2.34+，有 BOF/OOB 但无 free 函数

```
原理: 利用 sysmalloc 对 top chunk 的 _int_free（malloc.c:2913）
步骤:
  1. malloc 探测当前 top size
  2. OOB 改 top size 为页对齐（保留 PAGE_MASK 位绕过检查）
  3. malloc(SIZE_3)（大于可用 top）→ 旧 top 经 _int_free 进 tcache
  4. 用堆泄漏计算 safe-linking，改 tcache next 指向目标
  5. 两次 malloc 取回目标地址
需要: 5 次 malloc + 3 次 OOB
源码: how2heap-house_of_tangerine.c（含详细 glibc 代码行引用）
```

### sysmalloc_int_free（同类技术）
- 源码: how2heap-sysmalloc_int_free.c
- 与 House of Tangerine 类似，利用 sysmalloc 对超大 top chunk 的 _int_free

## §6 House of Water（glibc 2.36+，UAF → tcache metadata 控制）

**场景**: 仅 UAF/双 free，无任意写，glibc 2.32-2.39

```
原理: 把 UAF 转换为 tcache_perthread_struct 元数据控制（任意地址分配）
步骤:
  1. 布置 relative_chunk（紧邻 tcache metadata，共享 ASLR 第二 nibble=2）
  2. 伪造 0x331/0x321 头部使 small_start/end 头部进 0x330/0x320 tcache
  3. 三块进 unsorted bin，大分配归入同一 small bin
  4. UAF 改 small_start 的 fd 和 small_end 的 bk 低位为 0x00
     → 指向 tcache metadata 上的 fake chunk
  5. 排空 tcache → 从 small bin 取出 → 第三次分配返回 fake chunk
     → 控制 tcache 元数据 → 任意地址分配
优势: smallbin 变体无需 4-bit 爆破
源码: how2heap-house_of_water.c（317 行，含 step-by-step 注释）
```

## §7 版本边界速查（哪些技术在哪个版本被补）

| 技术 | 有效版本 | 被补版本 | 替代方案 |
|------|---------|---------|---------|
| `__malloc_hook`/`__free_hook` | ≤ 2.33 | 2.34 移除 | IO_FILE / exit_funcs / _rtld_global |
| large_bin_attack | 2.30+ | **2.42 补** | House of Water / Tangerine |
| fastbin_reverse_into_tcache | 2.26+ | **2.42 补** | tcache_metadata_hijacking |
| fastbin_dup / house_of_mind_fastbin | < 2.43 | **2.43 补** | 同上 |
| safe-linking | ≥ 2.32 新增 | 未补 | 泄漏法 / double_protect / unsorted bin |

> **glibc 2.42+ 策略**：优先 House of Water / Tangerine / tcache_metadata_hijacking / exit_funcs / _rtld_global，避开已补的原语。

## §8 关联文件

- `$SHARED_DIR/knowledge-base/pwn-methodology.md` — 标准 8 步流程、mitigations 速查、卡点突破表
- `$SHARED_DIR/knowledge-base/pwn-kernel-methodology.md` — 内核利用详解
- 源文档库 `docs/资料/writeup-sources/pwn/` — how2heap PoC 一手源码（10 个核心 PoC）
