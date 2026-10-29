#!/usr/bin/env python3
"""Portable implementation of glibc's srand(1)/rand() sequence.

The challenge is built on glibc, but the exploit's cached planners are also
useful from the repository-wide Windows virtual environment.  Keeping the
generator in Python avoids accidentally calling the Windows C runtime through
``ctypes.CDLL(None)``.
"""


def glibc_sequence(count: int) -> list[int]:
    """Return ``glibc rand() % 7`` values after ``srand(1)``."""
    if count < 0:
        raise ValueError("count must be non-negative")

    state = [1]
    for _ in range(1, 31):
        state.append((16807 * state[-1]) % 2147483647)
    state.extend(state[:3])

    for index in range(34, 344):
        state.append((state[index - 31] + state[index - 3]) & 0xFFFFFFFF)

    result = []
    for index in range(344, 344 + count):
        state.append((state[index - 31] + state[index - 3]) & 0xFFFFFFFF)
        result.append((state[index] >> 1) % 7)
    return result
