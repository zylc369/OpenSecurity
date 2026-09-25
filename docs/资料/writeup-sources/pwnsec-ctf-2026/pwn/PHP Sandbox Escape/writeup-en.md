# PHP Sandbox Escape

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | pwn |
| Difficulty | Hard |
| Flag format | `pwnsec{...}` |

The service passes the POST parameter `cmd` to `eval()`, while `disable_functions` and `open_basedir` block file and process APIs. The decisive observation was that `SplDoublyLinkedList::unserialize()` still invokes PHP's serialization parser even though the global `unserialize()` function is disabled. A `Serializable::unserialize()` callback grows the property HashTable of an already registered object, leaving the parser's shared `var_hash` pointing into freed buckets. That UAF becomes arbitrary read and a fake `Closure`, which executes `/readflag`.

## Environment and Initial Analysis

The official input is [`public.zip`](../challenge/public.zip), encrypted with password `infected`, with SHA-256 `4cb98c42514e5f1925ace170d8762c1f663b4328fdb34f0f7c8b0b5068e63778`. Its [`Dockerfile`](../challenge/public/Dockerfile) builds PHP master on Ubuntu and runs PHP-FPM. [`php.ini`](../challenge/public/src/php.ini) sets `open_basedir=/home/ctf/scripts/:/tmp` and disables a large set of functions including `system`, `exec`, `unserialize`, and file-reading APIs. [`readflag.c`](../challenge/public/src/readflag.c) is installed setuid root and reads `/flag`.

The remote service identified itself as PHP `8.6.0-dev`. After probing available calls, the matching PHP revision was compiled under WSL to verify structure sizes and exploit assumptions. From the write-up directory, the shared environment manifest is [`../../../requirements.txt`](../../../requirements.txt); from the challenge root, the corresponding shell path is `../../requirements.txt`.

## Core Analysis

The serialized list stream starts with a `stdClass` containing eight properties and a `CachedData implements Serializable` object, followed by spray strings and references `R:3` through `R:10`. While `SplDoublyLinkedList::unserialize()` parses the stream, `CachedData::unserialize()` adds a ninth property named `x` to the globally retained first object. That insertion grows its property HashTable from 8 to 16 slots and frees the original 288-byte `arData`. The outer parser's shared `var_hash`, however, still contains addresses of the old property zvals.

Reallocating the freed 288-byte chunk with a 280-byte string makes the `R:n` references interpret string contents as zvals. The exploit extends this primitive as follows.

1. A reference write-through difference in a long-zval spray leaks a `zend_reference` heap address.
2. A string exposes the same 2 MiB Zend heap chunk; scanning 256 sprayed `Closure` objects yields repeated `zend_object` layouts and the `ce` and handlers pointers.
3. Reads near the handlers `.bss` locate `executor_globals`, including `function_table` and `symbol_table`.
4. The active `bin2hex` entry leads through `zend_internal_function.module` to the standard module. `zend_function_entry` is `0x38` bytes in this PHP 8.6 build, and the remote function table places `system` at entry 287. Disabled functions disappear from the runtime function table, but their static module entries and original handlers remain mapped.
5. A fake `zend_closure` is written into a string using the genuine Closure `ce`/handlers and the `zif_system` handler. A final UAF exposes its address as an `IS_OBJECT` zval, then invokes it with `/readflag`.

The complete research payload and stage diagnostics are preserved in [`exploit.php`](../analysis/exploit.php). The final solver embeds the same payload as gzip/base64 and does not depend on files under `analysis/`.

## Solution and Reproduction

[`solve.py`](../solve.py) reads the HTTPS endpoint from [`instance.json`](../instance.json), POSTs its embedded PHP payload as `cmd`, and extracts only the `pwnsec{...}` value. It writes the flag without a newline to stdout and sends failures to stderr. Activate the competition `.venv` and run from the challenge root.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

## Result

An actual `python solve.py` run exited with code `0`, produced 0 bytes on stderr and 24 bytes on stdout. Those stdout bytes exactly matched [`flag`](../flag).

```text
pwnsec{5dbe4132b1294725}
```

## Takeaways

`disable_functions` does not remove internal function handlers from memory and is not a sandbox boundary once a memory-corruption primitive exists. Blocking a global function name is also insufficient when wrapper methods expose the same serialization engine. For this target, verifying PHP 8.6's `0x38`-byte `zend_function_entry` and the build-specific `system` index 287 directly against remote memory was essential for reliable reproduction.

## References

- [Official PHP Sandbox Escape attachment](../challenge/public/README.md): service layout, sandbox objective, and local execution conditions.
- [Calif, “21-Year-Old PHP Serializable shared-var_hash UAF”](https://calif.io/research/php-uaf): the `Serializable` re-entry and shared `var_hash` UAF mechanism, plus the original exploit chain.
- [Calif public local exploit](https://github.com/califio/publications/blob/main/MADBugs/php/local_exploit.php): reference implementation for heap spraying, executor-global discovery, and fake Closure construction.
