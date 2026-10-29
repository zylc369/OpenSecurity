---
title: "Hokan"
ctf: "BlackHat MEA Qualification CTF 2026"
date: 2026-09-05
category: crypto
difficulty: easy
points: 100
flag_format: "BHFlagY{...}"
author: "participant"
---

# Hokan

## Summary

11변수·차수 11 이하의 5항 희소 다항식을 8회만 평가할 수 있다. 값이 작은 8개 점을 고른 뒤 출력의 짧은 정수 선형관계를 LLL로 찾으면 단항식 705,432개를 정확한 5개 항으로 걸러낼 수 있다.

## Solution

### 1. 8개 질의에서 단항식 지수 복원

고정 질의점의 각 좌표를 `1`, `2`, `3` 중 하나로 골랐다. 실제 단항식들을 `m_j`, 계수를 `c_j`, 질의 출력을 `y_i`라 하면 다음 식이 성립한다.

```text
M[i,j] = m_j(probe_i) <= 3^11
y = M c (mod p)
```

`M`은 `8 x 5`이므로 정수 왼쪽 영공간의 차원은 3이다. 그 영공간의 벡터 `w`마다 `w*y = k*p`이고, 세 식에서 `k`를 소거하면 `w*y = 0`인 매우 짧은 정수관계 두 개를 얻는다. 출력 벡터의 정수 영공간을 LLL로 축약하면 이 두 벡터가 다른 관계보다 확연히 짧게 나타난다.

사용한 8개 질의점은 차수 11 이하의 모든 11변수 단항식에 대해 서로 다른 평가 서명을 만든다. 따라서 모든 약한 조합 705,432개를 열거하고 두 관계를 모두 만족하는 평가 열만 남기면 실제 지수 벡터 5개가 정확히 복원된다.

### 2. 법과 계수 복원

복원한 `M`에 출력 열 `y`를 붙인 `8 x 6` 행렬은 법 `p`에서 랭크가 5 이하이다. 모든 `6 x 6` 소행렬식의 최대공약수는 `p`와 작은 공통 인자만 포함한다. 질의점에서 생긴 `2`, `3`의 거듭제곱 인자를 제거해 `p`를 얻고, 유한체에서 `M c = y`를 풀어 다섯 계수를 복원했다.

전체 자동화는 [solve.py](solve.py)가 TCP 질의와 제출을 담당하고 [recover.sage](recover.sage)가 LLL, 후보 열거, 법·계수 복원을 담당한다.

```powershell
.\.venv\Scripts\python.exe .\crypto\Hokan\solve.py
```

SageMath 10.9 Docker 이미지로 실행한 실제 결과는 다음과 같았다.

```text
[+] query 8/8
[+] collected all eight oracle outputs
[+] recovered 5 terms and the modulus
[+] flag: BHFlagY{651a2a5a3f4579b739f4671463cdb0b5}
```

## Flag

```text
BHFlagY{651a2a5a3f4579b739f4671463cdb0b5}
```
