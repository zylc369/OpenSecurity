# Two Worlds, One Heart

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | reverse |
| Difficulty | Easy (194 points) |
| Flag format | `pwnsec{...}` |

`portal33.exe` executes the same verifier bytes once as x86 and once as x86-64. The decisive observation is that the 32-bit interpretation validates the first 20 bytes of the 40-byte input, while the 64-bit interpretation validates the remaining 20 bytes. Inverting each rotate-and-XOR comparison recovers the complete input.

## Environment and Initial Analysis

The official input is [public.zip](../challenge/public.zip), protected with the password `infected`, and it contains only [portal33.exe](../challenge/portal33.exe). The SHA-256 hashes of the ZIP and EXE are `16f7079aec0118b57faca43cc0b2fa73963887b9d3bc5837f944e9eddf8b11d9` and `d35911333fae7cfc7a305c93e2f14cad678487ef724d4ea610c3e047a42194f0`, respectively.

`file` 5.45 and GNU `objdump` 2.42 identify the EXE as a PE32 console executable for Intel i386. The length comparison at VA `0x408e1e` requires exactly `0x28` (40) input bytes. The solver uses only the Python 3.12.10 standard library, and the shared competition environment is restored from [requirements.txt](../../../requirements.txt).

## Core Analysis

The bytes at VA `0x401600` decode differently depending on the execution mode. The 32-bit path checks five little-endian 4-byte words with the following recurrence:

```text
T[i] = ROL32(word[i] XOR previous, 11)
previous = 0x1337c0de (i = 0), otherwise T[i-1]
T = [0xcdbd7302, 0x30833d2e, 0xb310ea05, 0xdef1b433, 0x1c3b640e]
```

The wrapper at VA `0x4016b3` uses `retf` with selector `0x33` to call the same VA as 64-bit code, then returns to 32-bit mode with selector `0x23`. In 64-bit mode, the initial bytes `31 c0 48 85 c0` decode as `xor eax,eax; test rax,rax`, which skips the 32-bit checker block. The remaining checks are:

```text
ROL64(qword[0] XOR 0x5a33c0d313379090, 19) == 0x87326027c52b7005
ROL64(qword[1] XOR 0x87326027c52b7005, 29) == 0x7e6e88add6ebc7e2
ROL32(word[9] XOR 0xd6ebc7e2, 13)          == 0x5e929579
```

Each `ROL` is inverted with a same-width `ROR`, followed by XOR with the previous target or initial key. This deterministically recovers every word. [verifier.md](../analysis/verifier.md) records the static addresses and equations.

## Solution and Reproduction

[solve.py](../solve.py) first checks the opcode skeleton in the original PE, reads the instruction immediates directly, and applies the inverse operations. It replays both the 32-bit and 64-bit verifier equations over the recovered 40 bytes and writes the flag only if every check succeeds. Activate the competition `.venv` and run from the challenge root:

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

## Result

`python solve.py` returned exit code 0, empty stderr, and exactly 40 stdout bytes without a trailing newline. Passing the same bytes to the original `portal33.exe` also returned exit code 0 and printed `Access Granted! Flag verified.`

```text
pwnsec{h3_5p34k5_32_5h3_5p34k5_64_l0v3!}
```

## Takeaways

With a Heaven's Gate pattern, disassembling a byte sequence in only the process's nominal mode can hide half of the verifier. The `retf` selectors and target VA reveal that the same region must be disassembled in both architecture modes. A rotate-and-XOR chain remains directly invertible when each comparison target also supplies the state for the next block.

## References

No external references were used. The analysis used only local `file`, GNU `objdump`, the Python standard library, and the provided binary.
