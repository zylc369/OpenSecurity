# Reduce, Reuse, Recycle

> 스포일러: 이 문서는 문제의 분석 과정과 최종 풀이를 포함합니다.

## 개요

| 항목 | 내용 |
|---|---|
| 상태 | solved |
| 대회·플랫폼 | BlackHat MEA Qualification CTF 2026 |
| 분야 | `crypto` |
| 난이도 | not provided |
| Flag 형식 | `BHFlagY{...}` |

같은 키와 nonce를 재사용한 AES-GCM 및 부분 태그 노출을 결합해 키 재료를 복구하는 문제다.

## 환경 및 초기 분석

원본 서비스가 두 키를 번갈아 사용하면서 동일한 nonce를 재사용하고 태그의 교차 니블을 노출함을 확인했다. 기존 유한체 방정식과 길이 선택 전략을 한 실행 경로로 정리했다.

## 핵심 분석

선택 평문의 길이를 바꿔 GHASH 식의 미지수를 제한하고 첫 번째 키의 해시 서브키를 복원한다. 완전한 태그를 재구성한 뒤 두 번째 키로 처리되는 nonce 질의에 필요한 값을 구한다.

```text
Primitive: AES-GCM
Fault: identical nonce reused across alternating keys
Leak: alternating authentication-tag nibbles
Chosen UTF-8 lengths: 47, 48, 49, 50
Recovery: GF(2) equations -> GHASH H -> full tags -> nonce value
```

## 풀이 및 재현

[`../solve.py`](../solve.py)는 [`../instance.json`](../instance.json)의 TCP 주소를 사용한다. 기본 실행은 기존 원격 풀이 경로이며, 자체 검사는 별도 옵션으로 유지했다.

```bash
python solve.py
```

## 결과

원본 풀이에서 검증된 결과를 루트의 `flag`와 대조했다.

```text
BHFlagY{cf4aece12ca6b0b0b9f8a0111dfd3132}
```

## 정리 및 회고

인증 태그가 일부만 보여도 nonce 재사용으로 식들이 연결되면 충분한 제약이 생긴다. 입력 길이를 조절해 GHASH 항의 구조를 단순화한 것이 핵심이다.

## 참고 자료

- [원본 분석](../analysis/original-write-up.md)
- [공식 배포물](../challenge/)

