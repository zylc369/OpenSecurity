# not json

> 스포일러: 이 문서는 문제의 분석 과정과 최종 풀이를 포함합니다.

## 개요

| 항목 | 내용 |
|---|---|
| 상태 | solved |
| 대회·플랫폼 | K17 CTF 2026 |
| 분야 | pwn |
| 난이도 | hard |
| 점수 | 219 |
| Flag 형식 | `K17{...}` |

재귀 JSON 유사 파서의 key 정규화는 길이 제한용 counter를 감소시키면서도 `buffer[strlen(buffer)]`에는 계속 문자를 추가한다. 이 stack overflow로 canary, PIE, libc를 누출한 뒤, 정렬된 재귀 프레임의 saved `rbp` 하위 바이트를 바꿔 상위 프레임의 description buffer로 stack pivot했다.

## 환경 및 초기 분석

원본 [handout.zip](../challenge/handout.zip)의 SHA-256은 `F3ED77F1A952F55403794579A83CBA81DCE614BDD2B9880A3D4AD7B4396B8340`이며, ELF [chal](../challenge/notjson/chal)의 SHA-256은 `F192460B07BAD0E04EB3DC2736A55847302CCF6077826223CF1AA7DB3289642E`이다. [Dockerfile](../challenge/notjson/Dockerfile)은 `debian@sha256:1d3c811171a08a5adaa4a163fbafd96b61b87aa871bbc7aa15431ac275d3d430`과 `pwn.red/jail`을 사용하고 `/flag`를 chroot 안에 배치한다.

`readelf` 결과 ELF는 x86-64 PIE(`ET_DYN`)이고 `GNU_RELRO`와 `BIND_NOW`가 있어 Full RELRO이다. `GNU_STACK`은 `RW`여서 NX가 켜져 있고, `__stack_chk_fail` 참조와 함수 prologue에서 stack canary도 확인된다. 분석에는 Python 3.12.10, file 5.45, GNU Binutils 2.42, GDB 15.1을 사용했다. Solver는 Python 표준 라이브러리만 사용하므로 [공용 requirements.txt](../../../requirements.txt)는 비어 있다.

## 핵심 분석

`do_parse_json_object`의 frame 크기는 `0x70`이고 key/description은 같은 40-byte buffer(`rbp-0x30`)를 사용한다. key 처리의 본질은 다음과 같다.

```c
buffer[strlen(buffer)] = c;
counter++;
if (!isalnum(c) && c != '_') {
    buffer[strlen(buffer) - 1] = '_';
    counter--;
}
```

따라서 `!` 같은 문자는 counter를 늘리지 않지만 NUL을 하나씩 메우며 buffer 밖으로 진행한다. 반면 영숫자는 후속 `strlen` 정규화를 거치지 않으므로 포인터 바로 앞 byte를 보존하는 데 쓸 수 있다.

첫 누출은 `!` 40개와 `ABC`를 사용한다. `A`가 canary의 NUL byte를, `B`, `C`가 saved `rbp`의 상위 NUL 두 개를 채운 뒤 `|`로 멈추면 `%s` 출력은 62 byte가 된다. 이 중 `41..47`에서 canary의 나머지 7 byte, `48..53`에서 stack 주소, `56..61`에서 `PIE+0x161a`를 얻는다. 이어 description을 정확히 40 byte 쓰면 종료 NUL이 canary의 첫 byte를 다시 `0x00`으로 복구한다.

`run_aligned`는 `mov sp, 0`과 `sub rsp, 0x20000`으로 parser stack을 정렬한다. Root key buffer에서 `run_aligned`의 원래 frame pointer slot은 항상 offset `0x250`에 있고, 그 frame의 `+0x18`에는 libc startup return address가 있다. Docker digest에서 추출한 libc(SHA-256 `06E87BC6946702848D7F6AEB7E3759CA904458EFD8C3DED85CA63099944181ED`)로 다음 offset을 확정했다.

| 대상 | Offset |
|---|---:|
| libc startup return | `0x29ca8` |
| `system` | `0x53110` |
| `"/bin/sh"` | `0x1a6ea4` |

장거리 누출은 libc 포인터 뒤의 NUL에서 정확히 멈춰 포인터의 최상위 유효 byte를 보존한다. [solve.py](../solve.py)는 보수적인 non-NUL 상한 `0x900`에서 시작하고, 짧은 후속 key로 다음 NUL까지 한 칸씩 진행해 출력 길이가 목표 offset과 같아질 때 libc 주소를 읽는다.

마지막으로 `run_aligned+0x1f`, 즉 `PIE+0x11e8`에는 `mov` 즉시값 안에 숨은 `pop rdi; ret`가 있다. Root `rbp`의 하위 16 bit는 `0xfdd0`이고 재귀 frame마다 `0x70`씩 감소하므로 depth 11의 `rbp`는 `...f900`이다. Depth 12 key에서 `!` 40개, canary용 `A`, pivot용 `H`(`0x48`)를 쓰면 depth 11의 saved `rbp`가 depth 10 description buffer의 `+8`을 가리킨다. 그 40-byte buffer에는 다음 fake frame을 둔다.

```text
+0x00  canary
+0x08  fake rbp
+0x10  PIE+0x11e8          pop rdi; ret
+0x18  libc+0x1a6ea4      "/bin/sh"
+0x20  libc+0x53110       system
```

Depth 11이 `leave; ret`를 실행하면 이 frame으로 pivot하고 `system("/bin/sh")`이 실행된다.

## 풀이 및 재현

[solve.py](../solve.py)는 [instance.json](../instance.json)만으로 endpoint를 읽고, 주소에 우연한 NUL 또는 `"`가 포함된 연결은 안전하게 다시 시도한다. Competition의 `.venv`를 활성화한 뒤 challenge root에서 실행한다.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

Solver는 shell에 `cat /flag`를 보내고 `K17{...}` 한 개만 stdout에 출력한다.

## 결과

2026-09-12 원격 `chal.secso.cc:4003`에서 실행한 결과 exit code `0`, 빈 stderr, 무개행 stdout을 확인했다.

```text
K17{b3cau$e_rbp_taste$_bett3r_th@n_key}
```

동일한 39 byte가 challenge root의 `flag` 파일에 무개행으로 기록되었다.

## 정리 및 회고

길이 제한 counter와 실제 write 위치가 다른 상태를 기준으로 계산되면, 입력 정규화 자체가 unbounded write가 될 수 있다. 또한 재귀 frame 크기와 강제 stack alignment를 함께 계산하면 단일-byte saved-frame-pointer overwrite만으로도 작은 buffer 안의 fake frame을 정확히 선택할 수 있다. 즉시값 내부의 unaligned instruction도 유효한 ROP gadget이므로 정상 instruction 경계만 검색해서는 안 된다.

## 참고 자료

- [Docker Official Image: Debian](https://hub.docker.com/_/debian): Dockerfile에 고정된 Debian 13.3 slim digest의 amd64 libc를 확인하는 데 사용했다.
- [pwn.red/jail](https://github.com/redpwn/jail): 제공 Dockerfile의 chroot 및 `/app/run` 서비스 구성을 확인하는 데 사용했다.
- 외부 풀이 또는 write-up은 사용하지 않았다.

