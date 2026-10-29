#!/usr/bin/env python3
import argparse
import json
import re
import socket
import subprocess
import sys
from pathlib import Path


PROBES = [
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 2, 3, 2, 3, 1, 1, 3, 3, 3],
    [2, 2, 2, 3, 1, 2, 2, 2, 2, 2, 1],
    [2, 2, 2, 3, 1, 2, 1, 3, 3, 3, 2],
    [2, 3, 2, 2, 1, 3, 2, 2, 3, 1, 2],
    [2, 2, 3, 3, 3, 1, 2, 2, 2, 2, 1],
    [2, 2, 3, 1, 3, 2, 1, 2, 2, 1, 3],
    [2, 3, 2, 1, 1, 1, 2, 3, 3, 2, 3],
]
FLAG_PATTERN = re.compile(rb"BHFlagY\{[^\r\n}]+\}")


def receive_until(sock, marker, timeout):
    sock.settimeout(timeout)
    data = bytearray()
    while marker not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise EOFError(f"connection closed before {marker!r}")
        data.extend(chunk)
    return bytes(data)


def collect_outputs(sock):
    receive_until(sock, b"> ", 90)
    outputs = []
    for probe in PROBES:
        sock.sendall((",".join(map(str, probe)) + "\n").encode())
        response = receive_until(sock, b"> ", 30)
        payload = response[: response.rfind(b"> ")].strip()
        line = payload.splitlines()[-1]
        outputs.append(int(line))
    return outputs


def recover_polynomial(outputs, challenge_dir):
    recovery_script = (
        challenge_dir / "output" / "support" / "recover.sage"
    ).read_bytes()
    command = [
        "docker",
        "run",
        "--rm",
        "-i",
        "-e",
        "HOKAN_OUTPUTS=" + ",".join(map(str, outputs)),
        "--entrypoint",
        "bash",
        "sagemath/sagemath:latest",
        "-lc",
        "sage /dev/stdin",
    ]
    result = subprocess.run(
        command,
        input=recovery_script,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=240,
        check=False,
    )
    transcript = result.stdout.decode(errors="replace")
    for line in transcript.splitlines():
        if line.startswith("RESULT_JSON="):
            return json.loads(line.removeprefix("RESULT_JSON="))
    raise RuntimeError(transcript.strip() or f"Sage exited with status {result.returncode}")


def receive_to_close(sock, timeout=15):
    sock.settimeout(timeout)
    data = bytearray()
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data.extend(chunk)
    except TimeoutError:
        pass
    return bytes(data)


def main():
    challenge_dir = Path(__file__).resolve().parent
    instance = json.loads(
        (challenge_dir / "instance.json").read_text(encoding="utf-8")
    )
    endpoint = next(item for item in instance["endpoints"] if item["name"] == "main")
    parser = argparse.ArgumentParser(description="Solve the Hokan sparse-interpolation oracle")
    parser.add_argument("--host", default=endpoint["host"])
    parser.add_argument("--port", type=int, default=endpoint["port"])
    parser.add_argument("--attempts", type=int, default=20)
    args = parser.parse_args()
    if args.attempts < 1:
        parser.error("--attempts must be positive")

    for attempt in range(1, args.attempts + 1):
        try:
            with socket.create_connection((args.host, args.port), timeout=10) as sock:
                outputs = collect_outputs(sock)
                recovered = recover_polynomial(outputs, challenge_dir)
                polynomial = recovered["polynomial"]
                sock.sendall(polynomial.encode() + b"\n")
                response = receive_to_close(sock)
                match = FLAG_PATTERN.search(response)
                if not match:
                    raise RuntimeError("the recovered polynomial was not accepted")
                sys.stdout.buffer.write(match.group())
                return 0
        except (OSError, EOFError, RuntimeError, subprocess.TimeoutExpired, ValueError) as error:
            last_error = error
    print(f"error: exhausted all attempts: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
