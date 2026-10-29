# huge binary 2

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

이 문제는 스택 기준 1바이트 OOB read와 두 번의 31바이트 format string을 제공한다. 핵심은 제공된 glibc의 `main` 반환 지점을 1바이트만 바꿔 같은 프로세스에서 `main`을 반복 호출하고, 두 format string을 파이프라인으로 사용해 스택에 ROP 체인을 만드는 것이다.

## 환경 및 초기 분석

공식 입력은 [handout.zip](../challenge/handout.zip), [chal](../challenge/huge-binary-2/chal), [libc.so.6](../challenge/huge-binary-2/libc.so.6), [Dockerfile](../challenge/huge-binary-2/Dockerfile)이다. `chal`의 SHA-256은 `17801b24ad804e3785c96bc1860dde06117bf3a5bb65667fc28ce37cfe7efca5`이고, 제공 libc의 SHA-256은 `adeedbc69ac402b762a3bd94759441e0546c33972cb2c0f5bc6869a2d32efed6`이다.

GNU Binutils 2.42로 확인한 바이너리는 x86-64 PIE이며 NX, Partial RELRO가 적용되어 있고 stack canary는 없다. 공용 Python 3.12.10 환경은 [requirements.txt](../../../requirements.txt)로 복원하며 solver는 표준 라이브러리만 사용한다. `main`은 `scanf("%d")`로 받은 signed index를 `rbp + index - 1`의 바이트 읽기에 사용하고, 두 번의 `scanf("%31s")` 결과를 각각 format 인자로 `printf`에 전달한다.

## 핵심 분석

원격 스택에서 arg19는 `libc_base + 0x29ca8`, arg21은 PIE의 `main`, arg20은 arg50 슬롯의 주소였다. arg50은 처음에 저장된 RIP보다 정확히 `0x100` 높은 주소를 가리킨다. Index `258`은 arg50 포인터의 두 번째 바이트를 읽는다. 이 바이트에서 1을 빼고, 16바이트 정렬로 가능한 하위 바이트 `0x08`부터 `0xf8`까지 시도하면 `%20$hn`으로 arg50을 저장된 RIP에 맞출 수 있다.

제공된 Debian glibc `2.41-12+deb13u2`에서 정상 반환 지점 주변은 다음과 같다.

```text
0x29ca1: mov rax, qword ptr [rsp+8]
0x29ca6: call rax
0x29ca8: mov edi, eax
0x29caa: call exit
```

따라서 `%161c%50$hhn`으로 반환 주소의 하위 바이트를 `0xa1`로 바꾸면 저장된 `main` 포인터를 다시 호출한다. 재호출할 때 `0x29ca8`이 저장된 RIP에 다시 push되므로, 각 반쪽워드 쓰기는 두 번의 호출로 구성한다. 첫 호출에서 루프를 유지하며 arg50을 목적지로 바꾸고, 다음 호출에서 값을 쓴 뒤 arg50과 하위 바이트 `0xa1`을 복구한다. 정확한 원격 관찰과 스택 배치는 [분석 증거](../analysis/notes.md)에 기록했다.

## 풀이 및 재현

[solve.py](../solve.py)는 `instance.json`에서 TCP endpoint를 읽고 다음 작업을 자동화한다.

1. Index `258`의 누출과 하위 바이트 16개 후보를 이용해 같은 프로세스의 `main` 재호출을 만든다.
2. arg19, arg21, 재지정된 arg50에서 libc base, PIE base, 저장된 RIP 주소를 구한다.
3. 반복 반쪽워드 쓰기로 `pop rdi; ret`, 명령 주소, `system`, `exit`, `cat</flag`를 스택에 배치한다.
4. 마지막 두 format string으로 저장된 RIP와 caller의 `main` 슬롯을 동시에 전환해 ROP를 실행한다.

Competition의 `.venv`를 활성화하고 challenge root에서 실행한다.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

## 결과

기본 모드에서 `python solve.py`는 exit code 0, 빈 stderr, trailing newline 없는 31바이트 stdout을 생성했다. 같은 바이트를 `flag` 파일에 기록해 일치 여부를 검증했다.

```text
K17{turn$_0ut_siz3_do3s_m@tter}
```

## 정리 및 회고

짧은 format string도 기존 스택 포인터가 다른 인자 슬롯을 가리키면 강한 쓰기 primitive가 된다. 또한 호출 직후의 libc 명령 경계로 1바이트 partial overwrite를 수행하면 ASLR base를 몰라도 재진입을 만들 수 있다. 이 문제에서는 재호출마다 저장된 RIP가 원상 복구된다는 점 때문에, 대상 지정과 실제 쓰기를 두 호출로 나누는 파이프라인이 필요했다.

## 참고 자료

- 공식 제공 파일인 [chal](../challenge/huge-binary-2/chal), [libc.so.6](../challenge/huge-binary-2/libc.so.6), [Dockerfile](../challenge/huge-binary-2/Dockerfile)을 정적 분석과 원격 환경 확인에 사용했다.
- 외부 풀이 또는 비공식 자료는 사용하지 않았다.

