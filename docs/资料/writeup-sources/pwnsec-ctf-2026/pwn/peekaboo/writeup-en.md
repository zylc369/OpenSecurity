# peekaboo

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | pwn |
| Difficulty | Medium |
| Flag format | `pwnsec{...}` |

The program encrypts the flag, hides it at a randomized page, and then executes arbitrary user code while seccomp prevents direct reads and unrestricted output. The decisive observation is that the permitted `mmap(MAP_FIXED_NOREPLACE)` returns `EEXIST` when a requested range overlaps the existing hidden mapping. This oracle locates the page by binary search; the leaked ciphertext then permits recovery of the 24-bit glibc PRNG seed and AES-256-GCM-SIV key.

## Environment and Initial Analysis

The official inputs are [`public.zip`](../challenge/public.zip), [`prob`](../challenge/prob), and [`libcrypto.so.3`](../challenge/lib/libcrypto.so.3). The shared Python environment is restored from [`requirements.txt`](../../../requirements.txt); the solver uses NumPy and `cryptography`.

`prob` is a stripped x86-64 PIE. Its ELF program headers, dynamic flags, symbols, and GNU properties confirm PIE, NX, a stack canary, Full RELRO, IBT, and SHSTK. It reads `./flag`, encrypts it, maps three fixed pages, and executes user code at `0x3133709a`. The TLS service sends no banner before receiving input.

## Core Analysis

Three bytes from `/dev/urandom` seed `srand()`. The first `rand()` selects the following address:

```text
hidden = (0x100000000 + (rand() & 0x3fffff)) << 12
```

The encrypted Base64 string remains at that page. Seccomp permits `mmap`, `munmap`, and `exit_group`; it permits `write` only when `buf & ~0xfff == 0x31339000` and `count <= 8`.

[`leak.S`](../analysis/leak.S) calls `MAP_FIXED_NOREPLACE` over half of the 16 GiB candidate range. A return value of `-EEXIST` places the hidden page in that half. A successful probe is immediately removed with `munmap`, after which the other half is selected. Twenty-two probes leave one exact 4 KiB page. The shellcode copies its contents through the permitted output page and writes eight bytes at a time. Both the local dummy flag and the remote service produced 264 bytes: an eight-byte address followed by 256 bytes of data.

Filtering the 24-bit seed space by the leaked low 22 bits left only `0x0cbec1`, `0x5abf7c`, and `0x8eec08` remotely. The low bytes of the next 32 `rand()` outputs form a candidate key; only `0x5abf7c` authenticated. Inspection of the OpenSSL call arguments shows that the first 12 stored bytes are passed as AAD through `EVP_EncryptUpdate`, not as the IV argument. The actual nonce is therefore twelve `00` bytes, and the storage layout is `AAD || tag || ciphertext`. A debugger-observed local key and buffer independently authenticated and decrypted the dummy flag with this interpretation. [`findings.md`](../analysis/findings.md) preserves the exact evidence.

## Solution and Reproduction

[`solve.py`](../solve.py) loads the TLS endpoint from `instance.json` and sends the 164-byte shellcode. It uses NumPy to search every 24-bit seed from the leaked address, then performs AES-256-GCM-SIV authenticated decryption for each candidate key.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

After recording the replacement live endpoint in [`instance.json`](../instance.json), the solver was rerun from a temporary working directory outside the challenge root.

## Result

The remote leak and authenticated decryption before instance expiry recovered:

```text
pwnsec{ad7aa53d59d0f8af}
```

The final `python solve.py` run completed in approximately 10.7 seconds with exit code 0, empty stderr, and only the newline-free 24-byte flag on stdout. The two incorrect seed candidates failed with `InvalidTag`.

## Takeaways

A large ASLR candidate space can be reduced by binary search when `MAP_FIXED_NOREPLACE` exposes range collisions. EVP buffer semantics must also be derived from the actual argument registers rather than assumed from nearby variable names. Here, the random 12-byte value was AAD rather than a nonce, and that distinction determined authentication success.

## References

No external references were used. The solution relies on ELF metadata, disassembly, local debugger observations, the supplied `libcrypto.so.3`, and remote request and response evidence.
