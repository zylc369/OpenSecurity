# Death Ops

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | pwn |
| Difficulty | Medium |
| Flag format | `pwnsec{...}` |

The challenge combines an alphanumeric-only seccomp sandbox with a kernel module that provides 2 arbitrary eight-byte writes. The decisive observation is that `/proc/modules` discloses the module address and the write primitive can reset its own `used` counter and replace its module code. This yields a kernel KASLR leak, after which overwriting `core_pattern` executes a root usermode helper that prints the flag.

## Environment and Initial Analysis

The official input is [`public.zip`](../challenge/public.zip), encrypted with password `infected`. Its extracted [`dist`](../challenge/public/dist/) contains a Linux 4.9.333 `bzImage`, `rootfs.cpio.gz`, a QEMU launcher, and a Dockerfile. Restore the shared Python environment from [`../../../requirements.txt`](../../../requirements.txt) while in the challenge root:

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
```

`blackops` is PIE, opens `/dev/shadowops`, and presents a menu. Intel Extract rejects paths containing `flag`, but prints the first 0x1000 bytes of one arbitrary file. The payload path accepts at most 0x60 alphanumeric bytes, then installs seccomp allowing only `read`, `write`, `exit`, and `exit_group`. The module's `shadowops_write` accepts a 16-byte `{target, value}` structure and performs `*(u64 *)target = value`, but its `.bss` variable `used` limits this to two successful calls.

## Core Analysis

Reading `/proc/modules` through Intel Extract reveals the independently randomized module base in the `shadowops ... Live 0xffffffffc...` line. The loaded layout is `.text = base`, `.data = base + 0xc80`, `.bss = base + 0xcd0`, with `used` at `base + 0xcd0`.

The initial alphanumeric stage uses ALPHA3's RAX decoder. Its decoded 12-byte body invokes `read(0, r8+0x7a, 0x60)` to load stage two. Later stages use short read loops to receive exactly 0x200 and 0x400 bytes regardless of TCP fragmentation.

The module `.text` is writable on the local kernel. The exploit places a 30-byte primitive in the unused `shadowops_open`/`shadowops_release` area at `base+0x00..0x1f`. With `count == 8`, it reads the kernel qword addressed by the request's first qword back into the user request buffer. With `count == 16`, it performs the original `{target, value}` write. Between eight-byte patches, writing zero to `base+0xcd0` resets the original two-call limit. Finally, `shadowops_write` at `base+0x30` is changed to `jmp base`.

The original instruction at `shadowops_write+0x57` is an `e8 disp32` call to `_copy_from_user`. Reading eight bytes at `base+0x57` recovers the relocated target and the kernel KASLR slide:

```text
copy_from_user = module_base + 0x5c + sign_extend(disp32)
slide = copy_from_user - 0xffffffff81371700
core_pattern = 0xffffffff820674e0 + slide
```

The final writes replace writable kernel data `core_pattern` with:

```text
|/bin/sh -c cat${IFS}/flag*${IFS}>/dev/console
```

A user-space NULL dereference then starts `/bin/sh` through the piped core-dump helper as root. `${IFS}` keeps the third argument as one shell command after the core helper's whitespace-based argv splitting. The syscall seccomp policy does not block this signal and core-dump path.

Three failed hypotheses materially changed the approach. Directly overwriting `sys_call_table` faulted because the mapping is read-only. A forged LSM hook that called a user RWX payload failed on the user-address instruction fetch under KPTI/NX. The address returned by `SIDT` was fixed and unrelated to the KASLR slide, so it was not a usable leak.

## Solution and Reproduction

The complete implementation is [`solve.py`](../solve.py). [`instance.json`](../instance.json) stores the TLS endpoint. Activate the competition `.venv` and run from the challenge root:

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

The solver opens up to three fresh connections and prints only the flag to stdout on success. Local reproduction exposed a QEMU instance using the official `bzImage` and `rootfs.cpio.gz` over TCP; `instance.json` was pointed at that local endpoint only during validation.

## Result

With KASLR enabled, repeated local QEMU runs printed the following test flag:

```text
flag{test_flag_for_ctf_challenge}
```

The evidence is recorded in [`analysis/validation.txt`](../analysis/validation.txt). Against the refreshed TLS endpoint `9ee4d30c7a4bbd0c.chal.ctf.ae:443`, `python solve.py` exited with status 0 and printed:

```text
pwnsec{527916de221fe1c8}
```

## Takeaways

A call-count limit is ineffective when the counter itself is writable through the primitive. A module-to-core relocation can recover the kernel KASLR slide even when the core base cannot be leaked directly. Finally, restrictive syscall filtering still requires analysis of kernel-driven paths such as signal handling and piped core helpers.

## References

- [`challenge/public/dist/README.md`](../challenge/public/dist/README.md): kernel version and alphabet-seccomp description.
- [`challenge/public/dist/rootfs.cpio.gz`](../challenge/public/dist/rootfs.cpio.gz): static and dynamic analysis of `blackops`, `shadowops.ko`, and init behavior.
- ALPHA3, commit `4faca5302c81f7ff8a93943d62d765d18569fd4b`: source of the RAX-based alphanumeric decoder.
- No external vulnerability explanation or public solution code was used.
