# baiby-pwn

## 문제 정보

- 분야: PWN
- 설명: `tainy bainary`
- 바이너리: `baiby-pwn`
- 보호 기법: Partial RELRO, Canary, NX, No PIE, SHSTK/IBT note
- 제공 런타임: Ubuntu 24.04, glibc 2.39

## 요약

`arr[i] = v`에서 `i`의 범위를 검사하지 않아 음수 인덱스로 writable GOT와
`.bss`의 표준 스트림 포인터를 덮을 수 있다. 입력값은 7바이트 `atol()`로
파싱되므로 높은 libc·스택 주소를 직접 기록할 수 없지만, 다음 세 주소는
7자리 십진수로 기록할 수 있다.

- `__stack_chk_fail@GOT = 0x401259`: `main`의 입력 루프로 복귀
- `memset@GOT = 0x401231`: `stdout` 포인터를 `rax`에 읽고 `setbuf` 호출
- `setbuf@GOT = 0x4011e2`: `read(0, rax, rdx)` 실행

opcode 2는 원래 `memset(arr, 0, 0x40)`을 호출하므로 `rdx = 0x40`이 유지된다.
위 리다이렉션을 조합하면 `read(0, stdout, 0x40)`이 되어 libc의
`_IO_2_1_stdout_` 객체 앞 64바이트를 자유롭게 고칠 수 있다.

## 취약점

```c
case 1:
    i = getval();
    v = getval();
    arr[i] = v;
    break;
```

`arr`는 8개 원소뿐이지만 `i`에 대한 검사 없이 qword 쓰기를 수행한다.
No PIE이므로 다음 음수 인덱스가 고정된다.

| 인덱스 | 대상 |
|---:|---|
| `-16` | `__stack_chk_fail@GOT` (`0x404000`) |
| `-15` | `setbuf@GOT` (`0x404008`) |
| `-14` | `memset@GOT` (`0x404010`) |
| `-8` | `stdout` COPY relocation (`0x404040`) |

## 익스플로잇

### 1. 64바이트 raw write

`memset@GOT`를 `0x401231`로 보내면 다음 코드가 실행된다.

```asm
mov rax, [stdout]
mov esi, 0
mov rdi, rax
call setbuf@plt
```

`setbuf@GOT`를 `0x4011e2`로 보내면 `rax`를 목적지로 사용하는 다음 조각과
연결된다.

```asm
mov rsi, rax
mov edi, 0
call read@plt
```

opcode 2가 설정한 `rdx = 0x40`이 그대로 남으므로 결과는
`read(0, *stdout_copy, 0x40)`이다. 뒤이어 `getval`의 카나리 검사가 실패하지만,
`__stack_chk_fail@GOT`를 `0x401259`로 바꾸어 둬 같은 `main` 프레임의 루프로
돌아간다.

### 2. FSOP 임의 읽기

raw write로 실제 `stdout` 객체의 처음 64바이트를 다음과 같이 위조한다.

```text
_flags         = 0xfbad1801  (_IO_CURRENTLY_PUTTING | _IO_USER_BUF 포함)
_IO_read_ptr   = target
_IO_read_end   = target
_IO_read_base  = target
_IO_write_base = target
_IO_write_ptr  = target + size
_IO_write_end  = target + size
_IO_buf_base   = target
```

vtable은 건드리지 않는다. 이후 `setbuf@GOT`를 원래 PLT lazy-binding stub인
`0x401040`으로 되돌리고 opcode 2를 실행하면 진짜 `setbuf(stdout, NULL)`이
호출된다. 내부 flush가 `[target, target + size)`를 표준 출력으로 내보낸다.
`_IO_USER_BUF` 비트는 위조한 `_IO_buf_base`를 `free()`하지 못하게 하므로 같은
연결에서 이 읽기 원시 기능을 반복할 수 있다.

이 기능으로 다음을 순서대로 읽는다.

1. `0x403fd8`의 `__libc_start_main` GOT 값으로 libc 베이스 계산
2. libc의 `__environ`으로 스택 주소 획득
3. `environ - 0x1000`부터 스택을 읽어 `libc_base + 0x2a1ca` 검색

`0x2a1ca`는 제공 libc에서 `__libc_start_call_main`이 `main()`을 호출한 직후의
주소이므로, 검색된 qword가 `main`의 저장 RIP 슬롯이다.

### 3. 제한 없는 주소 쓰기와 스택 피벗

`stdout` COPY relocation 자체는 `0x404040`이라는 낮은 주소에 있다.
먼저 `arr[-8] = 0x404040`으로 만든 뒤 raw write를 수행하면 첫 qword에 임의의
64비트 목적지를 넣을 수 있다. 다음 opcode 2는 그 높은 libc·스택 주소에
64바이트를 기록한다. 이 과정을 반복해 스택 아래쪽에 ROP 영역을 구성한다.

제공 glibc에는 간단한 `pop rdx; ret`이 없으므로 각 파일 연산은
`setcontext()` 프레임으로 레지스터를 설정한다. 구성한 연산은 다음과 같다.

1. `open("/", O_DIRECTORY)`
2. `getdents64(3, dirbuf, 0x400)`
3. `write(1, dirbuf, 0x400)`
4. `read(0, pathbuf, 0x40)`
5. `open(pathbuf, O_RDONLY)`
6. `read(4, filebuf, 0x100)`
7. `write(1, filebuf, 0x100)`

마지막으로 저장 RIP를 `pop rsp; ret`과 ROP 영역 주소로 덮고 잘못된 opcode를
보내 `main`을 반환시킨다. 디렉터리 출력에서 `flag-[0-9a-f]{32}.txt`를 찾아
두 번째 단계의 `read()`에 전체 경로를 보내면 플래그가 출력된다.

## 재현

```bash
python3 solve.py
```

호스트와 포트가 바뀌었다면 다음처럼 지정한다.

```bash
python3 solve.py --host tcp.flagyard.com --port PORT
```

제공 libc를 로드한 네이티브 로컬 서비스에서 ASLR이 서로 다른 두 실행 모두
libc 베이스, `__environ`, 저장 RIP를 찾아 `/etc/hostname`을 읽는 데 성공했다.

## 플래그

```text
BHFlagY{7e972e2c3d079ab499db13f678ebfbd0}
```
