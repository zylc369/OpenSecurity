# waf

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | K17 CTF 2026 |
| Category | pwn |
| Difficulty | medium |
| Flag format | `K17{...}` |

The program reads up to 128 bytes into an 80-byte stack buffer, allowing the saved return address to be overwritten. The decisive observation is that the NUL filter clears only the range returned by the current `read`, not the entire buffer. Prompt-synchronized short writes can therefore install NUL bytes from high offsets to low offsets while preserving the ROP suffix already built behind the filter boundary.

## Environment and Initial Analysis

The official inputs are [handout.zip](../challenge/handout.zip), [chal](../challenge/waf/chal), and [Dockerfile](../challenge/waf/Dockerfile). The SHA-256 of `chal` is `5e0712c1b21a83adfc4a6f761455a141956be4f209e74981b76c445e29c4d0ec`. It is a dynamically linked amd64 ELF with symbols. `readelf` and `objdump` show no PIE, NX, no stack canary, and Partial RELRO. The GNU properties advertise IBT and SHSTK, but replacing the remote saved return address with `main` printed the banner twice, confirming that this execution path permits practical `ret` control.

The shared competition environment is restored from [requirements.txt](../../../requirements.txt). Analysis used ROPGadget 7.7 and Capstone 5.0.9; the final [solve.py](../solve.py) uses only the Python standard library. Addresses, hashes, image digests, and glibc offsets are recorded in the [analysis notes](../analysis/notes.md).

## Core Analysis

`main` clears an 80-byte buffer at `[rbp-0x50]` and passes it to `__gets`. When its first byte is zero, `__gets` calls `read(0, buf, 0x80)`, placing the saved RIP at offset 88. Later calls use `strlen(buf)` as the read size.

After each `read`, the filter scans only `buf[0:n]`, where `n` is that call's return value. If the first NUL occurs at offset `i`, it executes `memset(buf+i, 0, n-i)`. A normal 64-bit address consequently erases the chain after its first NUL, but the following sequence bypasses the filter.

1. Send 128 NUL-free `A` bytes to establish a preserved stack suffix.
2. Process the target payload's NUL offsets from largest to smallest.
3. At offset `i`, send only `payload[:i+1]`. Replace lower, not-yet-installed NUL bytes with `A`, and keep the first four bytes as `AAAA` in intermediate stages so the input loop continues.
4. Because `read` returns exactly `i+1`, the filter cannot touch the suffix beyond `i`. Only the final stage starts with `exit`, causing `main` to return.

The first ROP stack is:

| Buffer offset | Value | Purpose |
|---:|---|---|
| 0–79 | `exitLEAK%6$sEND\n` + padding | `printf` format |
| 80–87 | filler | saved RBP |
| 88–95 | `0x4010d0` | `printf@plt` |
| 96–103 | `0x4012a2` | return to `main` |
| 104–111 | `0x404020` | `puts@got`, dereferenced by `%6$s` |

This chain prints the six-byte resolved `puts` pointer and returns to `main`. The amd64 glibc was extracted from the Dockerfile's pinned `debian:13.4-slim` image index, `sha256:4ffb3a1511099754cddc70eb1b12e50ffdb67619aa0ab6c13fcd800a78ef7c7a`. The required offsets are `puts=0x805a0`, `system=0x53110`, `"/bin/sh"=0x1a5ea4`, and `pop rdi; ret=0x2a145`.

The second stack contains `pop rdi; ret`, `"/bin/sh"`, an alignment `ret`, and `system` starting at offset 88. The same reverse NUL installation builds the chain, enters `system("/bin/sh")`, and sends `cat /flag`.

## Solution and Reproduction

[solve.py](../solve.py) reads the TCP endpoint from [instance.json](../instance.json) and performs the complete exploit in one connection:

- verify the official `chal` SHA-256;
- build stage 1 with reverse short writes and leak `puts`;
- calculate and validate a page-aligned libc base;
- build stage 2 and execute `/bin/sh`;
- extract the `K17{...}` value from `/flag` output.

Activate the competition `.venv` and run from the challenge root.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

On success, stdout contains only the flag bytes with no trailing newline, and stderr is empty.

## Result

`python solve.py` returned exit code 0, empty stderr, and 32 stdout bytes. Those bytes match [flag](../flag), and final validation also passed a fresh remote runtime execution.

```text
K17{ma_a1n7_pr0uD_0f_me_n0_m0r3}
```

## Takeaways

When input sanitization covers only the range returned by the current syscall while retaining an older buffer suffix, synchronized short writes can assemble a payload from the end toward the beginning. Validation must consider the buffer's full lifetime and the relationship between sanitization and the next read length, not merely whether one input is cleared after its first NUL. A pinned container image also makes exact libc offsets reproducible from a single function leak.

## References

- [Official Dockerfile](../challenge/waf/Dockerfile): runtime layout and pinned Debian image digest.
- [Official chal](../challenge/waf/chal): functions, protections, overflow, and filter logic.
- ROPGadget 7.7: located the glibc `pop rdi; ret` offset.
- Docker Registry v2 response: selected the linux/amd64 manifest and rootfs layer for the pinned image.
- No external solution or challenge walkthrough was used.
