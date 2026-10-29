# upyx - Write-up

## 개요

- 대회명: BlackHat MEA Qualification CTF 2026
- 문제명: `upyx`
- 분야: Reversing
- 제공 파일: `Challenge.exe`, `dist.zip`
- 실행 환경: Windows x64, Python, Frida

문제 설명의 “don't rename this file”은 단순한 경고가 아니었다. 프로그램은 실행 과정에서 만든 파일명 suffix를 검증 seed에 포함하며, 입력 검증은 Python 코드, Cython 확장 모듈, 두 named pipe 서비스, self-modifying native verifier에 나뉘어 있었다.

## 초기 분석

제공 파일의 해시는 다음과 같다.

| 파일 | SHA-256 |
|---|---|
| `dist.zip` | `5E89F95F43C5187B209B95227BBC67CF9B96CB08D5EEE2E4ED4FDC04DDE73BEF` |
| `Challenge.exe` | `C2E4AD099F905F53C8CDCD7FB3971DA7334042A1BBF332C85B96826E8D31AC23` |

`Challenge.exe`는 Python 3.13 기반 PyInstaller one-file 실행 파일이며 PE section에 UPX 흔적이 있다. `pyinstxtractor-ng`로 추출하면 주요 파일은 다음과 같다.

- `main.pyc`: base85, zlib, marshal 조합을 100회 중첩한 loader
- `enhanced.cp313-win_amd64.pyd`: GUI, 문자별 token 생성, named pipe protocol
- `check.cp313-win_amd64.pyd`: 마지막 960바이트 native 검증

`work/unwrap_layers.py`로 `main.pyc`를 반복 해제한 최종 코드는 사실상 아래 두 줄이다.

```python
import enhanced
enhanced._c605a4bf()
```

GUI는 허용 문자 버튼만 제공하고 입력 길이를 정확히 60자로 제한한다. 각 문자를 누를 때 `enhanced._afa6b920()`가 16바이트 token을 만들며, token 60개가 검증 입력이 된다.

## 핵심 분석

### 파일명에 결합된 seed

PyInstaller parent는 자신을 다음과 같은 command line 이름으로 다시 실행했다.

```text
Cha.H8TUZibnsS
```

`check.pyd`의 wrapper는 PEB의 `ProcessParameters->CommandLine`을 직접 읽는다. 마지막 `.` 뒤의 연속된 영숫자를 소문자로 바꿔 FNV-1a 형태로 해시한다.

```text
initial = 0xb5f6f899
hash = (hash ^ lower(byte)) * 16777619 mod 2^32
```

`H8TUZibnsS`의 결과는 `0xa2c2fdf1`이다. 파일을 임의로 바꾸면 이 값이 달라지므로 문제 설명의 힌트와 연결된다.

### named pipe protocol

`enhanced.pyd`는 두 pipe를 사용한다.

- `\\.\pipe\supyxsvc`: GUI 문자 하나를 16바이트 token으로 변환
- `\\.\pipe\upyxsvc`: token 60개를 최종 검증용 960바이트로 변환

두 번째 pipe에서 확인한 명령은 다음과 같다.

| 명령 | 의미 | 응답 |
|---|---|---|
| `0x10 || tokens` | 960바이트 token vector 등록 | `01` |
| `0x12` | 마지막 두 문자에 대응하는 값 조회 | 32바이트 |
| `0x11` | native verifier 입력 조회 | 960바이트 |
| `0x13` | 현재 상태 초기화 | `01` |

`0x11` 응답의 앞 928바이트는 처음 58자에 대해 각각 독립적인 16바이트 block이다. 마지막 32바이트는 `0x12` 응답과 같으며 마지막 두 문자를 함께 표현한다. 따라서 앞 58자는 문자별로, 마지막 두 자리는 조합으로 탐색할 수 있다.

### self-modifying verifier 역산

`check.check()`는 `0x11` 명령으로 960바이트를 읽고 `check.pyd` RVA `0xe99e`의 verifier를 호출한다. 비교 대상 960바이트는 RVA `0x191f0`에 있다. verifier는 `UD2`와 vectored exception handler를 이용해 실행 중 코드를 복원하므로 정적 decompiler 결과만으로는 제어 흐름을 얻기 어렵다.

다음 두 지점에 hardware breakpoint를 사용했다.

