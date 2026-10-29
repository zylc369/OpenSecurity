# upyx

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | BlackHat MEA Qualification CTF 2026 |
| Category | `reverse` |
| Difficulty | not provided |
| Flag format | `BHFlagY{...}` |

This challenge solves a self-modifying verifier in a PyInstaller-and-Cython Windows application through dynamic instrumentation.

## Environment and Initial Analysis

The supplied executable's PyInstaller layout, Cython extension, and named-pipe communication were checked against the original analysis. The established Frida instrumentation and recovered constant are preserved in the final solver.

## Core Analysis

A filename suffix selects the seed and launches the verifier through named pipes. A token oracle built by hooking Python C API calls recovers the input incrementally and checks the final group.

```text
Input: Challenge.exe
Packaging: PyInstaller + Cython
IPC: Windows named pipes
Instrumentation: Frida Python C API hook
Recovered length: 60 characters
Embedded verifier constant: 960 bytes
```

## Solution and Reproduction

[`../solve.py`](../solve.py) instruments a temporary copy of `challenge/Challenge.exe` and verifies the recovered value. Its default successful output contains only the flag.

```bash
python solve.py
```

## Result

The result verified by the original solution was checked against the root `flag` file.

```text
BHFlagY{cy7h0n_pyth0n_w1th_3nh4nced_upx__e8f278059549f9ded9}
```

## Takeaways

Building an oracle at a meaningful runtime boundary was more reliable than porting all obfuscated arithmetic statically. Separating instrumentation from final verification prevents false positives.

## References

- [Original analysis](../analysis/original-write-up.md)
- [Official artifacts](../challenge/)
