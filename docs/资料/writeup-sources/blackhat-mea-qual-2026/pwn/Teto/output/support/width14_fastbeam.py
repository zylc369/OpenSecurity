#!/usr/bin/env python3
"""Fast exact bitmask beam planner for width-14 waiting rounds."""

import pickle
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import exploit_agent as base
from glibc_rand import glibc_sequence


PIECES = base.PIECES
CELLS = {
    (kind, rotation): tuple(
        (x, y) for y in range(4) for x in range(4)
        if PIECES[kind][rotation][4 * y + x] == "#"
    )
    for kind in range(7) for rotation in range(4)
}
SEQ = tuple(glibc_sequence(100000))


@dataclass
class Node:
    rows: tuple
    parent: object = None
    index: int = -1
    command: bytes = b""


@dataclass
class Plan:
    start: int
    trigger: int
    setup: int
    high_width: int
    end: int
    commands: dict
    writers: tuple


def command(rotation, delta):
    return (
        b"w" * rotation
        + (b"d" * delta if delta >= 0 else b"a" * -delta)
        + b" "
    )


def occupied(rows):
    return sum(row.bit_count() for row in rows)


def board_rank(rows):
    heights = []
    holes = 0
    for x in range(10):
        bit = 1 << x
        first = next((y for y, row in enumerate(rows) if row & bit), 20)
        height = 20 - first
        heights.append(height)
        if first < 20:
            holes += sum(not (rows[y] & bit) for y in range(first, 20))
    bump = sum(abs(a - b) for a, b in zip(heights, heights[1:]))
    wells = sum(max(
        0,
        min(heights[x - 1] if x else 20,
            heights[x + 1] if x < 9 else 20) - heights[x],
    ) for x in range(10))
    return (
        -0.55 * sum(heights) - 1.25 * holes - 0.22 * bump
        - 0.18 * wells - 0.85 * max(heights)
    )


def place(rows, kind, rotations, delta, allow_clear, reserve_col9):
    x = 3 if kind == 0 else 4
    y = -2
    rotation = 0

    def collides(nx, ny, nrot):
        for px, py in CELLS[kind, nrot]:
            xx, yy = nx + px, ny + py
            if xx < 0 or yy >= 20:
                return True
            if yy < 0:
                if xx >= 10:
                    return True
            elif xx >= 10 or rows[yy] & (1 << xx):
                return True
        return False

    for _ in range(rotations):
        next_rotation = (rotation + 1) & 3
        for dx, dy in ((0, 0), (-1, 0), (1, 0), (0, -1), (-1, -1), (1, -1)):
            if not collides(x + dx, y + dy, next_rotation):
                x += dx
                y += dy
                rotation = next_rotation
                break
    direction = 1 if delta >= 0 else -1
    for _ in range(abs(delta)):
        if not collides(x + direction, y, rotation):
            x += direction
    if collides(x, y, rotation):
        return None
    while y + 1 < 20 and not collides(x, y + 1, rotation):
        y += 1
    if y < 0:
        return None
    placed = [(x + px, y + py) for px, py in CELLS[kind, rotation]]
    if reserve_col9 and any(xx == 9 for xx, _ in placed):
        return None
    updated = list(rows)
    for xx, yy in placed:
        updated[yy] |= 1 << xx
    lines = 0
    row = 0
    while row < 20:
        if updated[row] == 0x3FF:
            if not allow_clear:
                return None
            del updated[row]
            updated.insert(0, 0)
            lines += 1
        row += 1
    return tuple(updated), lines


@lru_cache(maxsize=400000)
def transitions(rows, kind, allow_clear=True, reserve_col9=False):
    found = {}
    rotations = (0,) if kind == 0 and occupied(rows) >= 60 else range(4)
    for rotation in rotations:
        for delta in range(-7, 8):
            result = place(
                rows, kind, rotation, delta, allow_clear, reserve_col9
            )
            if result is None:
                continue
            updated, lines = result
            cmd = command(rotation, delta)
            old = found.get(updated)
            if old is None or len(cmd) < len(old[0]):
                found[updated] = (cmd, lines)
    return tuple((rows, cmd, lines) for rows, (cmd, lines) in found.items())


