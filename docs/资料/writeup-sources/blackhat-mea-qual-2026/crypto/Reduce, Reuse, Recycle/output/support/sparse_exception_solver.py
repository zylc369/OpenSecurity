#!/usr/bin/env python3
"""Fast candidate recovery using the sparse 8/9 positions of hex ASCII.

For the five-bit (q0..q3, alpha) representation used by the tag equations,
q3 is one only for the hexadecimal symbols 8 and 9.  A random 32-nibble key
therefore has only four such positions on average.  Guessing those positions
turns 32 dense domain constraints into linear equations and leaves a tiny
affine space to check.
"""

from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

from Crypto.Cipher import AES

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import enumerate_key_candidates as enum
import experimental_sat_solver as rrr


VALID = frozenset(range(10)) | frozenset(range(17, 23))


def parity(value: int) -> int:
    return value.bit_count() & 1


def affine_solutions(rows: list[tuple[int, int]], variables: int) -> tuple[int, list[int]] | None:
    """Return one solution and a nullspace basis for parity(mask & x) == rhs."""
    packed = [mask | ((rhs & 1) << variables) for mask, rhs in rows]
    pivot_rows: dict[int, int] = {}
    row_index = 0
    for column in range(variables):
        pivot = next((i for i in range(row_index, len(packed)) if packed[i] & (1 << column)), None)
        if pivot is None:
            continue
        packed[row_index], packed[pivot] = packed[pivot], packed[row_index]
        value = packed[row_index]
        for i in range(len(packed)):
            if i != row_index and packed[i] & (1 << column):
                packed[i] ^= value
        pivot_rows[column] = row_index
        row_index += 1
    mask_all = (1 << variables) - 1
    if any((row & mask_all) == 0 and ((row >> variables) & 1) for row in packed):
        return None
    solution = 0
    for column, index in pivot_rows.items():
        if (packed[index] >> variables) & 1:
            solution |= 1 << column
    basis = []
    for free in range(variables):
        if free in pivot_rows:
            continue
        vector = 1 << free
        for column, index in pivot_rows.items():
            if packed[index] & (1 << free):
                vector |= 1 << column
        basis.append(vector)
    return solution, basis


def transform_model(solution: int, kernel: list[int]):
    # q3 at each character is bit 5*i+3 in the original affine assignment.
    q3_constant = sum(((solution >> (5 * char + 3)) & 1) << char for char in range(32))
    q3_columns = []
    for selector in range(len(kernel)):
        q3_columns.append(sum(((kernel[selector] >> (5 * char + 3)) & 1) << char for char in range(32)))
    zero_selectors, q_kernel = rrr.linear_preimage(q3_columns, q3_constant)
    if len(q_kernel) != len(kernel) - 32:
        raise AssertionError(f"q3 map is not full rank: nullity={len(q_kernel)}")
    responses = []
    for char in range(32):
        response, _ = rrr.linear_preimage(q3_columns, 1 << char)
        responses.append(response)

    def lift(selector_value: int) -> int:
        assignment = solution
        while selector_value:
            bit = (selector_value & -selector_value).bit_length() - 1
            assignment ^= kernel[bit]
            selector_value &= selector_value - 1
        return assignment

    base_assignment = lift(zero_selectors)
    response_assignments = [lift(zero_selectors ^ response) ^ base_assignment for response in responses]
    free_assignments = [lift(zero_selectors ^ vector) ^ base_assignment for vector in q_kernel]
    return base_assignment, response_assignments, free_assignments


def candidate_key(assignment: int) -> bytes | None:
    nibbles = []
    for char in range(32):
        encoded = (assignment >> (5 * char)) & 31
        if encoded not in VALID:
            return None
        q = encoded & 15
        alpha = encoded >> 4
        nibbles.append(q if alpha == 0 else q + 9)
    return bytes((nibbles[i] << 4) | nibbles[i + 1] for i in range(0, 32, 2))


def recover_from_reduced(solution: int, kernel: list[int], expected_h: bytes, progress: bool = True):
    base, responses, free_vectors = transform_model(solution, kernel)
    if len(free_vectors) != 16:
        raise AssertionError(f"expected 16 free bits after fixing q3, got {len(free_vectors)}")
    # Precompute how every original assignment bit depends on the 16 free bits.
    bit_forms = []
    for bit in range(160):
        bit_forms.append(sum(((vector >> bit) & 1) << index for index, vector in enumerate(free_vectors)))

    started = time.monotonic()
    patterns = 0
    affine_candidates = 0
    valid_candidates = 0
    for weight in range(33):
        if progress:
            print(f"[.] trying {weight} positions containing 8/9", flush=True)
        for exceptional in itertools.combinations(range(32), weight):
            patterns += 1
            assignment_base = base
            for char in exceptional:
                assignment_base ^= responses[char]
            # If q3=1, validity forces alpha=q2=q1=0. q0 selects 8 or 9.
            rows = []
            for char in exceptional:
                for offset in (4, 2, 1):
                    bit = 5 * char + offset
                    rows.append((bit_forms[bit], (assignment_base >> bit) & 1))
            reduced = affine_solutions(rows, 16)
            if reduced is None:
                continue
            free_solution, remaining = reduced
            assignment0 = assignment_base
            for index, vector in enumerate(free_vectors):
                if free_solution & (1 << index):
                    assignment0 ^= vector
            lifted_remaining = []
            for free_vector in remaining:
                value = 0
                for index, vector in enumerate(free_vectors):
                    if free_vector & (1 << index):
                        value ^= vector
                lifted_remaining.append(value)
            for selector in range(1 << len(lifted_remaining)):
                assignment = assignment0
                for index, vector in enumerate(lifted_remaining):
                    if selector & (1 << index):
                        assignment ^= vector
                affine_candidates += 1
                key = candidate_key(assignment)
                if key is None:
                    continue
                valid_candidates += 1
                if AES.new(key, AES.MODE_ECB).encrypt(bytes(16)) == expected_h:
                    return key, {
                        "weight": weight,
                        "patterns": patterns,
                        "affine_candidates": affine_candidates,
                        "valid_candidates": valid_candidates,
                        "elapsed": time.monotonic() - started,
                    }
        if progress:
            print(
                f"[.] through weight {weight}: patterns={patterns} valid={valid_candidates} "
                f"elapsed={time.monotonic()-started:.3f}s",
                flush=True,
            )
    raise ValueError("no candidate satisfies AES_K(0)=H")


def self_test() -> None:
    data = json.loads((HERE / "reduced-selftest.json").read_text())
    key, stats = recover_from_reduced(
        int(data["solution"], 16),
        [int(item, 16) for item in data["kernel"]],
        bytes.fromhex(data["H"]),
    )
    expected = bytes.fromhex(data["expected_key"])
    if key != expected:
        raise AssertionError(f"wrong key: {key.hex()} != {expected.hex()}")
    print(f"FOUND {key.hex()} {stats}")


if __name__ == "__main__":
    self_test()
