# Pwn 堆利用方法论 — 原语、落点与伪造模板

> 堆利用详细参考。标准 8 步流程见 `$SHARED_DIR/knowledge-base/pwn-methodology.md`。

## 触发条件

已定位到堆漏洞（UAF/OOB/DF），需要升级为 RCE。本文件回答："拿到漏洞后怎么构造利用链"。

## §0 bins 基础结构（64-bit）

| bin | 大小范围 | 结构 | 核心特征 |
|---|---|---|---|
| tcache | 0x20-0x410 | 单链表 LIFO | 每线程每 size 最多 7 个; <2.29 无检查; 2.32+ safe-linking |
| fastbin | 0x20-0x80 | 单链表 LIFO | 不合并相邻 chunk; 分配时验证目标处 size 合法 |
| unsorted bin | 任意 | 双向循环链表 | free 暂存处; 唯一空闲 chunk 的 fd/bk 都指向 main_arena+offset（libc 泄漏点）|
| small bin | 0x20-0x3F0 | 双向循环链表 FIFO | 精确匹配 |
| large bin | ≥0x400 | 双向循环 + skip | 按大小排序，含 fd_nextsize/bk_nextsize（攻击面）|

chunk 头: prev_size(8B，仅前块空闲有效) + size(8B，低 3 bit: P=PREV_INUSE/M=IS_MMAPPED/A=NON_MAIN_ARENA); 空闲时 user data 前 16B 变 fd/bk。
first-fit: tcache/fastbin 均 LIFO，free 后同 size malloc 极大概率返回同一地址——UAF 重分配占领的基础。
安全机制版本线: 2.26 tcache → 2.29 tcache key+unsorted 链表完整性检查 → 2.32 safe-linking → 2.34 移除 hooks → 2.35+ count/arena 校验增强。

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

**C++ 对象的 vtable 劫持模式**: UAF 对象含 vtable → 同 size malloc 覆盖，vtable 指针位写 fake_vtable → 对应虚函数槽位放 one_gadget/system → 悬垂指针触发 `call [rax+N]`。system 参数: 虚函数 rdi=this 指向对象自身 → 对象起始放 "/bin/sh"，system(this) 即 shell。定位: gdb `p sizeof(*obj)` 定大小 / vtable 通常在 offset 0 / 反编译找 `call [rax+N]` 定槽位。**指针值即参数变体**: 喷洒使对象地址低字节恰为 `0x6873`（ASCII "sh\0"）——vtable 指针值自身即合法命令串，system(this) 直接执行，无需另控字符串。

**变体技巧三条**:
- **计数器算术 shim**: OOB 写 QWORD 对齐无法切片函数指针时，用同 struct 内按已知步进递增的计数器（written_bytes 类）做指针算术——指针挪进计数器槽、正常操作 N 次加 N*stride、写回函数指针槽。绕 PIE 零泄漏。
- **IS_MMAPED 位翻转**: calloc 清零阻断 unsorted 泄漏时，溢出改相邻已释放块 size |= 0x2（IS_MMAPED）→ calloc 视作 mmap 来源跳过 memset → fd/bk 的 main_arena 指针保留可读。2-bit 覆写破"calloc 无泄漏"假设。
- **regex 约束 LSB 覆写**: 内容过滤（regex/charset）两个突破口——①过滤器只校验首个 null 终止串，null 后字节任意 ②堆指针共享高位，只覆写 LSB 在同 256B 窗口重定位（如 prev_file→file->data 伪造 fake chunk）。

