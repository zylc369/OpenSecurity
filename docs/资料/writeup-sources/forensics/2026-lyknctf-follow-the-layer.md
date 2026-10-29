---
来源: https://cybersecurityelite.com/ctf-writeups/lyknctf-2026-forensics-writeup/
类型: html
获取日期: 2026-06-30
---

![LYKNCTF 2026 forensics writeup — four challenges solved covering PNG metadata XOR, red-channel LSB stego, JPEG-as-PNG ZIP append, and TRON USDT OFAC chain trace](https://cybersecurityelite.com/images/articles/lyknctf-2026-forensics-writeup.png)Table of Contents

**LYKNCTF 2026**’s forensics track is small but well-shaped, and this **CyberSecurity Elite** writeup walks all four solves — challenges that cover the whole spectrum of file-format triage, from PNG chunk parsing and repeating-key XOR through steganographic LSB extraction and polyglot ZIP appending to a real on-chain USDT trace on TRON that ends at an OFAC-sanctioned wallet before landing in a Bitget hot wallet. Each challenge deliberately ships a decoy layer (an EXIF cover story, an `IEND` trailer with a fake “password hint,” a `.png` extension that lies about the container format, a suggestive first hop) that looks like the answer if you stop reading too early.

This writeup walks all four forensics solves in the order they appear in the repository: Photograph (PNG with an eXIf decoy and a `Description` tEXt chunk carrying a repeating-key-XOR ciphertext), WorldCup 1 (PNG red-channel LSB stego with a decoy `HIDDEN_DATA_START` trailer after `IEND`), WorldCup 2 (JPEG under a `.png` extension with a ZIP appended after `FFD9` whose End-of-Central-Directory self-locates), and Follow The Layer (TRC-20 USDT hop-by-hop trace via TronGrid, cross-checked against OFAC’s SDN feed, stopping at a `Bitget 9` hot wallet where the money co-mingles with 20 million other transactions).

Handouts, per-challenge READMEs, artifacts, and Python solvers live at [Abdelkad3r/LYKNCTF](https://github.com/Abdelkad3r/LYKNCTF). Every exploit uses the Python standard library plus one small dependency at most (Pillow + NumPy for LSB extraction, or the standard `urllib` for the on-chain solver’s three HTTP endpoints).

## The four LYKNCTF 2026 forensics challenges[#](#the-four-lyknctf-2026-forensics-challenges)

| # | Challenge | Primitive | Flag |
| --- | --- | --- | --- |
| 1 | Photograph | PNG with eXIf decoy (iPhone spoof, ROT-13 UserComment, Ho Chi Minh City GPS). Real payload in `Description` tEXt chunk: 49-byte hex ciphertext. Repeating `0x7e` at every 8-byte boundary from offset 16 = 8-byte repeating-key XOR. Known-plaintext with `LYKNCTF{` recovers the key. | `LYKNCTF{Would_Be_Nice_If_Someone_Grow_Up_One_Day}` |
| 2 | WorldCup 1 | PNG with three tEXt chunks including `Flag_Hint: Look deeper in the red pixels`. Decoy: 69-byte `HIDDEN_DATA_START` trailer after `IEND` with no matching end marker. Real flag: first 30 bytes of red-channel LSB stream, MSB-first packed. | `LYKNCTF{Argentina3-2CaboVerde}` |
| 3 | WorldCup 2 | `.png` extension lies: file is actually JPEG (JFIF 1.01, 1536×2048). ZIP archive appended after JPEG’s `FFD9` EOI marker. ZIP’s End-of-Central-Directory self-locates from EOF, so `unzip -p worldcup2_challenge.png flag_hidden.txt` works without carving. | `LYKNCTF{RespectToCaboVerde}` |
| 4 | Follow The Layer | On-chain forensics on TRON. Follow-the-money hop-by-hop via TronGrid TRC-20 API. Hop 1 recipient is on OFAC SDN list (FUNNULL TECHNOLOGY INC, CYBER3 program). Amount-matched hops 2 and 3 land at `Bitget 9` exchange hot wallet where the money co-mingles. | `LYKNCTF{7e401f8004084d4bf9f792535fdf5b89138a935d027b6b75ceb2dd3ac8838fab:03/21/2025:FUNNULL}` |

The track’s design signature is layered decoy content that would be a valid solve for a different challenge. Photograph’s eXIf blob would be the answer to “extract EXIF metadata”; WorldCup 1’s post-`IEND` trailer would be the answer to “find data appended after PNG EOF”; WorldCup 2’s `.png` extension would be the answer to “identify container format from magic bytes”; Follow The Layer’s first-hop OFAC hit would be the answer to “identify the sanctioned recipient.” Each challenge asks a specific question, and every solver who submits the decoy answer gets rejected. Reading the brief carefully and finishing the trace before submitting is the general discipline.

## Methodology — walk every layer before committing to one[#](#methodology--walk-every-layer-before-committing-to-one)

A pattern that worked across all four challenges: enumerate every layer the file has, then decide which one contains the flag by matching the brief to the layer’s contents. Photograph’s chunk walk shows an eXIf (decoy) and a `Description` tEXt (real). WorldCup 1’s chunk walk shows three tEXt chunks (metadata) plus 69 bytes past `IEND` (decoy) plus 512×640 pixels (real, in red-channel LSB). WorldCup 2’s `file(1)` output disagrees with the extension (JPEG, not PNG), which reframes the whole search. Follow The Layer’s TronGrid `transaction-info` gives the first hop’s parties immediately; the OFAC XML confirms the sanctioned recipient in one grep.

The second discipline is treating structural signals as high-priority evidence. Photograph’s 49-byte ciphertext length matches `LYKNCTF{` + 40 chars + `}` exactly, framing the known-plaintext attack before any decryption. The `0x7e` at every 8-byte boundary from offset 16 telegraphs the key period. WorldCup 1’s `HIDDEN_DATA_START` with no matching `HIDDEN_DATA_END` is a red flag that the trailer is decoy staging. WorldCup 2’s `PK\x03\x04` two bytes after `FF D9` announces the appended ZIP without any tool at all. On-chain, matching amounts across hops (5222.00 USDT twice) confirms the same funds are moving forward while amount jumps signal an aggregation wallet. Every one of these signals is visible in `xxd`, `unzip -l`, or `jq` output; no specialised tooling required.

Per-challenge walkthroughs follow.

## 1. Photograph[#](#1-photograph)

An anime-girl PNG with an eXIf decoy and a `Description` tEXt chunk carrying a 49-byte hex ciphertext. The whole solve is a known-plaintext attack against a repeating-key XOR whose period is telegraphed by a byte pattern in the ciphertext.

#### Step 1 — Walk the PNG chunks[#](#step-1--walk-the-png-chunks)

The pixels are visually inert (no LSB static, no obvious watermark, no compression artifacts). Two chunks stand out from a `struct`-based walk:

```
IHDR  at 0x0008    13 bytes
eXIf  at 0x0021   322 bytes   ← EXIF on a PNG is unusual
tEXt  at 0x016f   110 bytes   ← Description = long hex string
iCCP  at 0x01e9   354 bytes
...
IDAT ×6 ...
IEND
```

Two unusual things: an `eXIf` chunk on a PNG (PNGs pick up EXIF far less often than JPEGs), and a `Description` tEXt whose payload is 90-character hex.

#### Step 2 — Recognise the eXIf as decoy[#](#step-2--recognise-the-exif-as-decoy)

The eXIf blob parses cleanly:

| Tag | Value |
| --- | --- |
| Make | `Iphone_12_Pro` |
| Model | `Normal_Camera` |
| DateTimeOriginal | `2013:07:04 13:37:00` (13:37 leetspeak) |
| UserComment | `Gnxvat Cubgbf Znlor Sha` (ROT-13) |
| GPSLatitudeRef / Latitude | N, 10° 46’ 36.84" |
| GPSLongitudeRef / Longitude | E, 106° 42’ 3.24" |

ROT-13 of the UserComment: `Taking Photos Maybe Fun`. GPS resolves to 10.7769 N, 106.7009 E, which is Ho Chi Minh City. Nothing here decrypts anything downstream. It’s flavour text, and it burns time if you treat the ROT-13 result or the GPS coordinates as candidate XOR keys.

#### Step 3 — Read the ciphertext structure[#](#step-3--read-the-ciphertext-structure)

The `Description` tEXt payload (after stripping the `Description\x00` key) decodes from hex to 49 bytes:

```
00: 6d 14 16 68 42 b6 ec b6
08: 76 22 28 4a 65 bd e8 a8
10: 7e 03 34 45 64 bd e3 ab
18: 7e 1e 32 4b 64 8d c4 a8
20: 7e 0a 2f 49 76 bd ff bd
28: 7e 02 33 43 5e a6 cb b4
30: 5c
```

Two structural observations kick the door in:

* **Length is 49 bytes**, exactly `LYKNCTF{` (8) + 40-byte body + `}` (1). This is likely the raw flag, encrypted 1-for-1.
* **`0x7e` at offsets 0x10, 0x18, 0x20, 0x28**, every 8 bytes from offset 16 onward. Not a coincidence: this is a repeating-key XOR with an 8-byte period, and the plaintext at those positions is the same character (a space or an underscore, most likely).

#### Step 4 — Known-plaintext attack[#](#step-4--known-plaintext-attack)

If the key is 8 bytes and the plaintext starts with `LYKNCTF{`, the key drops out for free:

```
ct = bytes.fromhex(
    "6d14166842b6ecb67622284a65bde8a8"
    "7e03344564bde3ab7e1e324b648dc4a8"
    "7e0a2f4976bdffbd7e0233435ea6cbb4"
    "5c"
)
prefix = b"LYKNCTF{"
key = bytes(c ^ p for c, p in zip(ct[:8], prefix))
# key = 21 4d 5d 26 01 e2 aa cd

pt = bytes(ct[i] ^ key[i % 8] for i in range(len(ct)))
print(pt.decode("ascii"))
# LYKNCTF{Would_Be_Nice_If_Someone_Grow_Up_One_Day}
```

The key `21 4d 5d 26 01 e2 aa cd` starts with `!M]&` and then goes non-printable, which is why searching for a “password-shaped” key earlier turned up nothing. Repeated `0x7e` in the ciphertext at offsets 16, 24, 32, 40 corresponds to `_` (`0x5f`) in the plaintext at those positions (the word separators in `Would_Be_Nice_If_Someone_Grow_Up_One_Day`), because `0x5f XOR 0x21 = 0x7e`. Self-consistent.

Per-challenge README + Python solver: [forensics/photograph](https://github.com/Abdelkad3r/LYKNCTF/tree/main/forensics/photograph).

The defender lesson is that the eXIf chunk is a well-crafted decoy that would be a valid solve for any “extract EXIF metadata” challenge. The correct read is not “found a suspicious-looking string, that’s the flag,” it is “the brief asks for a flag, and the ciphertext structure is announcing itself; solve the ciphertext.”

## 2. WorldCup 1[#](#2-worldcup-1)

A football-result PNG whose metadata literally tells you where the flag lives. The whole solve is one Pillow read of the red channel’s LSBs, MSB-first packed. The trap is a fake `HIDDEN_DATA_START` trailer after `IEND` that stages a puzzle nobody needs to solve.

#### Step 1 — Read every tEXt chunk[#](#step-1--read-every-text-chunk)

The PNG chunk table has three tEXt chunks:

| Key | Value |
| --- | --- |
| `Flag_Hint` | `Look deeper in the red pixels` |
| `Comment` | `The score was 3-2 after extra time` |
| `Description` | `Argentina vs Cabo Verde - World Cup 2026` |

`Flag_Hint` names the primitive outright. `Comment` and `Description` describe the eventual flag content (`Argentina3-2CaboVerde`), so if you never open the image and never look at the LSBs, the metadata alone hands you the answer to guess.

#### Step 2 — Recognise the post-IEND trailer as decoy[#](#step-2--recognise-the-post-iend-trailer-as-decoy)

Sixty-nine bytes appear after the `IEND` chunk:

```
HIDDEN_DATA_STARTPassword hint: What was the final score? Format: X-Y
```

That’s the whole trailer. There’s no `HIDDEN_DATA_END`, and there’s no ciphertext after `HIDDEN_DATA_START`; just the “password hint.” The trailer is staging a puzzle (“figure out the score, that’s the password to decrypt the blob”) that doesn’t exist because there is no blob. Any solver who chases the “figure out the password” thread burns time on a non-existent decryption step.

#### Step 3 — Extract red-channel LSB[#](#step-3--extract-red-channel-lsb)

The reflex for “hidden in the red channel” is to pull the low bit of each red byte and pack into bytes. At 512×640 the red channel has 327 680 bits available, plenty for a flag:

```
from PIL import Image
import numpy as np

arr = np.array(Image.open("worldcup1_challenge.png").convert("RGB"))
bits = (arr[:, :, 0].flatten() & 1)               # red-channel LSBs

# Pack MSB-first (most common convention for hand-written LSB stego).
first_bytes = bytes(
    int("".join(str(b) for b in bits[i:i + 8]), 2)
    for i in range(0, 30 * 8, 8)
)
print(first_bytes.decode())
# LYKNCTF{Argentina3-2CaboVerde}
```

The flag is the first 30 bytes of the stream. Everything after byte 30 is the natural noise in the un-modified red-channel LSBs; the author only wrote the flag string and left the rest of the image alone.

#### Step 4 — Note the bit-order convention[#](#step-4--note-the-bit-order-convention)

LSB-first packing of the same stream reads as `2\x9a\xd2r\xc2*b\xde...` (random noise). MSB-first is what worked. This is a general point for hand-written LSB stego: most authors reach for MSB-first when writing the encoder by hand, because it maps directly to the natural “for each bit, shift left and OR in the next” pattern. LSB-first is more common when the encoder uses a bit-vector library that packs the way memory layouts prefer.

Per-challenge README + solver: [forensics/worldcup1](https://github.com/Abdelkad3r/LYKNCTF/tree/main/forensics/worldcup1).

## 3. WorldCup 2[#](#3-worldcup-2)

A file called `worldcup2_challenge.png` that isn’t a PNG. `file(1)` says JPEG (JFIF 1.01, 1536×2048). A ZIP archive is appended after the JPEG’s `FFD9` EOI marker, and because ZIP’s End-of-Central-Directory locates itself by scanning backward from EOF, `unzip` on the `.png` finds the archive without any carving.

#### Step 1 — Identify the real container[#](#step-1--identify-the-real-container)

```
$ file worldcup2_challenge.png
worldcup2_challenge.png: JPEG image data, JFIF standard 1.01, ..., 1536x2048
```

Extension lies. The file is JPEG. Every downstream tool that keys on extension (image viewers, browsers, PNG chunk parsers) reads this correctly as JPEG at the byte level while displaying it under a name that suggests PNG.

#### Step 2 — Read the tail[#](#step-2--read-the-tail)

An `xxd` of the last 200 bytes shows:

```
0004 53de  ... 1f ff d9         ; JPEG stream ends (FFD9)
0004 53e4  50 4b 03 04           ; ZIP local file header (PK\x03\x04)
                                  ;   flag_hidden.txt, 27 bytes stored
0004 5451  50 4b 05 06           ; ZIP End-of-Central-Directory (PK\x05\x06)
0004 54a1  RESPECT_TO_CABO_VERDE
0004 54c6  The warriors fought bravely
0004 54f1  Check the file structure
```

Three tells stack. `FFD9` is JPEG EOI, so anything after it is not part of the image. `PK\x03\x04` two bytes later is a ZIP local file header. `PK\x05\x06` a hundred bytes further is the ZIP End-of-Central-Directory signature. The trailing plaintext `Check the file structure` is the intended solver nudge.

#### Step 3 — Extract without carving[#](#step-3--extract-without-carving)

ZIP’s EOCD locates itself by scanning backward from EOF for the signature `PK\x05\x06`, then follows offsets recorded in that record to find the central directory and local file headers. The scan doesn’t care about anything preceding the ZIP; it starts at the file’s end and works backward. So:

```
$ unzip -p worldcup2_challenge.png flag_hidden.txt
LYKNCTF{RespectToCaboVerde}
```

`binwalk -e` works identically. Carving from the `PK\x03\x04` offset and piping into `funzip` also works:

```
$ tail -c +$((0x453e4 + 1)) worldcup2_challenge.png | funzip
LYKNCTF{RespectToCaboVerde}
```

Per-challenge README + one-line extractor: [forensics/worldcup2](https://github.com/Abdelkad3r/LYKNCTF/tree/main/forensics/worldcup2).

The trick is old but reliable: any file format whose parser stops at its own end marker (JPEG’s `FFD9`, PNG’s `IEND` CRC, PDF’s `%%EOF`, PE overlay boundaries) can host a ZIP appended at the end, and the ZIP self-locates from EOF regardless of what precedes it. Triage on any suspicious-looking image should include `file(1)`, a tail hex dump, and a straight `unzip` attempt before believing the container is what its name claims.

## 4. Follow The Layer[#](#4-follow-the-layer)

An on-chain forensics challenge. Given one TRC-20 USDT transaction hash on TRON, follow the money hop-by-hop until it lands in an exchange hot wallet where attribution stops, and cross-check every touched wallet against OFAC’s SDN list.

#### Step 1 — Identify the chain[#](#step-1--identify-the-chain)

The starting hash is 64 hex characters, which could be Ethereum, TRON, BSC, or any of a dozen other chains. Trying TronGrid’s `transaction-info` endpoint returns immediately:

```
$ curl -s "https://apilist.tronscanapi.com/api/transaction-info?hash=d4500023..." | jq .
{
  "trc20TransferInfo": [{
    "symbol":"USDT",
    "contract_address":"TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
    "from_address":"TXk7Dor9GeRRpR5hbCGd4rBieM21v4BcwX",
    "to_address":"TNmRfnSUXZoWWzxcDDbf95eGQYXt1mJDt8",
    "amount_str":"2700000000"
  }],
  "timestamp": 1740661449000,
  ...
}
```

TRON, TRC-20 USDT, 2 700 USDT sent on 2025-02-27 13:04 UTC. The two addresses are the first hop’s parties.

#### Step 2 — Walk hops via TronGrid TRC-20 endpoint[#](#step-2--walk-hops-via-trongrid-trc-20-endpoint)

TronGrid’s `/v1/accounts/{addr}/transactions/trc20` filtered by the USDT contract and `only_from=true` returns outgoing USDT transfers for any address. Iterate hop-by-hop, preferring outgoing transfers whose amount matches the incoming one:

| Hop | Time (UTC) | From → To | USDT | Tx |
| --- | --- | --- | --- | --- |
| 1 | 2025-02-27 13:04 | `TXk7Dor9…BcwX` → `TNmRfn…mJDt8` | 2 700.00 | `d4500023…ae336b` |
| 2 | 2025-03-21 03:03 | `TNmRfn…mJDt8` → `TQMq9s…Do3tb` | 5 222.00 | `2ef09557…56b9d9` |
| 3 | 2025-03-21 03:07 | `TQMq9s…Do3tb` → `TJ7hh…JSdb` (Bitget 9) | 5 222.00 | `7e401f80…8838fab` |

The amount jump between hop 1 (2 700) and hop 2 (5 222) is expected: `TNmRfn…mJDt8` is a **collector wallet** that aggregates many victim payments and forwards a pooled bundle. From hop 2 onward the amount is preserved byte-for-byte (5 222.00 USDT twice), which is the strongest possible signal that the same funds are moving forward.

#### Step 3 — Screen every wallet against OFAC SDN[#](#step-3--screen-every-wallet-against-ofac-sdn)

OFAC publishes the SDN list as XML directly from Treasury:

```
$ curl -o sdn.xml https://www.treasury.gov/ofac/downloads/sdn.xml
$ grep -c TNmRfnSUXZoWWzxcDDbf95eGQYXt1mJDt8 sdn.xml
1
```

The hit is on hop 1’s recipient. The SDN entry:

```
<sdnEntry>
  <lastName>FUNNULL TECHNOLOGY INC</lastName>
  <sdnType>Entity</sdnType>
  <programList><program>CYBER3</program></programList>
  <idList>
    <id><idType>Digital Currency Address - TRX</idType>
        <idNumber>TNmRfnSUXZoWWzxcDDbf95eGQYXt1mJDt8</idNumber></id>
  </idList>
  <akaList>
    <aka>FUNNULL</aka>
    <aka>FANG NENG CDN</aka>
  </akaList>
</sdnEntry>
```

FUNNULL TECHNOLOGY INC is a Filipino CDN operator designated by OFAC on 2025-05-29 as the CDN backbone behind tens of thousands of “pig-butchering” (romance-crypto-scam) domains, under the CYBER3 program. The challenge’s mention of an “online scam operation” resolves exactly to this designation.

#### Step 4 — Recognise the “attribution stops” endpoint[#](#step-4--recognise-the-attribution-stops-endpoint)

Hop 3’s recipient `TJ7hhYhVhaxNx6BPyq7yFpqZrQULL3JSdb` is tagged **`Bitget 9`** on Tronscan and has 20 002 234 transactions on it. Once the funds land there, they’re co-mingled with the entire exchange’s flow; the next outgoing USDT from that address is unrelated to our 5 222 USDT and happens every few seconds. That’s the definition of “money stops being attributable.” The stopping rule for the trace is exactly this: land at a labelled exchange hot wallet with high throughput, and record the deposit receipt as the last traceable hop.

#### Step 5 — Assemble the flag[#](#step-5--assemble-the-flag)

* Last traceable tx hash: `7e401f8004084d4bf9f792535fdf5b89138a935d027b6b75ceb2dd3ac8838fab`
* Date (UTC): `03/21/2025`
* Sanctioned entity: `FUNNULL`

```
LYKNCTF{7e401f8004084d4bf9f792535fdf5b89138a935d027b6b75ceb2dd3ac8838fab:03/21/2025:FUNNULL}
```

Per-challenge README + end-to-end Python solver (TronGrid + Tronscan + OFAC XML in one pass): [forensics/follow-the-layer](https://github.com/Abdelkad3r/LYKNCTF/tree/main/forensics/follow-the-layer).

Two things worth internalising for any on-chain investigation. First, screen every wallet you touch against OFAC directly. The SDN feed is free, small, and canonical; Chainalysis and Elliptic tags are commercial mirrors of it plus their own attribution work. Second, the point where tracing stops is meaningful data on its own. Choosing an explicit stopping rule (high-transaction-count destination, labelled exchange, mixer signature) turns “the chain got messy” into “the money hit an exchange hot wallet at this block, here’s the deposit receipt,” which is often what investigators actually want to hand off downstream.

## Cross-cutting defender notes[#](#cross-cutting-defender-notes)

Five patterns recur across the LYKNCTF forensics track and translate directly into triage discipline.

**Every file has multiple layers; every layer can carry a payload.** Photograph has pixels, PNG chunks, an eXIf blob, tEXt metadata, and an appended tail. WorldCup 1 has pixels, chunks, and a post-`IEND` trailer. WorldCup 2 has JPEG segments and a ZIP tail. Follow The Layer has TRX transaction records, timestamps, addresses, amounts, and OFAC labels. The triage discipline is to enumerate all layers, extract whatever each holds, and only then decide which layer contains the answer. The correct question is not “where’s the flag?” but “what does each layer hold, and which one matches the brief?”

**Decoy layers are common; brief-matching is the disambiguator.** Photograph’s eXIf blob is a well-crafted iPhone-photo cover story; WorldCup 1’s `HIDDEN_DATA_START` trailer is a fake encryption-challenge frame; WorldCup 2’s `.png` extension is a container-format lie; Follow The Layer’s first-hop OFAC hit is a suggestive dead-end that isn’t the flag by itself. Every decoy is a valid answer to a different question. The brief specifies which question is being asked, and the correct layer is the one whose contents answer that specific question. This is exactly the same discipline that solves the RIFFHACK “flag-shaped strings salted across the codebase” problem, applied to file-format layers.

**Structural signals are high-priority evidence.** Ciphertext length matching a plausible plaintext structure (Photograph’s 49 = 8 + 40 + 1), repeated bytes at fixed periods (Photograph’s `0x7e` every 8 bytes), missing end markers (WorldCup 1’s `HIDDEN_DATA_START` with no matching end), extension/magic-byte mismatches (WorldCup 2), amount preservation across hops (Follow The Layer’s 5 222 twice): these are the fastest way to a correct answer, and every one of them is visible in a few lines of tool output. Prefer the structural signal to the semantic one.

**Metadata is more informative than pixels 90% of the time.** WorldCup 1 hands you the answer in three tEXt chunks before you touch a pixel. Photograph’s ciphertext is entirely in a tEXt chunk. The pixels in both cases are the second-priority target: WorldCup 1 uses the red-channel LSB (real), Photograph uses nothing (decoy). Read every chunk before you touch pixels; if a chunk has a value that looks like the flag, verify it against the brief before submitting.

**On-chain trace stopping rules matter as much as the trace itself.** Follow The Layer’s answer is not “the funds went here → here → here → forever.” It’s “the funds went here → here → here, and at the final address they hit an exchange hot wallet with 20 million transactions, so the last attributable state is the deposit receipt.” Explicit stopping rules (labelled exchange, high transaction count, mixer signature, or crossing a chain-bridge) are what turn a chain trace into a report. Without an explicit stopping rule the trace either continues into noise forever or stops arbitrarily.

## Frequently asked questions[#](#frequently-asked-questions)

### What is LYKNCTF 2026?[#](#what-is-lyknctf-2026)

LYKNCTF 2026 is a CTF whose challenges span multiple categories including web, reverse-engineering (crack), pwn, and forensics. This writeup covers the four forensics challenges I solved. Flag prefix `LYKNCTF{...}` (Follow The Layer uses an internal colon-separated payload). Per-challenge READMEs, artifacts, and solver scripts are mirrored at [Abdelkad3r/LYKNCTF](https://github.com/Abdelkad3r/LYKNCTF). Companion writeups for the same event’s other tracks are at [LYKNCTF web writeup](https://cybersecurityelite.com/ctf-writeups/lyknctf-2026-web-writeup/), [LYKNCTF crack writeup](https://cybersecurityelite.com/ctf-writeups/lyknctf-2026-crack-writeup/), and [LYKNCTF pwn writeup](https://cybersecurityelite.com/ctf-writeups/lyknctf-2026-pwn-writeup/).

### What’s the actual ciphertext in Photograph and why is the eXIf chunk a decoy?[#](#whats-the-actual-ciphertext-in-photograph-and-why-is-the-exif-chunk-a-decoy)

The 49-byte ciphertext is the hex-decoded value of the `Description` tEXt chunk’s payload. It has `0x7e` at every 8-byte boundary from offset 16 onward, which is the classic tell of a repeating-key XOR with an 8-byte period. Known-plaintext with `LYKNCTF{` against the first 8 ciphertext bytes recovers the key `21 4d 5d 26 01 e2 aa cd`. The eXIf chunk parses cleanly (iPhone 12 Pro spoof, ROT-13 UserComment decoding to “Taking Photos Maybe Fun”, GPS resolving to Ho Chi Minh City), but none of those values decrypt the ciphertext. The chunk is flavour text that would answer “extract EXIF metadata” on a different challenge.

### How did you recognise the 8-byte period in Photograph’s ciphertext?[#](#how-did-you-recognise-the-8-byte-period-in-photographs-ciphertext)

The repeated byte `0x7e` at offsets 0x10, 0x18, 0x20, 0x28 (every 8 bytes from offset 16) is only possible if the same plaintext-byte-XOR-key-byte pair recurs at those positions. That happens exactly when the key has period 8 (so key[16 % 8] = key[24 % 8] = key[32 % 8] = key[40 % 8] = key[0]) and the plaintext at those positions is the same character. For a repeating-key XOR whose plaintext is `LYKNCTF{...}` with underscores as separators, the `_` (`0x5f`) sits at positions 16, 24, 32, 40, and `0x5f XOR 0x21 = 0x7e`, exactly matching.

### Why does the flag in WorldCup 1 live in the red channel and not the green or blue?[#](#why-does-the-flag-in-worldcup-1-live-in-the-red-channel-and-not-the-green-or-blue)

Because the `Flag_Hint` tEXt chunk literally says `Look deeper in the red pixels`. The author chose the red channel; the challenge names the channel; the extraction is one Pillow read of `arr[:, :, 0].flatten() & 1`. Green and blue LSBs on the same image are just the natural noise from PNG encoding. For general LSB triage, extracting each channel’s LSB separately and checking for printable ASCII is a two-line loop; a hint chunk simply says which channel to check first.

### What’s the trap with WorldCup 1’s post-IEND trailer?[#](#whats-the-trap-with-worldcup-1s-post-iend-trailer)

The 69-byte trailer `HIDDEN_DATA_STARTPassword hint: What was the final score? Format: X-Y` is staging a fake encryption puzzle. There is no `HIDDEN_DATA_END` marker, no ciphertext after `HIDDEN_DATA_START`, and no encrypted blob to unlock. Solvers who take the “figure out the password to decrypt the hidden data” framing at face value burn time on a nonexistent decryption step. The correct read is: the trailer has no ciphertext, so there’s nothing to decrypt; the `Flag_Hint` chunk names the red-channel LSB primitive, which is the real path.

### Why does `unzip` work on the WorldCup 2 file even though it’s a JPEG?[#](#why-does-unzip-work-on-the-worldcup-2-file-even-though-its-a-jpeg)

Because ZIP’s End-of-Central-Directory record locates itself by scanning backward from EOF for the signature `PK\x05\x06`. The scan doesn’t care what precedes the ZIP; it starts at the file’s end and works backward until it finds the EOCD signature, then follows offsets recorded in that record to find the central directory and local file headers. So a JPEG followed by a ZIP is a valid ZIP as far as `unzip` is concerned. The same trick works with PNG-followed-by-ZIP, PDF-followed-by-ZIP, PE-overlay-followed-by-ZIP, and any other format whose parser stops at its own end marker.

### How do you identify a file whose extension lies?[#](#how-do-you-identify-a-file-whose-extension-lies)

`file(1)` reads magic bytes at the start of the file and reports the actual container format regardless of extension. JPEG’s magic is `FF D8 FF`, PNG’s is `89 50 4E 47`, ZIP’s is `50 4B 03 04`. Any triage on a suspicious-looking image (or any file whose extension seems too neat for the challenge) starts with `file(1)`, followed by an `xxd | head` and an `xxd | tail` to see the actual start-of-file and end-of-file bytes. Extension mismatches are common in forensics challenges and are frequent in real-world incidents (malware droppers hiding as images, exfil archives disguised as documents).

### What TronGrid endpoint follows a TRC-20 chain hop-by-hop?[#](#what-trongrid-endpoint-follows-a-trc-20-chain-hop-by-hop)

`/v1/accounts/{address}/transactions/trc20?contract_address={USDT_contract}&only_from=true` returns outgoing TRC-20 transfers of the specified contract for a given address, sorted by timestamp. Iterating hop-by-hop, at each address, take the outgoing transfer whose amount matches the incoming one (or the earliest one if the wallet is a collector that aggregates and forwards). For USDT on TRON, the contract is `TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t`. Amounts are stored in the smallest unit (`amount_str`) with 6 decimals for USDT, so `2700000000` = 2 700 USDT.

### Why is FUNNULL TECHNOLOGY INC on OFAC’s SDN list?[#](#why-is-funnull-technology-inc-on-ofacs-sdn-list)

Designated by OFAC on 2025-05-29 under the CYBER3 program as the CDN backbone behind tens of thousands of “pig-butchering” (romance-crypto-scam) domains. Funnull is a Filipino CDN operator that provided infrastructure for scam sites targeting Western victims. The SDN entry includes a Digital Currency Address (TRX) for `TNmRfnSUXZoWWzxcDDbf95eGQYXt1mJDt8`, which is exactly the recipient of hop 1 in the Follow The Layer trace. That immediate match on the first hop is the “smoking gun” that identifies the sanctioned entity.

### Why does the on-chain trace stop at Bitget 9?[#](#why-does-the-on-chain-trace-stop-at-bitget-9)

`TJ7hhYhVhaxNx6BPyq7yFpqZrQULL3JSdb` is tagged `Bitget 9` on Tronscan and has 20 002 234 transactions on it. Once the funds land there, they’re co-mingled with the entire exchange’s flow; the next outgoing USDT from that address is unrelated to the 5 222 USDT deposit and happens every few seconds. That’s the definition of “money stops being attributable.” The stopping rule for a public-blockchain trace is exactly this: land at a labelled exchange hot wallet with high throughput, and record the deposit receipt as the last attributable state. Continuing the trace past that point is meaningless because the outputs mix contributions from thousands of unrelated deposits.

### What’s the broader lesson from the LYKNCTF 2026 forensics track?[#](#whats-the-broader-lesson-from-the-lyknctf-2026-forensics-track)

Every file is layered, and every layer has semantic content. The triage discipline is to enumerate all layers first (chunks, blocks, metadata, tails), extract whatever each holds, then match the brief to the layer whose contents answer the specific question. Decoy layers are common; each one is a valid answer to a different question. Structural signals (length, period, missing markers, format mismatches, amount preservation) are the fastest disambiguators. And for on-chain traces, explicit stopping rules (labelled exchange, high transaction count, mixer signature) are what turn a trace into a report.

### Where can I find the solver scripts?[#](#where-can-i-find-the-solver-scripts)

Per-challenge READMEs, artifacts, and Python solvers are at [Abdelkad3r/LYKNCTF](https://github.com/Abdelkad3r/LYKNCTF). Each forensics challenge has a `solve.sh` wrapper and an `exploit.py` or `solve.py` that reproduces the flag from the handout files. Photograph’s solver is a 10-line known-plaintext XOR. WorldCup 1 uses Pillow + NumPy for the LSB extraction. WorldCup 2 is a one-liner with `unzip -p`. Follow The Layer uses the Python standard library plus three HTTP endpoints (TronGrid, Tronscan, Treasury OFAC XML) and prints the whole flag automatically after cross-checking every touched wallet against the SDN list.

## Closing notes[#](#closing-notes)

Four forensics challenges, four distinct primitives, and one recurring discipline: read every layer before committing to one. Photograph teaches the structural-signal read (49-byte ciphertext + `0x7e` pattern + known-plaintext attack). WorldCup 1 teaches metadata-first triage (three tEXt chunks name the primitive; the pixel LSB is the mechanical last step). WorldCup 2 teaches format-versus-extension discipline (`file(1)` before believing any container name; ZIP EOCD self-locates). Follow The Layer teaches the on-chain investigator’s workflow (identify chain, walk hops preferring amount matches, screen every wallet against OFAC directly, choose an explicit stopping rule at a labelled exchange).

For more forensics-adjacent content on this site, the paired [LYKNCTF web writeup](https://cybersecurityelite.com/ctf-writeups/lyknctf-2026-web-writeup/) covers a Legacy Profile Importer AES-CBC padding oracle that shares the “recognise the primitive from its structural signature” discipline. The [LYKNCTF crack writeup](https://cybersecurityelite.com/ctf-writeups/lyknctf-2026-crack-writeup/) walks the crypto-constant recognition pattern (`0x9E3779B9`, `0xD1B54A32D192ED03`) that applies equally to file-format analysis. The [LYKNCTF pwn writeup](https://cybersecurityelite.com/ctf-writeups/lyknctf-2026-pwn-writeup/) covers the paired binary exploitation track. The [SEKAI CTF 2026 master writeup](https://cybersecurityelite.com/ctf-writeups/sekai-ctf-2026-writeup/) walks an AI-gateway-log-replay stego challenge (`impossible stego`) that has a similar “the log format itself is the payload” structure. Full [CTF writeups index](https://cybersecurityelite.com/ctf-writeups/) for everything else.

### Join the CyberSecurity Elite newsletter

Weekly writeups, tools, and tactics — straight to your inbox. No spam, unsubscribe anytime.

Email address

Subscribe