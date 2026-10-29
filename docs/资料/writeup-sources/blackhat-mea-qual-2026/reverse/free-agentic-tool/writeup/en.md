# free-agentic-tool

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | BlackHat MEA Qualification CTF 2026 |
| Category | `reverse` |
| Difficulty | not provided |
| Flag format | `BHFlagY{...}` |

This challenge recovers a deterministic X25519 session and final ciphertext from a Go Windows executable and a PCAP.

## Environment and Initial Analysis

The executable, debug archive, and packet capture in the supplied ZIP were checked against the original writeup's data flow. The input path was anchored to the challenge root instead of the caller's working directory.

## Core Analysis

An embedded AES-CBC key opens the debug material and reveals the username plus hostname. These values deterministically produce the X25519 private key, enabling session decryption, and the capture-specific final stream recovers the Base64 plaintext.

```text
Input: dist.zip
Executable: Go 1.20.5 PE
Debug archive: AES-CBC
Key agreement: deterministic X25519(username + '_' + hostname)
Capture: init/session packets
Final t7 recovery: embedded capture-specific T7_STREAM
```

## Solution and Reproduction

[`../solve.py`](../solve.py) reads `challenge/dist.zip` directly and executes the full recovery path. Successful default output contains only the flag; detailed values require the explicit verbose option.

```bash
python solve.py
```

## Result

The result verified by the original solution was checked against the root `flag` file.

```text
BHFlagY{wh4t_y0u_5Ee_15n't_wh4t_y0u_G3t_8cc56ad688964fd5f72f3c414971b1d6}
```

## Takeaways

The key exchange is deterministic and reproducible, while the final stream is specific to this capture. Separating the general algorithm from instance constants prevents overstating the solver's scope.

## References

- [Original analysis](../analysis/original-write-up.md)
- [Official artifacts](../challenge/)
