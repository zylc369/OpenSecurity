# ihyh

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | K17 CTF 2026 |
| Category | pwn |
| Difficulty | hard |
| Points | 213 |
| Author | not provided |
| Flag format | `K17{...}` |

This x86-64 heap challenge implements note creation, editing, deletion, and an edit-history viewer. The decisive bug is a dangling global `FILE *fp` left behind after the history file is closed. A 472-byte note can reclaim glibc's `locked_FILE` allocation. A preserved vtable pointer leaks libc; forged FILE read and write behavior then leaks the heap and poisons tcache; finally, House of Apple 2 reads `/flag`.

## Environment and Initial Analysis

The official input is [handout.zip](../challenge/handout.zip), containing [chal](../challenge/ihyh/chal) and its [Dockerfile](../challenge/ihyh/Dockerfile). The ZIP SHA-256 is `4a503795553ea58a6938de352353aece54d0e6fd449e41c11a3e677830203a77`; the ELF SHA-256 is `f378d988d5face9d7c2cd1946f686e7bf224524a64e04844f36c535c925874c3`.

`readelf` and `objdump` show Full RELRO, NX, PIE, and a stack canary. The binary is not stripped and retains the `create`, `edit`, `delete`, `view`, and `view_history` symbols. The Dockerfile pins `ubuntu:22.04@sha256:2edbbc...`. The [libc.so.6](../analysis/runtime/usr/lib/x86_64-linux-gnu/libc.so.6) extracted from that image is Ubuntu GLIBC `2.35-0ubuntu3.14`, build ID `22ca0a83a4004122e30a69b597be96e134068616`. Analysis used Python 3.12.10, GDB 15.1, and GNU Binutils 2.42. The solver uses only the standard library, so [requirements.txt](../../../requirements.txt) is empty.

## Core Analysis

Each global `hate` entry holds a note pointer and a 32-bit size. `create()` accepts 1 through 512 bytes, uses `malloc` for that size, and calls `read` for the same number of bytes. `view()` and `edit()` later treat a note as `%s`, although `read` does not always append a NUL terminator.

The first `edit()` opens `/tmp/log.txt` in `a+` mode and stores the stream in global `fp`. `view_history()` calls `rewind`, `fgetc`, and `fclose`, but never performs `fp = NULL`. GDB confirmed that this FILE object has 472 usable bytes.

The dangling FILE is moved to the unsorted bin as follows:

1. Edit a 16-byte note to open and retain `fp`.
2. Allocate 7 notes of 472 bytes and delete all of them, filling the 0x1e0 tcache bin.
3. Call `view_history()`. Since tcache is full, closing `fp` puts its chunk in the unsorted bin.
4. Allocate 7 notes of 472 bytes again to drain tcache.
5. Allocate a 464-byte note. It still uses a 0x1e0 chunk, but the application initializes only its first 464 bytes.

`locked_FILE` retains `_IO_wfile_jumps` at offset `0x1d0`. Supplying 464 nonzero `L` bytes makes `view()` continue into this pointer. Subtracting `0x2170c0` from the leak gives the libc base.

The same chunk is then rebuilt as a fake FILE using `_IO_file_jumps`. Setting `_IO_write_base` and `_IO_write_ptr` around a target range and using fd 1 makes `fwrite()` flush that range to stdout. This primitive snapshots 472 bytes at `_IO_list_all - 0x1d0` and reads `main_arena.top`. The verified heap relations are:

```text
fake FILE address = top - 0x1f00
tcache victim     = top - 0x0d10
```

Changing the fake FILE into a buffered writer makes `edit()` copy its history string into heap memory. The fixed history prefix is 44 bytes, so the buffer starts at `victim - 44`; the note begins with the first six bytes of:

```text
encoded_next = (_IO_list_all - 0x1d0) ^ (victim >> 12)
```

After two chunks enter tcache, this value replaces the head's protected `next`. Popping the head makes the following allocation return `_IO_list_all - 0x1d0`. This 472-byte region also contains wide-data state referenced by stdin, so simply clearing it breaks the next `scanf`. The solver restores the earlier 472-byte runtime snapshot and changes only its final qword, `_IO_list_all`, to the fake FILE address.

The final FILE has `_IO_write_ptr > _IO_write_base`, `_IO_wfile_jumps`, a valid lock, and controlled `_wide_data` inside the same chunk. The fake wide vtable places `system` in its `__doallocate` slot, while the FILE starts with `  cat /flag\0`. Menu option 6 calls `exit(1)`, producing `_IO_wfile_overflow` → `_IO_wdoallocbuf` → `system(fp)` while `_IO_list_all` is walked.

The complete offsets and GDB observations are in [analysis/notes.md](../analysis/notes.md); the complete implementation is [solve.py](../solve.py).

## Solution and Reproduction

Activate the event-wide `.venv` and run these commands from the challenge root. The complete solver is [../solve.py](../solve.py), and it reads the public endpoint from [instance.json](../instance.json).

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

The solver opens a new connection only when ASLR places a NUL or newline in the six transmitted safe-linking bytes. On success it writes only the flag bytes to stdout, without a trailing newline.

## Result

The exact extracted glibc reproduced the full chain locally and printed the marker `LOCAL_HOUSE_OF_APPLE_OK`. Against the official endpoint, `python solve.py` exited with code 0, left stderr empty, and produced 48 stdout bytes exactly matching [flag](../flag).

```text
K17{50pp1n355_0f_l0v3_f1nd1ng_1t5_way_1n_f1l35!}
```

## Takeaways

For a FILE UAF, matching the FILE allocation size is only the start. A gap between the application's initialization length and the allocator's usable size can preserve a trailing vtable pointer for a leak. When poisoning tcache into libc data, the complete allocation range matters as much as the target field. Here, snapshotting and restoring the 472 bytes before `_IO_list_all` was required to keep stdin usable for the final menu choice.

## References

- [K17 CTF 2026 official site](https://k17ctf.secso.cc/): event and challenge environment.
- [GNU C Library 2.35 source](https://sourceware.org/git/?p=glibc.git;a=tree;h=refs/heads/release/2.35/master;hb=refs/heads/release/2.35/master): allocator safe-linking and `libio` FILE behavior.
- [Ubuntu Docker Official Image](https://hub.docker.com/_/ubuntu): extraction of the exact amd64 glibc selected by the pinned OCI digest.
- No third-party challenge write-up was used.
