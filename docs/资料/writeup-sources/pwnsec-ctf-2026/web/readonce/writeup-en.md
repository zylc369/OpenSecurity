# readonce

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | web |
| Difficulty | Hard |
| Flag format | `pwnsec{...}` |

The objective is to recover the value returned by `/api/flag`, which is restricted to the administrator bot's session. The decisive observation is that `/review` stores an attacker URL as a `<script src>` carrying a server-generated nonce, while a redirect from the reported page can make the bot open the internal `/sandbox` as a top-level document. Together, these behaviors run attacker JavaScript in the administrator origin without the intended iframe sandbox.

## Environment and Initial Analysis

The official input is [public.zip](../challenge/public.zip), extracted with password `infected`. It contains an Express application and a Puppeteer administrator bot. The application declares Express 4.19.2 and the bot declares Puppeteer 25.3.0. Analysis and reproduction used Python 3.12.10, Node.js 24.20.0, and cloudflared 2026.9.1. The shared Python environment was restored from [requirements.txt](../../../requirements.txt).

In `bot/bot.js`, `review()` creates an administrator session, then visits `/reports/check`, `/api/flag`, and `/reports/arm/:id`. It finally appends `rid` to the reported URL, opens it in the same browser context, and waits 10 seconds. The administrator cookie is therefore already present if code reached from the reported URL can navigate to the internal application origin.

## Core Analysis

`GET /review?rid=RID&u=URL` checks only the active report identifier, appends `rid` to `URL`, and stores it in `currentReview.document.url` without authentication. `GET /sandbox?rid=RID` then renders an element of this form:

```html
<script nonce="SERVER_NONCE" src="ATTACKER_URL"></script>
```

The CSP specifies `script-src 'nonce-SERVER_NONCE'` and requires Trusted Types, but this is a parser-created script carrying the correct nonce from the server template. JavaScript from the attacker URL is consequently allowed. The normal `/review` page embeds `/sandbox` in a restricted iframe. Returning a 302 from the bot's reported URL to `http://localhost:3000/sandbox?rid=RID` instead opens the same resource in the top-level browsing context.

Direct `fetch` exfiltration is blocked by `/sandbox`'s `default-src 'none'`. The payload instead submits a GET form with `target=flagwin` to `/api/flag`. The resulting auxiliary window displays the same-origin JSON response. After 500 ms, `open('', 'flagwin')` retrieves the existing window, `document.body.innerText` reads the response, and a top-level navigation sends it to the attacker's `/leak?data=...` endpoint. The observed request sequence is preserved in [exploit-notes.md](../analysis/exploit-notes.md).

## Solution and Reproduction

[solve.py](../solve.py) uses only the Python standard library to run a callback HTTP server. When the bot requests `/start?rid=...`, the solver calls the remote `/review` to register `/payload.js`, then redirects the bot to the internal `/sandbox`. The payload reads the flag JSON through the form target window and returns it to `/leak`.

The callback server must be internet-accessible. Set `READONCE_PUBLIC_URL` to an HTTPS tunnel forwarding to local port 8000. `READONCE_LISTEN_PORT` defaults to `8000`. The target URL is read exclusively from [instance.json](../instance.json).

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

For PowerShell, prepare the tunnel and set `$env:READONCE_PUBLIC_URL='https://your-public-tunnel.example'` before running the commands.

## Result

Against the remote instance, the solver exited with code 0, produced empty stderr, and wrote a 24-byte stdout value with no trailing newline. Its stdout matched the `flag` file byte-for-byte.

```text
pwnsec{f73af0e53bf677dc}
```

## Takeaways

A nonce-based CSP does not establish a trust boundary when attacker input controls the `src` of a server-created script that already carries the nonce. An iframe-only sandbox is also ineffective if the protected resource can be opened directly as a top-level document. Finally, blocking `connect-src` is insufficient when navigation and form-target browser primitives remain available.

## References

- [bot/bot.js](../challenge/bot/bot.js): administrator session setup and report visitation order.
- [server.js](../challenge/src/server.js): input, state, and response conditions for `/review`, `/sandbox`, `/api/flag`, and `/report`.
- [sandbox.ejs](../challenge/src/views/sandbox.ejs): the nonced external script element.
- No external technical references were used.
