# waf analysis notes

- Official archive SHA-256: `acd080fc17a9fed49881335933a528423dca7efc414e0dfafcd9527ef4566b50`
- `chal` SHA-256: `5e0712c1b21a83adfc4a6f761455a141956be4f209e74981b76c445e29c4d0ec`
- ELF: amd64, dynamically linked, not stripped, no PIE, NX, no stack canary, Partial RELRO; GNU properties advertise IBT and SHSTK.
- Relevant symbols: `__gets` at `0x4011f6`, `main` at `0x4012a2`, `printf@plt` at `0x4010d0`, and `puts@got` at `0x404020`.
- The 80-byte `main` buffer is passed to `__gets`, whose first `read` accepts 128 bytes. The return address begins at offset 88.
- After every `read`, `__gets` scans only the returned byte count. At the first NUL it clears the remainder of that count, not the full requested length or previous buffer suffix.
- A 128-byte NUL-free baseline followed by synchronized short reads can therefore install required NUL bytes from the largest offset down to the smallest without erasing the suffix.
- Stage 1 uses `printf("exitLEAK%6$sEND\\n", ..., puts@got)` and returns to `main`, yielding the resolved `puts` pointer.
- The pinned `debian:13.4-slim` amd64 image manifest is `sha256:5fb70129351edec3723d13f427400ecae3f13b83750e23ad47c46721effcf2db`; its layer digest is `sha256:5435b2dcdf5cb7faa0d5b1d4d54be2c72a776fab9a605336f5067d6e9ecb5976`.
- Extracted glibc SHA-256: `adeedbc69ac402b762a3bd94759441e0546c33972cb2c0f5bc6869a2d32efed6`.
- glibc offsets: `puts = 0x805a0`, `system = 0x53110`, `"/bin/sh" = 0x1a5ea4`, `pop rdi; ret = 0x2a145`.
- Stage 2 runs `system("/bin/sh")`, then sends `cat /flag` and extracts the `K17{...}` response.
