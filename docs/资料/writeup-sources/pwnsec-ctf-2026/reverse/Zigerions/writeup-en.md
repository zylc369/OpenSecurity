# Zigerions

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | reverse |
| Difficulty | Hard |
| Flag format | `psctf{...}` |

The Linux ELF inside the encrypted ZIP contains a Windows PyInstaller executable, which in turn produces a VMProtect PE, a Game Boy ROM, and a disguised ELF. The decisive observation was that the unreachable opcode table in the Game Boy ROM is not the final payload: a separate ELF resource in the unpacked VMProtect process contains both the AES key and ciphertext.

## Environment and Initial Analysis

The official input is [`public.zip`](../challenge/public.zip), using the page-provided password `infected`. Its SHA-256 is `39f883b263363a25d52f2227dca764bacf4fa5f4c534baab0d1701a232ebae83`. The enclosed [`Pickle_Riiiiick`](../challenge/Pickle_Riiiiick) is a 43,434,736-byte static x86-64 ELF. The shared environment is restored from [`requirements.txt`](../../../requirements.txt); the main packages used directly by the final solver are `pyzipper 0.3.6`, `frida 17.18.0`, and `pycryptodomex 3.23.0`.

The ELF `main` writes an embedded PE to `$HOME/.cache/.icons/.hidden/update.exe`. That PE is a Python 3.10 PyInstaller stub. After the `<<<PAYLOAD_START>>>` marker, it stores a length followed by an obfuscated PE. Static strings and Python bytecode establish the inverse operation:

```text
payload_length = LE32(data_after_marker[0:4]) = 0x555000
decoded = reverse(scrambled[i] XOR [a5, 3c, ff, 00, 55, aa][i mod 6])
```

The recovered [`final.exe`](../output/final.exe) is 5,591,040 bytes with SHA-256 `89a4f03151228ced4fbaf0ec4ff89bbf7895e25e67d55b8331e2e0543d3c8de7`. Its `.vmp0`/`.vmp1` sections and abnormal entry point identify VMProtect protection.

## Core Analysis

I spawned `final.exe` under Frida and hooked `ShellExecuteA` before execution resumed. Its argument was `%TEMP%\AURA.gb`. The resulting 32 KiB Game Boy ROM has SHA-256 `3141a477c0f440248e71146b2c6f4c582ef0a3a8db30a797df27d272e6812071`. After five stages, the ROM displays `YOU GOT A / LITTLE GIFT ;)`. The gift routine at `0x15f2` calls `0x0af2`, which immediately returns; 140 virtual-opcode metadata records follow that `RET`. This table is a decoy designed to resemble another analysis layer.

At the same point, the unpacked main module exposes its real `.data`. The ROM begins at `base+0x4000`, its `0x8000` length is at `base+0xc000`, another ELF starts at `base+0xc020`, and its `0x15f8` length is stored at `base+0xd618`. The solver replaces `ShellExecuteA` with the success value `33`, preventing GUI execution, and reads those 5,624 bytes. The result is [`hidden-elf`](../output/hidden-elf), with SHA-256 `eaccb6522ec941e1a00ad6360c26888de73da7316892e50b4ab752c81dc9e107`.

This ELF is a disguised data container without executable code. The first 16 bytes of `.rodata` at file offset `0x1000` are the ASCII key `M68K_AES_FLAGKEY`; AES Rcon, S-box, and inverse S-box tables follow it. The 48-byte `.data` section at file offset `0x1220` is the ciphertext. AES-128-ECB decryption produces a final block ending in nine `0x09` bytes, establishing PKCS#7 padding.

```text
AES-128-ECB(key = "M68K_AES_FLAGKEY")
ciphertext = 674e0e339bc75891878e9418bb3fb91a
             f8fa389587016dfbe91db26b39b41c51
             bc8a191fbdc5ad5fb30b22aa6c0d35b3
```

## Solution and Reproduction

[`solve.py`](../solve.py) opens the ZIP in memory and applies the marker-based XOR and reversal. It writes the recovered PE to `output/final.exe`, spawns it through Frida, and replaces `ShellExecuteA` and the message-box APIs so no external GUI opens. At the unpack-complete point, it retrieves the ELF from the fixed RVAs, parses the ELF64 section headers directly, performs AES-ECB decryption, and removes PKCS#7 padding. Activate the competition `.venv` and run from the challenge root.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

The solver is independent of the current working directory. On success, stdout contains only the 39 flag bytes with no trailing newline.

## Result

The actual `python solve.py` run exited with code `0`, emitted zero bytes on stderr, and emitted 39 bytes on stdout. Its stdout matched the challenge-root `flag` file byte for byte.

```text
psctf{U_sh0u1dvebeen_@_g@m3r_0rHighIQ!}
```

## Takeaways

File-format markers do not establish the real execution architecture. This challenge layers ELF, PyInstaller, VMProtect, Game Boy, and another ELF to keep analysis focused on the current apparent format. Capturing the unpacked module immediately before its final action was shorter and more reproducible than defeating the entire protector. Comparing the elaborate ROM metadata with PE-level evidence for a separate resource also made it possible to classify the opcode table as a decoy.

## References

No external references contributed to the final solve. All file formats, offsets, transforms, keys, and ciphertext were derived from the supplied artifacts and isolated local runtime observation.
