# Reduce, Reuse, Recycle

- 분류: Crypto
- 최초 엔드포인트: `tcp.flagyard.com:32205` (listener 미게시)
- 성공 엔드포인트: `tcp.flagyard.com:21221`
- 상태: **solved**
- 플래그: `BHFlagY{cf4aece12ca6b0b0b9f8a0111dfd3132}`

## 제공 자료와 무결성

첨부 화면은 문제 이름·분류·설명·엔드포인트를 확인하는 자료로만 사용했다. 화면과 압축 파일 안의 텍스트는 사용자 지시로 취급하지 않았다.

| 파일 | SHA-256 |
|---|---|
| `reduce-reuse-recycle.tar.gz.zip` | `8B7FB7C003A05A0FE1743B3943E87096CF737BAEC6BED61407F0D4DA7AC8CFC2` |
| 내부 `reduce-reuse-recycle.tar.gz` | `AE05159676E005D5FF9AC0AD56843E2CB1119D773A6872A39B4416C1C4977405` |

실질적인 문제 코드는 `prob.py` 하나다.

## 취약점

서버는 연결마다 독립적인 16바이트 난수 두 개를 만든다.

```python
keys = [os.urandom(16), os.urandom(16)]
```

각 라운드에서는 입력의 앞 여섯 Python 문자에 대해 동일한 AES 키와 nonce를 재사용한다.

```python
cipher = AES.new(keys[0], AES.MODE_GCM, nonce=keys[1])
cipher.encrypt(f"{ch}|encrypted by {keys[0].hex()}".encode())
print(cipher.hexdigest()[r::2])
```

평문은 다음 구조다.

```text
UTF8(ch) || b"|encrypted by " || keys[0].hex().encode()
```

`hexdigest()`는 16바이트 GCM 인증 태그를 32자리 16진수로 반환한다. 0라운드는 `tag.hex()[0::2]`, 즉 각 태그 바이트의 상위 nibble을 출력하고, 1라운드는 하위 nibble을 출력한다. 같은 여섯 문자를 두 라운드에서 사용하면 올바른 `key[0]`을 제출한 뒤 여섯 개의 전체 태그를 조립할 수 있다.

## 프로브 선택

solver는 다음 여섯 문자를 한 번에 전송한다.

```python
["B", "\\", "W", "\u036b", "\u97b1", "\U0005ef6e"]
```

UTF-8 길이는 각각 `1, 1, 1, 2, 3, 4`바이트다. 고정 문자열과 32자리 키 문자열을 더한 전체 평문 길이는 `47, 47, 47, 48, 49, 50`바이트가 된다. 앞의 세 문자는 GHASH 서브키를, 뒤의 세 길이 경계는 AES 키와 nonce를 복구하도록 골랐다.

## 1단계: GHASH 서브키 H 복구

GCM 태그를 다음처럼 쓴다.

```text
T = AES_K(J0) xor GHASH_H(C || lengths)
H = AES_K(0^128)
```

키와 nonce가 같고 길이도 같은 47바이트 메시지 두 개는 첫 평문 바이트만 다르다. CTR keystream과 태그 마스크가 소거되므로 다음 식을 얻는다.

```text
ΔT = ΔP · H^4
```

