# Bug Where

> 스포일러: 이 문서는 문제의 분석 과정과 최종 풀이를 포함합니다.

## 개요

| 항목 | 내용 |
|---|---|
| 상태 | solved |
| 대회·플랫폼 | BlackHat MEA Qualification CTF 2026 |
| 분야 | `pwn` |
| 난이도 | not provided |
| Flag 형식 | `BHFlagY{...}` |

io_uring 제공 버퍼의 수명 관리 오류를 커널 힙 재사용으로 연결하는 커널 익스플로잇 문제다.

## 환경 및 초기 분석

제공 커널 설정과 패치를 기준으로 취약 경로와 실행 환경을 확인했다. 기존 익스플로잇 소스와 재시도 하네스는 분석 자료로 보존했다.

## 핵심 분석

제공 버퍼 번들의 해제 뒤 남는 iovec 참조를 이용해 이중 해제 상태를 만든다. 해제된 객체를 pipe_buffer로 재점유하고 연산 테이블을 바꿔 커널 권한 상승 경로를 실행한다.

```text
Kernel: Linux 7.2-rc3
Subsystem: io_uring provided-buffer bundles
Fault: dangling iovec -> double free
Reclaim: pipe_buffer
Hardening: CONFIG_KMALLOC_PARTITION_RANDOM
KASLR side channel: QEMU PREFETCH
```

## 풀이 및 재현

[`../solve.py`](../solve.py)는 빌드된 게스트 익스플로잇과 [`../instance.json`](../instance.json)의 TCP 주소를 사용하고, 힙 파티션 충돌이 날 때까지 제한된 횟수로 재시도한다.

```bash
python solve.py
```

## 결과

원본 풀이에서 검증된 결과를 루트의 `flag`와 대조했다.

```text
BHFlagY{ef2d81621299ed9b3a5d1f418cc352d2}
```

## 정리 및 회고

취약점 자체와 실제 재점유 성공률은 별개의 문제다. 랜덤 파티션 환경에서는 새 VM 재시도를 풀이 계약에 포함해야 재현성이 생긴다.

## 참고 자료

- [원본 분석](../analysis/original-write-up.md)
- [공식 배포물](../challenge/)
- [Upstream fix](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=f1596ba3e6b390aa0fef8466afce44efecf39d8d)