**漏洞形态两条**:
- **realloc(ptr,0) 造 UAF**: glibc 的 realloc(ptr,0)=free+返回 NULL——edit/resize 功能 size 用户可控时传 0 即释放，**不走应用 delete 处理器**（绕过引用计数/指针置空/数组清槽），旧索引变悬垂; tcache 时代可反复触发做 poisoning。审计: 找 realloc+size 来自输入+返回值未更新指针。
- **单字节 refcount 回绕**: uint8_t 引用计数 addref 256 次回绕到 0，全部 handle 仍持指针但一次 release 即 free——重分配填 fake vtable 后经存活 handle 调用。生命周期计数器宽度必须超过会话 handle 上限，uint8_t 恒红旗。
- **进制转换表示膨胀**: 数字高进制短表示（base-36）存入后转低进制（base-2）原地覆写——长度差溢出相邻 chunk 元数据。可写字符集限于 0-9a-z 时选"值域可达"的元数据组合（size 低位落字母数字区间的合法值）。审计一切"数字↔字符串"原地转换。

**杂项识别点**: cgo 编译的 Go 二进制中 C 结构体（含函数指针首字段）与 Go buffer 相邻——经典 C 堆技术适用，反编译找 GoString+char*+fn 指针确定性布局; tcache/fastbin 在 size class 边界共享，分配预算 <7 时可用"填 tcache→溢出改 fastbin fd→drain tcache→free 促 promotion 回 tcache"作额外交互步; strcpy 尾部 NUL 天然 off-by-null 源（不需专门漏洞，Einherjar 布局直接可用）; 菜单题先反汇编解析器找未文档化分支（1337/9999 类调试后门常绕分配计数上限）; 未初始化字段是"反向 write-what-where"——不控内容但可控位置（chunk 复用把残留指针送进只读不写的字段，print 解引用即泄漏）; **free(NULL) 是合法 no-op**——计算器类程序对内容可控缓冲 free 时把该槽置 0 防崩（非零非法指针 free 会 abort）。

**结构体指针覆写（堆菜单题）**: struct 混合 data 缓冲区+指针字段（如 `{char name[36]; int *grade_ptr; float gpa;}`），modify/edit 读入超过 data 长度 → 溢出覆盖相邻指针字段为 GOT 地址 → 之后经该指针的正常写操作（`scanf("%d", s->ptr)`）变成 GOT 任意写。**GOT 目标选择**: 先看 win 函数内部调用哪些 libc 函数，禁止覆盖 win 内部用的（死循环/崩溃）; 选主循环中写入之后仍会调用的（printf/free/getchar/malloc/scanf 常安全; win 用 puts/fopen/exit 时可选 printf/free; win 用 printf/system 时可选 puts/exit/free）。

## §2 safe-linking 绕过（glibc ≥ 2.32）

glibc 2.32 起 tcache/fastbin 的 fd 经 `(pos >> 12) ^ ptr` 异或保护（pos = fd 字段所在地址）。

### 方法 1：泄漏堆地址（最可靠）
```python
# 泄漏堆地址（从堆指针：unsorted bin 中多 chunk 的 fd/bk、或 UAF 读相邻 free chunk 的指针）
heap_addr = leaked_heap_ptr
key = heap_addr >> 12  # safe-linking key
poisoned_fd = key ^ target_addr  # 构造毒化 fd
```
**首 entry 直读变体**: bin 尾首个 entry 的 fd = NULL ^ (chunk_addr>>12) = 纯 key——UAF 读到该 fd 时 `heap = fd << 12` 直接得堆页基址，零额外泄漏。

### 方法 1a：tcache 尺寸 chunk 泄漏 libc（伪造 size 升 bin）
字节级写改下一 chunk size 为 0x431（≥0x420 unsorted 门槛）→ free 进 unsorted → fd/bk=main_arena+96 可读。一致性检查: fake next_chunk（+0x431 处）size 须 PREV_INUSE 且合理——预置合法元数据在该边界。

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

目标变体: `mp_.tcache_bins`——写入堆地址破坏 tcache bins 数量阈值，造成 tcache/largebin 混淆（后续大块也走 tcache 路径）作为二阶原语。
**2.42 补后替代**: House of Water / Tangerine / tcache_metadata_hijacking（§5/§6/§7）

