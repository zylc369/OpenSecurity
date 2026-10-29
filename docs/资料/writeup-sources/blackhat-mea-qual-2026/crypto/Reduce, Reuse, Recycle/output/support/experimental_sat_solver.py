#!/usr/bin/env python3
"""Solver for BlackHat MEA Qualification CTF 2026 - Reduce, Reuse, Recycle."""

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import socket
import sys
import time
from pathlib import Path

from Crypto.Cipher import AES
from pycryptosat import Solver as CryptoSolver
from pysat.solvers import Solver as PySatSolver


HOST = "tcp.flagyard.com"
PORT = 32205
FLAG_RE = re.compile(rb"BHFlagY\{[^}\r\n]+\}")
R = 0xE1000000000000000000000000000000
FIELD_ONE = 1 << 127
ZERO_BLOCK = bytes(16)
FIXED = b"|encrypted by "
PROBE_CHARS = ["B", "\\", "W", "\u036b", "\u97b1", "\U0005ef6e"]
PROBE = "".join(PROBE_CHARS)


def gf_mul(x: int, y: int) -> int:
    z = 0
    v = y
    for i in range(128):
        if x & (1 << (127 - i)):
            z ^= v
        v = (v >> 1) ^ (R if v & 1 else 0)
    return z


def gf_pow(x: int, exponent: int) -> int:
    result = FIELD_ONE
    while exponent:
        if exponent & 1:
            result = gf_mul(result, x)
        x = gf_mul(x, x)
        exponent >>= 1
    return result


def ghash_blocks(blocks: list[bytes], h: int) -> int:
    y = 0
    for block in blocks:
        if len(block) != 16:
            raise ValueError("GHASH blocks must be 16 bytes")
        y = gf_mul(y ^ int.from_bytes(block, "big"), h)
    return y


def padded_blocks(data: bytes) -> list[bytes]:
    padded = data + bytes((-len(data)) % 16)
    return [padded[i : i + 16] for i in range(0, len(padded), 16)]


def ghash_ciphertext_shape(data: bytes, h: int) -> int:
    length_block = (len(data) * 8).to_bytes(16, "big")
    return ghash_blocks(padded_blocks(data) + [length_block], h)


def project_high_nibbles(value: int) -> int:
    projected = 0
    for byte in value.to_bytes(16, "big"):
        projected = (projected << 4) | (byte >> 4)
    return projected


def high_nibble_text(tag: bytes) -> str:
    return "".join(f"{byte >> 4:x}" for byte in tag)


def low_nibble_text(tag: bytes) -> str:
    return "".join(f"{byte & 0xF:x}" for byte in tag)


def combine_nibbles(high: str, low: str) -> bytes:
    if len(high) != 16 or len(low) != 16:
        raise ValueError("expected 16 high and low tag nibbles")
    return bytes((int(a, 16) << 4) | int(b, 16) for a, b in zip(high, low))


def linear_preimage(columns: list[int], target: int) -> tuple[int, list[int]]:
    """Return one x with columns*x=target and a basis for the kernel."""
    basis: dict[int, tuple[int, int]] = {}
    kernel: list[int] = []
    for index, original in enumerate(columns):
        value = original
        combination = 1 << index
        while value:
            pivot = value.bit_length() - 1
            if pivot in basis:
                old_value, old_combination = basis[pivot]
                value ^= old_value
                combination ^= old_combination
            else:
                basis[pivot] = (value, combination)
                break
        if value == 0:
            kernel.append(combination)

    solution = 0
    remaining = target
    while remaining:
        pivot = remaining.bit_length() - 1
        if pivot not in basis:
            raise ValueError("linear system is inconsistent")
        value, combination = basis[pivot]
        remaining ^= value
        solution ^= combination
    return solution, kernel


