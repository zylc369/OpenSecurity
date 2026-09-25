# pickle

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | web |
| Difficulty | Easy |
| Flag format | `pwnsec{...}` |

The service restores a base64-encoded Python pickle through a restricted unpickler. The decisive flaw is that a disassembly failure skips the `REDUCE` check, while the real unpickler executes the same incomplete stream first. This mismatch permits reading `/app/flag.txt` without placing banned strings in the raw pickle.

## Environment and Initial Analysis

The official input consists of [public.zip](../challenge/public.zip), its [webapp.py](../challenge/challenge/webapp.py) and [sessionstore.py](../challenge/challenge/sessionstore.py), and the Docker configuration. The shared Python environment is restored from `../../../requirements.txt`. The service base64-decodes the JSON `payload` sent to `POST /restore`, then applies a byte blocklist, `pickletools.dis()`, and `RestrictedUnpickler.load()`. Only globals whose first module segment is `sessionstore` or `collections` are allowed. The raw pickle also blocks the `REDUCE` instruction and byte strings such as `.`, `flag`, and `getattr`. The remote service was verified at `https://d5680026f8c80379.chal.ctf.ae`.

## Core Analysis

`check()` places `pickletools.dis()` and the textual `REDUCE` check in one `try` block and suppresses every exception. Pickle's terminating `STOP` opcode is byte `.`, so a normal pickle is rejected by the byte blocklist as well. Omitting `STOP` makes `pickletools.dis()` raise `ValueError` at EOF, which skips the `REDUCE` test. The real unpickler then executes every opcode and side effect before reaching EOF, and `restore()` suppresses its final exception.

Resolving a dotted name beneath the allowed `sessionstore.render` object with `STACK_GLOBAL` exposes `render.__globals__.__class__.__getitem__`, the unbound `dict.__getitem__` descriptor. Applying it to `render.__globals__['__builtins__']` retrieves `open`, `getattr`, and `print`. The payload opens `/app/flag.txt`, calls `read()`, and sends the result to `print()`, whose output Flask has redirected into the response. Every string is encoded with `\\uXXXX`, so the raw payload contains none of `.`, `flag`, or `getattr`. Detailed execution evidence is preserved in [evidence.md](../analysis/evidence.md).

## Solution and Reproduction

[solve.py](../solve.py) reads the `main` URL from `instance.json`, generates the pickle, sends it with `POST /restore`, and extracts `pwnsec{...}` from the returned `output`. Activate the competition `.venv` and run from the challenge root.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

When a new instance is issued, change only `url` in `instance.json`. The endpoint is not duplicated in the solver source.

## Result

[payload_probe.py](../analysis/payload_probe.py) confirmed disassembly failure, byte-blocklist compliance, and file-content output under the same restricted unpickler as the supplied source. Running `python solve.py` against the remote instance then produced exit code 0, empty stderr, and a 24-byte stdout with no trailing newline. The recorded flag is:

```text
pwnsec{d51962f679918668}
```

## Takeaways

A validator must not continue into a dangerous deserializer after a parser error. Pickle can execute function-call side effects before `STOP`, so malformed streams bypass checks when the disassembler and unpickler have different success conditions. A module-name allowlist is also insufficient when dotted global resolution exposes the allowed module's full object graph.

## References

- No external web references were used.
- Python standard-library `pickle` and `pickletools` behavior was verified against the supplied source with local Python 3.12.