#### fastbin_reverse_into_tcache（2.26-2.41，⚠2.42 已补）
1. **标准操作（所有版本）**: free 7 次填满 tcache → victim 进 fastbin → 再 free 6 次填满 fastbin（共 14 次 free）
2. **2.32+ 额外**: 需堆泄漏（safe-linking）
3. **优化路径**: 若能控制栈上 ≥8 字节，在栈上放 `stack_addr>>12`（safe-linking 加密的 NULL，即 `(pos>>12)^0`）作为 fake chunk 的 fd → 只需再 free 1 次即可终止 fastbin 遍历（省掉后 6 次 free）
**2.42 补后替代**: tcache_metadata_hijacking（§7）

#### tcache_stashing_unlink（2.29+）
1. **必须用 calloc 触发**（calloc 跳过 tcache 直接取 smallbin，才触发"剩余 smallbin 回填 tcache"的逻辑；malloc 会先消费 tcache 不触发）
2. **需一个 writable 地址**作 fake_chunk->bk（绕过 glibc 的 `bck->fd = bin` 检查，只读地址会 crash）

#### fastbin → __malloc_hook-0x23（< 2.34）
malloc_hook 前 0x23 字节处常可找到 0x7f 字节 → 可解释为合法 0x70 fastbin size:
分配 0x68 chunk → free → 篡改 fd → `__malloc_hook-0x23`（2.32+ 需 safe-linking 编码）→ malloc 两次，第二次返回 hook 附近 → 覆写 hook 为 one_gadget → 触发 malloc 即执行。fastbin 分配时验证目标 size 字段——0x7f 字节满足 0x70 桶检查是本技巧核心。

**stdout 变体（两段 vtable 劫持）**: `_IO_2_1_stdout_` 区域（如 +0x91）也有 0x7f 假 size——PIE+Full RELRO 时 fastbin 打 stdout 结构: 第一段 vtable 改 `gets`（触发时 rdi=fp，gets(stdout) 从 stdin 自写整个 FILE）→ 第二段输入把 vtable 写 system+_flags=" sh" → 再输出触发 system。目标在 libc 可写数据段，绕开 RELRO。

#### unsorted bin attack（< 2.29 已失效，留作理解）
从 unsorted bin 分配时执行 `bk->fd = unsorted_chunks(av)`。篡改空闲 chunk bk 为 `target-0x10` → 分配时 target 被写 libc 地址。经典用法: 写 global_max_fast 扩大 fastbin 检查范围。2.29 双向链表完整性检查后失效; 现代（≥2.29）任意写主力是 large_bin_attack/tcache 路线。
目标应用变体: 写 stdin `_IO_buf_end` 为大值 → 下次 scanf 读超长输入进 libc stdin 缓冲区（__malloc_hook 邻近）→ 单次大读覆写 hook; **mp_ 当假 chunk 宿主**: bk 指向 mp_ 内偏移，`trim_threshold` 字段的大数值天然过 size<system_mem 校验（mp_+0x48 的 system_mem 自身也大）→ malloc 返回 mp_ 区内存直写 __malloc_hook——无需堆侧伪造 chunk，代价是堆对齐 1/16 爆破。

## §3a House of X 技法全集

**House of Spirit**（全版本，目标地址可构造合法 size 时）:
target_addr+0x08 放 fake size（如 0x40）→ 需保证 next chunk（+size 处）size 合法（>0x10 且 < av->system_mem）→ `free(target_addr+0x10)` 入 tcache/fastbin → malloc 对应 size 取回。tcache 路径（≥2.26）检查更少，**不需验证 next chunk size**。

