import hashlib
import secrets
import os

f_read = os.fdopen(3, "r")
f_write = os.fdopen(4, "w")

r1 = secrets.token_bytes(16)
salt = secrets.token_bytes(16)
commit = hashlib.sha256(r1 + salt).hexdigest()

# send commitment
f_write.write(commit)
f_write.flush()

# get r2
r2 = bytes.fromhex(f_read.readline().strip())

# send reveal
reveal = (r1 + salt).hex()
f_write.write(reveal + "\n")
f_write.flush()

# derive random number
r = int.from_bytes(r1) ^ int.from_bytes(r2)
print(f"Client: random number = {r}")