def recover_h(high_tags: list[str]) -> int:
    ref = PROBE_CHARS[0].encode()
    if any(len(PROBE_CHARS[i].encode()) != 1 for i in (0, 1, 2)):
        raise AssertionError("first three probes must be one-byte UTF-8")
    deltas = []
    observations = []
    for index in (1, 2):
        raw = PROBE_CHARS[index].encode()
        block = bytes([ref[0] ^ raw[0]]) + bytes(15)
        deltas.append(int.from_bytes(block, "big"))
        observations.append(int(high_tags[0], 16) ^ int(high_tags[index], 16))

    columns = []
    for bit in range(128):
        v = 1 << bit
        columns.append(
            (project_high_nibbles(gf_mul(deltas[0], v)) << 64)
            | project_high_nibbles(gf_mul(deltas[1], v))
        )
    h4, kernel = linear_preimage(columns, (observations[0] << 64) | observations[1])
    if kernel:
        raise ValueError(f"probe matrix unexpectedly has nullity {len(kernel)}")

    # In GF(2^128), Frobenius x -> x^4 is bijective. Its inverse is x -> x^(2^126).
    h = gf_pow(h4, 1 << 126)
    if gf_pow(h, 4) != h4:
        raise ValueError("failed to take the fourth root in GF(2^128)")
    return h


def variable_byte(first_variable: int):
    return [(0, {first_variable + bit}) for bit in range(8)]


def constant_byte(value: int):
    return [((value >> bit) & 1, set()) for bit in range(8)]


def xor_byte(left, right):
    return [(a ^ b, variables_a ^ variables_b) for (a, variables_a), (b, variables_b) in zip(left, right)]


def symbolic_plaintext(prefix: bytes, key_hex):
    return [constant_byte(value) for value in prefix + FIXED] + list(key_hex)


def tag_difference_equations(short_prefix: bytes, long_prefix: bytes, key_hex, tail_stream, h: int):
    short = symbolic_plaintext(short_prefix, key_hex)
    long = symbolic_plaintext(long_prefix, key_hex)
    if len(long) != len(short) + 1:
        raise ValueError("the alignment pair must differ by exactly one byte")

    difference = [xor_byte(short[i], long[i]) for i in range(len(short))]
    difference.append(xor_byte(long[-1], tail_stream))
    difference.extend([constant_byte(0)] * ((-len(difference)) % 16))
    block_count = len(difference) // 16
    length_delta = (len(short) * 8) ^ (len(long) * 8)
    constant = gf_mul(length_delta, h)
    equations = [set() for _ in range(128)]

    for position, byte in enumerate(difference):
        block_index = position // 16
        h_power = gf_pow(h, block_count + 1 - block_index)
        byte_offset = position % 16
        for bit in range(8):
            bit_block = (1 << bit) << (8 * (15 - byte_offset))
            contribution = gf_mul(bit_block, h_power)
            constant_bit, variables = byte[bit]
            if constant_bit:
                constant ^= contribution
            output = contribution
            while output:
                output_bit = output.bit_length() - 1
                equations[output_bit].symmetric_difference_update(variables)
                output ^= 1 << output_bit
    return constant, equations


def constrain_high_nibbles(circuit, linear_form, observed: int) -> None:
    constant, equations = linear_form
    for index in range(16):
        for nibble_bit in range(4):
            output_bit = 124 - 8 * index + nibble_bit
            observed_bit = (observed >> (4 * (15 - index) + nibble_bit)) & 1
            wanted = observed_bit ^ ((constant >> output_bit) & 1)
            variables = sorted(equations[output_bit])
            if not variables:
                if wanted:
                    circuit.solver.add_clause([])
                continue
            value = circuit.xor(*variables) if len(variables) > 1 else variables[0]
            circuit.solver.add_clause([value if wanted else -value])


