---
来源: https://www.zkdocs.com/docs/zkdocs/security-of-zkps/when-to-use-hvzk/
类型: html
获取日期: 2026-06-30
---

## Using HVZKP in the wrong context [#](#using-hvzkp-in-the-wrong-context)

Honest verifier zero-knowledge proofs (HVZKP) assume –yes, you guessed it– an honest verifier! This means that in the presence of malicious verifiers, non-interactive protocols should always be used. These also exchange fewer messages between prover and verifier.

A malicious verifier can employ different attacks depending on the proof system. Here, we will present attacks for the [Short factoring proofs](../../zero-knowledge-protocols/short-factoring-proofs) and the [Two prime divisors proof](../../zero-knowledge-protocols/product-primes/two-prime-divisors).

## The case of the Short-Factoring-Proofs [#](#the-case-of-the-short-factoring-proofs)

Recall that in [Short factoring proofs](../../zero-knowledge-protocols/short-factoring-proofs) the prover shows that they know $\varphi(\varN)$ in the style of [Girault’s scheme](../../zero-knowledge-protocols/girault-identification).
$$
\begin{array}{c}
\work{\varprover}{\varverifier}
\alicework{\sampleRange{\varr}{A}}
\alicework{\varx\_i = \varz\_i^\varr \mod \varN}
\alicework{\forb}
\alicebob{}{\bunch{\varx}}{}
\bobwork{\sampleRange{\vare}{B}}
\bobalice{}{\vare}{}
\alicework{\vary = \varr + (\varN - \varphi(\varN))\cdot \vare \in \naturals}
\alicebob{}{\vary}{}
\bobwork{\vary \inQ \range{A}}
\bobwork{\varx\_i \equalQ \varz\_i^{\vary- \vare\cdot\varN} \mod \varN \forb}
\end{array}
$$

After the initial commit, the verifier responds with a challenge $e$ supposedly sampled from $\range{B}$. However, being malicious, the verifier chooses $\vare=A$, the maximum value that $\varr$ can be. So, that after receiving $\vary = \varr + (\varN - \varphi(\varN))\cdot \vare$, they can compute $\varN - \vary//\vare$ which will reveal $\varphi(\varN)$.

## The case of the Two-Prime-Divisor proof [#](#the-case-of-the-two-prime-divisor-proof)

In the [Two prime divisors proof](../../zero-knowledge-protocols/product-primes/two-prime-divisors), the prover has no way of checking if the verifier is trying to attack them. Recall the beginning of the protocol that the verifier chooses $\rhovar\_i$ values:
$$
\begin{array}{c}
\work{\varprover}{\varverifier}
\bobwork{\sampleSet{\rhovar\_i}{J\_\varN}, \text{ for }i=1,\ldots,m}
\bobalice{}{\{\rhovar\_i\}\_{i=1}^m}{}
\alicework{\sigmavar\_i = \begin{cases}
\sqrt{\rhovar\_i} \mod \varN &\text{ if }\rhovar\_i \in QR\_\varN \\
0 &\text{ otherwise}
\end{cases}
}
\alicework{\text{ for }i=1,\ldots,m}
\alicebob{}{\{\sigmavar\_i\}\_{i=1}^m}{}
\end{array}
$$

Then, the verifier computes the square-roots of these values! It is known that factoring and computing modular square-roots are equivalent [[HOC](https://cacr.uwaterloo.ca/hac/) - Fact 3.46].

An attacker can:

* select random numbers $r\_i$
* send their square $r^2\_i \mod \varN$ to the prover,

The prover will compute their square roots, $\sigma\_i$ which can be different than $\pm \varr\_i$ since there are four different square-roots modulo $\varN = p q$. When $\sigma\_i\neq \pm \varr\_i$, computing $\gcd (\varN, \sigma\_i - r\_i)$ will reveal one of the factors of $\varN$. This is because

$\begin{align\*}
\sigma\_i^2 &\equiv r\_i^2 \mod \varN \\
(\sigma\_i^2 - r\_i^2) &\equiv 0 \mod \varN \\
(\sigma\_i - r\_i)(\sigma\_i + r\_i) &\equiv 0 \mod \varN
\end{align\*}$

## References [#](#references)

* [HOC] [Handbook of Applied Cryptography](https://cacr.uwaterloo.ca/hac/ "Menezes, A. J., Van Oorschot, P. C., & Vanstone, S. A. (2018). Handbook of Applied Cryptography. CRC press.") (2018).

* [GG21] [UC non-interactive, proactive, threshold ECDSA with identifiable aborts](https://eprint.iacr.org/2021/060.pdf "Canetti, R., Gennaro, R., Goldfeder, S., Makriyannis, N., & Peled, U. (2020, October). UC non-interactive, proactive, threshold ECDSA with identifiable aborts. In Proceedings of the 2020 ACM SIGSAC Conference on Computer and Communications Security (pp. 1769-1787).") (2020).