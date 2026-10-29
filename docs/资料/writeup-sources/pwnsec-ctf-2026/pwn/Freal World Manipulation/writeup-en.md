# Freal World Manipulation

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | pwn |
| Difficulty | Medium (500 points) |
| Flag format | `pwnsec{...}` |

The challenge combines inconsistent index validation with incorrectly ordered floating-point exception handling to obtain arbitrary read and write. A `__dso_handle` self-reference leaks PIE; more than 512 MiB of allocations and an overflowing multiplication enable OOB indexing; GOT, libc, `__environ`, and the stack then provide the final ROP target.

## Environment and Initial Analysis

The official inputs are [public.zip](../challenge/public.zip), [Dockerfile](../challenge/Dockerfile), [freal](../challenge/src/freal), and placeholder [flag.txt](../challenge/flag.txt). The archive password `infected` is public on the challenge page. The shared Python environment is restored from [requirements.txt](../../../requirements.txt), although the final [solve.py](../solve.py) uses only the Python standard library.

`freal` is a non-stripped x86-64 PIE ELF. `GNU_RELRO` plus `BIND_NOW` gives Full RELRO, `GNU_STACK` is non-executable, and stack canaries are present. The Dockerfile runs the binary as user `ctf` on Ubuntu 22.04 and renames the flag file with a random suffix.

## Core Analysis

`decimal` is at `0x5060` and `__dso_handle` is at `0x5008`, so index `-11` selects the self-referential relocation. `view(-11)` emits relocated `PIE+0x5008`, revealing the PIE base.

`calibrated()` requires the page-rounded live allocation total to exceed `0x1fffffff`. Freeing an initial 8 MiB mmap chunk raises glibc's dynamic mmap threshold, after which 65 allocations of 8 MiB form a contiguous heap. Loading `1e308` into two slots and multiplying under upward rounding produces infinity. Because `multiply` calls `fetestexcept` before performing the multiplication, it accepts the overflow and expands the index limit using the product of the allocation usable sizes.

One 8 MiB chunk is filled with repeated `p64(PIE+0x5060)`. Scanning from PIE at 8 MiB intervals over about 1 GiB must hit the patterned chunk; the successful OOB `view` returns 256 bytes from the `decimal` table. An OOB `load` through the same index overwrites `decimal`, so controlling slot 0's pointer and usable size yields direct arbitrary read and write.

The exploit reads `puts@GOT`, walks backward by pages to the libc ELF header, and parses the remote program headers, `PT_DYNAMIC`, and GNU hash table to resolve `system` and `__environ`. It leaks the stack through `__environ`, locates `main` by the invariant `[rsp+8] == rsp+0x10`, and replaces the saved return address with `ret; pop rdi; ret; command; system`. Exact offsets and test evidence are in [evidence.md](../analysis/evidence.md).

## Solution and Reproduction

Activate the competition `.venv` and run from the challenge root. If the endpoint changes, edit only [instance.json](../instance.json).

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

[solve.py](../solve.py) performs the TLS connection, PIE leak, heap calibration, patterned OOB search, remote GNU-hash symbol resolution, stack search, and ROP execution non-interactively in one file.

## Result

Against a local `socat` wrapper, a verification run with only the final command changed to `echo pwnsec{local_test}` exited 0 and emitted exactly `pwnsec{local_test}`. The solver was then restored to the remote flag command and the `pwnsec{...}` matcher.

The restored solver was run against the fresh remote instance at `b31501f4e8de5bb6.chal.ctf.ae:443`. It exited with code 0 and its stdout was exactly `pwnsec{34910c7c74c2525b}`. The verified flag is recorded in [flag](../flag).

## Takeaways

Individually strict checks can still compose into an exploit when signed indices, pointer coherence, and allocation accounting differ across code paths. A reliable arbitrary-read primitive also removes the need for a supplied libc: parsing the in-memory ELF and GNU hash table resolves the required symbols independently of the exact build.

## References

- Official `Dockerfile` and `freal`: service configuration, memory layout, and vulnerable control flow.
- GNU binutils `readelf`, `objdump`, `nm`, and `strings`: ELF headers, relocations, symbols, and gadgets.
- No public solution or same-challenge write-up was used.