class SatCircuit:
    def __init__(self, solver, first_free_variable: int, native_xor: bool = True):
        self.solver = solver
        self.next_variable = first_free_variable
        self.native_xor = native_xor

    def new_variable(self) -> int:
        result = self.next_variable
        self.next_variable += 1
        return result

    def xor(self, *variables: int, constant: bool = False) -> int:
        if not variables:
            raise ValueError("xor gate needs at least one input")
        if self.native_xor and hasattr(self.solver, "add_xor_clause"):
            output = self.new_variable()
            self.solver.add_xor_clause([*variables, output], constant)
            return output

        def xor2(left: int, right: int) -> int:
            output = self.new_variable()
            self.solver.add_clause([-left, -right, -output])
            self.solver.add_clause([left, right, -output])
            self.solver.add_clause([left, -right, output])
            self.solver.add_clause([-left, right, output])
            return output

        current = variables[0]
        for variable in variables[1:]:
            current = xor2(current, variable)
        output = self.new_variable()
        if constant:
            self.solver.add_clause([current, output])
            self.solver.add_clause([-current, -output])
        else:
            self.solver.add_clause([-current, output])
            self.solver.add_clause([current, -output])
        return output

    def and_(self, left: int, right: int) -> int:
        output = self.new_variable()
        self.solver.add_clause([-left, -right, output])
        self.solver.add_clause([left, -output])
        self.solver.add_clause([right, -output])
        return output

    def sbox(self, q):
        """Boyar-Peralta bitsliced AES S-box; q is little-endian by bit."""
        x0, x1, x2, x3, x4, x5, x6, x7 = q[7], q[6], q[5], q[4], q[3], q[2], q[1], q[0]
        y14 = self.xor(x3, x5)
        y13 = self.xor(x0, x6)
        y9 = self.xor(x0, x3)
        y8 = self.xor(x0, x5)
        t0 = self.xor(x1, x2)
        y1 = self.xor(t0, x7)
        y4 = self.xor(y1, x3)
        y12 = self.xor(y13, y14)
        y2 = self.xor(y1, x0)
        y5 = self.xor(y1, x6)
        y3 = self.xor(y5, y8)
        t1 = self.xor(x4, y12)
        y15 = self.xor(t1, x5)
        y20 = self.xor(t1, x1)
        y6 = self.xor(y15, x7)
        y10 = self.xor(y15, t0)
        y11 = self.xor(y20, y9)
        y7 = self.xor(x7, y11)
        y17 = self.xor(y10, y11)
        y19 = self.xor(y10, y8)
        y16 = self.xor(t0, y11)
        y21 = self.xor(y13, y16)
        y18 = self.xor(x0, y16)

        t2 = self.and_(y12, y15)
        t3 = self.and_(y3, y6)
        t4 = self.xor(t3, t2)
        t5 = self.and_(y4, x7)
        t6 = self.xor(t5, t2)
        t7 = self.and_(y13, y16)
        t8 = self.and_(y5, y1)
        t9 = self.xor(t8, t7)
        t10 = self.and_(y2, y7)
        t11 = self.xor(t10, t7)
        t12 = self.and_(y9, y11)
        t13 = self.and_(y14, y17)
        t14 = self.xor(t13, t12)
        t15 = self.and_(y8, y10)
        t16 = self.xor(t15, t12)
        t17 = self.xor(t4, t14)
        t18 = self.xor(t6, t16)
        t19 = self.xor(t9, t14)
        t20 = self.xor(t11, t16)
        t21 = self.xor(t17, y20)
        t22 = self.xor(t18, y19)
        t23 = self.xor(t19, y21)
        t24 = self.xor(t20, y18)

        t25 = self.xor(t21, t22)
        t26 = self.and_(t21, t23)
        t27 = self.xor(t24, t26)
        t28 = self.and_(t25, t27)
        t29 = self.xor(t28, t22)
        t30 = self.xor(t23, t24)
        t31 = self.xor(t22, t26)
        t32 = self.and_(t31, t30)
        t33 = self.xor(t32, t24)
        t34 = self.xor(t23, t33)
        t35 = self.xor(t27, t33)
        t36 = self.and_(t24, t35)
        t37 = self.xor(t36, t34)
        t38 = self.xor(t27, t36)
        t39 = self.and_(t29, t38)
        t40 = self.xor(t25, t39)

        t41 = self.xor(t40, t37)
        t42 = self.xor(t29, t33)
        t43 = self.xor(t29, t40)
        t44 = self.xor(t33, t37)
        t45 = self.xor(t42, t41)
        z0 = self.and_(t44, y15)
        z1 = self.and_(t37, y6)
        z2 = self.and_(t33, x7)
        z3 = self.and_(t43, y16)
        z4 = self.and_(t40, y1)
        z5 = self.and_(t29, y7)
        z6 = self.and_(t42, y11)
        z7 = self.and_(t45, y17)
        z8 = self.and_(t41, y10)
        z9 = self.and_(t44, y12)
        z10 = self.and_(t37, y3)
        z11 = self.and_(t33, y4)
        z12 = self.and_(t43, y13)
        z13 = self.and_(t40, y5)
        z14 = self.and_(t29, y2)
        z15 = self.and_(t42, y9)
        z16 = self.and_(t45, y14)
        z17 = self.and_(t41, y8)

        t46 = self.xor(z15, z16)
        t47 = self.xor(z10, z11)
        t48 = self.xor(z5, z13)
        t49 = self.xor(z9, z10)
        t50 = self.xor(z2, z12)
        t51 = self.xor(z2, z5)
        t52 = self.xor(z7, z8)
        t53 = self.xor(z0, z3)
        t54 = self.xor(z6, z7)
        t55 = self.xor(z16, z17)
        t56 = self.xor(z12, t48)
        t57 = self.xor(t50, t53)
        t58 = self.xor(z4, t46)
        t59 = self.xor(z3, t54)
        t60 = self.xor(t46, t57)
        t61 = self.xor(z14, t57)
        t62 = self.xor(t52, t58)
        t63 = self.xor(t49, t58)
        t64 = self.xor(z4, t59)
        t65 = self.xor(t61, t62)
        t66 = self.xor(z1, t63)
        s0 = self.xor(t59, t63)
        s6 = self.xor(t56, t62, constant=True)
        s7 = self.xor(t48, t60, constant=True)
        t67 = self.xor(t64, t65)
        s3 = self.xor(t53, t66)
        s4 = self.xor(t51, t66)
        s5 = self.xor(t47, t65)
        s1 = self.xor(t64, s3, constant=True)
        s2 = self.xor(t55, t67, constant=True)
        return [s7, s6, s5, s4, s3, s2, s1, s0]


