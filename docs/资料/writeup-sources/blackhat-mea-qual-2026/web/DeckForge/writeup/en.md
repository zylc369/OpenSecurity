# DeckForge

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | BlackHat MEA Qualification CTF 2026 |
| Category | `web` |
| Difficulty | not provided |
| Flag format | `BHFlagY{...}` |

This web challenge links JavaScript execution in an HTML-to-image feature with an internal ChromeDriver to read a local file.

## Environment and Initial Analysis

The original experiments show that the renderer permits JavaScript plus file URLs and that internal runners expose several ChromeDriver ports. Output handling was narrowed to evidence required by the final path.

## Core Analysis

Code in the renderer scans internal ports, creates a WebDriver session, and gains the higher-privileged runner context. It locates the flag filename in a local directory and returns a JPEG encoding the content as brightness bars.

```text
Entry point: /html-to-image
Browser capabilities: JavaScript + file://
Internal service: ChromeDriver
Candidate ports: 38560..38567
Chrome option: --allowed-origins=*
Exfiltration: JPEG grayscale bars
```

## Solution and Reproduction

[`../solve.py`](../solve.py) uses the HTTP endpoint from [`../instance.json`](../instance.json) to identify a helper port, create a session, locate the file, and decode the image. Evidence is stored under `output/`.

```bash
python solve.py
```

## Result

The result verified by the original solution was checked against the root `flag` file.

```text
BHFlagY{879b9b8fccd447a6a1ac233f4971bd1e}
```

## Takeaways

The boundary between the low-privileged renderer and higher-privileged automation runner is the attack surface. Even image-only output can carry arbitrary data through quantitative pixel values.

## References

- [Original analysis](../analysis/original-write-up.md)
- [Official artifacts](../challenge/)
