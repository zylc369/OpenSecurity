import json
import math
import os
import re
import socket
import ssl
import sys
from pathlib import Path

from flint import fmpz_mat
from sympy import Poly, gcd, symbols


ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "challenge" / "remote-output.txt"
SAMPLE_INPUT = ROOT / "challenge" / "output.txt"
UNKNOWN_DIGITS = 30
SUFFIX_DIGITS = 47
LATTICE_T = 3


def load_endpoint() -> dict:
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    return next(item for item in data["endpoints"] if item["name"] == "main")


def fetch_remote_output(endpoint: dict) -> str:
    if endpoint["protocol"] != "tls":
        raise ValueError("the main endpoint must use TLS")
    context = ssl.create_default_context()
    with socket.create_connection((endpoint["host"], endpoint["port"]), timeout=20) as raw:
        with context.wrap_socket(raw, server_hostname=endpoint["host"]) as connection:
            connection.settimeout(300)
            chunks = []
            while True:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
    return b"".join(chunks).decode("utf-8")


def parse_input(text: str) -> tuple[int, int, int, str]:
    values = {
        name: int(value)
        for name, value in re.findall(r"^(N|e|c) = (\d+)$", text, re.MULTILINE)
    }
    match = re.search(r"^d_leak = '([^']+)'$", text, re.MULTILINE)
    if set(values) != {"N", "e", "c"} or match is None:
        raise ValueError("invalid challenge output")
    return values["N"], values["e"], values["c"], match.group(1)


def build_private_exponent_parts(leak: str) -> tuple[int, int, int]:
    marker = "*" * UNKNOWN_DIGITS
    prefix, separator, suffix = leak.partition(marker)
    if not separator or len(suffix) != SUFFIX_DIGITS:
        raise ValueError("unexpected private-exponent leak format")
    base = 10**SUFFIX_DIGITS
    known = int(prefix) * 10 ** (UNKNOWN_DIGITS + SUFFIX_DIGITS) + int(suffix)
    return known, base, 10**UNKNOWN_DIGITS


def lattice_indices(N: int, e: int, unknown_bound: int, t: int) -> list[tuple[int, int]]:
    gamma = 1.0 - math.log(e, N)
    unknown_weight = math.log(unknown_bound, N)
    indices = []
    for i in range(math.ceil(gamma * t / unknown_weight) + 1):
        for j in range(math.ceil(2 * gamma * t) + 1):
            if unknown_weight * i + 0.5 * j <= gamma * t + 1e-15:
                indices.append((i, j))
    return sorted(indices)


def recover_missing_digits(N: int, e: int, known: int, place: int, bound: int) -> int:
    modulus = (N - 1) // 2
    coefficient = e * place
    if math.gcd(coefficient, modulus) != 1:
        raise ValueError("normalizing coefficient is not invertible")

    # At the root, f1(x)=x+a1 is divisible by g, while
    # f2(y)=y+N+1 is divisible by g^2 for y=-(p+q).
    a1 = ((e * known - 1) * pow(coefficient, -1, modulus)) % modulus
    a2 = N + 1
    y_bound = 2 * math.isqrt(N) + 2
    monomials = lattice_indices(N, e, bound, LATTICE_T)

    rows = []
    for i, j in monomials:
        modulus_power = max(math.ceil(LATTICE_T - i - 2 * j), 0)
        row = []
        for x_degree, y_degree in monomials:
            if x_degree <= i and y_degree <= j:
                value = (
                    math.comb(i, x_degree)
                    * a1 ** (i - x_degree)
                    * math.comb(j, y_degree)
                    * a2 ** (j - y_degree)
                    * (N - 1) ** modulus_power
                )
            else:
                value = 0
            row.append(value * bound**x_degree * y_bound**y_degree)
        rows.append(row)

    reduced = fmpz_mat(rows).lll(delta=0.8, eta=0.51)
    x, y = symbols("x y")
    polynomials = []
    for row_index in range(reduced.nrows()):
        coefficients = {}
        for column, monomial in enumerate(monomials):
            value = int(reduced[row_index, column])
            if value:
                scale = bound ** monomial[0] * y_bound ** monomial[1]
                coefficients[monomial] = value // scale
        polynomial = Poly.from_dict(coefficients, (x, y), domain="ZZ").primitive()[1]
        if not polynomial.is_ground:
            polynomials.append(polynomial)

    for i, left in enumerate(polynomials):
        for right in polynomials[:i]:
            common = gcd(left, right)
            if common.degree(x) != 1 or common.degree(y) != 0:
                continue
            leading = int(common.coeff_monomial(x))
            constant = int(common.coeff_monomial(1))
            if leading == 0 or (-constant) % leading:
                continue
            candidate = (-constant) // leading
            if not 0 <= candidate < bound:
                continue
            d = known + place * candidate
            if pow(2, e * d - 1, N) == 1:
                return candidate
    raise ValueError("lattice did not recover the missing digits")


def convergents(numerator: int, denominator: int):
    p0, p1 = 0, 1
    q0, q1 = 1, 0
    while denominator:
        quotient, remainder = divmod(numerator, denominator)
        numerator, denominator = denominator, remainder
        p0, p1 = p1, quotient * p1 + p0
        q0, q1 = q1, quotient * q1 + q0
        yield p1, q1


def recover_factors(N: int, e: int, d: int) -> tuple[int, int]:
    multiple = e * d - 1
    target = N - 1
    for k, common in convergents(multiple, target):
        if k <= 0 or common <= 0 or common % 2 or target % common or multiple % k:
            continue
        lam = multiple // k
        h = target // common
        total = h - lam
        product, remainder = divmod(lam, common)
        if remainder or total <= 0:
            continue
        discriminant = total * total - 4 * product
        if discriminant < 0:
            continue
        root = math.isqrt(discriminant)
        if root * root != discriminant or (total + root) % 2:
            continue
        a = (total + root) // 2
        b = (total - root) // 2
        p = common * a + 1
        q = common * b + 1
        if p * q == N:
            return p, q
    raise ValueError("continued fractions did not recover the factors")


def main() -> None:
    endpoint = load_endpoint()
    if os.environ.get("GAP_GAP_REMOTE") == "1":
        text = fetch_remote_output(endpoint)
    elif os.environ.get("GAP_GAP_SAMPLE") == "1":
        text = SAMPLE_INPUT.read_text(encoding="utf-8")
    else:
        text = INPUT.read_text(encoding="utf-8")
    N, e, ciphertext, leak = parse_input(text)
    known, place, bound = build_private_exponent_parts(leak)
    missing = recover_missing_digits(N, e, known, place, bound)
    d = known + place * missing
    p, q = recover_factors(N, e, d)
    if p * q != N:
        raise ValueError("factorization verification failed")
    plaintext = pow(ciphertext, d, N)
    flag = plaintext.to_bytes((plaintext.bit_length() + 7) // 8, "big")
    if re.fullmatch(rb"pwnsec\{[^}\r\n]+\}", flag) is None:
        raise ValueError("decrypted plaintext is not a flag")
    sys.stdout.buffer.write(flag)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"solve failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
