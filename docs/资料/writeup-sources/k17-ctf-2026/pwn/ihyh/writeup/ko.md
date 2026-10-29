# ihyh

> 스포일러: 이 문서는 문제의 분석 과정과 최종 풀이를 포함합니다.

## 개요

| 항목 | 내용 |
|---|---|
| 상태 | solved |
| 대회·플랫폼 | K17 CTF 2026 |
| 분야 | pwn |
| 난이도 | hard |
| 배점 | 213 |
| 작성자 | 미제공 |
| Flag 형식 | `K17{...}` |

이 문제는 note의 생성·수정·삭제와 수정 이력 조회 기능을 제공하는 x86-64 heap 문제다. 결정적인 결함은 이력 파일을 닫은 뒤 전역 `FILE *fp`를 비우지 않는 UAF이며, 472바이트 note로 glibc의 `locked_FILE` 객체를 재사용할 수 있다. 남은 vtable 포인터로 libc를 누출하고, 가짜 FILE의 read/write 동작으로 heap 누출과 tcache poisoning을 만든 뒤 House of Apple 2로 `/flag`를 읽었다.

## 환경 및 초기 분석

공식 입력은 [handout.zip](../challenge/handout.zip)이며 내부에 [chal](../challenge/ihyh/chal)과 [Dockerfile](../challenge/ihyh/Dockerfile)이 있다. ZIP의 SHA-256은 `4a503795553ea58a6938de352353aece54d0e6fd449e41c11a3e677830203a77`, ELF의 SHA-256은 `f378d988d5face9d7c2cd1946f686e7bf224524a64e04844f36c535c925874c3`이다.

`readelf`와 `objdump`로 Full RELRO, NX, PIE, stack canary를 확인했다. 바이너리는 strip되지 않아 `create`, `edit`, `delete`, `view`, `view_history` 심볼이 남아 있다. Dockerfile은 `ubuntu:22.04@sha256:2edbbc...`를 고정하며, 이 이미지에서 추출한 [libc.so.6](../analysis/runtime/usr/lib/x86_64-linux-gnu/libc.so.6)은 Ubuntu GLIBC `2.35-0ubuntu3.14`, build ID `22ca0a83a4004122e30a69b597be96e134068616`이다. 분석에는 Python 3.12.10, GDB 15.1, GNU Binutils 2.42를 사용했다. Solver는 표준 라이브러리만 사용하므로 [requirements.txt](../../../requirements.txt)는 비어 있다.

## 핵심 분석

전역 `hate` 배열의 각 원소는 note 포인터와 32-bit 크기를 갖고, `create()`는 1~512바이트를 `malloc`한 뒤 같은 길이를 `read`한다. `view()`와 `edit()`는 note를 `%s`로 처리하지만 `read` 뒤에 항상 NUL을 붙이지 않는다.

`edit()`가 처음 호출되면 `/tmp/log.txt`를 `a+`로 열어 전역 `fp`에 저장한다. 반면 `view_history()`는 `rewind`, `fgetc`, `fclose`를 호출한 뒤 `fp = NULL`을 수행하지 않는다. GDB에서 이 FILE 객체의 usable size가 472바이트임을 확인했다.

다음 순서로 dangling FILE을 unsorted bin에 보냈다.

1. 16바이트 note를 수정해 `fp`를 열어 둔다.
2. 472바이트 note 7개를 만들고 모두 삭제해 0x1e0 tcache bin을 채운다.
3. `view_history()`로 `fp`를 닫는다. tcache가 가득 찼으므로 FILE chunk는 unsorted bin으로 간다.
4. 472바이트 note 7개를 다시 만들어 tcache를 비운다.
5. 464바이트 note를 만든다. 이 요청도 0x1e0 chunk를 사용하지만 앱은 처음 464바이트만 초기화한다.

`locked_FILE`의 offset `0x1d0`에는 `_IO_wfile_jumps`가 남는다. 464개의 `L` 뒤에 NUL이 없으므로 `view()`의 `%s`가 이 포인터까지 출력한다. 누출값에서 `0x2170c0`을 빼 libc base를 얻었다.

