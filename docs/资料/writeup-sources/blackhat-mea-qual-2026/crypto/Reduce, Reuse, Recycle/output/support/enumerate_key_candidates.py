#!/usr/bin/env python3
"""Benchmark reduced tag-only key enumeration (analysis artifact)."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

from Crypto.Cipher import AES
from pycryptosat import Solver
from pysat.solvers import Solver as PySatSolver


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("rrr_experimental", HERE / "experimental_sat_solver.py")
assert SPEC and SPEC.loader
rrr = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = rrr
SPEC.loader.exec_module(rrr)


def hex_symbol(index: int):
    """ASCII hex byte as affine bits q[0:4], alpha."""
    q = [5 * index + bit for bit in range(4)]
    alpha = 5 * index + 4
    return [
        (0, {q[0]}), (0, {q[1]}), (0, {q[2]}), (0, {q[3]}),
        (1, {alpha}), (1, set()), (0, {alpha}), (0, set()),
    ]


def tail_symbol(first: int):
    return [(0, {first + bit}) for bit in range(8)]


def projected_system(high_tags: list[str], h: int):
    hex_vars = [hex_symbol(index) for index in range(32)]
    pairs = [(0, 3), (4, 5)]
    forms = [
        rrr.tag_difference_equations(
            rrr.PROBE_CHARS[left].encode(),
            rrr.PROBE_CHARS[right].encode(),
            hex_vars,
            tail_symbol(160 + 8 * pair_index),
            h,
        )
        for pair_index, (left, right) in enumerate(pairs)
    ]
    observed = [int(high_tags[left], 16) ^ int(high_tags[right], 16) for left, right in pairs]
    columns = [0] * 176
    target = 0
    row = 0
    for (constant, equations), projected in zip(forms, observed):
        for byte_index in range(16):
            for nibble_bit in range(4):
                output_bit = 124 - 8 * byte_index + nibble_bit
                projected_bit = 4 * (15 - byte_index) + nibble_bit
                rhs = ((projected >> projected_bit) & 1) ^ ((constant >> output_bit) & 1)
                if rhs:
                    target |= 1 << row
                for variable in equations[output_bit]:
                    columns[variable] |= 1 << row
                row += 1
    assert row == 128
    return columns, target


def assignment_for(key: bytes, stream: bytes) -> int:
    value = 0
    for index, char in enumerate(key.hex()):
        nibble = int(char, 16)
        if nibble <= 9:
            q, alpha = nibble, 0
        else:
            q, alpha = nibble - 9, 1
        value |= q << (5 * index)
        value |= alpha << (5 * index + 4)
    value |= stream[47] << 160
    value |= stream[49] << 168
    return value


def apply_columns(columns: list[int], assignment: int) -> int:
    output = 0
    while assignment:
        bit = (assignment & -assignment).bit_length() - 1
        output ^= columns[bit]
        assignment &= assignment - 1
    return output


def build_reduced_solver(solution: int, kernel: list[int]):
    solver = Solver(threads=16)
    selectors = list(range(1, len(kernel) + 1))
    originals = []
    next_variable = len(selectors) + 1
    for original_bit in range(160):
        auxiliary = next_variable
        next_variable += 1
        originals.append(auxiliary)
        expression = [selectors[index] for index, vector in enumerate(kernel) if vector & (1 << original_bit)]
        solver.add_xor_clause([auxiliary, *expression], bool(solution & (1 << original_bit)))

    for index in range(32):
        bits = originals[5 * index : 5 * index + 5]
        for alpha in range(2):
            for q in range(16):
                valid = (alpha == 0 and q <= 9) or (alpha == 1 and 1 <= q <= 6)
                if valid:
                    continue
                encoded = q | (alpha << 4)
                solver.add_clause([
                    -variable if encoded & (1 << bit) else variable
                    for bit, variable in enumerate(bits)
                ])
    return solver, selectors, originals, next_variable


def dump_reduced_xcnf(solution: int, kernel: list[int], path: Path):
    solver = rrr.XorDimacsRecorder()
    selectors = list(range(1, len(kernel) + 1))
    originals = []
    next_variable = len(selectors) + 1
    for original_bit in range(160):
        auxiliary = next_variable
        next_variable += 1
        originals.append(auxiliary)
        expression = [selectors[index] for index, vector in enumerate(kernel) if vector & (1 << original_bit)]
        solver.add_xor_clause([auxiliary, *expression], bool(solution & (1 << original_bit)))
    for index in range(32):
        bits = originals[5 * index : 5 * index + 5]
        for alpha in range(2):
            for q in range(16):
                valid = (alpha == 0 and q <= 9) or (alpha == 1 and 1 <= q <= 6)
                if valid:
                    continue
                encoded = q | (alpha << 4)
                solver.add_clause([
                    -variable if encoded & (1 << bit) else variable
                    for bit, variable in enumerate(bits)
                ])
    solver.write(path)
    return selectors, originals


def invalid_hex_anf_masks() -> list[int]:
    values = []
    for encoded in range(32):
        q = encoded & 15
        alpha = encoded >> 4
        valid = (alpha == 0 and q <= 9) or (alpha == 1 and 1 <= q <= 6)
        values.append(int(not valid))
    for bit in range(5):
        for mask in range(32):
            if mask & (1 << bit):
                values[mask] ^= values[mask ^ (1 << bit)]
    return [mask for mask, coefficient in enumerate(values) if coefficient]


def dump_anf(columns: list[int], target: int, path: Path) -> None:
    lines = []
    for row in range(128):
        terms = [f"x({variable})" for variable, column in enumerate(columns) if column & (1 << row)]
        if target & (1 << row):
            terms.append("1")
        lines.append(" + ".join(terms) if terms else "0")
    for char_index in range(32):
        terms = []
        for mask in invalid_hex_anf_masks():
            if mask == 0:
                terms.append("1")
            else:
                terms.append("*".join(
                    f"x({5 * char_index + bit})" for bit in range(5) if mask & (1 << bit)
                ))
        lines.append(" + ".join(terms))
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def build_reduced_pysat(solution: int, kernel: list[int]):
    solver = PySatSolver(name="cadical195")
    selectors = list(range(1, len(kernel) + 1))
    circuit = rrr.SatCircuit(solver, len(selectors) + 1, native_xor=False)
    originals = []
    for original_bit in range(160):
        auxiliary = circuit.new_variable()
        originals.append(auxiliary)
        expression = [selectors[index] for index, vector in enumerate(kernel) if vector & (1 << original_bit)]
        value = circuit.xor(*expression, constant=bool(solution & (1 << original_bit)))
        solver.add_clause([-auxiliary, value])
        solver.add_clause([auxiliary, -value])
    for index in range(32):
        bits = originals[5 * index : 5 * index + 5]
        for alpha in range(2):
            for q in range(16):
                valid = (alpha == 0 and q <= 9) or (alpha == 1 and 1 <= q <= 6)
                if valid:
                    continue
                encoded = q | (alpha << 4)
                solver.add_clause([
                    -variable if encoded & (1 << bit) else variable
                    for bit, variable in enumerate(bits)
                ])
    return solver, selectors, originals


def dump_reduced_cnf(solution: int, kernel: list[int], path: Path) -> None:
    solver = rrr.XorDimacsRecorder()
    selectors = list(range(1, len(kernel) + 1))
    circuit = rrr.SatCircuit(solver, len(selectors) + 1, native_xor=False)
    originals = []
    for original_bit in range(160):
        auxiliary = circuit.new_variable()
        originals.append(auxiliary)
        expression = [selectors[index] for index, vector in enumerate(kernel) if vector & (1 << original_bit)]
        value = circuit.xor(*expression, constant=bool(solution & (1 << original_bit)))
        solver.add_clause([-auxiliary, value])
        solver.add_clause([auxiliary, -value])
    for index in range(32):
        bits = originals[5 * index : 5 * index + 5]
        for alpha in range(2):
            for q in range(16):
                valid = (alpha == 0 and q <= 9) or (alpha == 1 and 1 <= q <= 6)
                if valid:
                    continue
                encoded = q | (alpha << 4)
                solver.add_clause([
                    -variable if encoded & (1 << bit) else variable
                    for bit, variable in enumerate(bits)
                ])
    solver.write(path)
    body = path.read_text(encoding="ascii")
    path.write_text(
        "c t pmc\n" + "c p show " + " ".join(map(str, selectors)) + " 0\n" + body,
        encoding="ascii",
    )


def pysat_key(model: list[int], originals) -> bytes:
    positive = {literal for literal in model if literal > 0}
    fake_model = [False] * (max(originals) + 1)
    for variable in positive:
        if variable < len(fake_model):
            fake_model[variable] = True
    return model_key(fake_model, originals)


def add_aes_constraint(solver, originals, next_variable: int, expected_h: bytes) -> None:
    nibble_bits = []
    for index in range(32):
        inputs = originals[5 * index : 5 * index + 5]
        outputs = list(range(next_variable, next_variable + 4))
        next_variable += 4
        nibble_bits.append(outputs)
        for alpha in range(2):
            for q in range(16):
                valid = (alpha == 0 and q <= 9) or (alpha == 1 and 1 <= q <= 6)
                if not valid:
                    continue
                encoded = q | (alpha << 4)
                nibble = q if alpha == 0 else q + 9
                mismatch = [
                    -variable if encoded & (1 << bit) else variable
                    for bit, variable in enumerate(inputs)
                ]
                for bit, output in enumerate(outputs):
                    solver.add_clause([*mismatch, output if nibble & (1 << bit) else -output])

    key_bytes = []
    for byte_index in range(16):
        key_bytes.append([
            *nibble_bits[2 * byte_index + 1],
            *nibble_bits[2 * byte_index],
        ])
    encrypted_zero, _ = rrr.circuit_aes_encrypt_zero(solver, key_bytes, next_variable)
    for byte_index, expected in enumerate(expected_h):
        for bit, variable in enumerate(encrypted_zero[byte_index]):
            solver.add_clause([variable if expected & (1 << bit) else -variable])


def model_key(model, originals) -> bytes:
    nibbles = []
    for index in range(32):
        q = sum((1 << bit) for bit in range(4) if model[originals[5 * index + bit]])
        alpha = int(model[originals[5 * index + 4]])
        nibbles.append(q if alpha == 0 else q + 9)
    return bytes((nibbles[index] << 4) | nibbles[index + 1] for index in range(0, 32, 2))


def main() -> None:
    high_tags, _, expected_key, nonce = rrr.simulate()
    h = rrr.recover_h(high_tags)
    columns, target = projected_system(high_tags, h)

    cipher = AES.new(expected_key, AES.MODE_GCM, nonce=nonce)
    stream = cipher.encrypt(bytes(50))
    expected_assignment = assignment_for(expected_key, stream)
    actual = apply_columns(columns, expected_assignment)
    if actual != target:
        delta = actual ^ target
        raise AssertionError(
            "true key/stream does not satisfy constructed equations: "
            f"delta chunks={[f'{(delta >> (64 * index)) & ((1 << 64) - 1):016x}' for index in range(3)]}"
        )

    solution, kernel = rrr.linear_preimage(columns, target)
    print(f"linear nullity={len(kernel)}", flush=True)
    model_path = os.environ.get("RRR_DUMP_MODEL")
    if model_path:
        Path(model_path).write_text(json.dumps({
            "solution": f"{solution:044x}",
            "kernel": [f"{vector:044x}" for vector in kernel],
            "H": f"{h:032x}",
            "expected_key": expected_key.hex(),
        }, indent=2) + "\n", encoding="ascii")
        print(f"dumped {model_path}")
        return
    dump_path = os.environ.get("RRR_DUMP_REDUCED")
    if dump_path:
        dump_reduced_xcnf(solution, kernel, Path(dump_path))
        print(f"dumped {dump_path}")
        return
    anf_path = os.environ.get("RRR_DUMP_ANF")
    if anf_path:
        dump_anf(columns, target, Path(anf_path))
        print(f"dumped {anf_path}")
        return
    cnf_path = os.environ.get("RRR_DUMP_CNF")
    if cnf_path:
        dump_reduced_cnf(solution, kernel, Path(cnf_path))
        print(f"dumped {cnf_path}")
        return
    solver, selectors, originals, _ = build_reduced_solver(solution, kernel)
    expected_h = h.to_bytes(16, "big")
    started = time.monotonic()
    count = 0
    while True:
        satisfiable, model = solver.solve()
        if not satisfiable:
            break
        count += 1
        candidate = model_key(model, originals)
        if AES.new(candidate, AES.MODE_ECB).encrypt(bytes(16)) == expected_h:
            elapsed = time.monotonic() - started
            print(f"FOUND {candidate.hex()} candidates={count} elapsed={elapsed:.3f}s")
            if candidate != expected_key:
                raise AssertionError("unexpected key collision")
            return
        solver.add_clause([-variable if model[variable] else variable for variable in selectors])
        if count % 100 == 0:
            print(f"{count} candidates in {time.monotonic() - started:.1f}s", flush=True)
    raise RuntimeError(f"exhausted {count} candidates")


if __name__ == "__main__":
    main()
