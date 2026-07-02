# Pwn 堆利用方法论 — 原语、落点与伪造模板

> 堆利用详细参考。标准 8 步流程见 `$SHARED_DIR/knowledge-base/pwn-methodology.md`。

## 触发条件

已定位到堆漏洞（UAF/OOB/DF），需要升级为 RCE。本文件回答："拿到漏洞后怎么构造利用链"。

## §1 漏洞 → 原语升级

| 漏洞类型 | 直接能力 | 升级路径 |
|---------|---------|---------|
| UAF（free 后指针未置空） | 读/写已释放块 | tcache poisoning → 任意地址分配；或 house_of_botcake → 重叠块 |
| OOB（越界读写） | 读/写相邻块 | 改 top chunk size → House of Tangerine；或改邻居 fd → tcache poisoning |
| DF（double free） | 同一块进 freelist 两次 | tcache dup → 任意地址分配（2.29+ 见下） |
| 栈溢出 (BOF) | 覆盖返回地址 | ROP / ret2libc / canary 泄漏 |
| 格式化字符串 | 任意读 + 任意写 | 直接泄漏 libc/栈 → 改 GOT / __malloc_hook（≤2.33） |

**double free 绕过（glibc 2.29+ tcache key 检查后）**:
连续双 free 同 bin 被 tcache key 拦截，剩 4 条路径:
1. fastbin 双 free（不连续）
2. 首次 fastbin、二次 tcache
3. 首次 unsorted、二次 tcache
4. 首次 unsorted、二次 fastbin
路径 3/4 的关键: unsorted bin coalesce 改变 chunk size，使第二次 free 落入不同 bin 绕过 key 检查（如 0xa0 chunk 合并成 0x130 → 进 0x130 tcache）

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

### 方法 3：解密已毒化的指针
```python
# 从 tcache fd 反推真实地址
real_addr = encrypted_fd ^ (chunk_addr >> 12)
```

## §3 核心堆原语速查

| 原语 | 输入要求 | 输出能力 | 版本边界 |
|------|---------|---------|---------|
| **tcache_poisoning** | UAF 或能改 tcache fd | 任意地址分配 | 2.26+ |
| **large_bin_attack** | 能改 large bin 块的 bk_nextsize | 堆地址写到任意地址 | 2.30+ ⚠**2.42 已补** |
| **house_of_botcake** | double free 能力 | 重叠块（同时 in tcache 和 unsorted） | 通用 |
| **tcache_stashing_unlink** | 能改 smallbin 块的 bk | smallbin 回填 tcache 时劫持 | 2.29+ |
| **fastbin_reverse_into_tcache** | 能控制 fastbin | fastbin 释放时向 tcache 写堆地址 | 2.26-2.41 ⚠**2.42 已补** |
| **poison_null_byte** | OOB 能写一个 \0 | off-by-one 制造重叠块 | 通用 |

### 原语操作详解

#### tcache_poisoning（2.26+，2.32+ 新增三项检查）
1. **safe-linking**: fd 经 `(pos>>12)^ptr` 加密，需先泄漏堆地址算 key（§2 方法 1/3）
2. **count 检查**: fd 劫持前需先 free 一个**同 size** chunk 作 padding（否则 count=0 时 malloc 触发 abort）
3. **对齐检查**: 目标地址须 **0x10 对齐**（glibc 检查返回地址对齐，不对齐 abort）

#### large_bin_attack（构造任意写的核心原语，2.30+，⚠2.42 已补）
```
前提: 一个块已在 large bin 中，且能改其 bk_nextsize
步骤:
  1. malloc(0x428) 和 malloc(0x418)（同 large bin 但不同 size）
  2. free(p1)，大分配使 p1 入 large bin
  3. free(p2)（进 unsorted bin）
  4. 改 p1->bk_nextsize = &target - 0x20
  5. 大分配把 p2（更小）从 unsorted 插入 large bin
  6. 执行 victim->bk_nextsize->fd_nextsize = victim → target 被写为 p2 地址
结果: target 处被写入一个堆地址（配合 IO_FILE 攻击改 _IO_list_all 等）
注意: glibc 2.30 起加了双检查，但新插入 chunk 比当前最小还小时不检查 bk_nextsize 链——这是唯一可用路径，构造时 victim(p2) size 必须严格小于已在 bin 的 p1
```
**2.42 补后替代**: House of Water / Tangerine / tcache_metadata_hijacking（§5/§6/§7）

