# jump-v2

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | reverse |
| Difficulty | Hard |
| Flag format | `pwnsec{...}` |

The Rust wrapper transforms the input with ChaCha20 and inserts it into an obfuscated inner ELF. Decrypting its 14 seccomp BPF programs produces bit constraints on the final state; combining them with the checksum uniquely fixes that state, after which all three transforms can be inverted.

## Environment and Initial Analysis

The official distribution is [public.zip](../challenge/public.zip), encrypted with `infected`, and its [jump_v2](../challenge/jump_v2) member. Their SHA-256 hashes are `bd9972edbf78713cc4b013335d2c52ea1baf06745d60158df5a7109eefca64e5` and `ee8973d9a3a88c6a70e557d1c6cb1fb717b7f72ef41c7bea20e4c654c6e68008`. The x86-64 PIE Rust wrapper executes an inner ELF through `memfd_create`. The inner ELF starts at file offset `0x7a90`, has length `0x145b48`, and is preserved as [embedded.elf](../analysis/embedded.elf).

The shared environment is restored from [requirements.txt](../../../requirements.txt). The main tools were Python 3.12, Unicorn 2.1.4, Capstone 5.0.3, Z3 5.1.0, and GNU `objdump`, `strace`, and `gdb`.

## Core Analysis

The inner ELF processes the 48 bytes at `0x5463a0` in four stages. Stage one is a 12-round shift register over three 16-byte registers. Each round applies `PSHUFB`, XOR, and `AESENC`, then shifts the state to `(x1, x2, new)`. Stage two is an eight-round generalized Feistel on each 16-byte block, using MBA functions at `0x544218`, `0x5443fa`, and `0x54450d`. [model_f2.py](../analysis/model_f2.py) matches every observed round state. Stage three applies `bswap`, `x ^= x >> {8,16,24}`, `x ^= 0xa1b2c3d4`, and `bswap` per word. Stage four starts at `0x243f6a88` and updates its accumulator for every word as `rol(acc ^ word, 5) * 0x9e3779b1 + 0x7f4a7c15`.

Each decrypted BPF program in [filters.bin](../analysis/filters.bin) checks a custom syscall from `0x1337` through `0x1344` with `((arg ^ k1) + k2) & mask == target`. Combining the mask equations and the final checksum in Z3 uniquely determines all 13 state words. Inverting the stages gives the required inner payload `55872b6b5f0ab8006676b24b37685c11811e6e757abcad32be64de10f7e8616f8b9795e7f9009478cfa04b535b80a0ad`.

The Rust wrapper XORs user input with a fixed ChaCha20 keystream. Dumping the memfd write for 48 `A` bytes reveals that stream. XORing it with the required inner payload yields `hi_astra_i_believe_you_can_jump_4c6a05cc40f5d4cb`.

## Solution and Reproduction

[solve.py](../solve.py) verifies the official binary hash, supplies the recovered input to the original wrapper, and writes only the flag emitted by that binary to stdout. Activate the competition's `.venv` and run from the challenge root.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

## Result

The original `jump_v2` exited with code `0`, printed `Congrats!`, and returned the following flag. It matches the `solve.py` stdout and `flag` file byte for byte.

```text
pwnsec{hi_astra_i_believe_you_can_jump_4c6a05cc40f5d4cb}
```

## Takeaways

The distinction between the normal Linux `-ENOSYS` result of an unknown syscall and seccomp's `ERRNO(1)` result of `-1` creates the validation oracle. For binaries dominated by indirect jumps and inert SIMD instructions, extracting the executed basic-block path, memory writes, and seccomp BPF is more effective than reconstructing all static control flow. Straight-line MBA functions can be translated instruction by instruction into Z3 expressions and checked against runtime states.

## References

No external references were used. ELF structure, seccomp BPF behavior, and AES-NI operations were established from local GNU-tool output and runtime observations.
