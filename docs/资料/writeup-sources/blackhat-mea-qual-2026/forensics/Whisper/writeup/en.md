# Whisper

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | BlackHat MEA Qualification CTF 2026 |
| Category | `forensics` |
| Difficulty | not provided |
| Flag format | `BHFlagY{...}` |

This forensics challenge reconstructs an encrypted session password from Ollama history and a deleted script.

## Environment and Initial Analysis

The supplied archive's model history, trashed script, and cached ZIP were compared in the order documented by the original writeup. The solver path reads only the required members into memory.

## Core Analysis

The model history reveals the phrase consumed by the script, and the deleted code defines its BLAKE2b derivation. That password opens the WinZip AES session, after which a Base64 value in the internal CSV is decoded.

```text
Input: whisper_evidence.tar.zip
History: .ollama/history
Deleted script: cache_mgr.py
Derivation: BLAKE2b
Container: WinZip AES session.zip
Recovered record: internal_api_keys.csv -> master_vault
```

## Solution and Reproduction

[`../solve.py`](../solve.py) reads `challenge/whisper_evidence.tar.zip` and can store intermediate results under `output/`. Its default successful output is only the flag.

```bash
python solve.py
```

## Result

The result verified by the original solution was checked against the root `flag` file.

```text
BHFlagY{l0c4l_0ll4m4_llm_f4r3n51c5_2026}
```

## Takeaways

A deleted file, model history, and application cache form one password-derivation chain. Following data dependencies is more direct than relying only on chronology.

## References

- [Original analysis](../analysis/original-write-up.md)
- [Official artifacts](../challenge/)
