#!/usr/bin/env python3
"""Solve Flagyard's Popcnt Oracle challenge.

The service leaks the Hamming weight of textbook-RSA decryptions.  Multiplying
the challenge ciphertext by Enc(a) therefore asks for HW(a*m mod n).
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
import secrets
import socket
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence


ROOT = Path(__file__).resolve().parent
PROMPT = b"x> "
FLAG_RE_BYTES = re.compile(rb"BHFlagY\{[^{}\r\n]+\}")
FLAG_RE_TEXT = re.compile(r"^BHFlagY\{[^{}\r\n]+\}$")


class SolveError(RuntimeError):
    """Raised when the protocol or mathematical checks fail."""


class FlagFound(Exception):
    """Carries a flag returned before the final submission."""

    def __init__(self, flag: str) -> None:
        super().__init__(flag)
        self.flag = flag


def log(message: str) -> None:
    del message


class OracleClient:
    def __init__(
        self,
        host: str,
        port: int,
        timeout: float = 180.0,
        batch_size: int = 256,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.batch_size = batch_size
        self.sock: socket.socket | None = None
        self.buffer = b""
        self.cache: dict[int, int] = {}
        self.query_count = 0
        self.e = 0
        self.n = 0
        self.c = 0

    def __enter__(self) -> "OracleClient":
        self.sock = socket.create_connection((self.host, self.port), timeout=15)
        self.sock.settimeout(self.timeout)
        banner = self._recv_until_prompt().decode("ascii", errors="strict")
        values: dict[str, int] = {}
        for name in ("e", "n", "c"):
            match = re.search(rf"(?m)^{name} = ([0-9]+)$", banner)
            if match is None:
                raise SolveError(f"banner에서 {name} 값을 찾지 못했습니다: {banner!r}")
            values[name] = int(match.group(1))
        self.e, self.n, self.c = values["e"], values["n"], values["c"]
        return self

    def __exit__(self, *args: object) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def _extract_flag(self, data: bytes) -> str | None:
        match = FLAG_RE_BYTES.search(data)
        return match.group(0).decode("ascii") if match else None

    def _recv_until_prompt(self) -> bytes:
        if self.sock is None:
            raise SolveError("socket이 연결되지 않았습니다")
        while True:
            index = self.buffer.find(PROMPT)
            if index >= 0:
                result = self.buffer[:index]
                self.buffer = self.buffer[index + len(PROMPT) :]
                return result
            chunk = self.sock.recv(65536)
            if not chunk:
                flag = self._extract_flag(self.buffer)
                if flag:
                    raise FlagFound(flag)
                raise SolveError(f"prompt 전에 연결이 종료되었습니다: {self.buffer!r}")
            self.buffer += chunk
            flag = self._extract_flag(self.buffer)
            if flag:
                raise FlagFound(flag)

    def query_many(self, values: Iterable[int]) -> list[int]:
        if self.sock is None:
            raise SolveError("socket이 연결되지 않았습니다")

        normalized = [value % self.n for value in values]
        pending = list(dict.fromkeys(value for value in normalized if value not in self.cache))
        for start in range(0, len(pending), self.batch_size):
            batch = pending[start : start + self.batch_size]
            payload = b"".join(f"{value}\n".encode("ascii") for value in batch)
            self.sock.sendall(payload)
            for value in batch:
                raw = self._recv_until_prompt()
                text = raw.decode("ascii", errors="strict").strip()
                if not re.fullmatch(r"[0-9]+", text):
                    raise SolveError(f"숫자가 아닌 oracle 응답: {text!r}")
                self.cache[value] = int(text)
                self.query_count += 1
            log(f"oracle queries: {self.query_count}")
        return [self.cache[value] for value in normalized]

    def submit(self, plaintext: int) -> str:
        if self.sock is None:
            raise SolveError("socket이 연결되지 않았습니다")
        self.sock.sendall(f"{plaintext}\n".encode("ascii"))
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            flag = self._extract_flag(self.buffer)
            if flag:
                return flag
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout as exc:
                raise SolveError("최종 plaintext 제출 응답 시간이 초과되었습니다") from exc
            if not chunk:
                break
            self.buffer += chunk
        flag = self._extract_flag(self.buffer)
        if flag:
            return flag
        raise SolveError(f"최종 응답에 flag가 없습니다: {self.buffer!r}")


class PlaintextOracle:
    """Local test double: its input already represents the decrypted value."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.query_count = 0

    def query_many(self, values: Iterable[int]) -> list[int]:
        result = []
        for value in values:
            self.query_count += 1
            result.append((value % self.n).bit_count())
        return result


def make_inverse_halving_states(start: int, multiplier: int, n: int, length: int) -> list[int]:
    states = [start]
    for _ in range(length):
        states.append(states[-1] * multiplier % n)
    return states


