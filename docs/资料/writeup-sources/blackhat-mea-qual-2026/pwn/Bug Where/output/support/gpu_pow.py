import argparse
import hashlib
import time

import numpy as np
import pyopencl as cl


KERNEL = r"""
#define ROR(x, n) rotate((x), (uint)(32 - (n)))
#define CH(x, y, z) ((x & y) ^ (~x & z))
#define MAJ(x, y, z) ((x & y) ^ (x & z) ^ (y & z))
#define BSIG0(x) (ROR(x, 2) ^ ROR(x, 13) ^ ROR(x, 22))
#define BSIG1(x) (ROR(x, 6) ^ ROR(x, 11) ^ ROR(x, 25))
#define SSIG0(x) (ROR(x, 7) ^ ROR(x, 18) ^ (x >> 3))
#define SSIG1(x) (ROR(x, 17) ^ ROR(x, 19) ^ (x >> 10))

__constant uint K[64] = {
    0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U,
    0x3956c25bU, 0x59f111f1U, 0x923f82a4U, 0xab1c5ed5U,
    0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U,
    0x72be5d74U, 0x80deb1feU, 0x9bdc06a7U, 0xc19bf174U,
    0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU,
    0x2de92c6fU, 0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU,
    0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U,
    0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U,
    0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU, 0x53380d13U,
    0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U,
    0xa2bfe8a1U, 0xa81a664bU, 0xc24b8b70U, 0xc76c51a3U,
    0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U,
    0x19a4c116U, 0x1e376c08U, 0x2748774cU, 0x34b0bcb5U,
    0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
    0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U,
    0x90befffaU, 0xa4506cebU, 0xbef9a3f7U, 0xc67178f2U
};

__kernel void search_sha256_4(
    const uint base,
    const uint target0,
    const uint target1,
    volatile __global uint *found,
    __global uint *answer
) {
    uint value = base + (uint)get_global_id(0);
    uint w[64];
    w[0] = value;
    w[1] = 0x80000000U;
    for (int index = 2; index < 15; index++)
        w[index] = 0;
    w[15] = 32U;
    for (int index = 16; index < 64; index++)
        w[index] = SSIG1(w[index - 2]) + w[index - 7]
                 + SSIG0(w[index - 15]) + w[index - 16];

    uint a = 0x6a09e667U;
    uint b = 0xbb67ae85U;
    uint c = 0x3c6ef372U;
    uint d = 0xa54ff53aU;
    uint e = 0x510e527fU;
    uint f = 0x9b05688cU;
    uint g = 0x1f83d9abU;
    uint h = 0x5be0cd19U;
    for (int index = 0; index < 64; index++) {
        uint t1 = h + BSIG1(e) + CH(e, f, g) + K[index] + w[index];
        uint t2 = BSIG0(a) + MAJ(a, b, c);
        h = g;
        g = f;
        f = e;
        e = d + t1;
        d = c;
        c = b;
        b = a;
        a = t1 + t2;
    }
    a += 0x6a09e667U;
    b += 0xbb67ae85U;
    if (a == target0 && b == target1) {
        if (atomic_cmpxchg(found, 0U, 1U) == 0U)
            answer[0] = value;
    }
}
"""


def solve(target_hex: str, batch_bits: int = 24) -> bytes | None:
    target = bytes.fromhex(target_hex)
    if len(target) != 8:
        raise ValueError("target must be exactly eight bytes")

    devices = [
        device
        for platform in cl.get_platforms()
        for device in platform.get_devices(device_type=cl.device_type.GPU)
    ]
    if not devices:
        raise RuntimeError("no OpenCL GPU found")
    context = cl.Context([devices[0]])
    queue = cl.CommandQueue(context)
    program = cl.Program(context, KERNEL).build()

    flags = cl.mem_flags
    found_host = np.zeros(1, dtype=np.uint32)
    answer_host = np.zeros(1, dtype=np.uint32)
    found_buffer = cl.Buffer(context, flags.READ_WRITE | flags.COPY_HOST_PTR, hostbuf=found_host)
    answer_buffer = cl.Buffer(context, flags.READ_WRITE | flags.COPY_HOST_PTR, hostbuf=answer_host)
    target0 = np.uint32(int.from_bytes(target[:4], "big"))
    target1 = np.uint32(int.from_bytes(target[4:], "big"))
    batch_size = 1 << batch_bits
    started = time.monotonic()

    for base in range(0, 1 << 32, batch_size):
        program.search_sha256_4(
            queue,
            (batch_size,),
            None,
            np.uint32(base),
            target0,
            target1,
            found_buffer,
            answer_buffer,
        )
        cl.enqueue_copy(queue, found_host, found_buffer).wait()
        if found_host[0]:
            cl.enqueue_copy(queue, answer_host, answer_buffer).wait()
            answer = int(answer_host[0]).to_bytes(4, "big")
            if hashlib.sha256(answer).digest()[:8] != target:
                raise RuntimeError("GPU returned an invalid preimage")
            elapsed = time.monotonic() - started
            print(f"{answer.hex()} {elapsed:.3f}")
            return answer
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target")
    parser.add_argument("--batch-bits", type=int, default=24)
    args = parser.parse_args()
    answer = solve(args.target, args.batch_bits)
    return 0 if answer is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
