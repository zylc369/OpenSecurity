# Dead Drop

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | BlackHat MEA Qualification CTF 2026 |
| Category | `web` |
| Difficulty | not provided |
| Flag format | `BHFlagY{...}` |

This web challenge exploits a parser mismatch between a CSS validator and HTML to exfiltrate a private pickup log.

## Environment and Initial Analysis

The original analysis establishes the report bot's private-page visit and the stored CSS validation. The existing attribute discovery and prefix recovery were consolidated into one run.

## Core Analysis

A string that appears to be a CSS comment is interpreted as an HTML raw-text closing tag, injecting a new style block. Attribute selectors and external background requests recover the flag-bearing attribute and then its value prefix by prefix.

```text
Breakout: /*</style><style>ATTACKER_CSS</style><style>*/
Target: private pickup log
Discovery: CSS attribute selectors
Exfiltration: external background requests
Recovery: prefix oracle over the value attribute
```

## Solution and Reproduction

[`../solve.py`](../solve.py) reads the HTTP endpoint from [`../instance.json`](../instance.json) and automates collector creation, bot reporting, attribute discovery, and value recovery. Progress is stored under `output/`.

```bash
python solve.py
```

## Result

The result verified by the original solution was checked against the root `flag` file.

```text
BHFlagY{c94c07c5096315b63847789d4976dc17}
```

## Takeaways

A string accepted by a filter is not guaranteed to retain the same meaning in the final HTML context. Both validator and browser parsing boundaries must be analyzed.

## References

- [Original analysis](../analysis/original-write-up.md)
- [Official artifacts](../challenge/)
