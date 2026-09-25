# skill issue '@'aelmo

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | crypto |
| Difficulty | Hard |
| Flag format | `pwnsec{...}` |

The service hides a 2048-bit prime `p` and three small 16×16 integer matrices, stacks them into a 48×48 upper-triangular block matrix `x`, and publishes only `f(x) mod p`. The decisive observation is that `x` commutes with `f(x)`. Eliminating the hidden modular quotients between two commutation equations exposes the first block through LLL; the modulus and the remaining blocks then follow sequentially.

## Environment and Initial Analysis

The official inputs are [`public.zip`](../challenge/public.zip) and its [`chall.py`](../challenge/chall.py). Their SHA-256 hashes are `a1c1b741d0df527a6cfc4fd35af0f98267b5aaba58702382b8e431ebdd4abd44` and `84758908e6a037b7a1af18fd6ee5820f4cbe5f7720b964188d558022da9637d1`, respectively. The remote TLS endpoint is recorded only in [`instance.json`](../instance.json).

The shared environment is restored from [`requirements.txt`](../../../requirements.txt). The non-standard packages directly needed by this solve are `python-flint==0.8.0`, `sympy==1.14.0`, and `mpmath==1.3.0`. The service returns `seed`, `flag_len=24`, and a 48×48 matrix `cap`. Its diagonal block `Y`, first superblock `Z`, and second superblock `W` repeat, while every lower block is zero.

## Core Analysis

Write `A=x0`, `B=x1`, and `C=x2`:

```text
x   = [[A, B, C], [0, A, B], [0, 0, A]]
cap = [[Y, Z, W], [0, Y, Z], [0, 0, Y]] = f(x) mod p
```

First, `AY=YA mod p`. For each `(i,j)`,

```text
t[i,j] p = A[i]·Y^T[j] - Y[i]·A^T[j]
```

Cross-multiplying two equations that share a row or column removes `p`. The result has a short integer kernel vector whose coefficients contain `t·A`. [`solve.py`](../solve.py) reduces the 48-dimensional lattice `[I | u]` with `python-flint` LLL and reconstructs every column of `A`. Dividing by the public `mix()` coefficient `1+d_i-d_j` must yield bytes, which fixes the sign and scale of each LLL candidate.

Commutation cannot distinguish scalar matrices, so a common shift remains on the diagonal. With the recovered off-diagonal matrix denoted by `A'`,

```text
[A,Y]i,j = [A',Y]i,j + (A[i,i]-A[j,j])Y[i,j] = 0 mod p.
```

The solver enumerates diagonal differences in `[-255,255]` for two entries and takes GCDs, producing the 2048-bit prime `p`. A third entry removes any small cofactor, after which primality is checked. Modular division recovers every diagonal difference, and evaluating `f(A)=Y` selects the correct value from the 12 possible common shifts.

The other two blocks follow from linearized commutation equations:

```text
YB - BY = AZ - ZA
YC - CY = AW - WA + BZ - ZB
```

Each Sylvester equation has rank 240 in the 240 off-diagonal unknowns when its 16 diagonal entries are treated as parameters. After solving this affine system, the requirement that every entry divided by its `mix()` coefficient is a byte becomes a 24-sample LWE/CVP instance. A 40-dimensional embedding is LLL-reduced and Babai nearest-plane recovers the diagonal bytes. The remaining common scalar shift is fixed with the Fréchet derivative `f'(A)` and the public block `Z` or `W`. Each recovered block is checked against the complete corresponding public block.

Finally, the seed places the 24-byte `sealed` value at offset 59 of `C`. Serializing the recovered `p` exactly as the challenge does regenerates the SHA-512 mask; XOR recovers the flag.

## Solution and Reproduction

Remote parsing, LLL recovery, modulus recovery, both Sylvester/CVP stages, and mask decryption are integrated into [`solve.py`](../solve.py). Activate the competition `.venv` and run from the challenge root:

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

The solver reads the `main` TLS endpoint from [`instance.json`](../instance.json). On success it writes only the flag bytes, without a trailing newline.

## Result

`python solve.py` exited with code 0, left stderr empty, and produced the following 24 bytes, which were matched byte-for-byte against the `flag` file:

```text
pwnsec{6a9c2ea004a8dee0}
```

## Takeaways

Even a large matrix exponent modulo an omitted prime leaks its small base matrix through the linear relation `M·f(M)=f(M)·M`. The block extension yields sequential Sylvester equations rather than a new nonlinear problem, and each 16-dimensional kernel can be removed by interpreting the byte bounds as a small-error LWE instance. The final common scalar ambiguity must be resolved and verified with the original polynomial or its Fréchet derivative.

## References

- [HITCON CTF 2025 MRSA write-up](https://rechn0.github.io/2025/08/25/2025-hitconctf/): the two-equation commutation and LLL technique for recovering a small matrix under an omitted modulus.
- [fplll README](https://github.com/fplll/fplll): LLL and CVP/Babai lattice conventions. The final solver uses `python-flint` LLL and an in-file Babai implementation from the same lattice formulation.
