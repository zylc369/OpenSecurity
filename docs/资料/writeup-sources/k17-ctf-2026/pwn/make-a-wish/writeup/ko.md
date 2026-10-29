# make-a-wish

> 스포일러: 이 문서는 문제의 분석 과정과 최종 풀이를 포함합니다.

## 개요

| 항목 | 내용 |
|---|---|
| 상태 | solved |
| 대회·플랫폼 | K17 CTF 2026 |
| 분야 | pwn |
| 난이도 | medium |
| Flag 형식 | `K17{...}` |

메뉴가 wish 번호를 `5`로 나눈 signed 나머지를 검증 없이 인덱스로 사용한다. `wishes[-2]`가 성을 가리키는 스택 포인터와 겹치는 점을 이용하면 이름 버퍼의 가짜 청크를 tcache에 넣을 수 있고, 다음 `malloc(0x90)`을 스택으로 돌려 `fgets`로 `main`의 반환 주소를 덮을 수 있다.

## 환경 및 초기 분석

공식 입력은 [handout.zip](../challenge/handout.zip), [chal](../challenge/make-a-wish/chal), [Dockerfile](../challenge/make-a-wish/Dockerfile)이다. ZIP과 바이너리의 SHA-256은 각각 `af1ba822245a37c6492248a8392fdb3f74f23827d8c17e34671b62fb18d68cd6`, `5f509bcc657e13347a69c8bb0291ba500c48f24adcdfd598b9a6d0bf3a407bbe`이다. 공용 환경은 [requirements.txt](../../../requirements.txt)로 복원했다.

`file` 5.45와 GNU Binutils 2.42로 확인한 `chal`은 x86-64 동적 링크 ELF이며 symbol이 남아 있다. 보호 기법은 No PIE, NX, No Canary, Partial RELRO이다. ELF note에는 IBT와 SHSTK 속성이 있지만 검증된 원격 환경에서 아래 ROP 체인이 실행됐다. Dockerfile은 `/flag`를 복사하고 `pwn.red/jail`에서 `/app/chal`을 서비스한다.

## 핵심 분석

`main`의 주요 스택 배치는 다음과 같다.

| 주소 | 용도 |
|---|---|
| `rbp-0x70` | 두 번째 이름 포인터 |
| `rbp-0x60` .. `rbp-0x40` | `wishes[0..4]` |
| `rbp-0x30` | 30바이트 이름 버퍼 시작 |
| `rbp-0x8` | 첫 번째 이름 포인터 |
| `rbp+0x8` | 저장된 반환 주소 |

`create`와 `delete`는 입력을 signed `number % 5`로 줄이지만 음수인지 검사하지 않는다. 배열 시작이 `rbp-0x60`이므로 `wishes[-2]`는 `rbp-0x70`의 두 번째 이름 포인터다.

초기 이름 입력에서 `rbp-0x30`에 `prev_size = 0`, `size = 0xa1`을 배치하고 offset `0x0f`를 공백으로 둔다. `split`은 이 공백을 NUL로 바꾸고 두 번째 이름을 offset `0x10`, 즉 정렬된 `rbp-0x20`으로 지정한다. 따라서 `delete(-2)`는 `free(rbp-0x20)`을 호출하며, forged `0xa0` 청크가 tcache에 들어간다.

이후 `create(0)`의 `malloc(0x90)`은 `rbp-0x20`을 반환한다. 이어지는 `fgets(..., 0x90, stdin)`에서 시작점부터 저장된 반환 주소까지의 거리는 `0x28`이다. 최종 출력에 쓰이는 첫 번째 이름 포인터는 offset `0x18`에서 `0x402013`의 빈 문자열로 바꾸고, 다음 체인을 기록했다.

| Payload offset | 값 | 의미 |
|---:|---:|---|
| `0x28` | `0x4012e2` | `pop rdi; pop rbp; ret` |
| `0x30` | `0x402011` | 메뉴 문자열 안의 `sh\0` |
| `0x38` | `0` | dummy `rbp` |
| `0x40` | `0x401130` | `system@plt` |
| `0x48` | `0x4011e0` | `exit@plt` |

`0x4012e2`의 gadget은 `sub_401296` 안의 `mov eax, 0x5fc3c031` immediate 중간에서 시작한다. 이 체인은 `system("sh")`를 실행한다. 상세 관찰과 로컬 검증은 [analysis notes](../analysis/notes.md)와 [probe.py](../analysis/probe.py)에 보존했다.

## 풀이 및 재현

[solve.py](../solve.py)는 표준 라이브러리만 사용한다. `instance.json`의 `main` TCP endpoint를 읽고, 가짜 이름 청크 생성 → `delete(-2)` → `create(0)`의 스택 재할당 → ROP 기록 → `system("sh")` 순서로 진행한 뒤 `cat /flag` 결과에서 플래그를 추출한다. 대회 공용 `.venv`를 활성화하고 challenge root에서 실행한다.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

## 결과

로컬 [probe.py](../analysis/probe.py)는 glibc 2.39에서 `LOCAL_CODE_EXECUTION_OK`를 출력하고 exit code 0으로 종료했다. 원격 `python solve.py`도 exit code 0, 빈 stderr로 종료했으며 stdout은 아래 47바이트만 포함했고 trailing newline은 없었다.

```text
K17{my_f4v0ur1t3_fl4v0ur_15_k1w1_p1n34ppl3_btw}
```

검증된 flag는 `K17{my_f4v0ur1t3_fl4v0ur_15_k1w1_p1n34ppl3_btw}`이다.

## 정리 및 회고

작은 signed OOB라도 인접한 포인터가 공격자 입력 내부를 가리키면 arbitrary free로 확장될 수 있다. tcache의 House of Spirit은 가짜 청크의 user pointer를 올바르게 정렬하고 요청 크기와 size class를 맞추는 것이 핵심이다. 또한 작은 non-PIE 바이너리에서는 일반 gadget이 없어도 instruction immediate 내부 바이트와 기존 문자열의 suffix를 ROP 자원으로 사용할 수 있다.

## 참고 자료

- [공식 handout](../challenge/handout.zip): 바이너리와 컨테이너 구성을 제공했다.
- 외부 자료는 사용하지 않았다. 정적 분석에는 로컬 `file` 5.45와 GNU Binutils 2.42를 사용했다.
