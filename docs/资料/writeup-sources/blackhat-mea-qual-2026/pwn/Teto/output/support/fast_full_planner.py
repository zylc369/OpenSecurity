#!/usr/bin/env python3
"""Fast offline planner for IBT-safe, full-main restart rounds."""

import pickle
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from glibc_rand import glibc_sequence


PIECES = {
    0: ("####............", ".#...#...#...#..", "####............", ".#...#...#...#.."),
    1: ("##..##..........",) * 4,
    2: (".#..###.........", "#...##..#.......", "###..#..........", ".#..##...#......"),
    3: (".##.##..........", "#...##...#......", ".##.##..........", "#...##...#......"),
    4: ("##...##.........", ".#..##..#.......", "##...##.........", ".#..##..#......."),
    5: ("#...###.........", "##..#...#.......", "###...#.........", ".#...#..##......"),
    6: ("..#.###.........", "#...#...##......", "###.#...........", "##...#...#......"),
}
CELLS = {
    (kind, rotation): tuple(
        (x, y) for y in range(4) for x in range(4)
        if PIECES[kind][rotation][4 * y + x] == "#"
    )
    for kind in range(7) for rotation in range(4)
}


@dataclass
class RoundPlan:
    start: int
    trigger: int
    high_width: int
    end: int                 # active piece deliberately topped out
    placements: dict
    writers: list
    occupied: int


def rand_sequence(count=100000):
    return glibc_sequence(count)


def occupied(rows):
    return sum(row.bit_count() for row in rows)


def place(rows, kind, rotation, x, allow_clear=True, reserve_col9=False):
    cells = CELLS[kind, rotation]
    if min(x + px for px, _ in cells) < 0:
        return None
    if max(x + px for px, _ in cells) >= 10:
        return None
    if reserve_col9 and any(x + px == 9 for px, _ in cells):
        return None

    def collides(y):
        for px, py in cells:
            yy = y + py
            if yy >= 20:
                return True
            if yy >= 0 and rows[yy] & (1 << (x + px)):
                return True
        return False

    y = -2
    if collides(y):
        return None
    while not collides(y + 1):
        y += 1
    if y < 0:
        return None
    updated = list(rows)
    for px, py in cells:
        updated[y + py] |= 1 << (x + px)

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


def features(rows):
    heights = []
    holes = 0
    for x in range(10):
        bit = 1 << x
        first = next((y for y, row in enumerate(rows) if row & bit), None)
        height = 0 if first is None else 20 - first
        heights.append(height)
        if first is not None:
            holes += sum(not (rows[y] & bit) for y in range(first, 20))
    bumpiness = sum(abs(a - b) for a, b in zip(heights, heights[1:]))
    wells = sum(max(
        0,
        min(heights[x - 1] if x else 20,
            heights[x + 1] if x < 9 else 20) - heights[x],
    ) for x in range(10))
    return sum(heights), max(heights), holes, bumpiness, wells


@lru_cache(maxsize=1000000)
def choose(rows, kind, allow_clear=True, reserve_col9=False):
    best = None
    rotations = (0,) if kind == 0 and occupied(rows) >= 60 else range(4)
    for rotation in rotations:
        for x in range(-3, 10):
            result = place(rows, kind, rotation, x, allow_clear, reserve_col9)
            if result is None:
                continue
            updated, lines = result
            aggregate, maximum, holes, bumpiness, wells = features(updated)
            value = (
                0.76 * lines - 0.51 * aggregate - 0.76 * holes
                - 0.18 * bumpiness - 0.1 * wells - 0.5 * maximum
            )
            candidate = (value, -maximum, -holes, updated, rotation, x)
            if best is None or candidate[:3] > best[:3]:
                best = candidate
    if best is None:
        raise RuntimeError("no placement")
    return best[3], (best[4], best[5])


def promising_prefixes(sequence, start, lookahead=700):
    stop = min(len(sequence), start + lookahead)
    positions = [index for index in range(start, stop) if sequence[index] == 0]
    clusters = []
    # Nine I pieces means two setup pieces plus up to seven writers.
    for left in range(len(positions) - 8):
        first, last = positions[left], positions[left + 8]
        clusters.append((last - first, first))
    prefixes = set(range(32, 80, 4))
    for _, first in sorted(clusters)[:16]:
        for lead in range(8, 25, 2):
            prefix = first - start - lead
            if prefix >= 0:
                prefixes.add(prefix)
    return sorted(prefixes)


@lru_cache(maxsize=None)
def _candidate_cache_key(start, max_writers, min_writers):
    # Placeholder used only to make accidental direct caching obvious.
    return start, max_writers, min_writers


