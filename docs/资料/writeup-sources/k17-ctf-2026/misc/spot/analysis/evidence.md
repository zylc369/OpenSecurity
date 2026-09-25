# spot analysis evidence

## Supplied artifact

- `challenge/handout.zip` SHA-256: `24f5202474305bf872b6f370df4e7e3ba8b0d7fec63b87223a4a5572fe7b9e44`
- The archive contains `spot/Dockerfile`, the Python protocol implementation, the sample client, and the setuid runner source and ELF.

## Root cause

`main.py` waits for `FIONREAD >= 64`, generates and sends `r2`, and only later calls `f_read.read(128)`. The first 64 bytes have therefore been counted but not consumed when `r2` is disclosed.

On Linux, the custom client places those first 64 bytes into the pipe with `vmsplice`, backed by a writable `MAP_SHARED` page. After receiving `r2`, it chooses

```text
r1 = int(r2, big-endian) XOR 67
salt = 16 zero bytes
commit = SHA256(r1 || salt)
```

and overwrites the still-unconsumed page with `commit.hex()`. It then writes `(r1 || salt).hex()` as the remaining 64 bytes. The server reads a valid commitment and reveal, while its final XOR is forced to `67`.

## Local reproduction

The supplied runner source was copied to `runner_local.c` only to replace its absolute Python paths for WSL. Running it with `vmsplice_client.py` produced:

```text
Let's go gambling!
Rolling a really big die...
It landed on 67.
```

The subsequent local `FileNotFoundError` was expected because the local harness did not create `/flag`. The remote `solve.py` run exited with status 0 and returned one 49-byte `K17{...}` value; that exact stdout was piped into the solver skill's `write_flag.py` and recorded in `../flag` without a trailing newline.
