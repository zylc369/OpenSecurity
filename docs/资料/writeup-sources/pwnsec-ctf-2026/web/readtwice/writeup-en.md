# readtwice

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 · CTF.ae |
| Category | web |
| Difficulty | Hard |
| Flag format | `pwnsec{...}` |

The solution executes script through a parsing difference between the JavaScript-disabled validator and the JavaScript-enabled review, then combines the approval flow with a browser history traversal to read the protected document a second time.

## Environment and Initial Analysis

The official source is in [`../challenge/`](../challenge/). The shared environment is restored from [`../../../requirements.txt`](../../../requirements.txt). `/create` validates the final DOM in offline Chromium with JavaScript disabled, while `/sandbox` renders the note under a `sandbox allow-scripts` CSP. The second `/reports/check` request requires an admin session, approved and finalized state, `Sec-Fetch-Site: none`, and `Sec-Fetch-Dest: document`.

## Core Analysis

A Declarative Partial Updates processing instruction and the `noscript` parsing difference inside declarative shadow DOM are combined. In the validator the DOM is reduced to one CSP meta and one empty `div`; during the real review, external `/s.js` executes before the CSP meta is applied. It transfers the review iframe's `MessagePort` to the attacker window, which sends `ready` and causes `/complete` to set the approved state.

An ordinary cross-site navigation fails with `Sec-Fetch-Site: cross-site`. The attacker document navigates to `about:blank`, then a same-origin helper calls `opener.history.back()`. Because the entry response is `Cache-Control: no-store`, Chromium requests it again with `Sec-Fetch-Site: none`. The second response issues a 302 redirect to `http://localhost:3000/reports/check?rid=...`, preserving that header and the admin Lax cookie. The navigation request itself sets `finalized` in the watcher, so the endpoint returns the raw note; its script reads `/api/flag` and sends it to the callback.

## Solution and Reproduction

[`../solve.py`](../solve.py) reads the main and callback URLs from [`../instance.json`](../instance.json) and starts a local callback server. The callback URL must be a public HTTPS tunnel to local port 8000.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

## Result

`python solve.py` exited with code 0 and produced the following newline-free stdout, byte-identical to [`../flag`](../flag).

```text
pwnsec{1503fc99f750c466}
```

## Takeaways

Different JavaScript settings between DOM validation and execution can create a parser differential. Fetch Metadata is not a sufficient trust boundary when history traversal and redirects can produce a `none` navigation while preserving the required session cookie.

## References

- [`../challenge/bot/bot.js`](../challenge/bot/bot.js): DOM validator and reviewer behavior.
- [`../challenge/src/server.js`](../challenge/src/server.js): routes, session, state, and Fetch Metadata policy.
- No external references were used for the final solution.