def infer_parity_bits(
    n: int,
    states: Sequence[int],
    query_many: Callable[[Iterable[int]], list[int]],
) -> list[int | None]:
    """Infer parity of every state; None marks a coincidental equal-weight case."""

    weights = query_many(states)
    equal_indices = [i for i in range(len(states) - 1) if weights[i] == weights[i + 1]]
    complement_indices = sorted(set(equal_indices) | {i + 1 for i in equal_indices})
    complement_values = query_many((-states[i]) % n for i in complement_indices)
    complement_weights = dict(zip(complement_indices, complement_values, strict=True))

    bits: list[int | None] = []
    for i in range(len(states) - 1):
        if weights[i] != weights[i + 1]:
            bits.append(1)
            continue
        if complement_weights[i] != complement_weights[i + 1]:
            bits.append(0)
        else:
            bits.append(None)
    return bits


def infer_selected_parity_bits(
    n: int,
    states: Sequence[int],
    positions: Sequence[int],
    query_many: Callable[[Iterable[int]], list[int]],
) -> dict[int, int | None]:
    state_indices = sorted(set(positions) | {i + 1 for i in positions})
    weights = dict(
        zip(state_indices, query_many(states[i] for i in state_indices), strict=True)
    )
    equal_positions = [i for i in positions if weights[i] == weights[i + 1]]
    complement_indices = sorted(set(equal_positions) | {i + 1 for i in equal_positions})
    complement_weights = dict(
        zip(
            complement_indices,
            query_many((-states[i]) % n for i in complement_indices),
            strict=True,
        )
    )

    result: dict[int, int | None] = {}
    for i in positions:
        if weights[i] != weights[i + 1]:
            result[i] = 1
        elif complement_weights[i] != complement_weights[i + 1]:
            result[i] = 0
        else:
            result[i] = None
    return result


@dataclass(frozen=True)
class CandidateSearchResult:
    plaintexts: tuple[int, ...]
    peak_states: int


