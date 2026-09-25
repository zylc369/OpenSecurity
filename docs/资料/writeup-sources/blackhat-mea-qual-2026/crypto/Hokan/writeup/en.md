# Hokan

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | BlackHat MEA Qualification CTF 2026 |
| Category | `crypto` |
| Difficulty | easy |
| Flag format | `BHFlagY{...}` |

This cryptography challenge recovers exponents, coefficient relations, and the modulus from a sparse-polynomial evaluation oracle.

## Environment and Initial Analysis

The supplied archive and Sage source establish the input bounds and term-count constraints. The final automation path was checked against the original query record and recovery script.

## Core Analysis

Lattice reduction finds small integer relations among evaluations at fixed points. Those relations recover monomial exponents and coefficient ratios, after which the GCD of minors determines the hidden modulus.

```text
Artifact: hokan.tar.gz
Model: sparse polynomial over 11 variables, total degree <= 11, 5 nonzero terms
Oracle samples: 8
Recovery: LLL -> exponent vectors -> coefficient ratios -> GCD of minors -> modulus
```

## Solution and Reproduction

[`../solve.py`](../solve.py) reads the TCP endpoint from [`../instance.json`](../instance.json) and performs querying, recovery, and answer submission in one run. Only the instance file needs updating for a replacement service.

```bash
python solve.py
```

## Result

The result verified by the original solution was checked against the root `flag` file.

```text
BHFlagY{651a2a5a3f4579b739f4671463cdb0b5}
```

## Takeaways

The useful information lies in integer relations among evaluations rather than in isolated values. Deriving the modulus from those relations made the solution stable.

## References

- [Original analysis](../analysis/original-write-up.md)
- [Official artifacts](../challenge/)
