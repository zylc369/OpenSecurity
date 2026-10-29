import fcntl
import array
import hashlib
import secrets
import os
import time

fd_read = 3
fd_write = 4

f_read = os.fdopen(fd_read, "r")
f_write = os.fdopen(fd_write, "w")


def get_num_bytes_in_pipe(fd):
    FIONREAD = 0x541B
    buf = array.array("i", [0])
    fcntl.ioctl(fd, FIONREAD, buf)
    return buf[0]


print("Let's go gambling!")


# ensure r1 has been committed
wait_start = time.time()
while get_num_bytes_in_pipe(fd_read) < 64:
    if time.time() > wait_start + 30:
        raise Exception("Timed out waiting for commitment")
    time.sleep(0.1)

# send r2
r2 = secrets.token_bytes(16)
f_write.write(r2.hex() + "\n")
f_write.flush()

# commit is 32 bytes, reveal is 32 bytes (16 byte r1 and 16 byte salt) -> 128 bytes hex
wait_start = time.time()
while get_num_bytes_in_pipe(fd_read) < 128:
    if time.time() > wait_start + 30:
        raise Exception("Timed out waiting for reveal")
    time.sleep(0.1)

data = bytes.fromhex(f_read.read(128))
if len(data) != 64:
    raise ValueError(f"Read invalid data (length of {data} is {len(data)}, not 64)")
commit, reveal = data[:32], data[32:]

# verify
if hashlib.sha256(reveal).digest() != commit:
    raise ValueError("Reveal does not match commitment")

r1 = reveal[:16]
r = int.from_bytes(r1) ^ int.from_bytes(r2)

print("Rolling a really big die...")
print(f"It landed on {r}.")

if r == 67:
    print(
        "Congratulations! You have been randomly selected for a spot prize. "
        "Just send us your credit card number and the 3 digits on the back to claim it.\n"
        + open("/flag").read()
    )
else:
    print("Aw dangit.")
