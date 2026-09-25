# mouse in the house

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | web |
| Difficulty | not provided |
| Flag format | `pwnsec{...}` |

The goal is to read a private note owned by the bot session. The decisive observations are that DOMPurify preserves `data-prism-*` attributes that control a PrismJS dynamic module import, and that a `message` event exposes its sender through `event.source` even after the note assigns `window.opener = null`.

## Environment and Initial Analysis

The official input is [public.zip](../challenge/public.zip), extracted with the supplied password `infected`. The app uses Express 5.2.1, markdown-it 14.2.0, and DOMPurify 3.4.10. The bot uses Chromium 152 through Puppeteer 25.1.0. The shared Python environment is restored from [requirements.txt](../../../requirements.txt).

At startup, `server.js` generates an 8-character base-16 ID with `crypto.randomBytes(4)` and stores the flag note in a `Map` with `owner: BOT_SESSION_ID`. `/notes` only accepts `Sec-Fetch-Mode: navigate`, while `/notes/:id` only checks session ownership. Note pages receive a `sandbox allow-scripts allow-same-origin` CSP with restricted `script-src` and `connect-src` directives.

## Core Analysis

PrismJS `src/global.js` reads `data-prism-plugins` and `data-prism-plugin-path` from the document and runs `import(pluginPath + plugin + ".js")`. The following body is exactly 80 characters and both attributes survive DOMPurify:

```html
<p data-prism-plugins data-prism-plugin-path=data:text/javascript,import(name)#>
```

The empty `data-prism-plugins` attribute produces one empty plugin ID, and the first `data:` module executes `import(name)`. Storing a URL-encoded second `data:text/javascript,...` module in `window.name` provides arbitrary JavaScript execution without requiring `unsafe-eval`.

The inline note script assigns `window.opener = null`, and the CSP sandbox restricts auxiliary navigation. However, when the external parent sends `postMessage` to the popup, the popup recovers the parent's `WindowProxy` as `event.source`. The parent then navigates to the bot-internal `/notes/` page, making the parent and popup same-origin. The popup enumerates `/notes/<id>` links from the parent's DOM and fetches each `/notes/:id`, which is allowed by `connect-src`, until it finds the flag pattern.

## Solution and Reproduction

[solve.py](../solve.py) creates a public note containing the 80-character Prism payload, prepares temporary HTTP loader and callback endpoints, and submits the loader to the bot. The loader opens the XSS popup, sends it a message, and navigates itself to the internal `/notes/` page. The popup reads IDs from the listing DOM, fetches the private note, and sends only the flag to the callback. All mutable addresses are stored in [instance.json](../instance.json).

Activate the competition `.venv` and run from the challenge root:

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

## Result

The remote bot callback returned the flag, and the bytes matched both `python solve.py` stdout and the `flag` file.

```text
pwnsec{c723fccfe77783ae}
```

## Takeaways

A DOM sanitizer can remove event handlers and `<script>` elements while still leaving a script gadget when a library reads DOM attributes as dynamic-import configuration. Assigning `window.opener = null` also does not revoke a reference recovered later from `postMessage` through `event.source`. Combining a same-origin parent navigation with the Prism gadget bypassed the independent CSP sandbox and Fetch Metadata constraints.

## References

- [PrismJS global module](https://esm.sh/gh/PrismJS/prism@36ad7f8/src/global.js): confirmed `data-prism-*` configuration and dynamic-import behavior.
- [TikTok challenge hint](https://www.tiktok.com/@ketnipz/video/7193363887985659142): original link supplied in the challenge description.
- [Analysis evidence](../analysis/evidence.md): sanitizer result, CSP failure causes, and remote callback evidence.