#### fastbin_reverse_into_tcache（2.26-2.41，⚠2.42 已补）
1. **标准操作（所有版本）**: free 7 次填满 tcache → victim 进 fastbin → 再 free 6 次填满 fastbin（共 14 次 free）
2. **2.32+ 额外**: 需堆泄漏（safe-linking）
3. **优化路径**: 若能控制栈上 ≥8 字节，在栈上放 `stack_addr>>12`（safe-linking 加密的 NULL，即 `(pos>>12)^0`）作为 fake chunk 的 fd → 只需再 free 1 次即可终止 fastbin 遍历（省掉后 6 次 free）
**2.42 补后替代**: tcache_metadata_hijacking（§7）

#### tcache_stashing_unlink（2.29+）
1. **必须用 calloc 触发**（calloc 跳过 tcache 直接取 smallbin，才触发"剩余 smallbin 回填 tcache"的逻辑；malloc 会先消费 tcache 不触发）
2. **需一个 writable 地址**作 fake_chunk->bk（绕过 glibc 的 `bck->fd = bin` 检查，只读地址会 crash）

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

**stderr 宽字符 vtable payload 模板**（覆盖 stderr，system(";sh") 触发）:
```python
# 偏移相对伪造的 _IO_FILE 起始
fake = b""
fake += p32(0xfbad0101) + b";sh\x00"             # +0x00 _flags（含 ";sh" 供 system 切分参数）
fake = fake.ljust(0x58, b"\x00")
fake += p64(libc.sym['system'])                    # +0x58 vtable->__doallocate → system
fake = fake.ljust(0x88, b"\x00")
fake += p64(addr_of_fake - 0x10)                   # +0x88 _wide_data → 指向自身（伪造 wide_data）
fake = fake.ljust(0xa0, b"\x00")
fake += p64(addr_of_fake - 0x10)                   # +0xa0 _wide_data 备份
fake = fake.ljust(0xc0, b"\x00")
fake += p32(1)                                     # +0xc0 _mode != 0（走 wide 路径）
fake = fake.ljust(0xd0, b"\x00")
fake += p64(addr_of_fake - 0x10)                   # +0xd0 _wide_data->vtable
fake += p64(libc.sym['_IO_wfile_jumps'] + 0x18 - 0x58)  # +0xd8 vtable 偏移使 __doallocate 命中
# 用任意写把 fake 写到已知地址 addr_of_fake，再改 stderr 指向它，触发 exit
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
  2. OOB 改 top size: new_top_size = top_size & PAGE_MASK（清掉非页对齐位，绕过 malloc.c:2599 检查）
  3. malloc(SIZE_3)（大于可用 top）→ 旧 top 经 _int_free 进 tcache
  4. 用堆泄漏计算 safe-linking，改 tcache next 指向目标
  5. 两次 malloc 取回目标地址
关键约束:
  - freed_top_size = (new_top_size - FENCEPOST) & MALLOC_MASK
    FENCEPOST = 2*CHUNK_HDR_SZ = 0x20（两个 fencepost chunk 头）
  - freed_top_size 必须等于目标 tcache size（如 0x40），否则进错 bin
  - sysmalloc_int_free 适用范围更广（2.27/2.31/2.34/2.39），House of Tangerine 标称 2.34+；
    2.27-2.33 的无 free 场景应优先用 sysmalloc_int_free
需要: 5 次 malloc + 3 次 OOB
```

### sysmalloc_int_free（同类技术）
- 与 House of Tangerine 类似，利用 sysmalloc 对超大 top chunk 的 _int_free
- 适用范围更广（2.27/2.31/2.34/2.39），House of Tangerine 标称 2.34+；2.27-2.33 应优先用此法

## §6 House of Water（glibc 2.36+，UAF → tcache metadata 控制）

**场景**: 仅 UAF/双 free，无任意写，glibc 2.32-2.39

**目标结构**: `tcache_perthread_struct` 是堆上第一个 chunk（0x290 字节），含 `counts[64]`（每 bin 计数）和 `entries[64]`（每 bin 头指针）。控制 entries[idx] 即可让 `malloc(对应size)` 返回任意地址。entries 存的是**原始指针**（未 safe-linking 加密）。

**前提**: 需要 **arbitrary free** 原语（能 free 任意地址）。用于在 tcache metadata 上方伪造两个假的 chunk 头（size=0x331 和 0x321），使后续操作能控制 metadata。通常配合 house_of_botcake 获得任意 free。