class XorDimacsRecorder:
    def __init__(self):
        self.clauses: list[list[int]] = []
        self.xors: list[tuple[list[int], bool]] = []
        self.max_variable = 0

    def add_clause(self, clause) -> None:
        clause = list(clause)
        self.clauses.append(clause)
        if clause:
            self.max_variable = max(self.max_variable, max(abs(value) for value in clause))

    def add_xor_clause(self, variables, rhs) -> None:
        variables = list(variables)
        if not variables:
            if rhs:
                self.add_clause([])
            return
        self.xors.append((variables, bool(rhs)))
        self.max_variable = max(self.max_variable, max(variables))

    def write(self, path: Path) -> None:
        lines = [f"p cnf {self.max_variable} {len(self.clauses) + len(self.xors)}"]
        lines.extend(" ".join(map(str, clause)) + " 0" for clause in self.clauses)
        for variables, rhs in self.xors:
            literals = variables if rhs else [-variables[0], *variables[1:]]
            lines.append("x" + " ".join(map(str, literals)) + " 0")
        path.write_text("\n".join(lines) + "\n", encoding="ascii")


def circuit_xor_byte(circuit: SatCircuit, left, right, constant: int = 0):
    return [
        circuit.xor(left[bit], right[bit], constant=bool(constant & (1 << bit)))
        for bit in range(8)
    ]


def circuit_xtime(circuit: SatCircuit, byte):
    return [
        byte[7],
        circuit.xor(byte[0], byte[7]),
        byte[1],
        circuit.xor(byte[2], byte[7]),
        circuit.xor(byte[3], byte[7]),
        byte[4],
        byte[5],
        byte[6],
    ]


def circuit_mix_column(circuit: SatCircuit, column):
    doubled = [circuit_xtime(circuit, byte) for byte in column]
    tripled = [circuit_xor_byte(circuit, doubled[i], column[i]) for i in range(4)]
    coefficients = [
        (doubled[0], tripled[1], column[2], column[3]),
        (column[0], doubled[1], tripled[2], column[3]),
        (column[0], column[1], doubled[2], tripled[3]),
        (tripled[0], column[1], column[2], doubled[3]),
    ]
    return [
        [circuit.xor(*(byte[bit] for byte in row)) for bit in range(8)]
        for row in coefficients
    ]


