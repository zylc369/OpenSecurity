# baiby-pwn

> 스포일러: 이 문서는 문제의 분석 과정과 최종 풀이를 포함합니다.

## 개요

| 항목 | 내용 |
|---|---|
| 상태 | solved |
| 대회·플랫폼 | BlackHat MEA Qualification CTF 2026 |
| 분야 | `pwn` |
| 난이도 | not provided |
| Flag 형식 | `BHFlagY{...}` |

음수 인덱스 쓰기와 glibc 파일 구조 악용을 결합해 원격 파일을 읽는 바이너리 익스플로잇 문제다.

## 환경 및 초기 분석

보호 기법과 배열 인덱스 검사를 확인하고, 풀이 중 보존한 libc를 기준으로 GOT 및 파일 구조 오프셋을 다시 고정했다. 기존 단계별 익스플로잇을 하나의 자동 실행으로 유지했다.

## 핵심 분석

음수 인덱스로 GOT 주변과 stdout 구조에 접근해 원시 쓰기와 주소 누출을 만든다. libc와 스택 기준 주소를 얻은 뒤 setcontext 기반 체인으로 디렉터리와 플래그 파일을 읽는다.

```text
Protections: Partial RELRO, stack canary, NX, no PIE
Fault: unchecked negative arr[i]
Primitives: GOT write + stdout FSOP leak
Runtime: glibc 2.39
Endgame: setcontext -> open -> getdents -> read
```

## 풀이 및 재현

[`../solve.py`](../solve.py)는 보존된 libc와 [`../instance.json`](../instance.json)의 TCP 주소를 사용해 전체 익스플로잇을 실행한다.

```bash
python solve.py
```

## 결과

원본 풀이에서 검증된 결과를 루트의 `flag`와 대조했다.

```text
BHFlagY{7e972e2c3d079ab499db13f678ebfbd0}
```

## 정리 및 회고

작은 범위의 음수 인덱스도 인접한 전역 구조가 강한 원시 기능으로 확장될 수 있다. 누출, 임의 쓰기, 파일 읽기를 분리해 검증한 것이 안정성에 도움이 됐다.

## 참고 자료

- [원본 분석](../analysis/original-write-up.md)
- [공식 배포물](../challenge/)