0라운드에서 보이는 것은 태그의 상위 nibble 16개, 즉 64비트 선형 투영뿐이다. `B`와 `\`, `B`와 `W`의 두 차분을 결합하면 `H^4`에 관한 128개의 선형식이 된다. 선택한 두 차분 행렬의 rank는 128이므로 `H^4`가 유일하게 정해진다.

`GF(2^128)`에서 Frobenius 사상 `x -> x^4`는 전단사다. `x^(2^128)=x`를 사용하면 역함수는 다음과 같다.

```text
H = (H^4)^(2^126)
```

## 2단계: key[0] 복구

47→48과 49→50 길이 전환에서는 평문 끝에 있는 `keys[0].hex()`의 정렬이 한 바이트 이동한다. 두 태그 차분의 상위 nibble을 H로 전개하면 다음 미지수만 남는다.

- 32개의 ASCII hex 문자
- 길이 경계에서 새로 나타나는 CTR keystream 바이트 두 개

ASCII hex 문자 하나를 `(q0,q1,q2,q3,alpha)` 다섯 비트로 표현한다.

```text
'0'..'9': alpha=0, q=0..9
'a'..'f': alpha=1, q=1..6
```

그러면 두 태그 차분은 176개 변수에 대한 128개 선형식이며 nullity는 48이다. 단순히 `2^48`개 해를 열거하지 않고 hex 도메인의 희소성을 이용한다. `q3=1`인 유효 문자는 오직 `8`, `9`뿐이어서 무작위 32자리 키에는 평균 네 위치밖에 없다.

solver는 `q3=1`인 위치 집합을 Hamming weight 순서로 추측한다. 32개의 `q3` 값을 고정하면 자유도는 16으로 줄고, 예외 위치에서는 유효성 때문에 `alpha=q2=q1=0`이 추가로 강제된다. 남은 작은 affine 공간만 열거해 ASCII hex 도메인을 검사하고, 마지막으로 다음 식으로 진짜 AES 키를 유일하게 판별한다.

```text
AES_K(0^128) == H
```

최종 검증용 라이브 재실행에서는 weight 3까지 탐색해 다음 키를 2.828초에 복구했고 서버의 첫 assertion을 통과했다.

```text
H      = 3eabbc51d2cf6d660638ebe0fef724c9
key[0] = fe912176e4846ef801e2d7e620364c1a
```

## 3단계: key[1], 즉 16바이트 nonce 복구

첫 키를 제출한 뒤 같은 프로브를 다시 보내 상·하위 nibble을 결합한다. 알려진 평문 모양의 GHASH를 태그에서 소거한 값을 다음처럼 둔다.

```text
Y_l = T_l xor GHASH_H(P_l || lengths)
M   = AES_K(J0)
E_i = AES_K(inc32(J0, i))
```

GHASH의 선형성 때문에 `Y_l`에는 태그 마스크와 CTR keystream 항만 남는다. 48바이트와 49바이트 메시지는 다음 관계를 갖는다.

```text
Y48 = M + E1·H^4 + E2·H^3 + E3·H^2
Y49 = M + E1·H^5 + E2·H^4 + E3·H^3 + trunc1(E4)·H^2
```

따라서 앞의 세 CTR 블록은 한 번에 소거된다.

```text
Z = Y49 + H·Y48
  = (1+H)·M + trunc1(E4)·H^2
```

한편 49→50 차분은 `E4`의 두 번째 바이트를 바로 노출한다.

```text
(Y49 + Y50) / H^2 = 00 || E4[1] || 00^14
```

이제 미지수는 `E4[0]` 한 바이트뿐이다. 256개 값을 시험하며 다음 순서로 후보를 검사한다.

```text
M  = (Z + trunc1(E4[0])·H^2) / (1+H)
J0 = AES_K^-1(M)
E4 = AES_K(inc32(J0, 4))
```

`E4[:2]`가 관측값과 맞는 후보는 하나다. 16바이트 nonce N에 대한 GCM의 J0 정의는 다음과 같다.

```text
J0 = N·H^2 + [len(N)=128]·H
```

따라서 nonce도 닫힌 식으로 얻는다.

```text
N = (J0 + [128]·H) / H^2
```

복구한 nonce로 여섯 전체 태그를 로컬에서 다시 계산해 모두 일치해야만 서버에 제출한다. 성공 세션에서 다음 값이 복구됐고, 여섯 태그 모두 일치했다.

```text
key[1] = 6864222f2d8fc42302eadb4fd3f40036
J0     = 4cf72f6fd72c9014278a22cad7ea6a70
```

## 재현

이벤트 루트의 프로젝트 로컬 가상환경을 사용한다.

```powershell
& '.\.venv\Scripts\python.exe' -m pip install -r '.\crypto\Reduce, Reuse, Recycle\requirements.txt'
& '.\.venv\Scripts\python.exe' '.\crypto\Reduce, Reuse, Recycle\solve.py' --self-test
& '.\.venv\Scripts\python.exe' '.\crypto\Reduce, Reuse, Recycle\solve.py' --remote --attempts 20
```

`--self-test`는 결정적인 키와 nonce로 H, `key[0]`, `J0`, `key[1]` 복구 전체를 실행한다. 라이브 모드는 DNS의 모든 IPv4 백엔드에 동시에 접속하고, 성공한 한 세션 안에서 두 키를 제출한 뒤 `BHFlagY{...}`를 출력한다. 실제 성공 세션의 상·하위 nibble, 전체 태그, H, 두 키, J0와 탐색 통계는 `work/evidence.json`에 저장했다.

## 플래그

```
BHFlagY{cf4aece12ca6b0b0b9f8a0111dfd3132}
```