- 입력 바이트 읽기: RVA `0x150cd`, `movzx ecx, byte ptr [r12+rbx]`
- 결과 비교: RVA `0x151d4`, `cmp al, byte ptr [r13+rbx]`

각 offset의 입력을 `0..255`로 바꾸면서 저장해 둔 `CONTEXT`를 되감았다. 비교가 일치하는 바이트를 고정하고 다음 offset으로 진행하면 960바이트 전체의 유일한 preimage를 얻는다. 직접 heap buffer에서 실행하면 wrapper의 실제 stack 문맥과 달라질 수 있으므로, `work/invert_check.py`는 별도 프로세스의 one-shot named pipe 서버를 두고 실제 `check.check()` stack buffer를 역산한다.

역산된 960바이트를 다시 verifier에 넣었을 때 반환값 `1`을 확인했다. 이 값은 `solve.py`에 base64로 포함했다.

### 세션 상태와 문자 복구

`enhanced.pyd`의 256항 테이블은 실행 세션의 원본 프로세스 상태에 결합된다. 추출한 모듈을 별도 Python으로 실행해 만든 token은 원본의 token과 달랐다. 예를 들어 원본에서 첫 위치의 `a`는 다음 token이 된다.

```text
ebe81963e3dd5734a2a6f0d502362e66
```

`solve.py`는 원본 `Challenge.exe`의 Python child에 Frida로 연결한 뒤 `PyGILState_Ensure`와 Python C API를 사용해 `_afa6b920()`를 호출한다. 이 방식은 GUI 포커스를 가져오지 않으면서 원본 세션의 정확한 token을 얻는다.

복구 절차는 다음과 같다.

1. 현재까지 복구한 prefix와 token을 원본 모듈 상태에 설정한다.
2. 허용 alphabet의 각 문자를 `_afa6b920()`에 전달한다.
3. 반환 token vector를 `upyxsvc`에 보내 `0x11` 응답을 얻는다.
4. 해당 위치의 16바이트가 native verifier의 기대 block과 같은 유일 문자를 선택한다.
5. 앞 58자를 고정한 뒤, flag 형식상 마지막 문자인 `}`와 59번째 문자 후보를 조합해 32바이트 `0x12` 응답을 비교한다.

모든 위치에서 후보가 하나씩만 남았고 마지막 조합도 `9}` 하나였다.

## Solver

Windows에서 프로젝트의 `.venv`에 Frida를 설치하고 실행한다.

```powershell
..\..\.venv\Scripts\python.exe -m pip install frida==17.5.2
..\..\.venv\Scripts\python.exe .\solve.py
```

`Challenge.exe`가 이미 실행 중이면 해당 Python child를 사용하고, 없으면 solver가 숨김 상태로 실행한다. solver는 60개의 baseline token을 만든 뒤 앞 58개 위치를 순차 탐색하고 마지막 두 문자를 조합한다. 복구 결과가 60자 및 `BHFlagY{...}` 형식과 맞지 않거나 어느 위치에서 후보가 유일하지 않으면 nonzero로 종료한다.

## 검증 결과

`solve.py`를 독립 실행한 결과 마지막 출력은 다음과 같았다.

```text
BHFlagY{cy7h0n_pyth0n_w1th_3nh4nced_upx__e8f278059549f9ded9}
```

복구 문자열을 원본 `enhanced._982eeb61()` 검증 경로에 전달했을 때 입력 길이 60, token 수 60이었고 GUI 결과는 다음과 같았다.

```text
SHOWINFO ('Congrats', 'Congrats!') {}
```

검증된 flag는 다음과 같다.

```text
BHFlagY{cy7h0n_pyth0n_w1th_3nh4nced_upx__e8f278059549f9ded9}
```

## 회고

이 문제의 핵심은 난독화 한 계층만 해제하는 것이 아니라 검증 경계를 나누는 것이었다. Python loader는 100회 포장되어 있지만 실제 로직은 Cython에 있었고, Cython은 다시 token 서비스와 self-modifying verifier로 책임을 나눴다. 정적 분석으로 각 경계와 protocol을 찾고, VEH를 존중하는 동적 breakpoint로 native 기대값을 복구한 뒤, 원본 Python 세션을 그대로 token oracle로 사용하면 복잡한 전체 알고리즘을 재구현하지 않고도 결정적으로 풀 수 있다.