def circuit_aes_encrypt_zero(solver, key_bytes, first_free_variable: int):
    circuit = SatCircuit(solver, first_free_variable, native_xor=False)
    round_keys = [key_bytes]
    rcon = 1
    for _ in range(10):
        previous = round_keys[-1]
        temp = [circuit.sbox(previous[index]) for index in (13, 14, 15, 12)]
        temp[0] = [
            circuit.xor(temp[0][bit], constant=bool(rcon & (1 << bit)))
            for bit in range(8)
        ]
        current = []
        for word in range(4):
            source = temp if word == 0 else current[-4:]
            for offset in range(4):
                current.append(circuit_xor_byte(circuit, previous[4 * word + offset], source[offset]))
        round_keys.append(current)
        rcon = ((rcon << 1) ^ (0x11B if rcon & 0x80 else 0)) & 0xFF

    state = key_bytes  # AddRoundKey on an all-zero plaintext.
    for round_index in range(1, 11):
        state = [circuit.sbox(byte) for byte in state]
        state = [state[4 * ((column + row) % 4) + row] for column in range(4) for row in range(4)]
        if round_index != 10:
            mixed = []
            for column in range(4):
                mixed.extend(circuit_mix_column(circuit, state[4 * column : 4 * column + 4]))
            state = mixed
        state = [
            circuit_xor_byte(circuit, state[index], round_keys[round_index][index])
            for index in range(16)
        ]
    return state, circuit.next_variable


def recover_key(high_tags: list[str], h: int, progress: bool = False) -> tuple[bytes, int]:
    dump_path = os.environ.get("RRR_DUMP_XCNF")
    solver = XorDimacsRecorder() if dump_path else CryptoSolver(threads=1)
    circuit = SatCircuit(solver, 513)

    # Variables 1..512 are 32 groups of 16 one-hot nibble choices. This makes
    # both the lowercase ASCII representation and the raw AES key bits native
    # XORs, while the only nonlinear constraint is exactly-one per group.
    hex_vars = []
    for index in range(32):
        choices = list(range(1 + 16 * index, 17 + 16 * index))
        solver.add_clause(choices)
        for left in range(16):
            for right in range(left + 1, 16):
                solver.add_clause([-choices[left], -choices[right]])
        byte = []
        for bit in range(8):
            variables = {
                choices[nibble]
                for nibble in range(16)
                if ord(f"{nibble:x}") & (1 << bit)
            }
            byte.append((0, variables))
        hex_vars.append(byte)

    tail_47 = variable_byte(circuit.next_variable)
    circuit.next_variable += 8
    tail_49 = variable_byte(circuit.next_variable)
    circuit.next_variable += 8

    d12 = tag_difference_equations(PROBE_CHARS[0].encode(), PROBE_CHARS[3].encode(), hex_vars, tail_47, h)
    d34 = tag_difference_equations(PROBE_CHARS[4].encode(), PROBE_CHARS[5].encode(), hex_vars, tail_49, h)
    observed_12 = int(high_tags[0], 16) ^ int(high_tags[3], 16)
    observed_34 = int(high_tags[4], 16) ^ int(high_tags[5], 16)

    constrain_high_nibbles(circuit, d12, observed_12)
    constrain_high_nibbles(circuit, d34, observed_34)

    key_bytes = []
    for index in range(16):
        bits = []
        for nibble_index in (2 * index + 1, 2 * index):
            choices = list(range(1 + 16 * nibble_index, 17 + 16 * nibble_index))
            for bit in range(4):
                bits.append(circuit.xor(*[choices[value] for value in range(16) if value & (1 << bit)]))
        key_bytes.append(bits)

    encrypted_zero, _ = circuit_aes_encrypt_zero(solver, key_bytes, circuit.next_variable)
    expected_h = h.to_bytes(16, "big")
    started = time.monotonic()
    for index, expected_byte in enumerate(expected_h):
        for bit, variable in enumerate(encrypted_zero[index]):
            solver.add_clause([variable if expected_byte & (1 << bit) else -variable])

    if dump_path:
        solver.write(Path(dump_path))
        raise RuntimeError(f"wrote XCNF to {dump_path}")

    satisfiable, model = solver.solve()
    if not satisfiable:
        raise ValueError("the combined GHASH/AES key system is inconsistent")
    nibbles = []
    for index in range(32):
        choices = list(range(1 + 16 * index, 17 + 16 * index))
        selected = [value for value, variable in enumerate(choices) if model[variable]]
        if len(selected) != 1:
            raise ValueError(f"invalid one-hot model at nibble {index}")
        nibbles.append(selected[0])
    candidate = bytes((nibbles[index] << 4) | nibbles[index + 1] for index in range(0, 32, 2))
    if AES.new(candidate, AES.MODE_ECB).encrypt(ZERO_BLOCK) != expected_h:
        raise ValueError("SAT returned a key that does not encrypt zero to H")
    if progress:
        print(f"[.] stage 0 SAT solve completed in {time.monotonic() - started:.1f}s", flush=True)
    return candidate, 1


