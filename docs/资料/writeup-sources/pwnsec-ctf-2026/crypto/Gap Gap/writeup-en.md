# Gap Gap

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | crypto |
| Difficulty | Medium |
| Flag format | `pwnsec{...}` |

The challenge combines Common Prime RSA, where `p-1` and `q-1` share a large prime `g`, with a 30-digit hole in the middle of the 124-digit private exponent `d`. The decisive observation is that a linear expression in the missing block is divisible by `g`, while `N+1-(p+q)=phi(N)` is divisible by `g^2`. A simultaneous modular lattice recovers both small roots, after which a continued fraction reveals `2g` and the RSA factors.

## Environment and Initial Analysis

The official attachment contains [`chall.py`](../challenge/chall.py), [`output.txt`](../challenge/output.txt), and the encrypted original [`public.zip`](../challenge/public.zip). The live service instance is preserved verbatim as [`remote-output.txt`](../challenge/remote-output.txt). The shared competition environment is restored from [`../../../requirements.txt`](../../../requirements.txt). The solver uses LLL from `python-flint==0.8.0` and polynomial gcds from `sympy==1.14.0`.

`chall.py` generates the following relations:

```text
p = 2*g*a + 1
q = 2*g*b + 1
lambda = lcm(p-1, q-1) = 2*g*a*b
e*d - 1 = k*lambda
```

`d_leak` exposes a 47-digit prefix and 47-digit suffix, replacing the middle 30 digits with `*`. The remote TLS endpoint is stored in [`../instance.json`](../instance.json). The static attachment output encrypts a sample string, so the submission flag was recovered from the live service output. Deterministic reproduction uses the captured `remote-output.txt`; `GAP_GAP_REMOTE=1` reads a fresh instance, while `GAP_GAP_SAMPLE=1` checks the attachment sample separately.

## Core Analysis

Set `G=2g` and `A=ed-1`, so that `A=kGab`. Reducing this value modulo each RSA prime gives:

```text
A + b*k = b*k*p ≡ 0 (mod p)
A + a*k = a*k*q ≡ 0 (mod q)
```

Write the private exponent as `d=D0+10^47*x`, where `0<=x<10^30`. Although the factor `g` of `N-1` is unknown, the following two linear polynomials have simultaneous small roots:

```text
f1(x) = x + a1 ≡ 0 (mod g)
f2(y) = y + N + 1 ≡ 0 (mod g^2),  y = -(p+q)
```

The second congruence follows from `N+1-p-q=(p-1)(q-1)=4g^2ab`. Assigning weights 1 and 2 to `f1` and `f2` makes each selected shift `f1^i f2^j (N-1)^r` vanish modulo `g^t`. At `t=3`, these shifts form a 27-dimensional integer lattice. Pairwise gcds of the LLL-reduced polynomials expose the linear factor:

```text
x - 629965031111793143531495543250
```

Substituting this block into the leak reconstructs a `d` satisfying `2^(ed-1) mod N = 1`. The second gap uses the generation constraint `h=p*b+a=lambda+a+b`:

```text
N - 1 = G*h
G*(e*d-1) - k*(N-1) = -G*k*(a+b)
```

The right-hand side is small relative to the leading products, and `gcd(k,G)=1`, so `k/G` appears as a continued-fraction convergent of `(ed-1)/(N-1)`. After recovering the 601-bit denominator `G`, compute `lambda=(ed-1)/k`, `a+b=h-lambda`, and `ab=lambda/G`. The discriminant `(a+b)^2-4ab` is a square, yielding `a,b`, then `p=Ga+1`, `q=Gb+1`, with `pq=N`. The complete derivation is preserved in [`../analysis/derivation.md`](../analysis/derivation.md).

## Solution and Reproduction

The final [`../solve.py`](../solve.py) integrates input parsing, the simultaneous modular lattice, missing-digit recovery, continued-fraction factorization, and RSA decryption. Activate the competition `.venv` and run from the challenge root:

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

To solve a fresh remote instance, set `GAP_GAP_REMOTE=1` and run the same command. Remote key generation can take about two minutes.

## Result

`python solve.py` exited with code 0, left stderr empty, and emitted a 24-byte stdout with no trailing newline. Those bytes match [`../flag`](../flag); the recovered factors satisfy `p*q=N`, and re-encrypting the plaintext reproduces `c`.

```text
pwnsec{a037f98cd3e49a5f}
```

## Takeaways

For Common Prime RSA, tracking powers of the shared factor is more useful than applying only the usual `ed-k*phi(N)=1` equation. Combining a modulo-`g` relation from `ed-1` with a modulo-`g^2` relation from `phi(N)` turns an internal MSB/LSB gap into a low-dimensional lattice problem. Once `d` is complete, the extra relation `N-1=2g*h` converts the remaining small-error approximation into a continued-fraction recovery of the shared factor.

## References

- [M. Zheng and A. Nitaj, Partial Key Exposure Attack on Common Prime RSA](https://eprint.iacr.org/2024/061.pdf): basis for the simultaneous modular polynomial and MSB/LSB exposure attack.
- [MengceZheng/PKEA_CPRSA](https://github.com/MengceZheng/PKEA_CPRSA): author implementation used to cross-check weighted shifts and lattice parameters.
- Official [`chall.py`](../challenge/chall.py): authoritative source for the generation relations and bit/decimal bounds.
