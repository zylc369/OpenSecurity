---
title: "Popcnt Oracle"
ctf: "BlackHat MEA Qualification CTF 2026"
date: 2026-09-05
category: crypto
difficulty: 미공개
points: 미공개
flag_format: "BHFlagY{...}"
author: "Codex"
---

# Popcnt Oracle - Write-up

## 1. 개요 (Overview)

- **문제명:** Popcnt Oracle
- **분야:** Crypto
- **접속 정보:** `tcp.flagyard.com:29212`
- **제공 파일:** `popcnt_oracle.tar.gz.zip`

서버는 무작위 plaintext `m`을 textbook RSA로 암호화한 `c`를 공개한다. 사용자가 보낸 ciphertext `x`에 대해 서버는 `x^d mod n`의 Hamming weight를 반환한다. RSA의 곱셈 성질로 `2^{-i}m mod n`의 parity를 복구한 뒤 `m`을 재구성했다.

제공 파일의 SHA-256은 다음과 같다.

| 파일 | SHA-256 |
|---|---|
| `popcnt_oracle.tar.gz.zip` | `1f6efe4992196636ef89c4a142fef974a774585db2a44ca9cb9565753a35686b` |
| `popcnt_oracle.tar.gz` | `77837e84cd2193b25579d27e7a60f15e105831c3c3a28c3871a49e76af6398ae` |
| `prob.py` | `1213124586953840967745aee464ca1e3a554ecd5b43bcb4de89b0ca7ca7faa5` |

## 2. 초기 분석 (Initial Analysis)

`prob.py`는 1024비트 소수 두 개로 RSA modulus를 만들고 다음 값을 출력한다.

```python
m = secrets.randbelow(n)
c = pow(m, e, n)

print(f"{e = }")
print(f"{n = }")
print(f"{c = }")
while True:
    x = int(input("x> "))
    if x == m:
        print(flag)
        break
    print(pow(x, d, n).bit_count())
```

서버는 연결할 때마다 `m`, `p`, `q`를 새로 생성한다. 공격과 최종 제출을 한 TCP 세션에서 끝내야 한다.

## 3. 취약점 분석 (Vulnerability Analysis)

### Root Cause

서버는 padding이 없는 RSA와 반복 가능한 decryption side channel을 함께 제공한다. 공개 지수 `e`를 알면 원하는 정수 `a`에 대해 다음 ciphertext를 만들 수 있다.

\[
C_a = c \cdot a^e \bmod n
\]

서버가 이를 복호화하면 `a m mod n`을 얻는다.

\[
C_a^d \equiv m a \pmod n
\]

따라서 오라클 출력은 `HW(am mod n)`이다.

### Hamming weight에서 parity 추출

`L = bit_length(n)`이고 `n`은 홀수다. 다음 수열을 정의한다.

\[
y_i = 2^{-i}m \bmod n, \qquad
h_i = HW(y_i), \qquad
g_i = HW(-y_i \bmod n)
\]

`y_i`가 짝수이면 modular halving은 오른쪽 shift와 같다.

\[
y_{i+1}=y_i/2 \quad\Longrightarrow\quad h_{i+1}=h_i
\]

`y_i`가 홀수이면 `n-y_i`가 짝수다. 이 경우 보수 쪽 Hamming weight가 유지된다.

\[
y_{i+1}=(y_i+n)/2,
\quad n-y_{i+1}=(n-y_i)/2
\quad\Longrightarrow\quad g_{i+1}=g_i
\]

따라서 `h_i != h_{i+1}`이면 parity는 1이고, `h_i == h_{i+1}`이면서 `g_i != g_{i+1}`이면 parity는 0이다. 두 Hamming weight가 모두 우연히 같으면 해당 위치를 모호한 비트로 남긴다.

parity를 `b_i = y_i mod 2`라고 하면 다음 recurrence가 성립한다.

\[
2y_{i+1}=y_i+b_i n
\]

이를 `L`번 전개하고 `R=2^L`로 두면 parity 열이 정수 `u`의 비트열이 된다.

\[
u=\sum_{i=0}^{L-1}b_i2^i
\equiv -m n^{-1}\pmod R
\]

모든 비트를 알면 다음 식으로 `m`을 계산할 수 있다.

\[
m=(-un)\bmod R
\]

### 모호한 비트 해소

같은 과정을 `z=3m mod n`에 적용한다. `q=floor(3m/n)`이고 `q`는 0, 1, 2 중 하나다.

\[
u_z \equiv -z n^{-1}
\equiv 3u+q \pmod R
\]

`3u+q`의 관측 비트를 이용하면 binary carry를 낮은 비트부터 계산할 수 있다. solver는 세 가지 `q`를 시도하고 모호한 `u` 비트만 분기한다. 마지막에 다음 조건으로 후보를 검증한다.

```python
0 <= m < n
(3 * m) // n == q
pow(m, e, n) == c
```

## 4. 익스플로잇 (Exploit)

전체 solver는 같은 디렉터리의 `solve.py`다. Python 표준 라이브러리만 사용한다. 다음 명령은 로컬 수학 검증을 실행한다.

```powershell
.\.venv\Scripts\python.exe ".\crypto\Popcnt Oracle\solve.py" --self-test --self-test-rounds 20
```

확인한 출력은 다음과 같다.

```text
self-test passed: 80 cases
```

원격 공격은 다음 명령으로 실행했다.

```powershell
.\.venv\Scripts\python.exe ".\crypto\Popcnt Oracle\solve.py" `
  --host tcp.flagyard.com `
  --port 29212 `
  --batch-size 256 `
  --timeout 180 `
  --evidence ".\crypto\Popcnt Oracle\work\evidence.json"
```

solver는 `c * Enc(2^-1)^i mod n`을 연속 생성한다. 먼저 원래 값의 Hamming weight를 조회하고, weight가 유지된 전이에 대해서만 `-x mod n`을 추가로 조회한다. 이 방식은 보수 쿼리 수를 줄인다.

원격 실행 결과는 다음과 같다.

```text
[+] n bits: 2047, ambiguous base bits: 29
[+] multiplier 3 unresolved overlaps: 1
[+] recovered plaintext satisfies pow(m, e, n) == c
[+] oracle queries: 3680
BHFlagY{7ec59fc32589300df70f41b11db3e6ec}
```

`work/evidence.json`에는 해당 세션의 `n`, `c`, 복구한 `m`, 모호한 비트 위치, 보조 관측값과 쿼리 수를 저장했다. 공개값만으로 `pow(m,e,n)==c`를 다시 계산할 수 있다.

## 5. 결과 및 플래그 (Result & Flag)

서버에 복구한 `m`을 제출해 다음 flag를 받았다.

```text
BHFlagY{7ec59fc32589300df70f41b11db3e6ec}
```

## 6. 회고 (Retrospective)

RSA-OAEP 같은 probabilistic padding은 공격자가 `Enc(a)`를 곱해 예측 가능한 plaintext 변환을 만드는 일을 막는다. 서비스는 decryption 결과에서 계산한 Hamming weight도 반환하면 안 된다. 요청 제한은 공격 비용을 높이지만 기능적 side channel 자체를 제거하지 못한다.
