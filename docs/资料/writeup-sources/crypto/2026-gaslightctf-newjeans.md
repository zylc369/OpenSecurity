---
来源: https://cyb3r-bo1.github.io/posts/gaslightCTF_2026_writeup/
类型: webfetch-markdown
获取日期: 2026-09-12
---

# gaslightCTF 2026 Writeup（crypto 部分提取：NEWJEANS IS FIVE）

> 站点 curl 下载失败（反爬），经 webfetch 获取，仅保留 crypto 挑战部分。

## NEWJEANS IS FIVE (100)

- Flag: `gaslightCTF{newj34ns-nv-d!es}`
- Root cause: `SubBytes()`/`SubWord()` are identity functions, so the AES-like cipher collapses to an affine function of the 128-bit key, solvable with linear algebra over GF(2)

### Approach

1. `chall.py` encrypts a known plaintext ("incomprehensible") and the flag with an AES-128-like construction, both ciphertexts dumped to `output.txt`. Comparing against real AES: `SubBytes()` and `SubWord()` just return their input unchanged; everything else (ShiftRows, MixColumns, AddRoundKey, key schedule) is untouched.
2. That removes the only non-linear piece of AES. XOR, ShiftRows, MixColumns, and key expansion are all linear over GF(2), so with fixed Rcon constants folded in, the whole cipher collapses to an affine function of the key for a fixed plaintext: `C(K) = A·K ⊕ b`.
3. Pulled `chall.py`'s own functions into the solver so the forward direction matches exactly, then:
   - Encrypt known plaintext under all-zero key → `b`.
   - Encrypt same plaintext under each of the 128 single-bit keys; XOR each result with `b` → 128 columns of `A`.
   - Solve `A·K = C_real ⊕ b` over GF(2) with Gaussian elimination → master key.
4. Regenerate round keys from recovered key, run cipher backwards on second ciphertext → flag.

### PoC（关键部分）

```python
def recover_key(plaintext, ciphertext):
    zero_key = "00" * 16
    base = bytes.fromhex(AES_128(plaintext, GenerateRoundKeys(KeyExpansion(zero_key))))
    target = bytes.fromhex(ciphertext)
    rhs = int.from_bytes(xor(target, base), "big")

    columns = []
    for bit in range(128):
        key = (1 << (127 - bit)).to_bytes(16, "big").hex()
        diff = xor(bytes.fromhex(AES_128(plaintext, GenerateRoundKeys(KeyExpansion(key)))), base)
        columns.append(int.from_bytes(diff, "big"))

    rows = []
    for out_bit in range(128):
        row = 0
        for in_bit in range(128):
            if (columns[in_bit] >> (127 - out_bit)) & 1:
                row |= 1 << (128 - in_bit)
        if (rhs >> (127 - out_bit)) & 1:
            row |= 1
        rows.append(row)

    # GF(2) Gaussian elimination
    pivot = 0
    for col in range(128):
        if pivot >= 128: break
        r = next((i for i in range(pivot, 128) if (rows[i] >> (128 - col)) & 1), None)
        if r is None: continue
        rows[pivot], rows[r] = rows[r], rows[pivot]
        for i in range(128):
            if i != pivot and ((rows[i] >> (128 - col)) & 1):
                rows[i] ^= rows[pivot]
        pivot += 1

    key_int = 0
    for r in range(128):
        if rows[r] & 1:
            key_int |= 1 << (127 - r)
    return key_int.to_bytes(16, "big").hex()

# [+] Master key: d58d0b337eecb2e23c11436c8b2dcde2
# [+] Flag: newj34ns-nv-d!es
```