def advance(beam, index, allow_clear, reserve_col9, width):
    found = {}
    kind = SEQ[index]
    for node in beam:
        for rows, cmd, lines in transitions(
            node.rows, kind, allow_clear, reserve_col9
        ):
            candidate = Node(rows, node, index, cmd)
            old = found.get(rows)
            if old is None or len(cmd) < len(old.command):
                found[rows] = candidate
    return sorted(
        found.values(), key=lambda node: board_rank(node.rows), reverse=True
    )[:width]


def reconstruct(node):
    result = {}
    while node is not None and node.parent is not None:
        result[node.index] = node.command
        node = node.parent
    return result


def trigger_prefix(start):
    for pressure in range(8, 50, 3):
        rows = (0,) * 20
        node = Node(rows)
        try:
            for index in range(start, start + 180):
                if SEQ[index] == 0 and occupied(node.rows) >= 60:
                    return index, node
                options = transitions(
                    node.rows, SEQ[index], index < start + pressure, False
                )
                if not options:
                    break
                # Greedy prefix is enough to reach pressure; the long safe
                # wait below is beam-searched.
                rows, cmd, _ = max(options, key=lambda item: board_rank(item[0]))
                node = Node(rows, node, index, cmd)
        except IndexError:
            pass
    raise RuntimeError(f"no pressure trigger at {start}")


def tail(beam, setup, writer_count, width=100):
    i_positions = []
    for index in range(setup + 1, min(setup + 120, len(SEQ))):
        if SEQ[index] == 0:
            i_positions.append(index)
            if len(i_positions) == writer_count + 1:
                break
    if len(i_positions) != writer_count + 1:
        return None
    high = i_positions[0]
    writers = tuple(i_positions[1:])
    if writers[-1] - setup - writer_count - 1 > 34:
        return None
    specials = {high, *writers}
    current = beam
    for index in range(setup + 1, writers[-1] + 1):
        if index in specials:
            continue
        current = advance(current, index, False, True, width)
        if not current:
            return None
    return current[0], high, writers, writers[-1] + 1


def plan_round(start, writer_count=10, safe_width=80, tail_width=100,
               max_wait=3000):
    trigger, prefix = trigger_prefix(start)
    beam = [Node(prefix.rows)]
    for index in range(trigger + 1, trigger + max_wait):
        if SEQ[index] == 0:
            result = tail(beam, index, writer_count, tail_width)
            if result is not None:
                final, high, writers, end = result
                commands = reconstruct(prefix)
                commands.update(reconstruct(final))
                commands[index] = b"w"      # width 14 -> 30
                return Plan(
                    start, trigger, index, high, end, commands, writers
                )
            # Discarded waiting I: actual x=2 re-sets width bit 2.
            beam = [Node(node.rows, node, index, b"aaw") for node in beam]
            continue
        beam = advance(beam, index, True, False, safe_width)
        if not beam:
            raise RuntimeError(f"safe beam died at {index}")
    raise RuntimeError(f"no {writer_count}-writer tail at {start}")


def build_schedule(build_rounds=5, writer_count=10):
    cursor = 111
    plans = []
    for number in range(build_rounds + 1):
        plan = plan_round(cursor, writer_count)
        plans.append(plan)
        print(
            number, cursor, plan.trigger, plan.setup, plan.high_width,
            plan.end, plan.writers, flush=True,
        )
        cursor = plan.end + 1
    with Path("width14_fast_schedule.pkl").open("wb") as file:
        pickle.dump((SEQ, plans[:-1], plans[-1]), file)
    return plans


if __name__ == "__main__":
    build_schedule()
