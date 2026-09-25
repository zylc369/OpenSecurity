# Teto

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | BlackHat MEA Qualification CTF 2026 |
| Category | `pwn` |
| Difficulty | hard |
| Flag format | `BHFlagY{...}` |

This binary-exploitation challenge expands a negative board coordinate into one-bit OR writes and address disclosure.

## Environment and Initial Analysis

The original binary and source establish the coordinate check, random-number consumption order, and stack-frame changes. The established planner and verified schedules are preserved as analysis material.

## Core Analysis

A negative y coordinate ORs one selected bit in adjacent stack data, while width changes disclose PIE, libc, and stack addresses. Predicting the glibc random sequence schedules frame edits across games and reaches a posix_spawn shell path.

```text
Fault: set_cell accepts y == -1
Write primitive: one-bit OR
Leaks: PIE + libc + stack
Schedule source: deterministic glibc rand
Endgame: posix_spawn('/bin/sh')
Mitigations: IBT + SHSTK
```

## Solution and Reproduction

[`../solve.py`](../solve.py) loads the verified schedule assets and the TCP endpoint from [`../instance.json`](../instance.json), automating repeated connections.

```bash
python solve.py
```

## Result

The result verified by the original solution was checked against the root `flag` file.

```text
BHFlagY{6c890129abf30a3d6fb7d2b7bdb9606e}
```

## Takeaways

A weak one-bit write becomes cumulative when target state and random-number order are predictable. Separating schedule construction from transmission was essential for debugging.

## References

- [Original analysis](../analysis/original-write-up.md)
- [Official artifacts](../challenge/)
