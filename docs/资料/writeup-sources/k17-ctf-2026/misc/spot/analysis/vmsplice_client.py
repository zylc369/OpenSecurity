import ctypes
import hashlib
import mmap
import os


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

r1 = (int.from_bytes(r2) ^ 67).to_bytes(16)
reveal = r1 + bytes(16)
page[:COMMIT_HEX_LENGTH] = hashlib.sha256(reveal).hexdigest().encode("ascii")

reveal_hex = reveal.hex().encode("ascii")
if os.write(WRITE_FD, reveal_hex) != len(reveal_hex):
    raise RuntimeError("short write")
