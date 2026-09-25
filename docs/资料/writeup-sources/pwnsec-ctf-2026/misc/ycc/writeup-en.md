# ycc

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | misc |
| Difficulty | Easy |
| Flag format | `pwnsec{...}` |

The remote `ysh` compiles and runs submitted Y code with `ycc --no-exec --no-io`. The decisive observation is that the lexer decodes `\x22` into a quote, while the code-generation path for map property names inserts that decoded value into a C string without escaping it again. This closes the generated C statement and permits an injected `system` call.

## Environment and Initial Analysis

The official input is [public.zip](../challenge/public.zip). Its `Dockerfile`, `entrypoint.sh`, `ysh.y`, `ycc.c`, and `runtime.c` define the service. The Alpine service runs `/app/ycc --no-exec --no-io --compile`, but every generated native binary is linked with `runtime.c`. `entrypoint.sh` creates a setuid `/readflag` containing the flag, then removes the `FLAG` environment variable. The required action is therefore executing `/readflag owo`, not reading the environment.

The shared Python environment uses `../../requirements.txt` ([competition requirements](../../../requirements.txt)) from the challenge root and the competition-level `.venv`. No additional Python package is required; the solver uses the standard library for TLS.

## Core Analysis

String expressions are escaped before C output, so a direct `print("...\x22...")` test only printed its content. Map property access, however, becomes the following generated C pattern:

```c
YValue *_v = y_map_get(_m, "<property>");
```

The Y lexer converts source text `\x22` into an actual `"` character. Because property codegen inserts it verbatim, the following decoded property ends the first `y_map_get`, adds an arbitrary C statement, and restores a valid final `y_map_get(_m, "x")` expression:

```text
x"); system((char[]){47,114,101,97,100,102,108,97,103,32,111,119,111,0}); y_map_get(_m,"x
```

The byte array is the NUL-terminated string `/readflag owo`. The map contains a real `x` key, so the restored lookup succeeds after the injected flag-reader command runs. The root cause is missing C escaping when a decoded property value is embedded in a C string literal.

## Solution and Reproduction

[solve.py](../solve.py) connects to the TLS endpoint from [instance.json](../instance.json), waits for the prompt, and submits this Y source through `eval`. The complete implementation is independent of the current working directory.

```text
let m = {x: 1}; print(m."x\x22); system((char[]){47,114,101,97,100,102,108,97,103,32,111,119,111,0}); y_map_get(_m,\x22x");
```

Activate the competition `.venv` and run from the challenge root.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

## Result

`python solve.py` extracted only the flag-shaped value from the remote response and exited with status `0`.

```text
pwnsec{a8c305c05309d5eb}
```

The verified flag is `pwnsec{a8c305c05309d5eb}`.

## Takeaways

Removing language builtins does not preserve a sandbox when the code generator embeds untrusted token values into host-language source. Lexer escape decoding and code-generator C escaping are separate operations; every identifier and property string must pass through the same C literal encoder.

## References

No external references were used. The official archive's `Dockerfile`, `entrypoint.sh`, `ysh.y`, `ycc.c`, and `runtime.c` were the only sources used for analysis and reproduction.
