# Popcnt Oracle

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | BlackHat MEA Qualification CTF 2026 |
| Category | `crypto` |
| Difficulty | not provided |
| Flag format | `BHFlagY{...}` |

This challenge reconstructs an RSA plaintext from an oracle that returns only its Hamming weight.

## Environment and Initial Analysis

The original server source exposes the bit count of an arbitrary ciphertext's decryption. The final solver preserves the established query strategy and public-key verification.

## Core Analysis

Multiplying the ciphertext by an encryption of a chosen value yields the Hamming weight of the correspondingly multiplied plaintext. Inverse halving and complement queries determine bits, while an additional multiple resolves equal-weight ambiguity.

```text
Oracle: HW(m)
RSA transform: c' = c * a^e mod n -> HW(a*m mod n)
Bit recovery: inverse halving + complement query
Ambiguity recovery: query 3*m
Verification: pow(m, e, n) == c
```

## Solution and Reproduction

[`../solve.py`](../solve.py) loads the TCP endpoint from [`../instance.json`](../instance.json), reconstructs the plaintext, verifies it with the public RSA equation, and submits it.

```bash
python solve.py
```

## Result

The result verified by the original solution was checked against the root `flag` file.

```text
BHFlagY{7ec59fc32589300df70f41b11db3e6ec}
```

## Takeaways

A bit can be inferred from the direction of the weight change. A separate multiple query for ties completes the recovery.

## References

- [Original analysis](../analysis/original-write-up.md)
- [Official artifacts](../challenge/)
