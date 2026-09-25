# JavaScript After Core

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | pwn |
| Difficulty | Elite |
| Flag format | `pwnsec{...}` |

The goal is to make one `JSString` read `hello!!!` during the first `win()` check, `pwned!!!` after the first callback, and `world!!!` after the second. The decisive flaw is an FTL allocation-sinking bug in the pinned JavaScriptCore revision: after `haveABadTime()`, an array is rematerialized with the wrong butterfly layout. The exact local build reached both string transitions and the final `./readflag` call, and a fresh remote instance returned the real flag.

## Environment and Initial Analysis

The official inputs are [`public.zip`](../challenge/public.zip), [`diff.patch`](../challenge/diff.patch), [`Dockerfile`](../challenge/Dockerfile), [`README.md`](../challenge/README.md), `REVISION`, the service scripts, and `readflag.c`. The ZIP SHA-256 is `EDBEE20504AD2B9C0BC5545C40822B62D120CCA2B660B75D7B840F3CDF3605C6`. Analysis used the x86-64 JavaScriptCore revision from `REVISION`, built with the exact supplied patch.

The service is raw TCP behind TLS. It reads one JavaScript program through EOF and executes it once with `/jsc/bin/jsc`. Common exploit helpers were removed from the shell, but `generateHeapSnapshotForGCDebugging()` remained available. Python dependencies came from the competition-level [`requirements.txt`](../../../requirements.txt) and shared `.venv`; `pip check` passed.

## Core Analysis

Adding an accessor at `Array.prototype[0]` sends the VM through `haveABadTime()`. In the vulnerable revision, FTL OSR materialization allocates the original `Contiguous` butterfly in 80-byte chunks, then combines it with a `JSArray` whose structure has changed to `SlowPutArrayStorage`. Populating index 7 uses the mismatched layout and overwrites the next allocation's `IndexingHeader`.

Eight arrays of length 8 leave indices 0 and 1 as holes, while indices 2 through 6 contain objects to select `Contiguous` indexing. Index 7 receives finite IEEE-754 doubles whose low 32 bits range from `0x101` through `0x108`. After corruption, the only array with length 8 has physical rank 0. Repeatedly finding the array whose length is `0x101 + rank` reconstructs the physical order of all eight consecutive butterflies. The rank 1 array gains a very large `vectorLength`, providing forward OOB access.

A pre-trigger heap snapshot supplies the cell addresses of `target`, both source strings, and a normal double `victim` array. In the exact build, the first vulnerable buffer lands at either `target + 0x5960` or `target + 0x9960`. Reading the first `victim` word through both candidates selects the one whose `typeof` is `number`. Runs where `victim` is below the OOB region are safely retried.

Storing an arbitrary pointer bit pattern as a boxed number fails because JSValue tagging reinterprets it as a cell. Instead, the exploit stores the source string object itself into the `victim` butterfly word. Replacing the cell header with the exact-build double-array value `0x01082907010024e0` makes `victim[1]` read the source `JSString`'s `StringImpl*` word as a raw double. Retargeting the butterfly to the `target` cell and writing the same index swaps the target impl first to `pwned!!!` and then to `world!!!`.

## Solution and Reproduction

The sole entry point is [`solve.py`](../solve.py). It embeds the compressed payload and reads only the `main` endpoint from [`instance.json`](../instance.json). The standard-library client uses `ssl.MemoryBIO` so it can decrypt application data after sending TLS `close_notify`. It retries up to 40 fresh connections for unfavorable heap layouts or process crashes and writes only the flag bytes to stdout on success.

Activate the competition `.venv` and run from the challenge root.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

The exact local build produced this success evidence:

```text
targetNow=pwned!!!
targetNow=world!!!
sh: 1: ./readflag: not found
```

The last line is expected because the local analysis directory does not contain the challenge container's setuid `readflag`; it proves the gate reached `system("./readflag")`.

## Result

Running `python solve.py` against `d665d13875d6caa7.chal.ctf.ae:443` returned exit code 0, empty stderr, and the following stdout without a trailing newline:

```text
pwnsec{d1f6845ef4379573}
```

The identical byte sequence is stored in [`flag`](../flag). After the successful run, the instance changed to `404 Deployment not found`, preventing an additional remote rerun.

## Takeaways

The core primitive is not merely an oversized array length; it is the mismatch between the FTL-rematerialized structure and butterfly layout. Self-describing marker lengths remove nondeterministic materialization order. For NaN-boxed JSValue stores, using a real object value to write a cell pointer and compensating with an index in a forged double view is more reliable than trying to encode an arbitrary pointer as a number.

## References

- [`README.md`](../challenge/README.md): service I/O, removed shell helpers, and the `win()` contract.
- [`diff.patch`](../challenge/diff.patch): shell hardening and the `win()` implementation.
- [`REVISION`](../challenge/REVISION) and [`Dockerfile`](../challenge/Dockerfile): exact WebKit revision and build environment.
- No external sources were used.
