# whatsNew evidence

## Input integrity

- `challenge/handout.zip` SHA-256: `583B3EFDF428E5E93157EB1313EB08F44CF0DBFF21CF0125E42110FFC2E66C8C`
- Official source root: `challenge/whatsNew/`

## Source observations

- `src/routes/categoryRoutes.js` calls `decodeHtml()` and `isSuspicious()` only for `description`.
- Every category's `renderPost()` inserts `description` through `raw()`.
- `decodeHtml()` handles only references ending in `;`, while a browser also accepts selected numeric references without `;`.
- `public/static/updates.js` trusts the named global `window.whatsNew`, requires six properties, and redirects to `next.href` after appending `document.cookie` as the `cookie` query parameter.
- `src/routes/adminRoutes.js` exposes `/admin/preview` only to a browser carrying the per-instance admin bot cookie.

## Filter and browser proof

The first two stored descriptions are 150 and 148 characters after server decoding, and `isSuspicious()` returned `false` for both. In Chrome `153.0.8010.36`, the six anchors became an `[object HTMLCollection]` with these values:

```json
{
  "length": 6,
  "panel": "#latest-posts",
  "autoReview": "1",
  "nextRaw": "/admin/x"
}
```

With the local proof cookie set, the unmodified `updates.js` navigated to:

```text
/admin/x?cookie=admin_bot_token%3Dtest-token%3B+flag%3DK17%7Blocal_exact_app%7D
```

The compact browser harness is preserved as `analysis/poc.html`.

## Remote verification

- `GET /`: HTTP 200
- `GET /category/tech/new`: HTTP 200
- Unauthenticated `GET /admin/preview`: HTTP 403
- Stored payload posts in `tech`, `travel`, and `food`: HTTP 302 each
- `POST /report`: HTTP 202
- Admin bot callback received:

```text
/admin/x?cookie=token%3DK17%7BG4dg3t_D0M_Cl0663r1nggg%21%7D
```

- `solve.py` end-to-end run: exit code 0, empty stderr, exact stdout `K17{G4dg3t_D0M_Cl0663r1nggg!}`.

