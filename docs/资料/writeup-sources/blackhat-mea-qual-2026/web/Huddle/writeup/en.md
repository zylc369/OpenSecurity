# Huddle

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | BlackHat MEA Qualification CTF 2026 |
| Category | `web` |
| Difficulty | not provided |
| Flag format | `BHFlagY{...}` |

This web challenge chains a prefix-MAC length extension with a QuickTime external data reference to read a server file.

## Environment and Initial Analysis

The token hash construction and thumbnail-processing pipeline were confirmed from the original analysis. Request construction, video upload, and JPEG decoding remain in one solver.

## Core Analysis

A SHA-256 length extension using the secret length enables owner privileges and video functionality. A QuickTime file with an external data reference reads a server file as frame data, and a custom palette maps resulting pixels back to flag bytes.

```text
MAC: SHA-256(secret || message)
Secret length: 12 bytes
Privilege: owner + video enabled
Container: QuickTime dref external reference
Target: /flag.txt
Decode: custom palette over JPEG
```

## Solution and Reproduction

[`../solve.py`](../solve.py) uses the HTTP endpoint from [`../instance.json`](../instance.json) to forge the token, upload the media, retrieve the thumbnail, and decode its pixels.

```bash
python solve.py
```

## Result

The result verified by the original solution was checked against the root `flag` file.

```text
BHFlagY{31919d590eb234e12dbb832889a70055}
```

## Takeaways

The vulnerabilities play separate roles: privilege escalation and file read. Validating the chain stage by stage distinguishes image-compression errors from authorization failures.

## References

- [Original analysis](../analysis/original-write-up.md)
- [Official artifacts](../challenge/)