**House of Einherjar**（off-by-null 主力路径）:
布局 [A][B][C(victim)] → free(A) → off-by-null 清 C 的 P 位 + 伪造 C 的 prev_size=A 到 C 距离 → free(C) 按 prev_size 向后合并 → 覆盖 B 的大 chunk → B 在用但被覆盖，分配即控制。⚠ glibc ≥2.29 有 prev_size 与实际位置一致性检查，需更精确布局。**自引用四指针变体**: A 内伪造 largebin 风格 fake chunk——fd/bk/fd_nextsize/bk_nextsize **全指自身**（fake_addr），过 unlink_chunk 的 `FD->bk==P && BK->fd==P` + large chunk 的 `fd_nextsize->bk_nextsize==P && bk_nextsize->fd_nextsize==P` 全部检查; victim 的 prev_size 须等于 fake 到 victim 的精确距离。

**House of Force**（< 2.29 已失效）: top size 改 -1 → malloc 任意大 size（`evil_size = target - top - 0x20`）把 top 移到目标 → 任意位置分配。2.29 top size 合法性检查封堵。

**House of Orange**（2.23 经典）: top size 改小的合法值（页对齐+P 位）→ 大 malloc 触发 sysmalloc → 旧 top 入 unsorted → bk=_IO_list_all-0x10 → 整理时写 main_arena+0x68 到 _IO_list_all（与 smallbin[5] 重叠）→ 该处伪造 FILE → malloc error→abort→_IO_flush_all_lockp 触发。2.24 加 vtable 检查; 2.29 unsorted attack 失效。

**House of Roman**（无泄漏场景）: 三段 partial overwrite——fd 低 2 字节→malloc_hook-0x23 / unsorted attack 在 hook 附近写 libc 地址材料 / hook 低 2 字节改 one_gadget（4bit 猜）——~1/4096/次。需 <2.34 hook 存在。

**House of Pig**（2.31+）: largebin 写 _IO_list_all → fake FILE vtable=合法 _IO_str_jumps → _IO_str_overflow 内部 malloc → 触发 tcache stashing unlink 任意写 → __free_hook=system。

**House of Banana**: 劫持 _rtld_global 的 link_map 链 l_info[DT_FINI_ARRAY] → exit→_dl_fini 调伪造析构指针——绕过 IO vtable 检查，需 ld.so 基址。

**House of Cat**（≥2.35）: `_IO_wfile_seekoff → _IO_switch_to_wget_mode → _wide_data->_wide_vtable`（wide vtable 无范围检查）。约束: _mode>0、_wide_data 非空且其 _IO_write_ptr>_IO_write_base。

一行级: **unlink attack**（<2.26 主流，现代有 safe-unlink 检查）: 堆溢出伪造 prev_size+fd/bk，**已知堆指针**（如 bss 数组存 chunk 指针）时任意写。公式: `fd = &target-0x18`、`bk = &target-0x10`（target 通常取存 chunk 指针的 bss 槽——写入后该槽指向自身，经它继续 edit 即任意读写）。**SECCON 变体（unlink→top 合并）**: unlink 写自引用指针进 BSS 表后，BSS 再伪造跨度 chunk（`size = heap_top - bss_addr | P`）→ free 合并 top → 后续 malloc 全落 BSS 区，单次写升级为持续分配原语。**House of Lore**: 伪造 smallbin chunk 经 bk 破坏入链，需满足 victim->bk->fd==victim 完整性检查——fake->fd 指回真 smallbin chunk、改真 chunk 的 bk 指向 fake，两次 malloc（第一次真块第二次 fake 块）得任意写。

## §4 glibc 2.34+ 落点伪造模板

> `__malloc_hook`/`__free_hook` 在 2.34 被移除后，以下落点替代。

### 落点 A：House of Apple（IO_FILE wide-data vtable）
**场景**: glibc 2.35-2.39，有任意写 + 能触发 FSOP（exit / _IO_flush_all_lockp）

