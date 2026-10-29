#!/usr/bin/env python3
"""End-to-end live exploit for Reduce, Reuse, Recycle."""

from __future__ import annotations

import json
import queue
import re
import socket
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import enumerate_key_candidates as enum
import experimental_sat_solver as rrr
import recover_live_nonce as nonce_solver
import sparse_exception_solver as sparse


def connect_any() -> tuple[rrr.Remote, str]:
    addresses = sorted({item[4][0] for item in socket.getaddrinfo(rrr.HOST, rrr.PORT, socket.AF_INET, socket.SOCK_STREAM)})
    found: queue.Queue[tuple[socket.socket, str, bytes]] = queue.Queue()
    sockets: list[socket.socket] = []
    lock = threading.Lock()
    finished = threading.Event()

    def worker(address: str) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        with lock:
            sockets.append(sock)
        try:
            sock.settimeout(12)
            sock.connect((address, rrr.PORT))
            data = bytearray()
            while b"> " not in data and len(data) < 4096 and not finished.is_set():
                chunk = sock.recv(4096)
                if not chunk:
                    return
                data.extend(chunk)
            if b"> " in data and not finished.is_set():
                found.put((sock, address, bytes(data)))
                return
        except OSError:
            pass
        if not finished.is_set():
            try:
                sock.close()
            except OSError:
                pass

    for address in addresses:
        threading.Thread(target=worker, args=(address,), daemon=True).start()
    try:
        sock, address, banner = found.get(timeout=15)
    except queue.Empty as exc:
        finished.set()
        with lock:
            for item in sockets:
                try:
                    item.close()
                except OSError:
                    pass
        raise TimeoutError(f"none of the endpoint backends responded: {addresses}") from exc
    finished.set()
    with lock:
        for item in sockets:
            if item is not sock:
                try:
                    item.close()
                except OSError:
                    pass
    sock.settimeout(30)
    remote = object.__new__(rrr.Remote)
    remote.socket = sock
    remote.file = sock.makefile("rwb", buffering=0)
    remote.transcript = bytearray(banner)
    print(f"[+] connected backend {address}", flush=True)
    return remote, address


def main() -> None:
    if len(sys.argv) == 1 or sys.argv[1] == "auto":
        remote, host = connect_any()
        have_prompt = True
    else:
        host = sys.argv[1]
        remote = rrr.Remote(host, rrr.PORT)
        have_prompt = False
    evidence = {"endpoint": f"{host}:{rrr.PORT}", "probe_utf8": rrr.PROBE.encode().hex()}
    try:
        if not have_prompt:
            remote.read_until(b"> ")
        remote.send_line(rrr.PROBE.encode())
        high = rrr.parse_tag_lines(remote.read_until(b"keys[0]> "), b"keys[0]> ")
        h = rrr.recover_h(high)
        columns, target = enum.projected_system(high, h)
        solution, kernel = rrr.linear_preimage(columns, target)
        key, key_stats = sparse.recover_from_reduced(solution, kernel, h.to_bytes(16, "big"))
        print(f"[+] key[0]={key.hex()} ({key_stats['elapsed']:.3f}s)", flush=True)
        remote.send_line(key.hex().encode())

        remote.read_until(b"> ")
        remote.send_line(rrr.PROBE.encode())
        low = rrr.parse_tag_lines(remote.read_until(b"keys[1]> "), b"keys[1]> ")
        full = [rrr.combine_nibbles(a, b) for a, b in zip(high, low)]
        nonce, j0, _ = nonce_solver.recover_nonce(key, h, full)
        print(f"[+] key[1]={nonce.hex()}", flush=True)
        remote.send_line(nonce.hex().encode())

        tail = remote.read_until(b"}")
        match = re.search(rb"BHFlagY\{[^}\r\n]+\}", tail)
        if not match:
            raise ValueError(f"flag missing from final response: {tail!r}")
        flag = match.group(0).decode()
        print(flag, flush=True)
        evidence.update({
            "high": high,
            "low": low,
            "full": [tag.hex() for tag in full],
            "H": f"{h:032x}",
            "key0": key.hex(),
            "key1": nonce.hex(),
            "J0": j0.hex(),
            "key_stats": key_stats,
            "flag": flag,
        })
        (HERE / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="ascii")
    finally:
        remote.close()


if __name__ == "__main__":
    main()
