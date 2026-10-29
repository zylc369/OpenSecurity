# upyx

> 스포일러: 이 문서는 문제의 분석 과정과 최종 풀이를 포함합니다.

## 개요

| 항목 | 내용 |
|---|---|
| 상태 | solved |
| 대회·플랫폼 | BlackHat MEA Qualification CTF 2026 |
| 분야 | `reverse` |
| 난이도 | not provided |
| Flag 형식 | `BHFlagY{...}` |

PyInstaller와 Cython으로 패키징된 Windows 프로그램의 자기변형 검증기를 동적 계측으로 푸는 문제다.

## 환경 및 초기 분석

배포 실행 파일의 PyInstaller 구성과 Cython 확장, 명명 파이프 통신을 원본 분석과 대조했다. 기존 Frida 계측과 복구 상수를 최종 솔버에 보존했다.

## 핵심 분석

파일명 접미사가 시드를 결정하고 파이프를 통해 검증 프로세스가 시작된다. Python C API 호출을 후킹한 토큰 오라클로 입력을 점진적으로 복구하고 마지막 묶음을 확인한다.

```text
Input: Challenge.exe
Packaging: PyInstaller + Cython
IPC: Windows named pipes
Instrumentation: Frida Python C API hook
Recovered length: 60 characters
Embedded verifier constant: 960 bytes
```

## 풀이 및 재현

[`../solve.py`](../solve.py)는 `challenge/Challenge.exe`를 임시 복사해 계측하고 복구한 값을 검증한다. 기본 성공 출력에는 플래그만 남는다.

```bash
python solve.py
```

## 결과

원본 풀이에서 검증된 결과를 루트의 `flag`와 대조했다.

```text
BHFlagY{cy7h0n_pyth0n_w1th_3nh4nced_upx__e8f278059549f9ded9}
```

## 정리 및 회고

난독화된 산술을 전부 정적으로 옮기기보다 의미 있는 런타임 경계에 오라클을 세우는 편이 정확했다. 계측 대상과 최종 검증을 분리해 오탐을 막았다.

## 참고 자료

- [원본 분석](../analysis/original-write-up.md)
- [공식 배포물](../challenge/)

