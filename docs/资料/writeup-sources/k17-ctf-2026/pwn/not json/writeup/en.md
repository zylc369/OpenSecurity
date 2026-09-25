# not json

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

The recursive JSON-like parser decrements its key length counter during normalization while `buffer[strlen(buffer)]` continues appending bytes. I used the resulting stack overflow to leak the canary, PIE, and libc, then changed one low byte of a saved `rbp` in an aligned recursive frame to pivot into an ancestor's description buffer.

## Environment and Initial Analysis

The SHA-256 of the original [handout.zip](../challenge/handout.zip) is `F3ED77F1A952F55403794579A83CBA81DCE614BDD2B9880A3D4AD7B4396B8340`; the SHA-256 of the ELF [chal](../challenge/notjson/chal) is `F192460B07BAD0E04EB3DC2736A55847302CCF6077826223CF1AA7DB3289642E`. The supplied [Dockerfile](../challenge/notjson/Dockerfile) uses `debian@sha256:1d3c811171a08a5adaa4a163fbafd96b61b87aa871bbc7aa15431ac275d3d430` with `pwn.red/jail` and places `/flag` inside the chroot.

`readelf` identifies an x86-64 PIE (`ET_DYN`). `GNU_RELRO` plus `BIND_NOW` gives Full RELRO, the `RW`-only `GNU_STACK` enables NX, and the `__stack_chk_fail` reference and function prologues confirm stack canaries. Analysis used Python 3.12.10, file 5.45, GNU Binutils 2.42, and GDB 15.1. The solver uses only Python's standard library, so the shared [requirements.txt](../../../requirements.txt) is empty.

## Core Analysis

`do_parse_json_object` has `0x70`-byte frames, and keys and descriptions reuse a 40-byte buffer at `rbp-0x30`. The essential key logic is:

```c
buffer[strlen(buffer)] = c;
counter++;
if (!isalnum(c) && c != '_') {
    buffer[strlen(buffer) - 1] = '_';
    counter--;
}
```

A character such as `!` therefore does not increase the checked counter, but it fills successive NUL bytes and advances outside the buffer. An alphanumeric character skips the second `strlen` normalization, which lets the exploit preserve the byte immediately before a pointer terminator.

The first leak uses 40 `!` bytes followed by `ABC`. `A` fills the canary's NUL byte, while `B` and `C` fill the two high NUL bytes of the saved `rbp`; terminating with `|` produces a 62-byte `%s` leak. Bytes `41..47` disclose the remaining 7 canary bytes, `48..53` disclose a stack address, and `56..61` disclose `PIE+0x161a`. A description of exactly 40 bytes then writes its terminator over the canary's first byte, restoring it to `0x00`.

`run_aligned` executes `mov sp, 0` and `sub rsp, 0x20000`. The original `run_aligned` frame-pointer slot is consequently always at offset `0x250` from the root key buffer, and its `+0x18` slot holds a libc startup return address. I extracted the pinned libc (SHA-256 `06E87BC6946702848D7F6AEB7E3759CA904458EFD8C3DED85CA63099944181ED`) from the Docker digest and established these offsets:

| Target | Offset |
|---|---:|
| libc startup return | `0x29ca8` |
| `system` | `0x53110` |
| `"/bin/sh"` | `0x1a6ea4` |

The long leak stops exactly at the NUL after the libc pointer so its highest significant byte remains intact. [solve.py](../solve.py) starts from a conservative `0x900` upper bound on non-NUL stack bytes, then uses short keys to advance one NUL at a time until the output length equals the target offset.

Finally, the `mov` immediate embedded at `run_aligned+0x1f`, or `PIE+0x11e8`, decodes at an unaligned boundary as `pop rdi; ret`. The low 16 bits of the root `rbp` are `0xfdd0`, and every recursive frame subtracts `0x70`, so the depth-11 `rbp` ends in `...f900`. At depth 12, a key containing 40 `!` bytes, canary filler `A`, and pivot byte `H` (`0x48`) changes depth 11's saved `rbp` to point at offset `+8` in the depth-10 description buffer. That 40-byte buffer contains this fake frame:

```text
+0x00  canary
+0x08  fake rbp
+0x10  PIE+0x11e8          pop rdi; ret
+0x18  libc+0x1a6ea4      "/bin/sh"
+0x20  libc+0x53110       system
```

When depth 11 executes `leave; ret`, it pivots through this frame and calls `system("/bin/sh")`.

## Solution and Reproduction

[solve.py](../solve.py) loads the endpoint only from [instance.json](../instance.json). It safely retries connections whose randomized addresses contain an inconvenient NUL or `"` byte. Activate the competition `.venv` and run from the challenge root:

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

The solver sends `cat /flag` to the shell and emits only one `K17{...}` value on stdout.

## Result

The run against `chal.secso.cc:4003` on 2026-09-12 exited with code `0`, empty stderr, and stdout without a trailing newline:

```text
K17{b3cau$e_rbp_taste$_bett3r_th@n_key}
```

The identical 39 bytes are stored without a newline in the challenge root's `flag` file.

## Takeaways

When a length counter and the actual write position are derived from different state, normalization can itself create an unbounded write. Recursive frame size combined with forced stack alignment can also turn a one-byte saved-frame-pointer overwrite into a deterministic pivot into a small controlled buffer. ROP searches must consider unaligned instruction boundaries inside immediate values.

## References

- [Docker Official Image: Debian](https://hub.docker.com/_/debian): used to identify the amd64 libc for the Debian 13.3 slim digest pinned by the Dockerfile.
- [pwn.red/jail](https://github.com/redpwn/jail): used to confirm the chroot and `/app/run` service layout in the supplied Dockerfile.
- No external solution or write-up was used.
