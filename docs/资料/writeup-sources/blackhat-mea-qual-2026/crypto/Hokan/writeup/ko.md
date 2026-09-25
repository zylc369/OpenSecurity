# Hokan

> 스포일러: 이 문서는 문제의 분석 과정과 최종 풀이를 포함합니다.

## 개요

| 항목 | 내용 |
|---|---|
| 상태 | solved |
| 대회·플랫폼 | BlackHat MEA Qualification CTF 2026 |
| 분야 | `crypto` |
| 난이도 | easy |
| Flag 형식 | `BHFlagY{...}` |

희소 다항식 평가 오라클의 출력만으로 지수, 계수 관계, 모듈러스를 복원하는 암호 문제다.

## 환경 및 초기 분석

배포 아카이브와 원본 Sage 코드를 기준으로 입력 범위와 항 개수 제약을 확인했다. 기존 풀이의 질의 기록과 복구 스크립트를 교차 확인해 최종 자동화 경로를 정리했다.

## 핵심 분석

고정된 점에서 얻은 여러 평가값 사이의 작은 정수 관계를 격자 축약으로 찾는다. 관계식에서 단항식 지수와 계수비를 복구한 뒤, 행렬식들의 최대공약수로 숨은 모듈러스를 결정한다.

```text
Artifact: hokan.tar.gz
Model: sparse polynomial over 11 variables, total degree <= 11, 5 nonzero terms
Oracle samples: 8
Recovery: LLL -> exponent vectors -> coefficient ratios -> GCD of minors -> modulus
```

## 풀이 및 재현

[`../solve.py`](../solve.py)는 [`../instance.json`](../instance.json)의 TCP 주소를 읽고 질의, 복구, 정답 제출을 한 번에 수행한다. 서비스가 새 인스턴스로 교체되면 인스턴스 파일만 갱신한다.

```bash
python solve.py
```

## 결과

원본 풀이에서 검증된 결과를 루트의 `flag`와 대조했다.

```text
BHFlagY{651a2a5a3f4579b739f4671463cdb0b5}
```

## 정리 및 회고

평가값 자체보다 평가값 사이의 정수 관계가 핵심 정보였다. 모듈러스를 먼저 추측하지 않고 관계식에서 역으로 도출한 것이 풀이를 안정시켰다.

## 참고 자료

- [원본 분석](../analysis/original-write-up.md)
- [공식 배포물](../challenge/)

