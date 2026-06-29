# Pwn 方向源文档索引

> 创建: 2026-06-29

## how2heap 核心 PoC（glibc_2.39，一手可编译源码）

来源: https://github.com/shellphish/how2heap
覆盖 glibc 2.23-2.43 的堆利用技术，每个 PoC 含详细注释说明原理和触发条件。

| 文件 | 覆盖技术 | 适用 glibc | 说明 |
|------|---------|-----------|------|
| how2heap-house_of_tangerine.c | 无 free 堆利用（House of Orange 现代版） | 2.34-2.39+ | sysmalloc 对 top 的 _int_free + tcache poisoning |
| how2heap-house_of_water.c | smallbin 变体（无需爆破） | 2.36+ | UAF→tcache 元数据控制，Potluck CTF 2023 |
| how2heap-large_bin_attack.c | 堆地址写到任意地址 | 2.30+ ⚠2.42补 | 构造任意写原语，配合 FSOP |
| how2heap-house_of_botcake.c | UAF→重叠块 | 通用 | double free 制造重叠 |
| how2heap-tcache_stashing_unlink_attack.c | smallbin→tcache 劫持 | 2.29+ | 利用 smallbin 回填 tcache |
| how2heap-safe_link_double_protect.c | safe-linking 无泄漏绕过 | 2.32+ | 二次 PROTECT 实现任意链接 |
| how2heap-decrypt_safe_linking.c | safe-linking 编解码 | 2.32+ | PROTECT_PTR/REVEAL_PTR 原理 |
| how2heap-sysmalloc_int_free.c | 无 free 堆利用 | latest | 利用 sysmalloc 对超大 top 的 _int_free |
| how2heap-tcache_poisoning.c | 基础 tcache 毒化 | 2.26+ | tcache next 指针篡改 |
| how2heap-fastbin_reverse_into_tcache.c | fastbin→tcache | 2.26-2.41 ⚠2.42补 | fastbin 释放时回填 tcache |

## 待补充（标注待查找）
- ptr-yudai DiceCTF 2026 cornelslop（内核: MADV_DONTNEED+cross-cache+PTE overlap）— 需查找博客 URL
- ctf-wiki kernel pwn — 需下载
- House of Apple/Cat 详细文章（作者 roderickchan，非 roderickwang）— 需查找正确 URL
