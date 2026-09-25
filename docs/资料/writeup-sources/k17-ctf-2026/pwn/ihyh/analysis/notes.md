# ihyh analysis evidence

## Inputs and runtime

- `handout.zip` SHA-256: `4a503795553ea58a6938de352353aece54d0e6fd449e41c11a3e677830203a77`
- `chal` SHA-256: `f378d988d5face9d7c2cd1946f686e7bf224524a64e04844f36c535c925874c3`
- ELF: x86-64 PIE, dynamically linked, not stripped.
- Protections: Full RELRO, NX, PIE, stack canary, and CET `endbr64` entry points.
- The pinned `ubuntu:22.04` OCI image contains Ubuntu GLIBC `2.35-0ubuntu3.14`.
- Extracted `libc.so.6` build ID: `22ca0a83a4004122e30a69b597be96e134068616`.
- Tools: Python 3.12.10, GDB 15.1, GNU Binutils 2.42.

## Root cause

`view_history()` keeps the global `fp` value after `fclose(fp)`. The glibc
`locked_FILE` allocation has 472 usable bytes, exactly matching an allowed note
size. Opening the stream through `edit()`, filling the 0x1e0 tcache bin with
seven note chunks, and then invoking `view_history()` sends the freed FILE
object to the unsorted bin while `fp` remains dangling.

The final qword of the 472-byte object, at offset `0x1d0`, is the wide vtable
pointer. Reallocating this chunk with a 464-byte note clears and fills only the
first 464 bytes. `view()` uses `%s`, so 464 nonzero bytes make it continue into
the preserved `_IO_wfile_jumps` pointer and disclose libc.

## Verified offsets and relations

All libc offsets refer to Ubuntu GLIBC `2.35-0ubuntu3.14`:

| Object | Offset |
|---|---:|
| `system` | `0x50d70` |
| `_IO_wfile_jumps` | `0x2170c0` |
| `_IO_file_jumps` | `0x217600` |
| `main_arena.top` field | `0x21ace0` |
| `_IO_list_all` | `0x21b680` |
| stdout lock object | `0x21ca70` |

With ASLR disabled for one GDB evidence run:

```text
freed fp                = 0x55555555a2c0
unsorted fd/bk          = 0x7ffff7e1ace0
libc base               = 0x7ffff7c00000
main_arena.top           = 0x55555555c1c0
fp                       = top - 0x1f00
poisoned tcache entry    = top - 0x0d10
```

The FILE arbitrary-read primitive snapshots 472 runtime bytes beginning at
`_IO_list_all - 0x1d0` and leaks `main_arena.top`. Restoring that snapshot is
necessary because the region also contains state referenced by stdin. Only the
last qword is changed to the fake FILE address.

Safe-linking uses:

```text
encoded_next = (_IO_list_all - 0x1d0) ^ (victim_address >> 12)
```

The fake FILE writer places the fixed 44-byte edit-history prefix immediately
before the victim, so the following six nonzero bytes replace the protected
tcache `next`; its two existing high zero bytes remain unchanged. The solver
retries when ASLR puts NUL or newline in those six bytes.

## Code execution

The final fake FILE uses `_IO_wfile_jumps`, a writable lock, and controlled
`_wide_data` and wide-vtable objects inside the reclaimed 472-byte chunk. The
wide vtable's `__doallocate` slot points to `system`. Option 6 calls `exit(1)`,
which walks the forged `_IO_list_all` and reaches `system(fp)`. Since `fp`
starts with `  cat /flag\0`, the child process emits the flag.

Local reproduction with the exact extracted runtime returned the marker
`LOCAL_HOUSE_OF_APPLE_OK`. The official endpoint returned the verified
48-byte flag stored in `../flag` without a trailing newline.