그 다음 같은 chunk를 `_IO_file_jumps` 기반 가짜 FILE로 만들었다. `_IO_write_base`와 `_IO_write_ptr`를 원하는 주소 범위로 설정하고 fd를 1로 두면 `fwrite()`가 그 범위를 stdout으로 flush한다. 이 primitive로 `_IO_list_all - 0x1d0`에서 472바이트를 보존하고 `main_arena.top`을 읽었다. 관찰된 heap 관계는 다음과 같다.

```text
fake FILE address = top - 0x1f00
tcache victim     = top - 0x0d10
```

가짜 FILE을 buffer-write 모드로 바꾸면 `edit()`이 만든 history 문자열을 heap에 복사할 수 있다. history의 고정 prefix는 44바이트이므로 쓰기 시작점을 `victim - 44`로 잡고, note의 첫 6바이트에 다음 값을 배치했다.

```text
encoded_next = (_IO_list_all - 0x1d0) ^ (victim >> 12)
```

두 chunk를 tcache에 넣은 뒤 이 값을 head의 `next`에 쓰고 첫 chunk를 꺼내면, 다음 allocation은 `_IO_list_all - 0x1d0`을 반환한다. 이 472바이트 구간에는 stdin이 참조하는 wide-data 상태도 있으므로 전부 0으로 두면 다음 `scanf`가 깨진다. 앞서 보존한 런타임 472바이트를 그대로 복원하고 마지막 qword, 즉 `_IO_list_all`만 fake FILE 주소로 바꿨다.

마지막 FILE에는 `_IO_write_ptr > _IO_write_base`, `_IO_wfile_jumps`, 유효한 lock, chunk 내부의 fake `_wide_data`를 배치했다. fake wide vtable의 `__doallocate` slot은 `system`을 가리키고 FILE 시작은 `  cat /flag\0`이다. 메뉴 6의 `exit(1)`이 `_IO_list_all`을 순회하면 `_IO_wfile_overflow` → `_IO_wdoallocbuf` → `system(fp)`로 이어진다.

전체 offset과 GDB 관찰값은 [analysis/notes.md](../analysis/notes.md), 구현은 [solve.py](../solve.py)에 있다.

## 풀이 및 재현

대회 공용 `.venv`를 활성화하고 challenge root에서 실행한다. 최종 solver는 [../solve.py](../solve.py)에 있으며 접속 정보는 [instance.json](../instance.json)에서 읽는다.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

Solver는 NUL 또는 newline이 safe-linking 포인터의 하위 6바이트에 생기는 ASLR 경우에만 새 연결로 재시도한다. 성공 시 stdout에는 flag byte만 쓰고 newline을 붙이지 않는다.

## 결과

정확한 glibc를 사용한 로컬 복제에서 House of Apple 체인이 `LOCAL_HOUSE_OF_APPLE_OK` 표식을 출력했다. 공식 endpoint에서 `python solve.py`는 exit code 0, 빈 stderr, 48바이트 stdout을 반환했고 [flag](../flag)와 byte 단위로 일치했다.

```text
K17{50pp1n355_0f_l0v3_f1nd1ng_1t5_way_1n_f1l35!}
```

## 정리 및 회고

FILE UAF에서는 요청 크기가 FILE allocation과 같다는 사실만으로 충분하지 않다. 앱이 초기화하는 길이와 allocator의 usable size 차이를 이용하면 객체 끝의 vtable 포인터를 보존해 누출할 수 있다. 또한 tcache를 libc 정적 영역으로 유도할 때는 목표 포인터만 생각하지 말고 allocation 전체가 덮는 인접 상태를 보존해야 한다. 이 문제에서는 `_IO_list_all` 앞 472바이트를 먼저 읽고 복원한 것이 이후 stdin 사용을 가능하게 했다.

## 참고 자료

- [K17 CTF 2026 공식 사이트](https://k17ctf.secso.cc/): 대회와 문제 환경 확인.
- [GNU C Library 2.35 소스](https://sourceware.org/git/?p=glibc.git;a=tree;h=refs/heads/release/2.35/master;hb=refs/heads/release/2.35/master): `malloc` safe-linking과 `libio` FILE 동작 확인.
- [Docker Official Image의 Ubuntu 22.04 이미지](https://hub.docker.com/_/ubuntu): Dockerfile의 고정 OCI digest에서 정확한 amd64 glibc 추출.
- 제3자 문제 라이트업은 사용하지 않았다.
