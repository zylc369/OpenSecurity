# baiby-pwn

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | BlackHat MEA Qualification CTF 2026 |
| Category | `pwn` |
| Difficulty | not provided |
| Flag format | `BHFlagY{...}` |

This binary-exploitation challenge combines a negative-index write with glibc file-structure abuse to read the remote flag.

## Environment and Initial Analysis

The binary protections and array bounds check were reviewed, and GOT plus file-structure offsets were fixed against the libc preserved during the solve. The established staged exploit remains a single automated run.

## Core Analysis

A negative index reaches GOT-adjacent data and the stdout structure, creating raw write and address-leak primitives. After deriving libc and stack bases, a setcontext chain reads the directory and flag file.

```text
Protections: Partial RELRO, stack canary, NX, no PIE
Fault: unchecked negative arr[i]
Primitives: GOT write + stdout FSOP leak
Runtime: glibc 2.39
Endgame: setcontext -> open -> getdents -> read
```

## Solution and Reproduction

[`../solve.py`](../solve.py) runs the complete exploit using the preserved libc and the TCP endpoint in [`../instance.json`](../instance.json).

```bash
python solve.py
```

## Result

The result verified by the original solution was checked against the root `flag` file.

```text
BHFlagY{7e972e2c3d079ab499db13f678ebfbd0}
```

## Takeaways

Even a narrow negative index can expand into strong primitives when useful global structures are adjacent. Separately validating leaks, writes, and file reads improved reliability.

## References

- [Original analysis](../analysis/original-write-up.md)
- [Official artifacts](../challenge/)
