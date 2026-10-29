# waf

> 스포일러: 이 문서는 문제의 분석 과정과 최종 풀이를 포함합니다.

## 개요

| 항목 | 내용 |
|---|---|
| 상태 | solved |
| 대회·플랫폼 | K17 CTF 2026 |
| 분야 | pwn |
| 난이도 | medium |
| Flag 형식 | `K17{...}` |

`main`의 80바이트 스택 버퍼에 최대 128바이트를 읽어 반환 주소를 덮을 수 있다. 결정적인 관찰은 NUL 필터가 전체 버퍼가 아니라 매번 `read`가 반환한 범위만 지운다는 점이다. 프롬프트마다 짧은 입력을 동기화하고 높은 오프셋의 NUL부터 역순으로 기록하면 필터 뒤쪽에 이미 만든 ROP 체인을 보존할 수 있다.

## 환경 및 초기 분석

공식 입력은 [handout.zip](../challenge/handout.zip), [chal](../challenge/waf/chal), [Dockerfile](../challenge/waf/Dockerfile)이다. `chal`의 SHA-256은 `5e0712c1b21a83adfc4a6f761455a141956be4f209e74981b76c445e29c4d0ec`이다. ELF는 amd64 동적 실행 파일이며 심볼이 남아 있다. `readelf`와 `objdump`로 확인한 보호 기법은 no PIE, NX, no stack canary, Partial RELRO이다. GNU property에는 IBT와 SHSTK가 표시되지만, 원격에서 반환 주소를 `main`으로 바꿨을 때 배너가 다시 출력되어 해당 경로의 `ret` 제어가 실제로 가능함을 확인했다.

대회 공용 환경은 [requirements.txt](../../../requirements.txt)로 복원한다. 분석에는 ROPGadget 7.7과 Capstone 5.0.9를 사용했고, 최종 [solve.py](../solve.py)는 Python 표준 라이브러리만 사용한다. 주소, 해시, 이미지 digest, glibc offset은 [analysis notes](../analysis/notes.md)에 정리했다.

## 핵심 분석

`main`은 `[rbp-0x50]`부터 80바이트를 0으로 초기화한 뒤 `__gets`를 호출한다. 첫 바이트가 0이면 `__gets`는 같은 버퍼에 `read(0, buf, 0x80)`을 수행하므로 saved RIP는 오프셋 88에서 시작한다. 그 다음 호출부터는 `strlen(buf)`를 읽기 크기로 사용한다.

각 `read` 뒤의 필터는 반환 길이를 `n`이라 할 때 `buf[0:n]`만 순회한다. 처음 발견한 NUL의 오프셋을 `i`라고 하면 `memset(buf+i, 0, n-i)`를 실행한다. 따라서 한 번에 일반적인 64비트 주소를 쓰면 첫 NUL 뒤의 체인이 사라지지만, 다음 절차로 우회할 수 있다.

1. NUL이 없는 `A` 128바이트를 보내 스택 영역 전체에 보존할 suffix를 만든다.
2. 목표 payload의 NUL 오프셋을 큰 값부터 작은 값 순으로 처리한다.
3. 오프셋 `i` 단계에서는 목표 prefix `payload[:i+1]`만 보낸다. 아직 처리하지 않은 더 낮은 NUL은 `A`로 바꾸고, 중간 단계의 앞 4바이트도 `AAAA`로 두어 루프를 계속한다.
4. `read`가 정확히 `i+1`바이트를 반환하므로 필터는 `i`보다 뒤에 이미 만든 suffix를 지울 수 없다. 마지막 단계만 `exit`로 시작해 `main`이 반환하도록 한다.

첫 번째 ROP 스택은 다음과 같다.

| 버퍼 오프셋 | 값 | 역할 |
|---:|---|---|
| 0–79 | `exitLEAK%6$sEND\n` + padding | `printf` format |
| 80–87 | filler | saved RBP |
| 88–95 | `0x4010d0` | `printf@plt` |
| 96–103 | `0x4012a2` | `main`으로 복귀 |
| 104–111 | `0x404020` | `%6$s`가 역참조할 `puts@got` |

이 체인은 resolved `puts` 주소 6바이트를 출력하고 `main`으로 돌아간다. Dockerfile의 `debian:13.4-slim` index digest `sha256:4ffb3a1511099754cddc70eb1b12e50ffdb67619aa0ab6c13fcd800a78ef7c7a`에서 amd64 glibc를 추출했다. 사용한 offset은 `puts=0x805a0`, `system=0x53110`, `"/bin/sh"=0x1a5ea4`, `pop rdi; ret=0x2a145`이다.

두 번째 스택은 오프셋 88부터 `pop rdi; ret`, `"/bin/sh"`, 정렬용 `ret`, `system` 순으로 배치한다. 같은 역순 NUL 기록 기법으로 체인을 만든 뒤 `system("/bin/sh")`에 진입하고 `cat /flag`를 전송한다.

## 풀이 및 재현

[solve.py](../solve.py)는 [instance.json](../instance.json)에서 TCP endpoint를 읽고 다음 과정을 한 연결에서 자동 수행한다.

- 공식 `chal`의 SHA-256 검증
- 역순 짧은 쓰기로 stage 1 구성 및 `puts` 유출
- page-aligned libc base 계산
- stage 2 구성 및 `/bin/sh` 실행
- `/flag` 출력에서 `K17{...}` 추출

대회 `.venv`를 활성화한 뒤 challenge root에서 실행한다.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

성공 시 stdout에는 trailing newline 없이 flag 바이트만 출력되고 stderr는 비어 있다.

## 결과

`python solve.py`는 exit code 0, 빈 stderr, 32바이트 stdout을 반환했다. stdout과 [flag](../flag)의 바이트가 일치하며 최종 검증에서도 원격 runtime 재실행이 통과했다.

```text
K17{ma_a1n7_pr0uD_0f_me_n0_m0r3}
```

## 정리 및 회고

입력 정화가 현재 syscall이 반환한 구간만 다루고 이전 버퍼 suffix를 유지하면, 공격자는 짧은 쓰기를 동기화해 payload를 뒤에서 앞으로 조립할 수 있다. NUL을 제거하거나 뒤를 0으로 만드는 동작 자체보다 버퍼 전체 수명과 다음 읽기 길이의 관계를 함께 검증해야 한다. 또한 컨테이너 이미지 digest가 고정되어 있으면 함수 유출 하나로 정확한 libc offset을 재현할 수 있다.

## 참고 자료

- [공식 Dockerfile](../challenge/waf/Dockerfile): 실행 환경과 고정 Debian 이미지 digest 확인.
- [공식 chal](../challenge/waf/chal): 함수, 보호 기법, overflow와 필터 로직 분석.
- ROPGadget 7.7: glibc의 `pop rdi; ret` offset 확인.
- Docker Registry v2 응답: 고정 이미지에서 linux/amd64 manifest와 rootfs layer 선택.
- 외부 풀이 또는 문제 해설은 사용하지 않았다.
