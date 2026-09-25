# PHault

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | web |
| Difficulty | not provided |
| Flag format | `pwnsec{...}` |

The `id` value is concatenated into a MySQL query, but normal and error paths have the same text and elapsed time, hiding ordinary Boolean and timing oracles. The decisive observation is that a successful `SELECT ... INTO @var` makes `mysqli::query()` return boolean `true` instead of a result object. The following `fetch_row()` call can therefore be turned into a PHP fatal-error oracle and used to extract the flag.

## Environment and Initial Analysis

There are no official attachments; only an HTTPS instance is provided. Connection data is in `../instance.json`, the reproducer is `../solve.py`, and request/response evidence is preserved in [oracle.md](../analysis/oracle.md). The solver uses only Python's standard library and the shared competition environment is restored from `../../../requirements.txt`.

The root route displays its PHP source. The critical query appends `$_GET["id"]` to `SELECT username FROM users WHERE id = `. Both query failure and the normal path print `ill try to tell him, dw`, while a shutdown handler pads total execution to at least 2 seconds. In testing, both `SLEEP(4)` and `BENCHMARK(...)` probes still completed in approximately 2.6 seconds, providing no timing distinction.

## Core Analysis

MySQL `SELECT ... INTO @x` does not return a result set. If the query returns zero or one row, `mysqli::query()` returns boolean `true`, and the application's `$res->fetch_row()` raises `Call to a member function fetch_row() on bool` as a fatal error.

The payload makes the outer `users` query return either zero rows or every row:

```sql
0 OR IF((<condition>),1,0) INTO @phault
```

The `users` table contains the two rows `admin` and `guest`. A true condition attempts to store more than one row in `@phault`, causing a SQL error and reaching the explicit `die()` branch. A false condition returns zero rows successfully and causes the PHP fatal error. The observed responses were 4557 and 4744 bytes respectively and are reliably distinguished by the fatal-error string.

The same oracle enumerated `flag,users` from `information_schema` and confirmed the `flag(flag)` column. The final target expression is `(SELECT flag FROM flag LIMIT 1)`.

## Solution and Reproduction

[solve.py](../solve.py) first binary-searches the byte length of the flag, then binary-searches `ORD(SUBSTRING(...))` from 0 through 255 at every position. Up to 8 positions are processed concurrently, and each request is retried at most three times. The endpoint is loaded from `instance.json` rather than duplicated in source.

Activate the shared competition `.venv` and run from the challenge root:

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

## Result

`python solve.py` exited with code 0 and empty stderr, returning only the following stdout bytes. They match the `flag` file and the runtime validator result.

```text
pwnsec{74f8b0da59cbf20c}
```

## Takeaways

Even when response text and timing are normalized, a blind SQL injection can expose another oracle through whether a query returns a result set and whether the next PHP API receives the expected type. Combining the zero/one-row success and multi-row failure behavior of `SELECT ... INTO` recovers one condition bit without reflecting database data.

## References

No external references were used for the final solution. The solve relies only on the PHP source disclosed by the application and remote request/response observations recorded in [oracle.md](../analysis/oracle.md).