def round_candidates(sequence, start, max_writers=12, min_writers=5):
    prefix_range = promising_prefixes(sequence, start)
    wanted = set(prefix_range)
    normal_states = {}
    rows = (0,) * 20
    placements = {}
    for prefix in range(max(prefix_range) + 1):
        if prefix in wanted:
            normal_states[prefix] = (rows, dict(placements))
        if prefix != max(prefix_range):
            index = start + prefix
            try:
                rows, placements[index] = choose(rows, sequence[index])
            except RuntimeError:
                break

    result = {}
    for prefix in prefix_range:
        if prefix not in normal_states:
            continue
        rows, placements = normal_states[prefix]
        placements = dict(placements)
        try:
            index = start + prefix
            while True:
                kind = sequence[index]
                if kind == 0 and occupied(rows) >= 60:
                    trigger = index
                    break
                rows, placements[index] = choose(
                    rows, kind, False, True
                )
                index += 1

            high_width = None
            writers = []
            index = trigger + 1
            while index < min(len(sequence), trigger + 220):
                if high_width is not None and len(writers) >= min_writers:
                    item = RoundPlan(
                        start, trigger, high_width, index,
                        dict(placements), list(writers), occupied(rows),
                    )
                    key = (item.trigger, item.high_width, item.end,
                           tuple(item.writers))
                    result.setdefault(key, item)
                kind = sequence[index]
                if kind == 0:
                    if high_width is None:
                        high_width = index
                    else:
                        writers.append(index)
                        if len(writers) >= max_writers:
                            item = RoundPlan(
                                start, trigger, high_width, index + 1,
                                dict(placements), list(writers), occupied(rows),
                            )
                            key = (item.trigger, item.high_width, item.end,
                                   tuple(item.writers))
                            result.setdefault(key, item)
                            break
                else:
                    rows, placements[index] = choose(rows, kind, False, True)
                index += 1
        except (RuntimeError, IndexError):
            continue
    return list(result.values())


def find_schedule(target_payload=31, max_rounds=30, beam_width=12):
    sequence = rand_sequence()
    candidate_cache = {}

    def candidates(start):
        if start not in candidate_cache:
            candidate_cache[start] = round_candidates(sequence, start)
        return candidate_cache[start]

    # First/original game contributes one ef52b address bit after the two-bit
    # A->V patch and the five-bit restart patch.
    frontier = {111: (1, [])}
    for depth in range(max_rounds):
        following = {}
        for start, (score, path) in frontier.items():
            options = candidates(start)
            for item in options:
                # A >=7-writer round can be the final 5-bit restart + 2-bit
                # P->R pivot once the persistent gadget is complete.
                if score >= target_payload and len(item.writers) >= 7:
                    return sequence, path + [item], score, candidate_cache
                next_start = item.end + 1
                new_score = score + len(item.writers) - 5
                candidate = (new_score, path + [item])
                old = following.get(next_start)
                if old is None or new_score > old[0]:
                    following[next_start] = candidate
        if not following:
            raise RuntimeError(f"beam exhausted after {depth} rounds")
        ranked = sorted(
            following.items(),
            key=lambda pair: (
                pair[1][0],
                -sum(p.end - p.start for p in pair[1][1]),
            ),
            reverse=True,
        )[:beam_width]
        frontier = dict(ranked)
        best_start, (best_score, best_path) = max(
            frontier.items(), key=lambda pair: pair[1][0]
        )
        checkpoint = Path(__file__).with_name("fast_checkpoint.pkl")
        with checkpoint.open("wb") as file:
            pickle.dump((sequence, best_path, best_score, best_start), file)
        text_checkpoint = checkpoint.with_suffix(".txt")
        text_checkpoint.write_text("\n".join(
            f"{p.start} {p.trigger} {p.high_width} {p.end} "
            f"{','.join(map(str, p.writers))}"
            for p in best_path
        ) + f"\nnext={best_start} payload={best_score}\n")
        print(
            f"depth={depth+1} frontier={len(frontier)} "
            f"best_payload={max(value[0] for value in frontier.values())}",
            flush=True,
        )
    raise RuntimeError("no schedule within round limit")


if __name__ == "__main__":
    sequence, plans, score, _ = find_schedule()
    for number, item in enumerate(plans, 1):
        print(
            f"round={number:02d} start={item.start} trigger={item.trigger} "
            f"high={item.high_width} end={item.end} "
            f"writers={item.writers} capacity={len(item.writers)} "
            f"payload={max(0, len(item.writers)-5)}"
        )
    output = Path(__file__).with_name("full_main_schedule.pkl")
    with output.open("wb") as file:
        pickle.dump((sequence, [p.__dict__ for p in plans], score), file)
    print(f"saved {output} total_payload={score}")
