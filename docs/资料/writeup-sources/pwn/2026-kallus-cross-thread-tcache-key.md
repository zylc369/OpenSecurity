---
来源: https://kallus.org/blog_tcache_key.html
类型: html
获取日期: 2026-09-12
---

Ben Kallus's cool website




# [Ben Kallus](index.html)

## How cross-thread double free detection could work in glibc malloc

### disclaimer: allocators move fast

This is a post about glibc malloc internals, and glibc malloc changes a lot. This post applies basically as-written for the last 5 years, (fc859c304898a5ec72e0ba5269ed136ed0ea10e1 through 057e7c9aa1578964712ed01e9f7e986412d9fe6c), but might not match your expectations if you haven't looked at glibc in a while, or if you're reading this too far in the future.

### a chunk

malloc has a simple API. You give it a size\_t n, and it gives you back either a pointer to n bytes of memory you can use, or NULL. Otoh, free does not require passing a size, so allocators are on the hook to remember each allocation's size somehow. In glibc malloc (the usual Linux userspace allocator), this is accomplished by actually allocating an extra 8 bytes for each allocation, and storing the allocation's size there. glibc malloc also rounds each allocation's size up to (at least) the nearest multiple of 8 so that the low 3 bits of those 8 bytes can be repurposed to store a few extra allocation properties. It ends up looking something like this, where up is the direction of increasing addresses:

```
+---------------------------------------------+
|         at least n bytes of whatever        |
|                      .                      |
|                      .                      |
|                      .                      |
+---------------------------------------------+ <--- address returned from malloc
| (rounded_n + 8), with low 3 bits repurposed |
+---------------------------------------------+
```

We call this structure a chunk.

### the tcache

When you free an allocation, either it gets released back to the OS with a brk or munmap system call, or it's kept by the allocator for use in servicing a future call to malloc (or calloc, realloc, etc.). The freed allocations that are not immediately released back to the OS are tracked in linked lists called "bins" or "freelists." glibc has many kinds of freelists, but this post focuses on just one: the tcache. The tcache is the fastest type of glibc freelist. They're unique among the types of freelists in two ways:

* They're per-thread, and therefore not protected by a mutex, and
* they're singly-linked.

A chunk in the tcache looks like this:

```
+---------------------------------------------+
|      at least (n - 16) bytes of whatever    |
|                      .                      |
|                      .                      |
|                      .                      |
|                     key                     |
|                     next                    |
+---------------------------------------------+ <--- address returned from malloc
| (rounded_n + 8), with low 3 bits repurposed |
+---------------------------------------------+
```

The "next" field is just the forward link of the list, stored in kind of an interesting way (PROTECT\_PTR). The "key" field is used for double free detection. Note that both of these fields overlap what was once the chunk's data :)

### tcache double free detection

Before main runs, glibc's heap initialization code makes a getrandom syscall to get 8 random bytes and store them in a static (i.e., process-wide) variable named "tcache\_key." When free is going to place a chunk in the tcache, it copies the value of tcache\_key into the key field of the chunk. When malloc grabs a chunk out of the tcache, it overwrites that chunk's key field with 0. This gives us a nice way to detect double frees. When an allocation is passed to free, if the first 8 bytes of its data are already equal to tcache\_key, then this call to free is almost certainly a double free. glibc free implements this check. When it finds that the key is already in place when free is called, it searches the entirety of this thread's tcache to see if this chunk was already freed into the tcache by this thread. If it finds that our allocation is already in some tcache list, then it crashes the program with an error about having detected a double free. If it doesn't find our allocation in any of the tcache lists, it just continues execution as normal.

### the flaw

Suppose that this second scenario occurs. That is, suppose that a chunk is passed to free that already contains the tcache key in its key field, but the chunk is not found in any of this thread's tcache lists. There are 2 possibilities:

* Either this really is a double free, but the first free was executed in another thread, so the chunk is in that thread's tcache, or
* the user data happened to contain exactly our random number in exactly the right position (extremely unlikely).

Unfortunately, glibc can't distinguish between these cases because we can't walk the other threads' tcache lists due to the lack of mutexes, so it throws up its hands and keeps going.

### a proposed fix

In addition to detecting double frees as soon as they occur (i.e., inside of free), we could detect double frees inside of malloc. When malloc grabs a chunk from the tcache, that chunk should still have its key field populated with the special random number. If it doesn't, it indicates that the chunk data has been written after the chunk was freed. This could be due to a use after free, but it could also be due to the chunk having already been returned from malloc in another thread (recall that malloc overwrites the key field with 0). Either way is a big problem, so the process should abort.

### the patch

Adding this functionality is a 1-line change. The patch looks like this:

```
diff --git a/malloc/malloc.c b/malloc/malloc.c
index dcac903e2a..658f3bbfdd 100644
--- a/malloc/malloc.c
+++ b/malloc/malloc.c
@@ -3184,6 +3184,9 @@  tcache_get_n (size_t tc_idx, tcache_entry **ep)
   if (__glibc_unlikely (!aligned_OK (e)))
     malloc_printerr ("malloc(): unaligned tcache chunk detected");
 
+  if (__glibc_unlikely (e->key != tcache_key))
+    malloc_printerr ("malloc(): tcache key corrupted");
+
   if (ep == &(tcache->entries[tc_idx]))
       *ep = REVEAL_PTR (e->next);
   else
```

A friend and I [submitted this to glibc a little over a year ago](https://patchwork.sourceware.org/project/glibc/patch/20250225171319.889661-1-benjamin.p.kallus.gr@dartmouth.edu/), but it was rejected for having too much performance impact :( On my machines, I can't reproduce this. When I run the benchtests, the patch doesn't seem to affect much of anything at all. Someone who tested the patch on an ARM Neoverse N2 claimed that the patch made things up to 7% slower, but I don't have the hardware to see for myself, and I don't want to pay a big evil company.