```
核心思路: 把 UAF 转化为对 tcache_perthread_struct 的控制
步骤:
  1. 布置堆布局: 在紧邻 tcache metadata 的位置放两个 chunk（利用它们地址的低位相同）
  2. 用 arbitrary free 在 metadata 上方伪造假 chunk 头（0x331/0x321），使其被当作 smallbin chunk
  3. 三块进 unsorted bin → 大分配归入同一 small bin
  4. UAF 改 smallbin chunk 的 fd/bk 低位为 0x00 → 指向 metadata 上的假 chunk
  5. 排空 tcache → 从 small bin 取出 → 第三次分配返回 metadata → 改 entries[idx] → 任意地址分配
```

**为什么无需 4-bit 爆破**: tcache_perthread_struct 是堆第一个 chunk，地址低 12 位 ≈ 0x290。步骤 1 放的 chunk 紧邻 metadata（同页内），ASLR 第二 nibble（bit 12-15）相同。步骤 4 改 fd/bk 的 LSB 为 0x00 即可让指针落到 metadata 上（metadata+0x200 附近），无需猜测 nibble。

## §7 版本边界速查（哪些技术在哪个版本被补）

> 以下仅列 §3 速查表未覆盖的版本变化。large_bin_attack / fastbin_reverse 的版本与替代见 §3 原语操作详解。

| 技术 | 有效版本 | 被补版本 | 替代方案 |
|------|---------|---------|---------|
| `__malloc_hook`/`__free_hook` | ≤ 2.33 | 2.34 移除 | IO_FILE / exit_funcs / _rtld_global |
| fastbin_dup / house_of_mind_fastbin | < 2.43 | **2.43 补** | tcache_metadata_hijacking |
| safe-linking | ≥ 2.32 新增 | 未补 | 泄漏法 / double_protect / unsorted bin |

> **glibc 2.42+ 策略**：优先 House of Water / Tangerine / tcache_metadata_hijacking / exit_funcs / _rtld_global，避开已补的原语。

### tcache_metadata_hijacking（2.42+ 首选任意分配原语）

`tcache_perthread_struct` 是堆上第一个 chunk（通常 0x290），位于 `heap_base`：
```
counts[64]  : uint16_t × 64 = 0x80   (每个 tcache bin 计数)
entries[64] : ptr     × 64 = 0x200   (每个 tcache bin 头指针)
```
**关键**：`entries[]` 存的是**原始指针**（未 safe-linking）。写到 entries 后无需堆泄漏绕 safe-linking。

```
步骤（把"任意写"升级为"任意地址分配"）:
  1. 获得触及 tcache_perthread_struct 的写原语:
     - House of Water 路线: smallbin 改 fd/bk 低位指向 metadata
     - tcache_poisoning 反打: 毒化 fd 指向 heap_base
  2. 改 entries[tc_idx] = target_addr，counts[tc_idx] 写非 0
  3. malloc(对应大小) 直接返回 target_addr（首次取回不受 safe-linking 影响）
  4. 往目标写伪造内容（_dl_rtld_lock_recursive / IO 结构），触发 exit
```

### 2.42+ 落点决策树

| 手上原语 | 推荐落点 | 说明 |
|---------|---------|------|
| 单次任意写 | **`_rtld_global._dl_rtld_lock_recursive`** | 无加密，写一次即劫持，exit 触发。**2.42+ 最干净** |
| 任意写 + 泄漏 pointer guard | `__exit_funcs`（atexit 链） | fn 受 PTR_MANGLE 保护，需算值 |
| 任意写 + FSOP | 改 `_IO_list_all` + House of Apple | 2.42 前用 large_bin_attack；后用 metadata_hijack 直接分配伪造块 |
| 仅 UAF / 无 free | House of Tangerine → tcache poison → metadata_hijack | 2.34+ 通用 |
| UAF + 堆泄漏 | House of Water → metadata_hijack → 任意分配 | smallbin 变体无需爆破 |

**一句话**：2.42+ 通用公式 = `任意分配(metadata_hijack) → 落 _dl_rtld_lock_recursive / IO 伪造 → exit`

## §8 关联文件

- `$SHARED_DIR/knowledge-base/pwn-methodology.md` — 标准 8 步流程、mitigations 速查、卡点突破表
- `$SHARED_DIR/knowledge-base/pwn-kernel-methodology.md` — 内核利用详解
