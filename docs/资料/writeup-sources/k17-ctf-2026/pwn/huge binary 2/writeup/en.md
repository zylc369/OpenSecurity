# huge binary 2

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | K17 CTF 2026 |
| Category | pwn |
| Difficulty | hard |
| Points | 219 |
| Flag format | `K17{...}` |

The challenge provides a one-byte stack-relative OOB read and two 31-byte format strings. The decisive step is a one-byte change to the supplied glibc's return path that repeatedly calls `main` in the same process, after which the two format strings can be pipelined into stack halfword writes and a ROP chain.

## Environment and Initial Analysis

The official inputs are [handout.zip](../challenge/handout.zip), [chal](../challenge/huge-binary-2/chal), [libc.so.6](../challenge/huge-binary-2/libc.so.6), and [Dockerfile](../challenge/huge-binary-2/Dockerfile). The SHA-256 digest of `chal` is `17801b24ad804e3785c96bc1860dde06117bf3a5bb65667fc28ce37cfe7efca5`; the supplied libc digest is `adeedbc69ac402b762a3bd94759441e0546c33972cb2c0f5bc6869a2d32efed6`.

GNU Binutils 2.42 identified an x86-64 PIE with NX, Partial RELRO, and no stack canary. The shared Python 3.12.10 environment is restored from [requirements.txt](../../../requirements.txt), and the solver uses only the standard library. `main` uses the signed integer from `scanf("%d")` to read one byte at `rbp + index - 1`, then passes both `scanf("%31s")` buffers directly to `printf` as formats.

## Core Analysis

On the remote stack, arg19 is `libc_base + 0x29ca8`, arg21 is PIE `main`, and arg20 points to the arg50 slot. Arg50 initially points exactly `0x100` bytes above saved RIP. Index `258` reads byte 1 of that arg50 pointer. Subtracting one from the leaked byte and trying the 16 alignment-constrained low bytes from `0x08` through `0xf8` lets `%20$hn` retarget arg50 to saved RIP.

The relevant return path in the supplied Debian glibc `2.41-12+deb13u2` is:

```text
0x29ca1: mov rax, qword ptr [rsp+8]
0x29ca6: call rax
0x29ca8: mov edi, eax
0x29caa: call exit
```

Writing `0xa1` to the saved return's low byte with `%161c%50$hhn` therefore calls the saved `main` pointer again. The call pushes `0x29ca8` over saved RIP each time, so every arbitrary halfword write uses two calls: one preserves the loop and retargets arg50, and the next performs the write, restores arg50, and reinstates byte `0xa1`. The representative remote observation and exact stack layout are preserved in [analysis evidence](../analysis/notes.md).

## Solution and Reproduction

[solve.py](../solve.py) loads the TCP endpoint from `instance.json` and automates the complete exploit:

1. Bootstrap repeated `main` execution using index `258` and the 16 possible aligned low bytes.
2. Derive the libc base, PIE base, and saved RIP address from arg19, arg21, and the retargeted arg50.
3. Use repeated halfword writes to place `pop rdi; ret`, the command pointer, `system`, `exit`, and `cat</flag` on the stack.
4. Use the last two formats to arm saved RIP and the caller's saved `main` slot together, then enter the ROP chain.

Activate the competition `.venv` and run from the challenge root.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

## Result

In default mode, `python solve.py` exited with code 0, left stderr empty, and emitted exactly 31 stdout bytes with no trailing newline. The same bytes were written to `flag` and verified for equality.

```text
K17{turn$_0ut_siz3_do3s_m@tter}
```

## Takeaways

A short format string still yields a strong write primitive when existing stack pointers reference later argument slots. A one-byte partial overwrite to a nearby libc instruction boundary can also establish re-entry without knowing the ASLR base. Here, because each recursive call restores the normal return address, target selection and the actual halfword write had to be split across two calls.

## References

- The official [chal](../challenge/huge-binary-2/chal), [libc.so.6](../challenge/huge-binary-2/libc.so.6), and [Dockerfile](../challenge/huge-binary-2/Dockerfile) supported the static analysis and remote environment match.
- No external solution or unofficial reference was used.
