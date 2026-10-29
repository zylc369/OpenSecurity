# spot

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | K17 CTF 2026 / noCTF |
| Category | misc |
| Difficulty | hard |
| Flag format | `K17{...}` |

The honest protocol commits the client to `r1`, reveals the server's `r2`, and XORs both values, so an ordinary client cannot choose the result `67` after the reveal. The decisive observation is that the server only checks the pipe's byte count with `FIONREAD`; it does not read the 64-byte commitment before disclosing `r2`. A `vmsplice` pipe buffer backed by a mutable user page lets the client change the unconsumed commitment after seeing `r2`.

## Environment and Initial Analysis

The official input is [handout.zip](../challenge/handout.zip). The analysis covered [main.py](../challenge/spot/src/main.py), [client.py](../challenge/spot/src/client.py), [runner.c](../challenge/spot/src/runner.c), and the [Dockerfile](../challenge/spot/Dockerfile) inside it. The original ZIP has SHA-256 `24f5202474305bf872b6f370df4e7e3ba8b0d7fec63b87223a4a5572fe7b9e44`.

`runner` connects privileged `main.py` and a user-selected Python client with two pipes. The client-to-server direction is fd 4, while the server-to-client direction is fd 3. The server receives a 32-byte commitment and a 32-byte reveal as hex, for a final input of 128 ASCII bytes. The shared environment is restored from [requirements.txt](../../../requirements.txt); the solve used Python 3.12.10 and Paramiko 5.0.0. The supplied Dockerfile declares the remote image `python:3.14.4-slim-trixie`.

## Core Analysis

`main.py` performs these operations in order:

1. Wait until `FIONREAD` on fd 3 is at least 64.
2. Generate `r2` with `secrets.token_bytes(16)` and send it to the client.
3. Wait until `FIONREAD` on fd 3 is at least 128.
4. Only then call `f_read.read(128)` to consume `commit || reveal`.
5. Check `SHA256(reveal) == commit`, then print the flag when `int(r1) XOR int(r2) == 67`.

Step 1 observes only the amount of queued data; it does not consume the commitment. [vmsplice_client.py](../analysis/vmsplice_client.py) inserts the first 64 bytes from a page-aligned `MAP_SHARED` page with `vmsplice(fd=4)`. While that pipe buffer remains unconsumed, changing the source page changes the bytes that the server later reads.

After receiving `r2`, the client computes:

```text
r1 = int(r2, big-endian) XOR 67
salt = 00 * 16
reveal = r1 || salt
commit = SHA256(reveal)
```

It overwrites the previously spliced page with `commit.hex()` and appends the 64 bytes of `reveal.hex()` with a normal `write`. The complete 128-byte server read now contains a matching commitment and reveal, while the XOR is guaranteed to be `67`. A modified local runner on WSL2 Linux 6.18.33.2 and Python 3.12.3 printed `It landed on 67.`. The supporting transcript is preserved in [evidence.md](../analysis/evidence.md).

## Solution and Reproduction

[solve.py](../solve.py) reads the SSH endpoint from [instance.json](../instance.json) and obtains the password only from the `SPOT_SSH_PASSWORD` environment variable. It uploads the temporary client to `/tmp` with Paramiko, invokes `/home/ctf/runner`, and removes the temporary file. It validates the flag in the remote output and writes only the flag bytes to stdout.

Activate the competition `.venv` and run from the challenge root:

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
export SPOT_SSH_PASSWORD='<instance password>'
python solve.py
```

In PowerShell, replace the third line with `$env:SPOT_SSH_PASSWORD = '<instance password>'`. When the instance changes, update only `instance.json`.

## Result

The remote `python solve.py` run returned exit code 0, empty stderr, and a 49-byte stdout with no trailing newline. That exact stdout was piped into the canonical flag writer and matched [flag](../flag) byte for byte.

```text
K17{n3verm1nd_we're_br0ke_hav3_t#is_fl@g_in$tead}
```

## Takeaways

The cryptographic binding of a commit-reveal protocol matters only after the server has consumed the commitment or copied it into immutable storage. `FIONREAD` guarantees neither message boundaries nor data immutability. APIs such as `vmsplice`, which can leave a pipe buffer backed by user pages, invalidate an application's assumption that queued data has already been fixed. The server should read exactly 64 commitment bytes into a separate immutable `bytes` object before generating `r2`.

## References

- Supplied [main.py](../challenge/spot/src/main.py): commitment length check, `r2` disclosure, and final verification order.
- Supplied [runner.c](../challenge/spot/src/runner.c): fd 3/4 pipe layout and user-client execution.
- Supplied [Dockerfile](../challenge/spot/Dockerfile): remote privilege model and Python image version.
- No external references were used; the `vmsplice` hypothesis was verified against the supplied code and local and remote runtime evidence.
