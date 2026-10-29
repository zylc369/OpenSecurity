# readonce-revenge

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | web |
| Difficulty | Hard |
| Flag format | `pwnsec{...}` |

The admin bot puts the flag in memory before visiting the attacker URL. The decisive observation is that the first `/reports/check` URL, including its secret `state`, remains in the tab's session history, while the bot can reach the admin-only `/review` and `/sandbox` routes through top-level navigations. The exploit combines sandbox approval, history traversal, and stored XSS.

## Environment and Initial Analysis

The official input is [public.zip](../challenge/public.zip), with SHA-256 `2F8E225AE02DEB8C0A66B82246CAB0895FA6A5C2948E8BD68B6683ACAE0F3187`. The extracted Node.js/Express source is preserved under [challenge](../challenge). From the challenge root, the shared Python environment is restored from the competition [requirements.txt](../../../requirements.txt), whose shell path is `../../requirements.txt`.

`bot.js` performs these visits:

1. `GET /reports/check?rid=<id>&state=<nonce>`
2. `GET /api/flag`
3. `POST /reports/arm/<id>`
4. Visit the submitted URL and wait 10 seconds

The session cookie is `HttpOnly; SameSite=Lax`. The second `/reports/check` branch requires `prepared`, `approved`, unused state, exact `rid/state`, and both `Sec-Fetch-Site: none` and `Sec-Fetch-Dest: document`.

## Core Analysis

`/review` checks the admin session and `rid`, then stores the attacker script URL in `currentReview.document`. It opens `/sandbox` in an iframe and replaces that iframe with an `&end` document after its first load. If the attacker script sends `top.postMessage()` during the old document's `pagehide`, the received `event.source` is the old `WindowProxy`, which differs from the new `viewer.contentWindow`. The parent therefore sends `/complete` with the hidden state and sets `approved=true`.

The revenge variant applies `sandbox allow-scripts` CSP to `/sandbox`, giving its script an opaque origin. The exploit does not escape that origin directly:

1. Callback `/start` opens internal `http://localhost:3000/review` in a popup. This top-level GET carries the bot's Lax admin cookie.
2. The original tab navigates to internal `/sandbox?rid=...`. The same external `payload.js` now runs in a top-level sandbox.
3. A plain `history.go(-3)` only restores the first check from BFCache and never reaches the server. `/start` therefore registers a service worker on the callback origin; the worker synthesizes 40 fully loaded documents at 10 ms intervals, evicting the old check entry from BFCache.
4. The final synthetic document sets `sessionStorage.done` and uses `location.replace()` to enter the internal sandbox. The marker prevents its navigation timer from being revived during traversal and overwriting the returned check document.
5. The top-level sandbox payload calls `history.go(2-history.length)` to select the initial check entry without learning the nonce. Because that entry was evicted, Chrome performs a real network request. The first response's `view` cookie changes the `Vary: Cookie` cache variant, and the history navigation supplies the required `none/document` Fetch Metadata.
6. The approved second check renders the selected note HTML raw. A sub-128-byte stored XSS loads callback `final.js`, which reads `/api/flag` with synchronous XHR and navigates to the callback before a competing navigation can win.

The complete service-worker history fill, second network check, and flag recovery were verified twice consecutively in headless Chrome with BFCache left enabled. Evidence is recorded in [local-validation.txt](../analysis/local-validation.txt).

## Solution and Reproduction

[solve.py](../solve.py) reads only the `main` and `callback` URLs from `instance.json`. The callback URL must forward to TCP port 8000 on the execution host. The solver creates the note, starts the callback HTTP server, submits the report, and validates the returned flag in one run.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

On success, stdout contains only the flag without a trailing newline, and stderr is empty.

## Result

With BFCache enabled in the instrumented local environment, `python solve.py` completed twice consecutively with exit code `0`, empty stderr, and stdout containing only the local placeholder flag. The same solver then ran against `https://eb2735d8a9a959a2.chal.ctf.ae` with exit code `0` and exactly 24 stdout bytes. The recovered flag is `pwnsec{917872750f693769}`.

## Takeaways

`SameSite=Lax` withholds cookies from an external script fetch but still includes them on top-level GET navigations. An opaque sandbox can be bypassed structurally: complete the privileged transition in an admin popup, evict BFCache with service-worker-generated history, then revive an existing history entry as a network request. A one-time URL defense must account for `Cache-Control: no-store`, history, and BFCache behavior in addition to Fetch Metadata and a nonce.

## References

- [HTML Standard sandboxing flags](https://html.spec.whatwg.org/multipage/browsers.html): opaque-origin, popup, and navigation restrictions imposed by CSP sandbox.
- [Chromium BFCache overview](https://chromium.googlesource.com/chromium/src/+/main/docs/bfcache.md): distinction between history restoration and a network reload.
- Official challenge source: authoritative route, session, and bot-navigation behavior.
