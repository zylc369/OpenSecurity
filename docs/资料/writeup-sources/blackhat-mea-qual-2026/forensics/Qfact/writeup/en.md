# Qfact

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | BlackHat MEA Qualification CTF 2026 |
| Category | `forensics` |
| Difficulty | not provided |
| Flag format | `BHFlagY{...}` |

This forensics challenge recovers a malicious HTA and file-decryption material from a Windows Defender quarantine store.

## Environment and Initial Analysis

The original evidence ZIP is kept immutable while quarantine metadata and resources are parsed. The recovered HTA is never executed; only its strings and cryptographic routine are analyzed statically.

## Core Analysis

The fixed Defender RC4 layer recovers the HTA. Its character-code sequence yields the AES key, host information yields the IV, and decrypting the affected files exposes a Base64 value.

```text
Input: Evidence.zip
Quarantine layer: fixed Microsoft Defender RC4 key
Payload: HTA
File cipher: AES-256-CBC
IV: MD5(computer_name + username)
Recovered encrypted files: 9
```

## Solution and Reproduction

[`../solve.py`](../solve.py) reads `challenge/Evidence.zip` and writes recovered artifacts under `output/`. On success, standard output contains only the flag.

```bash
python solve.py
```

## Result

The result verified by the original solution was checked against the root `flag` file.

```text
BHFlagY{d3f3nd3r_qu4r4nt1n3_r3c0v3ry_2026}
```

## Takeaways

The evidence is recovered by separating container parsing from cryptographic analysis without executing the payload. Preserving source hashes and recovered artifacts makes the path auditable.

## References

- [Original analysis](../analysis/original-write-up.md)
- [Official artifacts](../challenge/)
