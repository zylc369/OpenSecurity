# Lumen

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | BlackHat MEA Qualification CTF 2026 |
| Category | `web` |
| Difficulty | easy |
| Flag format | `BHFlagY{...}` |

This web challenge uses double URL decoding and a PHP input-limit warning to remove CSP and exfiltrate a value stored by the admin bot.

## Environment and Initial Analysis

The supplied source establishes the path filter, PHP settings, and report bot's localStorage use. The established payload was adapted to dynamic instance input and exact successful output.

## Core Analysis

Split percent encoding is recombined by two decoding passes into a path character unseen by the filter. Exceeding the input-variable limit emits output before headers, preventing CSP from being applied, and an image error handler exfiltrates the localStorage value.

```text
Bypass: split %3 + c... across double URL decoding
PHP limit: max_input_vars = 1000
Payload variables: 1001
Buffering: output_buffering = 0
Execution: img onerror
Source: localStorage.flag
Sink: /trace
```

## Solution and Reproduction

[`../solve.py`](../solve.py) builds the bypass URL from the HTTP endpoint in [`../instance.json`](../instance.json), invokes the bot, and extracts the flag from the trace result.

```bash
python solve.py
```

## Result

The result verified by the original solution was checked against the root `flag` file.

```text
BHFlagY{55a16ae096ae9c534c1ccf5b02cfef9f}
```

## Takeaways

A URL filter must model every decoding pass performed by the application. Response-header security also depends on pre-header output and runtime warnings.

## References

- [Original analysis](../analysis/original-write-up.md)
- [Official artifacts](../challenge/)
