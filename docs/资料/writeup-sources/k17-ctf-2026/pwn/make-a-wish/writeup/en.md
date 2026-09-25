# make-a-wish

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | K17 CTF 2026 |
| Category | pwn |
| Difficulty | medium |
| Flag format | `K17{...}` |

The menu uses a signed remainder modulo five as a wish index without rejecting negative results. Because `wishes[-2]` aliases the stack pointer for the last name, a forged chunk in the name buffer can be inserted into tcache. The next `malloc(0x90)` then returns stack memory and lets `fgets` overwrite `main`'s return address.

## Environment and Initial Analysis

The official inputs are [handout.zip](../challenge/handout.zip), [chal](../challenge/make-a-wish/chal), and the [Dockerfile](../challenge/make-a-wish/Dockerfile). The archive and binary SHA-256 values are `af1ba822245a37c6492248a8392fdb3f74f23827d8c17e34671b62fb18d68cd6` and `5f509bcc657e13347a69c8bb0291ba500c48f24adcdfd598b9a6d0bf3a407bbe`, respectively. The shared environment is restored from [requirements.txt](../../../requirements.txt).

Inspection with `file` 5.45 and GNU Binutils 2.42 shows that `chal` is a dynamically linked x86-64 ELF with symbols. Its protections are No PIE, NX, No Canary, and Partial RELRO. The ELF notes advertise IBT and SHSTK properties, but the verified remote environment executes the ROP chain below. The Dockerfile copies the flag to `/flag` and serves `/app/chal` under `pwn.red/jail`.

## Core Analysis

The relevant `main` stack layout is:

| Address | Purpose |
|---|---|
| `rbp-0x70` | second-name pointer |
| `rbp-0x60` .. `rbp-0x40` | `wishes[0..4]` |
| `rbp-0x30` | start of the 30-byte name buffer |
| `rbp-0x8` | first-name pointer |
| `rbp+0x8` | saved return address |

`create` and `delete` reduce the input with signed `number % 5`, but neither rejects a negative result. With the array starting at `rbp-0x60`, `wishes[-2]` is the second-name pointer at `rbp-0x70`.

The initial name places `prev_size = 0` and `size = 0xa1` at `rbp-0x30`, with a space at offset `0x0f`. `split` replaces that space with NUL and sets the second name to offset `0x10`, the aligned address `rbp-0x20`. Thus, `delete(-2)` calls `free(rbp-0x20)` and inserts the forged `0xa0` chunk into tcache.

The following `malloc(0x90)` in `create(0)` returns `rbp-0x20`. Its `fgets(..., 0x90, stdin)` starts `0x28` bytes before the saved return address. The first-name pointer used by the final output is replaced at payload offset `0x18` with the empty string at `0x402013`, followed by this chain:

| Payload offset | Value | Meaning |
|---:|---:|---|
| `0x28` | `0x4012e2` | `pop rdi; pop rbp; ret` |
| `0x30` | `0x402011` | `sh\0` inside a menu string |
| `0x38` | `0` | dummy `rbp` |
| `0x40` | `0x401130` | `system@plt` |
| `0x48` | `0x4011e0` | `exit@plt` |

The gadget at `0x4012e2` starts inside the immediate of `mov eax, 0x5fc3c031` in `sub_401296`. The chain invokes `system("sh")`. The detailed observations and local verification are preserved in the [analysis notes](../analysis/notes.md) and [probe.py](../analysis/probe.py).

## Solution and Reproduction

[solve.py](../solve.py) uses only the Python standard library. It loads the `main` TCP endpoint from `instance.json`, forges the name chunk, runs `delete(-2)`, reclaims the stack chunk through `create(0)`, writes the ROP chain, invokes `system("sh")`, and extracts the flag from `cat /flag`. Activate the competition `.venv` and run from the challenge root.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

## Result

The local [probe.py](../analysis/probe.py) printed `LOCAL_CODE_EXECUTION_OK` under glibc 2.39 and exited with code 0. The remote `python solve.py` also exited with code 0 and empty stderr. Its stdout contained only the following 47 bytes with no trailing newline:

```text
K17{my_f4v0ur1t3_fl4v0ur_15_k1w1_p1n34ppl3_btw}
```

The verified flag is `K17{my_f4v0ur1t3_fl4v0ur_15_k1w1_p1n34ppl3_btw}`.

## Takeaways

Even a small signed OOB can become an arbitrary free when the adjacent pointer targets attacker-controlled input. For a tcache House of Spirit, the fake user pointer must be aligned and the forged size must match the allocation size class. In a small non-PIE binary, bytes inside instruction immediates and suffixes of existing strings can also supply missing ROP gadgets and command strings.

## References

- [Official handout](../challenge/handout.zip): supplied the binary and container configuration.
- No external references were used. Static analysis used local file 5.45 and GNU Binutils 2.42.