def recover_counter_and_nonce(key: bytes, h: int, full_tags: list[bytes]) -> tuple[bytes, bytes, int]:
    plaintexts = [ch.encode() + FIXED + key.hex().encode() for ch in PROBE_CHARS]
    representatives = [0, 3, 4, 5]  # UTF-8 lengths 1, 2, 3, 4
    lengths = [len(plaintexts[index]) for index in representatives]
    if lengths != [47, 48, 49, 50]:
        raise AssertionError(f"unexpected representative lengths: {lengths}")

    observations = []
    for index in representatives:
        observations.append(int.from_bytes(full_tags[index], "big") ^ ghash_ciphertext_shape(plaintexts[index], h))
    target = 0
    for value in observations:
        target = (target << 128) | value

    columns: list[int] = []
    # S = AES_K(J0) is XORed into every tag.
    for bit in range(128):
        value = 1 << bit
        columns.append((value << 384) | (value << 256) | (value << 128) | value)

    # Up to 50 bytes of reused CTR keystream are sufficient for all representatives.
    for position in range(50):
        for bit in range(8):
            outputs = []
            for length in lengths:
                if position >= length:
                    outputs.append(0)
                    continue
                stream = bytearray(length)
                stream[position] = 1 << bit
                data_blocks = padded_blocks(bytes(stream))
                outputs.append(ghash_blocks(data_blocks + [ZERO_BLOCK], h))
            combined = 0
            for value in outputs:
                combined = (combined << 128) | value
            columns.append(combined)

    solution, kernel = linear_preimage(columns, target)
    if len(kernel) > 24:
        raise ValueError(f"unexpectedly large stage-1 nullspace: {len(kernel)}")

    aes = AES.new(key, AES.MODE_ECB)
    tested = 0
    for selector in range(1 << len(kernel)):
        candidate = solution
        for index, vector in enumerate(kernel):
            if selector & (1 << index):
                candidate ^= vector
        tested += 1

        s = (candidate & ((1 << 128) - 1)).to_bytes(16, "big")
        stream = bytes((candidate >> (128 + 8 * position)) & 0xFF for position in range(50))
        j0 = aes.decrypt(s)
        prefix = j0[:12]
        counter = int.from_bytes(j0[12:], "big")
        expected_stream = b"".join(
            aes.encrypt(prefix + ((counter + step) & 0xFFFFFFFF).to_bytes(4, "big"))
            for step in range(1, 5)
        )[:50]
        if stream != expected_stream:
            continue

        h2 = gf_mul(h, h)
        nonce_length_block = (128).to_bytes(16, "big")
        numerator = int.from_bytes(j0, "big") ^ gf_mul(int.from_bytes(nonce_length_block, "big"), h)
        nonce_int = gf_mul(numerator, gf_pow(h2, (1 << 128) - 2))
        nonce = nonce_int.to_bytes(16, "big")

        # Final local confirmation against PyCryptodome's exact GCM implementation.
        for plaintext, tag in zip(plaintexts, full_tags):
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
            cipher.encrypt(plaintext)
            if cipher.digest() != tag:
                break
        else:
            return j0, nonce, tested
    raise ValueError(f"no counter state matched after testing {tested} affine candidates")


class Remote:
    def __init__(self, host: str, port: int):
        self.socket = socket.create_connection((host, port), timeout=15)
        self.socket.settimeout(30)
        self.file = self.socket.makefile("rwb", buffering=0)
        self.transcript = bytearray()

    def read_until(self, marker: bytes) -> bytes:
        data = bytearray()
        while marker not in data:
            chunk = self.socket.recv(4096)
            if not chunk:
                raise EOFError(f"connection closed before {marker!r}; got {bytes(data)!r}")
            data.extend(chunk)
        self.transcript.extend(data)
        return bytes(data)

    def send_line(self, data: bytes) -> None:
        self.file.write(data + b"\n")

    def close(self) -> None:
        self.file.close()
        self.socket.close()


