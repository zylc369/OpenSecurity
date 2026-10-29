# jailincpython

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | misc |
| Difficulty | Medium (347 points) |
| Flag format | `pwnsec{...}` |

The filter bans quotes, digits, and parentheses and permits only two dots, but it still permits assignments to comprehension targets and to `hint_A.__class_getitem__`. Replacing that method turns subscription into a call primitive; descriptor binding then reaches `ABCMeta.register.__builtins__` and `os.system`.

## Environment and Initial Analysis

The official input is [`../challenge/main.py`](../challenge/main.py), and the remote service reported Python 3.12.3. The shared environment uses `../../../requirements.txt` and the competition `.venv`. The filter enforces ASCII input of at most 800 bytes, at most 2 dots, and no quotes, digits, or parentheses, but does not block an attribute target such as `{... for hint_A.__class_getitem__ in{f}}`.

## Core Analysis

Because `hint_A[x]` invokes the runtime replacement for `__class_getitem__`, it executes functions without parentheses. The payload uses `lambda x:x.__getattribute__` to obtain the `object.__getattribute__` descriptor, then binds its `__get__` method to create arbitrary attribute getters.

Required names are assembled from the allowed `hint_B == "%jailincpython"` string and fixed slices of a bound-method repr. This yields `__class__`, `__dict__`, `__subclasses__`, `register`, `__builtins__`, `__import__`, `os`, `system`, and `sh`. Looking up `type.__dict__["__subclasses__"]` provides `ABCMeta`; the real Python function `ABCMeta.register` exposes the normal builtins dictionary. The final 788-byte expression executes `os.system("sh")`, so subsequent socket input is interpreted by the shell.

The remote `run.sh`, inspected through the escaped shell, writes the flag to `/${RAND}.txt` and unsets the `FLAG` environment variable. Sending `cat /*.txt` therefore reads the per-instance random flag path without hard-coding it.

## Solution and Reproduction

The complete implementation is [`../solve.py`](../solve.py). It reads the endpoint from [`../instance.json`](../instance.json), connects over TLS, sends the jail payload, waits for the shell prompt, and sends `cat /*.txt`.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

## Result

`python solve.py` returned exit code 0, empty stderr, and a 24-byte stdout with no trailing newline. Its bytes match [`../flag`](../flag) exactly.

```text
pwnsec{974f89d15ad10e5c}
```

## Takeaways

Pyjail review must cover assignment targets and replaceable special methods in addition to banned characters. `__class_getitem__` turns `obj[arg]` into a call primitive, while descriptor binding and a Python function's `__builtins__` escape the restricted eval globals. The solver also avoids fixing the randomized flag filename and uses a root-level glob instead.

## References

- [`../challenge/main.py`](../challenge/main.py): authoritative filter and eval-globals behavior.
- [`../solve.py`](../solve.py): final 788-byte payload and remote reproduction.
- No external references were used.
