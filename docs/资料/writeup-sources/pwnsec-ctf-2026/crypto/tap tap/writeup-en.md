# tap tap

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | crypto |
| Difficulty | not provided |
| Flag format | `pwnsec{...}` |

The challenge leaks the top 80 bits of 180 consecutive states from an order-25 Fibonacci recurrence over a 128-bit prime field. The decisive observation is that the modulus is very close to `2^128`, so short annihilating polynomials remain visible as short lattice vectors even after truncation. Recovering the modulus and taps reduces the hidden 48-bit state parts to a BDD/CVP problem, after which the SHAKE-256 key can be regenerated.

## Environment and Initial Analysis

The official input is [public.zip](../challenge/public.zip), protected with the password `infected`, and its inner [chall.py](../challenge/chall.py). Their SHA-256 hashes are `e1f54c52394d42987246afa0dacdfd771e09a8552e6480631244437b819f639c` and `21ad8088a41b9b4d03a0ff7cbeac79ec98eebbef12de0ab2b9f5e24ce31dd247`. The shared environment is restored from [requirements.txt](../../../requirements.txt); the solver uses the pinned `python-flint==0.8.0` and `mpmath==1.3.0` packages.

`chall.py` chooses a prime of the form `p = 2^128 - d`, where `2^48 <= d <= 2^50`. After sampling random taps `C[0..24]` and initial states `A[0..24]`, it performs 180 steps of

```text
A[i+25] = sum(C[j] * A[i+j] for j=0..24) mod p
```

The public values are `Y_i = A[25+i] >> 48`. The encryption key hashes the base-10 concatenation of all 205 states with SHA-256, then expands it with SHAKE-256. There is no remote endpoint, so no `instance.json` is needed.

## Core Analysis

Write every state as `A_i = 2^48 Y_i + Z_i`, with `0 <= Z_i < 2^48`. For a short length-90 annihilating vector `eta`, `sum(eta_i Y_{i+j}) mod 2^80` is also small over 90 sliding windows. Because `2^128-p` can be 4 times the hidden range, the coefficient coordinates were scaled by 64 to balance them against the residue coordinates. BKZ-35 reduction of the 180-dimensional basis exposed independent degree-89 annihilating polynomials.

The resultant of two such polynomials contains `p^25`, where 25 is the minimal recurrence degree. GCDs across independent resultants recovered

```text
p = 340282366920938463463374127620052448857
2^128 - p = 479811715762599
```

Reducing the polynomials in `F_p[x]` and taking their GCD produced the degree-25 characteristic polynomial. Negating its coefficients from degrees 0 through 24 yielded the taps `C`. The detailed equations and verification values are preserved in [derivation.md](../analysis/derivation.md).

Once the taps are known, every later state is a linear combination `q_j` of the first 25 leaked states. Centering the low parts with `Z_i = W_i + 2^47` gives `q_j W - t_j = W_j (mod p)`, where every unknown and residual has magnitude below `2^47`. Fifty future equations produce the 75-dimensional BDD lattice

```text
[ I_25   Q ]
[  0    pI_50 ]
```

LLL followed by Babai nearest-plane recovered the first 25 low parts. Regenerating the recurrence matched all 180 leaked high parts exactly. Finally, `C[0]^-1 mod p` stepped backward 25 times to recover the original `A[0..204]` sequence.

## Solution and Reproduction

[solve.py](../solve.py) contains the recovered `p` and taps, reads `Y` and the ciphertext from the official `chall.py`, and constructs the 75-dimensional state lattice. A single run performs LLL, Babai CVP, verification against all 180 outputs, 25 backward steps, and SHA-256/SHAKE-256 decryption. Activate the competition `.venv` and run from the challenge root.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

## Result

`python solve.py` exited with code 0 and empty stderr, and stdout contained only the following flag bytes. The recovered recurrence matched every one of the 180 public truncated outputs, and stdout was byte-for-byte identical to the `flag` file.

```text
pwnsec{wR17in6_17_t0oK_m3_thRe3__d4y5_d1d_4I_50lv3_i7_1n_thRe3_53c0nDs??}
```

## Takeaways

An unknown-modulus truncated Fibonacci generator remains vulnerable when its modulus lies close to a power of two, because annihilating relations survive as short lattice vectors. This instance required coordinate scaling to account for the actual bound on `2^128-p`; the later state BDD had a much larger distance gap than modulus and tap recovery. Regenerating every public output simultaneously ruled out lattice false positives and tap-orientation mistakes.

## References

- [Lattice Attacks on Truncated Fibonacci LFSRs](https://hackmd.io/@at20n0118/BkxzTRLgGg): basis for the unknown-modulus annihilating lattice, resultant modulus recovery, and state-recovery construction.
- [Reconstructing Truncated Integer Variables Satisfying Linear Congruences](https://epubs.siam.org/doi/10.1137/0217016): theoretical background for lattice recovery of truncated modular states.
- `python-flint 0.8.0`: used for integer LLL and finite-field polynomial GCD computations.
