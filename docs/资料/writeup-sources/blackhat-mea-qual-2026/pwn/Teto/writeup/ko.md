# Teto

> 스포일러: 이 문서는 문제의 분석 과정과 최종 풀이를 포함합니다.

## 개요

| 항목 | 내용 |
|---|---|
| 상태 | solved |
| 대회·플랫폼 | BlackHat MEA Qualification CTF 2026 |
| 분야 | `pwn` |
| 난이도 | hard |
| Flag 형식 | `BHFlagY{...}` |

게임판의 음수 좌표 버그를 단일 비트 OR 쓰기와 주소 누출로 확장하는 복합 바이너리 익스플로잇 문제다.

## 환경 및 초기 분석

원본 바이너리와 소스에서 좌표 검사, 난수 소비 순서, 스택 프레임 변화를 확인했다. 기존 플래너와 검증된 스케줄은 분석 자료로 보존했다.

## 핵심 분석

음수 y 좌표로 인접 스택 바이트의 한 비트를 OR하고, 보드 폭을 바꿔 PIE, libc, 스택 주소를 누출한다. glibc 난수 순서를 예측해 여러 게임에 걸쳐 프레임을 수정하고 posix_spawn 경로로 셸을 실행한다.

```text
Fault: set_cell accepts y == -1
Write primitive: one-bit OR
Leaks: PIE + libc + stack
Schedule source: deterministic glibc rand
Endgame: posix_spawn('/bin/sh')
Mitigations: IBT + SHSTK
```

## 풀이 및 재현

[`../solve.py`](../solve.py)는 검증된 스케줄 자산과 [`../instance.json`](../instance.json)의 TCP 주소를 불러와 반복 연결을 자동화한다.

```bash
python solve.py
```

## 결과

원본 풀이에서 검증된 결과를 루트의 `flag`와 대조했다.

```text
BHFlagY{6c890129abf30a3d6fb7d2b7bdb9606e}
```

## 정리 및 회고

약한 단일 비트 쓰기도 대상 상태와 난수 순서를 예측할 수 있으면 누적 공격이 된다. 스케줄 생성과 실제 전송을 분리한 구조가 디버깅에 중요했다.

## 참고 자료

- [원본 분석](../analysis/original-write-up.md)
- [공식 배포물](../challenge/)

