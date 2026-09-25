import ast
import re
import sys
from hashlib import sha256, shake_256
from pathlib import Path

import mpmath as mp
from flint import fmpz_mat


MODULUS = 340282366920938463463374127620052448857
TAPS = [
    293035234842710656412736428887605854899,
    126046435982634523386123535325317566669,
    50539310733782598498346228686128672411,
    35193389289669317614253576525975603096,
    277281610120093429027306919868263094838,
    128243298306457102296521529702683821683,
    231841689297714899080564941771106946748,
    261309335432180125604596664018325467240,
    271693870204004895584859363987487798646,
    171566445956109046631759922868314568548,
    184378149977304838002709937317725140819,
    319126747451968673131138175148860577580,
    324054280109006923188746652887153347069,
    163359905128528470343512174286790142665,
    205643871624279323099899264560107404742,
    27877149052111792306326949729330769241,
    273056604641263822637578588919711962911,
    245073510042741221910617747686554185983,
    223814707638365962422832370536135636498,
    274976596168285116182742028851886938889,
    233428930838408638312428348977922678592,
    258083229323676172394102451359202165653,
    44469478053435834005802116425087254564,
    37157306352275985873567365013213376592,
    276902783057126133850383175706724015142,
]


root = Path(__file__).resolve().parent
tree = ast.parse((root / "challenge" / "chall.py").read_text(encoding="utf-8"))
blob = next(
    node.value.value
    for node in reversed(tree.body)
    if isinstance(node, ast.Expr)
    and isinstance(node.value, ast.Constant)
    and isinstance(node.value.value, str)
)
ys = ast.literal_eval(blob.strip().splitlines()[0])
ciphertext = bytes.fromhex(blob.strip().splitlines()[1])

n = 25
hidden_bits = 48
unit = 1 << hidden_bits
half = unit >> 1

representations = [[int(i == j) for j in range(n)] for i in range(n)]
for _ in range(n, len(ys)):
    representations.append(
        [
            sum(TAPS[k] * representations[-n + k][column] for k in range(n))
            % MODULUS
            for column in range(n)
        ]
    )

equation_count = 50
matrix = representations[n : n + equation_count]
rhs = []
for j, coefficients in enumerate(matrix, start=n):
    b = unit * (ys[j] - sum(coefficients[i] * ys[i] for i in range(n)))
    rhs.append((b + half - half * sum(coefficients)) % MODULUS)

m = len(rhs)
dimension = n + m
rows = []
for i in range(n):
    rows.append(
        [int(i == j) for j in range(n)]
        + [matrix[j][i] for j in range(m)]
    )
for j in range(m):
    rows.append([0] * n + [MODULUS * int(j == k) for k in range(m)])

reduced = fmpz_mat(rows).lll(delta=0.99, eta=0.51, rep="zbasis")
basis = [[int(reduced[i, j]) for j in range(dimension)] for i in range(dimension)]

mp.mp.dps = 180
orthogonal = []
norms = []
for index, row in enumerate(basis):
    current = [mp.mpf(value) for value in row]
    for previous, norm in zip(orthogonal, norms):
        coefficient = sum(mp.mpf(a) * b for a, b in zip(row, previous)) / norm
        current = [value - coefficient * base for value, base in zip(current, previous)]
    orthogonal.append(current)
    norms.append(sum(value * value for value in current))

target = [0] * n + rhs
residual = [mp.mpf(value) for value in target]
closest = [0] * dimension
for row, ortho, norm in reversed(list(zip(basis, orthogonal, norms))):
    coefficient = int(mp.nint(sum(value * base for value, base in zip(residual, ortho)) / norm))
    residual = [value - coefficient * base for value, base in zip(residual, row)]
    closest = [value + coefficient * base for value, base in zip(closest, row)]

difference = [closest[i] - target[i] for i in range(dimension)]
centered_low = difference[:n]
initial = [unit * ys[i] + centered_low[i] + half for i in range(n)]
if not all(0 <= value < MODULUS and value >> hidden_bits == ys[i] for i, value in enumerate(initial)):
    raise RuntimeError("recovered initial observed state is out of bounds")

full = initial[:]
while len(full) < len(ys):
    full.append(sum(TAPS[k] * full[-n + k] for k in range(n)) % MODULUS)
if [value >> hidden_bits for value in full] != ys:
    raise RuntimeError("full-state recurrence verification failed")

all_states = full[:]
inverse_c0 = pow(TAPS[0], -1, MODULUS)
for _ in range(n):
    previous = (
        all_states[24]
        - sum(TAPS[k] * all_states[k - 1] for k in range(1, n))
    ) * inverse_c0 % MODULUS
    all_states.insert(0, previous)
if len(all_states) != 205:
    raise RuntimeError("unexpected full sequence length")
seed = sha256("".join(map(str, all_states)).encode()).digest()
key = shake_256(seed).digest(len(ciphertext))
flag = bytes(left ^ right for left, right in zip(ciphertext, key))
if re.fullmatch(rb"pwnsec\{[^\r\n{}]+\}", flag) is None:
    raise RuntimeError("decrypted plaintext is not a valid flag")
sys.stdout.buffer.write(flag)