def parse_tag_lines(data: bytes, prompt: bytes) -> list[str]:
    if not data.endswith(prompt):
        raise ValueError(f"missing prompt {prompt!r}")
    body = data[: -len(prompt)]
    lines = [line.decode("ascii") for line in body.splitlines() if line]
    if len(lines) != 6 or any(not re.fullmatch(r"[0-9a-f]{16}", line) for line in lines):
        raise ValueError(f"unexpected tag response: {data!r}")
    return lines


def run_remote(host: str, port: int, evidence_path: Path | None) -> bytes:
    remote = Remote(host, port)
    evidence: dict[str, object] = {
        "endpoint": f"{host}:{port}",
        "probe_codepoints": [f"U+{ord(ch):04X}" for ch in PROBE_CHARS],
        "probe_utf8": PROBE.encode().hex(),
    }
    try:
        remote.read_until(b"> ")
        remote.send_line(PROBE.encode())
        high_tags = parse_tag_lines(remote.read_until(b"keys[0]> "), b"keys[0]> ")
        print("[+] received stage-0 upper tag nibbles", flush=True)

        h = recover_h(high_tags)
        print(f"[+] recovered GHASH H = {h:032x}", flush=True)
        key, key_candidates = recover_key(high_tags, h, progress=True)
        print(f"[+] recovered key[0] after {key_candidates} candidates", flush=True)
        remote.send_line(key.hex().encode())

        remote.read_until(b"> ")
        remote.send_line(PROBE.encode())
        low_tags = parse_tag_lines(remote.read_until(b"keys[1]> "), b"keys[1]> ")
        full_tags = [combine_nibbles(high, low) for high, low in zip(high_tags, low_tags)]
        j0, nonce, nonce_candidates = recover_counter_and_nonce(key, h, full_tags)
        print(f"[+] recovered J0 = {j0.hex()}", flush=True)
        print(f"[+] recovered key[1] after {nonce_candidates} candidates", flush=True)
        remote.send_line(nonce.hex().encode())

        tail = remote.read_until(b"}")
        match = FLAG_RE.search(tail)
        if not match:
            raise ValueError(f"flag not found in final response: {tail!r}")
        flag = match.group(0)
        print(flag.decode(), flush=True)

        evidence.update(
            {
                "high_tags": high_tags,
                "low_tags": low_tags,
                "full_tags": [tag.hex() for tag in full_tags],
                "ghash_h": f"{h:032x}",
                "key_candidates_tested": key_candidates,
                "nonce_candidates_tested": nonce_candidates,
                "j0": j0.hex(),
                "flag": flag.decode(),
            }
        )
        if evidence_path is not None:
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        return flag
    finally:
        remote.close()


def simulate() -> tuple[list[str], list[str], bytes, bytes]:
    key = bytes.fromhex("00112233445566778899001122334455")
    nonce = bytes.fromhex("ffeeddccbbaa99887766554433221100")
    high_tags = []
    low_tags = []
    for ch in PROBE_CHARS:
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        cipher.encrypt(ch.encode() + FIXED + key.hex().encode())
        tag = cipher.digest()
        high_tags.append(high_nibble_text(tag))
        low_tags.append(low_nibble_text(tag))
    return high_tags, low_tags, key, nonce


def self_test() -> None:
    high_tags, low_tags, expected_key, expected_nonce = simulate()
    h = recover_h(high_tags)
    expected_h = int.from_bytes(AES.new(expected_key, AES.MODE_ECB).encrypt(ZERO_BLOCK), "big")
    if h != expected_h:
        raise AssertionError(f"H mismatch: {h:032x} != {expected_h:032x}")
    key, key_candidates = recover_key(high_tags, h, progress=True)
    if key != expected_key:
        raise AssertionError(f"key mismatch: {key.hex()} != {expected_key.hex()}")
    full_tags = [combine_nibbles(high, low) for high, low in zip(high_tags, low_tags)]
    _, nonce, nonce_candidates = recover_counter_and_nonce(key, h, full_tags)
    if nonce != expected_nonce:
        raise AssertionError(f"nonce mismatch: {nonce.hex()} != {expected_nonce.hex()}")
    print(f"self-test passed (key models={key_candidates}, nonce vectors={nonce_candidates})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        else:
            run_remote(args.host, args.port, args.evidence)
        return 0
    except Exception as exc:
        print(f"[-] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
