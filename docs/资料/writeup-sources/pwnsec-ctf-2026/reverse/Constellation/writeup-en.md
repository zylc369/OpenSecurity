# Constellation

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | reverse |
| Difficulty | Hard |
| Flag format | `pwnsec{...}` |

The container used by `main.exe` is a systematic Reed–Solomon-like format with 224 data shards and 32 parity shards. Although `flag.flag` has 32 erased shards per block, the internal materialization archive can be recovered by solving GF(256) systems and reversing a separate shard permutation. The remaining steps reorder and decrypt the archive records, recover a filesystem image, and reproduce the hash computed by its embedded `flag.py`.

## Environment and Initial Analysis

The official inputs are [`main.exe`](../challenge/main.exe) and [`flag.flag`](../challenge/flag.flag). `main.exe` is 497,097,807 bytes with SHA-256 `50f9c357eef50db9af6ac3df48af617595274c1b7794b73cc256dee5cad547c7`. `flag.flag` is 196,776 bytes with SHA-256 `8cd10a5e403850465568f79a01c8d49450c26e511e0dfca2e47f2012cf478a1b`.

The analysis used Python 3 and IDA Professional 9.4 on Windows x64. The shared environment is restored from [`../../../requirements.txt`](../../../requirements.txt). The program accepted input and output paths through a GUI and packed the input into a new container. The PE had about 496 MB of high-entropy overlay data, so ordinary string searches did not expose the transformation logic.

## Core Analysis

IDA identified `sub_1400383A0` as the container builder and `sub_140032020` as a comparator that sorts shard IDs using 32-bit keys from the plan. The container header is `<9I`; its observed parameters were magic `0xe70b1591`, width `192`, 224 data shards, 32 parity shards, seed `0xc1028a4d`, and 4 blocks. It is followed by 33 bytes per block in the form `count || erased_indices[32]`, then 256 permuted shards per block.

The GF(256) field uses primitive polynomial `0x11d`. The coefficient at parity row `p` and data column `d` is:

```text
M[p,d] = (p + 1)^d in GF(256)
```

The 256 sorting keys for each block were captured from the materialization plan while the program ran and compressed into [`solve.py`](../solve.py). The logical shard ID at physical position `j` is `sorted(range(256), key=(order_key[id], id))[j]`. Treating the permutation as the identity failed to produce an internal magic. Reversing it yielded the first bytes `11 50 9d 02`, matching archive magic `0x029d5011` observed in `sub_1400352C0`. Missing data shards were recovered by removing known-data terms from surviving parity equations and applying Gaussian elimination over GF(256).

The decoded stream uses entry magic `0xf12c04a7`; every entry stores `path_len`, `record_len`, path, and record. Each record was `8 + 128 + 5 = 141` bytes. The lower 16 bits of its second dword encode the original chunk number as:

```text
chunk_index = (record_word_1 & 0xffff) XOR 0x06d0
```

The 471 chunks covered `0..470` exactly once. After ordering the payloads, the solver XORs a `mix32` keystream. Its initial transformed seed is `mix32(0x5e17e11d XOR 0x50524144)`, and each dword state is updated as `mix32(output_offset + state + 0x6d2b79f5)`. This produced a 60,288-byte filesystem archive with SHA-256 `e9cbf4038148531e1d0b2acb0071b868d1fa41427b2420fbaf55dab89a0d7456`.

The filesystem archive contains 139 entries: 42 directories and 97 files. Its embedded `flag.py` excludes itself, sorts entries by path, and hashes `D || u32(name_len) || name` for directories or `F || u32(name_len) || name || u64(body_len) || body` for files with SHA3-512.

## Solution and Reproduction

[`solve.py`](../solve.py) performs container parsing, inverse shard permutation, GF(256) erasure recovery, record reordering, XOR-stream decryption, and filesystem hashing in one run. Activate the competition `.venv` and run it from the challenge root.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

The solver writes the recovered filesystem archive to [`../output/recovered.bin`](../output/recovered.bin) and emits only the flag bytes, without a newline, on stdout.

## Result

`python solve.py` completed with exit code `0`, 0 bytes on stderr, and 136 bytes on stdout. Its stdout matched [`../flag`](../flag) byte for byte.

```text
pwnsec{c0d3ebc92d57e1db301dbf8a6a9595b3e003078fc977c204ab6ff6372353a6da60a423b3d9b57fd1c7618b976df1500f2d3b137d9b5e57e92909a140ae6ee99f}
```

## Takeaways

Correct Reed–Solomon recovery is insufficient when the shard storage permutation is still wrong. Here, the known archive magic provided a strong independent check for both permutation and field arithmetic. Comparing a known input with a container repacked by the program also validated the record-index relation and XOR keystream without requiring a complete interpretation of the large VM.

## References

No external references were used. The algorithms and constants came from static analysis of the supplied binary, local execution observations, and comparisons between generated containers and the official input.
