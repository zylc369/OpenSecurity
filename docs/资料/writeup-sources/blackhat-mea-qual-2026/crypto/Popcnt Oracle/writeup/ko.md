# Popcnt Oracle

> 스포일러: 이 문서는 문제의 분석 과정과 최종 풀이를 포함합니다.

## 개요

| 항목 | 내용 |
|---|---|
| 상태 | solved |
| 대회·플랫폼 | BlackHat MEA Qualification CTF 2026 |
| 분야 | `crypto` |
| 난이도 | not provided |
| Flag 형식 | `BHFlagY{...}` |

RSA 평문 자체 대신 평문의 해밍 가중치를 반환하는 오라클에서 비트를 복원하는 문제다.

## 환경 및 초기 분석

원본 서버 코드에서 임의 암호문 복호 결과의 비트 개수가 노출됨을 확인했다. 기존 질의 전략과 공개키 검증 절차를 최종 솔버에 보존했다.

## 핵심 분석

암호문에 선택한 값의 공개키 암호화를 곱하면 평문에 그 값을 곱한 결과의 해밍 가중치를 얻는다. 역원 기반 반감과 보완 질의로 비트를 결정하고, 동률인 경우 추가 배수 질의로 모호성을 해소한다.

```text
Oracle: HW(m)
RSA transform: c' = c * a^e mod n -> HW(a*m mod n)
Bit recovery: inverse halving + complement query
Ambiguity recovery: query 3*m
Verification: pow(m, e, n) == c
```

## 풀이 및 재현

[`../solve.py`](../solve.py)는 [`../instance.json`](../instance.json)에서 TCP 주소를 불러와 평문을 복원하고 공개 RSA 식으로 확인한 다음 제출한다.

```bash
python solve.py
```

## 결과

원본 풀이에서 검증된 결과를 루트의 `flag`와 대조했다.

```text
BHFlagY{7ec59fc32589300df70f41b11db3e6ec}
```

## 정리 및 회고

한 비트의 값은 가중치 변화 방향으로 판별할 수 있다. 변화량이 동률일 때 사용할 독립적인 배수 질의를 준비한 점이 복구의 완결성을 만든다.

## 참고 자료

- [원본 분석](../analysis/original-write-up.md)
- [공식 배포물](../challenge/)

