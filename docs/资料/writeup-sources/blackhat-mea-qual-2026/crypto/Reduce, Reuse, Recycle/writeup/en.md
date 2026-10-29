# Reduce, Reuse, Recycle

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | BlackHat MEA Qualification CTF 2026 |
| Category | `crypto` |
| Difficulty | not provided |
| Flag format | `BHFlagY{...}` |

This challenge combines AES-GCM key-and-nonce reuse with partial tag disclosure to recover the required key material.

## Environment and Initial Analysis

The original service alternates between two keys, reuses one nonce, and reveals alternating tag nibbles. The established finite-field equations and length-selection strategy were consolidated into one execution path.

## Core Analysis

Chosen plaintext lengths constrain the unknowns in the GHASH equations and recover the first key's hash subkey. Reconstructed full tags then provide the value needed for the nonce query handled by the second key.

```text
Primitive: AES-GCM
Fault: identical nonce reused across alternating keys
Leak: alternating authentication-tag nibbles
Chosen UTF-8 lengths: 47, 48, 49, 50
Recovery: GF(2) equations -> GHASH H -> full tags -> nonce value
```

## Solution and Reproduction

[`../solve.py`](../solve.py) uses the TCP endpoint from [`../instance.json`](../instance.json). The default path is the established remote solution, with self-testing retained as a separate option.

```bash
python solve.py
```

## Result

The result verified by the original solution was checked against the root `flag` file.

```text
BHFlagY{cf4aece12ca6b0b0b9f8a0111dfd3132}
```

## Takeaways

Partial tags become sufficient once nonce reuse links the equations. Adjusting input lengths to simplify the GHASH structure is the key step.

## References

- [Original analysis](../analysis/original-write-up.md)
- [Official artifacts](../challenge/)