**vtable 范围检查绕过线**（2.24+）: 2.24-2.27 用合法 `_IO_str_jumps`（_IO_str_overflow 的 malloc(fp+0xe0) 可控 / _IO_str_finish 的 _s._free_buffer）；≥2.28 走 wide 路径（`_wide_data->_wide_vtable` **无范围检查**——Apple 2/Cat 主力）；_IO_wstr_jumps（Apple 3 任意写链）; _IO_cookie_jumps 需 pointer_guard。历史补遗（two-hop，2.24 时代）: 检查只验 vtable 地址范围不验子函数间接跳转——unsorted fd/bk 恰 0x10 间距布两指针（valid_vtable-0x18 / system），flush 走 `*(fp+0xd8)+0x18` 落 unchecked 子函数再调 `*(fp+0xe8)`。
**flush 触发时机**: exit / main 返回 / **malloc 检测到破坏时 abort**（主动触发手段）; 每文件条件: `(mode<=0 && write_ptr>write_base) || (mode>0 && wide_data->write_ptr>wide_data->write_base)`; fake FILE 的 `_lock`（+0x88）须指向有效可写且内容为 NULL 的锁。
**轻量原语**: 不走完整 FSOP——stdout 任意读（_flags=0xfbad1800 + write_base=target + write_ptr=target+size → 下次 puts 输出区间; partial 只改 write_base 末字节可向低地址带出 libc）; stdin 任意写（_IO_buf_base=target + buf_end=target+size + read_ptr=read_end → 下次 scanf 写入目标）。**off-by-null 升级链**: 只有单字节 null 溢出时，溢出 stdin `_IO_buf_base` 的 LSB 清零 → 指向 FILE 结构内部 `_shortbuf` → 下次 scanf/fgets 把输入直接写进 FILE 自身 → 改 buf_base/buf_end 为任意地址 → 完整任意写（1 字节 null 溢出直达 stdin 任意写的跳板）。
**setcontext 变体（SUID 场景）**: system("/bin/sh") 因 dash 在 uid!=euid 丢特权失败——wide vtable __doallocate(+0x68) 改指 `setcontext+61`（RDX 此刻指 _wide_data，从 [rdx+0x68]=RDI、[rdx+0xa0]=RSP、[rdx+0xa8]=RIP 装载）→ _wide_data 布置 RDI=0/RSP=ROP 链/RIP=setuid → 栈迁移 ROP 首项 setuid(0) 再 system。setcontext+61 是通用 pivot gadget——任何控 RDX 指可控内存的 FSOP/hook 场景皆可转 ROP。
**⚠ _mode 必须显式置 0**（Apple 2 最常见失败点）: `_IO_wfile_overflow` 内部检查 `f->_mode <= 0` 才走 wide-data 路径——fake FILE 未初始化时 _mode 残留非零值即整个链失效，构造时逐字段显式置 0。

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

**stderr 宽字符 vtable payload 模板**（覆盖 stderr，system(";sh") 触发; 变体 `"$0\0"`——system("$0") 中 $0 展开 shell 名直接起 shell）:
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
**guard 恢复两路**: ① TLS 直接泄漏（stdout FSOP: tcache 分配 `_IO_2_1_stdout_-0x20` 伪造 FILE、write_base 指 TLS 区，flush 输出后按 `...740` 对齐模式扫 TLS 地址，guard 在 tls+0x30——完整施工见 含双节点 setuid+system 链）② 已知明文: 初始 atexit 首条恒为 _dl_fini——`secret = ror17(mangled) ^ _dl_fini`; 无服务端 ld.so 时从 libc 末尾 4KB 步进扫 \x7fELF 得 ld 基址 → e_entry(+0x18) → 入口代码 `48 8d 15` lea 偏移定位 _dl_fini。同一 secret 保护 atexit/TLS 析构/longjmp 全部。

### 落点 C：_rtld_global 劫持（最简单，无加密）
**场景**: 有任意写 + exit 触发，`_dl_rtld_lock_recursive` 可写

```
步骤:
  1. 泄漏 ld.so 基址（_rtld_global 在 ld.so 数据段）
  2. 任意写覆盖 _rtld_global._dl_rtld_lock_recursive = one_gadget / system
  3. 触发 exit → _dl_fini → 调用 _dl_rtld_lock_recursive → RCE
优势: 该指针无 PTR_MANGLE 加密，一次任意写即可劫持
```

