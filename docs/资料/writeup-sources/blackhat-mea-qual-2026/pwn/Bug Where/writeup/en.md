# Bug Where

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | BlackHat MEA Qualification CTF 2026 |
| Category | `pwn` |
| Difficulty | not provided |
| Flag format | `BHFlagY{...}` |

This kernel-exploitation challenge turns an io_uring provided-buffer lifetime bug into controlled kernel-heap reuse.

## Environment and Initial Analysis

The vulnerable path and execution environment were checked against the supplied kernel configuration and patches. The established exploit source and retry harness are preserved as analysis material.

## Core Analysis

A stale iovec reference after releasing a provided-buffer bundle creates a double-free condition. Reclaiming the object as a pipe_buffer and replacing its operations table reaches the kernel privilege-escalation path.

```text
Kernel: Linux 7.2-rc3
Subsystem: io_uring provided-buffer bundles
Fault: dangling iovec -> double free
Reclaim: pipe_buffer
Hardening: CONFIG_KMALLOC_PARTITION_RANDOM
KASLR side channel: QEMU PREFETCH
```

## Solution and Reproduction

[`../solve.py`](../solve.py) uses the built guest exploit and the TCP endpoint from [`../instance.json`](../instance.json), retrying a bounded number of times for the required heap-partition collision.

```bash
python solve.py
```

## Result

The result verified by the original solution was checked against the root `flag` file.

```text
BHFlagY{ef2d81621299ed9b3a5d1f418cc352d2}
```

## Takeaways

The vulnerability and practical reclaim success rate are separate concerns. Under randomized partitions, fresh-VM retries are part of the reproducibility contract.

## References

- [Original analysis](../analysis/original-write-up.md)
- [Official artifacts](../challenge/)
- [Upstream fix](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=f1596ba3e6b390aa0fef8466afce44efecf39d8d)
