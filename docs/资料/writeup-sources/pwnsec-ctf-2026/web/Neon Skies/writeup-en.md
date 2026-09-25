# Neon Skies

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | web |
| Difficulty | Medium |
| Flag format | `pwnsec{...}` |

The objective is to recover the admin bot's HttpOnly `FLAG` cookie. The decisive flaw combines an allowed same-name domain cookie, Crystal's last-value-wins duplicate-cookie parsing, and an unescaped cookie value in `/admin`.

## Environment and Initial Analysis

The official input is [public.zip](../challenge/public.zip), containing the Crystal application, nginx configuration, and Playwright bot. The shared Python environment is restored from [requirements.txt](../../../requirements.txt).

The bot adds a host-only, HttpOnly, `SameSite=Strict` `FLAG` cookie for the public application origin, signs in as `archivist`, and visits the submitted URL. With a valid `sid`, `/admin` places the `FLAG` cookie inside `<output id="flag">` without HTML escaping. Direct login, request-path XSS, a `javascript:` redirect, and direct public container ports failed because of the changed remote password, `HTML.escape`, Chromium navigation blocking, and external port filtering respectively.

## Core Analysis

Because the cookie is named `FLAG` instead of using a `__Host-` prefix, a document on another `*.chal.ctf.ae` origin can create a same-name `Domain=chal.ctf.ae` cookie. An active `mouse in the house` instance supplied that sibling origin through its previously verified PrismJS dynamic-import gadget.

The stage script creates these two cookies:

```text
FLAG=<svg/onload=eval(atob(location.hash.slice(1)))>; Domain=chal.ctf.ae; Path=/admin
FLAG=<svg/onload=eval(atob(location.hash.slice(1)))>; Domain=chal.ctf.ae; Path=/
```

The browser sends longer paths first and older cookies first among equal paths. The `/admin` request therefore carries an attacker value, the original host-only secret, and another attacker value. Crystal 1.18.2 implements `HTTP::Cookies#<<` by assigning the name into a Hash again, so the final attacker value wins. `admin.ecr` places it in the raw sink, executing the SVG `onload` handler.

The handler running on the admin origin deletes both `Domain=chal.ctf.ae` cookies and calls `fetch` on `/admin` again. The remaining host-only HttpOnly `FLAG` is invisible to `document.cookie` but is still included in the HTTP request and rendered into the second response. The script extracts the flag from that body and sends it to the callback.

## Solution and Reproduction

[solve.py](../solve.py) reads the Neon application, sibling stage, loader, and callback addresses from `instance.json`. It creates the stage note, constructs the `window.name` data-module loader, performs domain-cookie tossing, reports the loader to the Neon bot, and polls the callback.

Activate the competition's `.venv` and run from the challenge root.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

## Result

The remote end-to-end run exited with code `0`, empty stderr, and exactly 24 stdout bytes without a trailing newline. The same bytes were recorded in the `flag` file.

```text
pwnsec{7f655c6d59355727}
```

## Takeaways

Sensitive cookies should use the `__Host-` prefix to prevent domain-cookie shadowing. Servers must not base security behavior on duplicate-cookie order, and cookie values still require context-appropriate output encoding. `HttpOnly` only prevents direct JavaScript cookie access; it does not protect a secret when same-origin XSS can refetch and read a response that renders it.

## References

- [neon_skies.cr](../challenge/public/web/src/neon_skies.cr): session handling, cookie selection, and the `/admin` route.
- [admin.ecr](../challenge/public/web/src/views/admin.ecr): the raw `FLAG` HTML sink.
- [conf.js](../challenge/public/bot/conf.js): bot cookie attributes and navigation sequence.
- [Crystal 1.18.2 `HTTP::Cookies`](https://github.com/crystal-lang/crystal/blob/1.18.2/src/http/cookies.cr): confirmation that later duplicate names overwrite earlier values.
- Existing official `mouse in the house` input and solver: confirmation that its PrismJS stage gadget could be reused.