### 落点 D：组合扩大 + environ 栈定位
- **攻击面扩大组合**: large_bin_attack 写 `global_max_fast`（扩大 fastbin 上限）或 `mp_.tcache_bins`（扩大 tcache 索引范围）→ 原本非法 size 区间变可用，fastbin/tcache poisoning 构造空间大增（如把 top chunk 当"合法 fastbin chunk"）。
- **environ 泄漏栈地址**: libc `environ` 指针 → 栈上环境变量数组 → 任意读 environ 值即得栈地址 → 定位目标函数返回地址 → 任意写直接覆盖为 ROP chain。适用 Full RELRO + 无 hook（≥2.34）场景。

### 落点速查表（含触发条件）
| 落点 | 版本 | 需知 | 触发 |
|---|---|---|---|
| __malloc_hook/__free_hook/__realloc_hook | <2.34 | libc 基址 | 任意 malloc（大格式串 printf 也触发）/free/realloc |
| _IO_list_all | 全版本 | libc 基址 | exit/abort |
| __exit_funcs | 全版本 | libc 基址+pointer guard | exit()（fn 受 PTR_MANGLE）|
| **TLS_dtor_list** | ≥2.34 | TLS 地址+pointer guard | 线程退出/exit()——线程局部析构链 |
| .fini_array | No/Partial RELRO | 二进制基址 | 正常退出 |
| _dl_fini link_map 链 | 全版本 | ld.so 基址 | exit()（多字段伪造）|
| 栈返回地址 | 总是 | 栈地址（environ 泄漏）| 函数返回 |

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

## §7c 非 ptmalloc 分配器与 musl

**自定义分配器通用四步**: 应用自有分配器（nginx pool/Apache apr/talloc/游戏引擎）时 glibc 技术全失效——①逆向元数据布局 ②找结构内析构/回调指针（cleanup handler）③溢出改"指针+首参" ④触发释放路径执行 system(可控串)。nginx: `ngx_destroy_pool()` 遍历 cleanup handler 调 `handler(data)`——改 handler=system、data=命令串。talloc: 伪造 pool 头 end 边界覆盖目标 → 下次 talloc() 返回选定地址（任意读写）; parent/child 层次结构破坏一头级联全树。识别: 符号含 talloc/ngx_pool/apr_pool。**自定义 unlink 直打 GOT**: 非 glibc 分配器几乎都没有 safe-unlink 检查（glibc 2004 年才加）——经典 unlink write-what-where 原样适用，fake fd=target-8/bk=值，shellcode 前烘 `jmp +8` 跳过 8 字节写槽; sentinel chunk 的 size 须伪造合法让分配器走合并而非 abort。

**musl libc 堆**: musl 用 group+meta 两级（无 chunk header/safe-linking/tcache）。链: ①OOB 读（如 +0x80）泄漏 meta 指针 ②首个 0x70 类分配的 meta0->mem 距 PIE 基址固定偏移（静态 musl）→ 恢复基址 ③覆写 `meta->mem` 重定向 group 分配到目标 ④atexit handler 列表覆写 system（程序退出触发，比 glibc 落点更简）。识别: `ldd`/`strings | grep musl`。

**堆风水应用层操作化**: 应用操作（create/reply/delete/modify）映射为可预测 size 的分配/释放——控制操作序列与次数即等效直接操纵堆: 造特定 size 的洞（先分配后删除）、把目标结构放溢出源旁、增量偏移喷射（如 0x200 步进）、错误消息读未初始化/已释放块泄漏 libc（fd/bk 指针）。

## §8 关联文件

- `$SHARED_DIR/knowledge-base/pwn-methodology.md` — 标准 8 步流程、mitigations 速查、卡点突破表
- `$SHARED_DIR/knowledge-base/pwn-kernel-methodology.md` — 内核利用详解
