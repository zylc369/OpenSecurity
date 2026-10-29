import json
import os
import sys

from sage.all import GF, Matrix, PolynomialRing, Subsets, ZZ, Zmod, gcd, prod, vector


PROBES = [
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 2, 3, 2, 3, 1, 1, 3, 3, 3],
    [2, 2, 2, 3, 1, 2, 2, 2, 2, 2, 1],
    [2, 2, 2, 3, 1, 2, 1, 3, 3, 3, 2],
    [2, 3, 2, 2, 1, 3, 2, 2, 3, 1, 2],
    [2, 2, 3, 3, 3, 1, 2, 2, 2, 2, 1],
    [2, 2, 3, 1, 3, 2, 1, 2, 2, 1, 3],
    [2, 3, 2, 1, 1, 1, 2, 3, 3, 2, 3],
]


def compositions(total, parts, prefix=()):
    if parts == 1:
        yield prefix + (total,)
        return
    for value in range(total + 1):
        yield from compositions(total - value, parts - 1, prefix + (value,))


def signature(exponents):
    return tuple(
        prod(base**exponent for base, exponent in zip(probe, exponents))
        for probe in PROBES
    )


def recover(outputs):
    output_vector = vector(ZZ, outputs)
    relation_lattice = Matrix(ZZ, [outputs]).right_kernel().basis_matrix().LLL()
    relations = relation_lattice[:2]

    candidates = []
    for degree in range(12):
        for exponents in compositions(degree, 11):
            column = vector(ZZ, signature(exponents))
            if all(row * column == 0 for row in relations.rows()):
                candidates.append(exponents)
    if len(candidates) != 5:
        raise ValueError(f"expected five monomials, found {len(candidates)}")

    evaluation_matrix = Matrix(ZZ, [signature(e) for e in candidates]).transpose()
    augmented = evaluation_matrix.augment(Matrix(ZZ, 8, 1, outputs))
    determinants = [
        abs(augmented.matrix_from_rows(rows).det())
        for rows in Subsets(range(8), 6)
    ]
    modulus = gcd(value for value in determinants if value)
    for small_prime in (2, 3):
        while modulus % small_prime == 0 and modulus // small_prime > max(outputs):
            modulus //= small_prime
    if modulus <= max(outputs) or modulus > 2**256 or not modulus.is_prime():
        raise ValueError(f"invalid recovered modulus ({modulus.nbits()} bits)")

    field = GF(modulus)
    coefficients = Matrix(field, evaluation_matrix).solve_right(vector(field, outputs))
    lifted = vector(ZZ, map(ZZ, coefficients))
    if any((evaluation_matrix * lifted - output_vector)[i] % modulus for i in range(8)):
        raise ValueError("recovered coefficients do not reproduce the oracle outputs")

    ring = PolynomialRing(Zmod(modulus), 11, "x")
    variables = ring.gens()
    polynomial = ring.zero()
    for coefficient, exponents in zip(coefficients, candidates):
        monomial = prod(x**e for x, e in zip(variables, exponents))
        polynomial += coefficient * monomial
    return {
        "modulus": str(modulus),
        "polynomial": str(polynomial),
        "exponents": [list(map(int, e)) for e in candidates],
    }


try:
    values = [ZZ(value) for value in os.environ["HOKAN_OUTPUTS"].split(",")]
    if len(values) != 8:
        raise ValueError("exactly eight oracle outputs are required")
    print("RESULT_JSON=" + json.dumps(recover(values), separators=(",", ":")))
except Exception as error:
    print(f"RECOVERY_ERROR={type(error).__name__}: {error}", file=sys.stderr)
    raise