def search_plaintexts(
    n: int,
    base_bits: Sequence[int | None],
    multiplier_observations: dict[int, dict[int, int | None]],
    validator: Callable[[int], bool],
    max_states: int = 1_000_000,
) -> CandidateSearchResult:
    """Reconstruct m from partial bits of u=-m*n^-1 mod 2^L."""

    length = len(base_bits)
    modulus = 1 << length
    multipliers = tuple(sorted(multiplier_observations))
    plaintexts: set[int] = set()
    peak_states = 0

    quotient_ranges = (range(multiplier) for multiplier in multipliers)
    for quotients in itertools.product(*quotient_ranges):
        # Each state is (carry tuple for a*u+q, accumulated u).
        states: set[tuple[tuple[int, ...], int]] = {(tuple(quotients), 0)}
        for bit_index, known_bit in enumerate(base_bits):
            next_states: set[tuple[tuple[int, ...], int]] = set()
            choices = (known_bit,) if known_bit is not None else (0, 1)
            for carries, value in states:
                for bit in choices:
                    new_carries: list[int] = []
                    valid = True
                    for j, multiplier in enumerate(multipliers):
                        total = carries[j] + multiplier * bit
                        observed = multiplier_observations[multiplier].get(bit_index)
                        if observed is not None and observed != (total & 1):
                            valid = False
                            break
                        new_carries.append(total >> 1)
                    if valid:
                        next_states.add((tuple(new_carries), value | (bit << bit_index)))
            states = next_states
            peak_states = max(peak_states, len(states))
            if len(states) > max_states:
                raise SolveError(
                    f"candidate state가 {max_states}개를 초과했습니다; 보조 multiplier가 필요합니다"
                )
            if not states:
                break

        for _, u in states:
            plaintext = (-u * n) % modulus
            if plaintext >= n:
                continue
            if any((multiplier * plaintext) // n != quotient for multiplier, quotient in zip(multipliers, quotients, strict=True)):
                continue
            if validator(plaintext):
                plaintexts.add(plaintext)

    return CandidateSearchResult(tuple(sorted(plaintexts)), peak_states)


def recover_plaintext(
    e: int,
    n: int,
    c: int,
    query_many: Callable[[Iterable[int]], list[int]],
) -> tuple[int, list[int], dict[int, dict[int, int | None]], int]:
    if c == 0:
        return 0, [], {}, 1

    length = n.bit_length()
    inverse_two = (n + 1) // 2
    encrypted_inverse_two = pow(inverse_two, e, n)
    base_states = make_inverse_halving_states(c, encrypted_inverse_two, n, length)
    base_bits = infer_parity_bits(n, base_states, query_many)
    unknown_positions = [i for i, bit in enumerate(base_bits) if bit is None]
    log(f"n bits: {length}, ambiguous base bits: {len(unknown_positions)}")

    observations: dict[int, dict[int, int | None]] = {}
    if unknown_positions:
        multiplier = 3
        encrypted_start = c * pow(multiplier, e, n) % n
        states = make_inverse_halving_states(
            encrypted_start, encrypted_inverse_two, n, length
        )
        observations[multiplier] = infer_selected_parity_bits(
            n, states, unknown_positions, query_many
        )
        overlap = sum(value is None for value in observations[multiplier].values())
        log(f"multiplier 3 unresolved overlaps: {overlap}")

    result = search_plaintexts(
        n,
        base_bits,
        observations,
        validator=lambda plaintext: pow(plaintext, e, n) == c,
    )
    if len(result.plaintexts) != 1:
        raise SolveError(f"public RSA 검증을 통과한 후보 수: {len(result.plaintexts)}")
    return result.plaintexts[0], unknown_positions, observations, result.peak_states


def run_self_test(rounds: int) -> None:
    tested = 0
    for bits in (64, 127, 256, 512):
        for _ in range(rounds):
            n = secrets.randbits(bits) | 1 | (1 << (bits - 1))
            plaintext = secrets.randbelow(n)
            length = n.bit_length()
            inverse_two = (n + 1) // 2
            oracle = PlaintextOracle(n)
            base_states = make_inverse_halving_states(plaintext, inverse_two, n, length)
            base_bits = infer_parity_bits(n, base_states, oracle.query_many)

            modulus = 1 << length
            true_u = (-plaintext * pow(n, -1, modulus)) % modulus
            for i, bit in enumerate(base_bits):
                if bit is not None and bit != ((true_u >> i) & 1):
                    raise AssertionError("base parity invariant failed")

            unknown_positions = [i for i, bit in enumerate(base_bits) if bit is None]
            observations: dict[int, dict[int, int | None]] = {}
            if unknown_positions:
                transformed = 3 * plaintext % n
                states = make_inverse_halving_states(transformed, inverse_two, n, length)
                observations[3] = infer_selected_parity_bits(
                    n, states, unknown_positions, oracle.query_many
                )
            result = search_plaintexts(
                n,
                base_bits,
                observations,
                validator=lambda candidate, expected=plaintext: candidate == expected,
            )
            if result.plaintexts != (plaintext,):
                raise AssertionError(
                    f"recovery failed: bits={bits}, candidates={result.plaintexts}"
                )
            tested += 1
    print(f"self-test passed: {tested} cases")


def write_evidence(
    path: Path,
    client: OracleClient,
    plaintext: int,
    flag: str,
    unknown_positions: Sequence[int],
    observations: dict[int, dict[int, int | None]],
    peak_states: int,
) -> None:
    payload = {
        "challenge": "Popcnt Oracle",
        "endpoint": f"{client.host}:{client.port}",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "e": client.e,
        "n": str(client.n),
        "n_bits": client.n.bit_length(),
        "n_sha256": hashlib.sha256(str(client.n).encode("ascii")).hexdigest(),
        "c": str(client.c),
        "recovered_m": str(plaintext),
        "public_relation_verified": pow(plaintext, client.e, client.n) == client.c,
        "ambiguous_base_bits": list(unknown_positions),
        "multiplier_observations": {
            str(multiplier): {str(i): bit for i, bit in values.items()}
            for multiplier, values in observations.items()
        },
        "candidate_peak_states": peak_states,
        "oracle_queries": client.query_count,
        "flag": flag,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    instance = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in instance["endpoints"] if item["name"] == "main")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=endpoint["host"])
    parser.add_argument("--port", type=int, default=endpoint["port"])
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--evidence", type=Path, default=ROOT / "output" / "evidence.json")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--self-test-rounds", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        run_self_test(args.self_test_rounds)
        return 0

    try:
        with OracleClient(args.host, args.port, args.timeout, args.batch_size) as client:
            log(f"connected to {args.host}:{args.port}")
            log(f"received e={client.e}, n_bits={client.n.bit_length()}")
            try:
                plaintext, unknown, observations, peak_states = recover_plaintext(
                    client.e, client.n, client.c, client.query_many
                )
                if pow(plaintext, client.e, client.n) != client.c:
                    raise SolveError("recovered plaintext가 공개 RSA 관계를 만족하지 않습니다")
                log("recovered plaintext satisfies pow(m, e, n) == c")
                flag = client.submit(plaintext)
            except FlagFound as found:
                plaintext, unknown, observations, peak_states = -1, [], {}, 0
                flag = found.flag

            if not FLAG_RE_TEXT.fullmatch(flag):
                raise SolveError(f"예상 형식과 다른 flag: {flag!r}")
            if args.evidence is not None:
                if plaintext < 0:
                    raise SolveError("조기 flag 반환 시에는 evidence를 만들 수 없습니다")
                write_evidence(
                    args.evidence,
                    client,
                    plaintext,
                    flag,
                    unknown,
                    observations,
                    peak_states,
                )
            sys.stdout.buffer.write(flag.encode("ascii"))
            return 0
    except (OSError, SolveError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
