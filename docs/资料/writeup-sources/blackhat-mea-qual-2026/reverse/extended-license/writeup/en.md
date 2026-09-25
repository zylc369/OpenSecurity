# extended-license

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | BlackHat MEA Qualification CTF 2026 |
| Category | `reverse` |
| Difficulty | not provided |
| Flag format | `BHFlagY{...}` |

This reverse-engineering challenge traces staged SIGTRAP shellcode, a cBPF selector, and license-derived AES decryption.

## Environment and Initial Analysis

The original analysis establishes the copied shellcode, trap stages, and license grammar in the PIE executable. The preserved test license and final flag are available, but the username and extension bytes used for the accepted submission were not retained in the original record.

## Core Analysis

The username feeds a PRNG and Feistel path to produce the selector value, while the license prefix and username are hashed into the AES key. Once the cBPF-selected payload constraint is satisfied, the embedded ciphertext can be decrypted.

```text
Binary: PIE ELF
Staging: SIGTRAP shellcode
Selector: static cBPF
License grammar: BHLCNS_ || payload || ! || extension
Key: SHA-256(license[:120] + username)
Cipher: AES-ECB
```

## Solution and Reproduction

[`../solve.py`](../solve.py) temporarily extracts the executable from `challenge/extended-license.tar.zip`, analyzes it, and generates plus verifies a license from an explicit username and extension bytes. The accepted submission inputs cannot be restored as defaults from the preserved record, so those arguments must be supplied.

```bash
python solve.py
```

## Result

The result verified by the original solution was checked against the root `flag` file.

```text
BHFlagY{BPF_c4n_b3_b4d_Bu7_I_d0n'7_Th1nK_7thIs_()ne_1s_B4D?_6b117fca1597}
```

## Takeaways

The final flag and general decryption procedure are preserved, but unattended reproduction is incomplete without the accepted submission inputs. Future records should retain the username, extension bytes, and generated license together.

## References

- [Original analysis](../analysis/original-write-up.md)
- [Official artifacts](../challenge/)
