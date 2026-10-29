# extended-license - Write-up

## 개요

- 대회명: BlackHat MEA Qualification CTF 2026
- 문제명: `extended-license`
- 분야: Reversing
- 제공 파일: `extended-license.tar.zip`, `challenge`
- 실행 환경: Linux x86-64, Python 3, GDB/Unicorn

64비트 PIE ELF가 사용자명에 종속된 라이선스를 검사하고, 성공하면 내장된 AES 암호문을 복호화하는 문제다. 실제 검증 코드는 평문 shellcode로 파일 안에 들어 있지만, 실행 시 RWX 영역으로 복사된 뒤 `SIGTRAP` dispatcher와 seccomp/eBPF oracle을 거치므로 일반적인 정적 decompile만으로 전체 흐름을 읽기 어렵다.

## 초기 분석

배포 ELF의 SHA-256은 다음과 같다.

```text
05cca43b4b9ef229e402fb6869f6613209a3d91542993af32e9984bb99d40563
```

`main`은 파일/가상 주소 `0x20e6b18`에서 `0x2ab55`바이트(174,933바이트)를 `memcpy`로 RWX `mmap` 영역에 복사하고 직접 호출한다. 즉 shellcode는 디스크에서는 암호화되어 있지 않으며 정적으로 그대로 추출할 수 있다.

shellcode가 반환된 직후에는 `rdtsc`로 실행 시간을 재고 `0x23c34600` cycles보다 오래 걸리면 실패한다. GDB에서 단일 단계로 추적할 때는 `main+0x6b4e`의 다음 6바이트 분기를 NOP로 바꾸면 된다.

```text
원본: 0f 87 67 01 00 00    ja failure
패치: 90 90 90 90 90 90
```

이 패치는 바깥쪽 시간 제한만 제거한다. 뒤에서 설명할 사용자명 validator 내부의 `rdtsc`와는 별개다.

## SIGTRAP shellcode 복원

shellcode는 `SIGTRAP` handler를 dispatcher로 사용한다. 각 단계는 handler가 다음 chunk를 복호화하거나 실행 권한이 있는 버퍼로 옮긴 뒤 이어서 실행한다. handler 진입과 복호 직후에 breakpoint를 두고 메모리를 저장해 총 16개의 실행 단계를 복원했다.

이후 분석은 원래 ELF의 signal 흐름을 매번 실행하는 대신 복호된 stage들을 직접 disassemble하고, 상태 구조체의 주요 필드인 `[r12+0x140..0x150]`을 추적하는 방식으로 진행했다.

## 사용자명과 validator

프로그램이 사용하는 사용자명은 다음 순서로 결정된다.

1. `SUDO_UID`가 있으면 UID를 `getpwuid`로 이름에 매핑
2. 없으면 비어 있지 않고 `root`가 아닌 `SUDO_USER` 사용
3. 마지막으로 `/proc/self/loginuid`를 읽어 `getpwuid`로 변환

사용자명 validator를 Unicorn에서 실행하면서 `rdtsc` 값을 통제하고 네이티브 결과와 비교하면 반환식은 다음과 같다.

```text
validator(username, tsc) = crc32(username) ^ 0x14 ^ (tsc >> 32)
```

`main+0x6c81`은 이 값을 `0xbf2b0fa2`와 비교한다. 내부 shellcode가 `rdtsc`의 상위 32비트가 들어 있는 `EDX`를 보존하지 않아 결과가 시간에 따라 달라지는 결함이 있다. 따라서 바깥쪽 timing branch만 NOP해도 사용자명 검사는 결정적이지 않다. `EDX=0`을 의도했다고 보면 필요한 CRC32는 다음과 같다.

```text
crc32(username) = 0xbf2b0fa2 ^ 0x14 = 0xbf2b0fb6
```

## PRNG와 Feistel 역산

먼저 사용자명 최대 20바이트를 NUL로 채운 고정 길이 입력에서 초기 state를 만든다.

```python
digest = SHA256(username[:20].ljust(20, b"\0"))
state = LE64(digest[0:8]) ^ LE64(digest[8:16]) \
      ^ LE64(digest[16:24]) ^ LE64(digest[24:32])
```

각 PRNG 단계는 carry-less multiplication의 하위 64비트와 상수를 사용한다.

```text
state = CLMUL_low64(state, 0x1d872b41f2a3c4d5)
state = state ^ 0x9e3779b97f4a7c15
```

하위 32비트는 단정도 부동소수점 연산으로 매핑된다. 중간마다 `float32` 반올림을 재현하지 않으면 네이티브 키와 달라진다.

```text
u    = f32(f32(state.low32) * f32(2^-32))
m    = f32(f32(u * f32(1.690000057220459)) + f32(0.12345670163631439))
frac = f32(m - f32(floor(m)))
key  = uint32(f32(frac * f32(2^32)))
```

이 과정을 32번 반복해 8개 블록에 각각 4개의 round key를 배정한다. 8바이트 블록을 little-endian `L`, `R` 두 dword로 나누면 한 Feistel round는 다음과 같다.

```text
mixed = (R + key) mod 2^32
F     = mixed ^ (mixed << 7) ^ (mixed >> 9)
(L,R) = (R, L ^ F)
```

따라서 oracle이 요구하는 최종 64바이트를 알면 round key를 역순으로 적용해 사용자명별 license payload를 직접 구할 수 있다.

## seccomp/eBPF oracle 정적 에뮬레이션

shellcode는 512개 비트를 하나씩 syscall 인자로 보내고 seccomp filter의 반환 경로를 확인한다. 추출한 eBPF object 안의 실제 classic BPF filter는 30개 명령으로 구성되어 있었다. 이 환경에서는 program load가 `EINVAL`로 실패했지만, 필터가 하는 일은 입력 비트와 내부 selector bit 비교뿐이므로 kernel에 올릴 필요가 없다.

all-zero transformed payload에 대한 selector 결과는 다음 64바이트였다.

```text
a79a5194654c7c84d9e3efae2e44e11961a2651ba7f2bd0e27983582626dd61c
704dc90fb1dfed76b0990690a8c1074ff13cf3148c774697b5c711bf73618afb
```

userspace chain은 512회 모두 반대 분기인 `EPERM` 경로를 요구한다. 따라서 실제 Feistel 목표는 각 비트를 반전한 값이다.

```text
5865ae6b9ab3837b261c1051d1bb1ee69e5d9ae4580d42f1d867ca7d9d9229e3
8fb236f04e2012894f66f96f573ef8b00ec30ceb7388b9684a38ee408c9e7504
```

결과적으로 kernel의 BPF verifier나 seccomp 동작 차이에 의존하지 않고 Python에서 동일한 검사를 재현할 수 있다.

## 라이선스 형식

기본 라이선스는 정확히 72바이트다.

```text
BHLCNS_ || 64-byte Feistel preimage || !
```

payload 안에 `!`가 먼저 나타나면 delimiter 검사에서 실패한다. `!` 뒤의 trailing bytes는 shellcode 검사를 통과하며, 최종 키 생성에서는 전체 라이선스 중 최대 120바이트가 사용된다. 즉 기본 72바이트 뒤에 최대 48바이트를 추가하면 Feistel 검증은 그대로 두면서 AES key에는 영향을 줄 수 있다.

## AES 복호 경로

Feistel 및 사용자명 검사를 통과한 뒤 `main`은 실제 라이선스 파일의 앞 120바이트와 전체 사용자명을 이어 SHA-256을 계산한다.

```text
aes_key = SHA256(actual_license_bytes[:120] || full_username)
```

파일 오프셋 `0x2111850`에는 80바이트 암호문이 있으며, 이를 16바이트씩 다섯 블록으로 나누어 AES-256-ECB 복호화한 뒤 `puts`로 출력한다.

```text
31626a4c1711dc1fcc173205c2729abb1a907327200c282ea02098de9eb82c92
8078ce25fb037a86dea668508afee0ced177c38f695211389b249387bba520c77
3ea5b380200569a86b83f171a093d79
```

테스트 사용자명 `zuackk`에 대해 Python으로 만든 payload를 원본 ELF에 주입하고 사용자명 비교만 우회했다. 원본이 출력한 80바이트와 Python의 AES 복호 결과가 byte-for-byte 일치해 PRNG, Feistel, oracle target, 키 입력 순서와 AES mode를 모두 검증했다.

## Solver

`solve.py`는 다음 항목을 재현한다.

- 사용자명 기반 seed 및 32개 PRNG 출력 생성
- 8개 Feistel block 역산과 재암호화 검증
- 정적으로 복원한 512비트 cBPF oracle target 적용
- binary license 생성
- 내부 `rdtsc`를 포함한 사용자명 validator 계산
- 원본 ELF에서 암호문 추출 및 AES-256-ECB 복호화

프로젝트 공용 가상환경에 의존성을 설치하고 self-test를 실행한다.

```powershell
& '..\..\.venv\Scripts\python.exe' -m pip install pycryptodome
& '..\..\.venv\Scripts\python.exe' .\solve.py --self-test
```

팀에서 사용한 정확한 사용자명과 `!` 뒤 extension bytes를 알고 있다면 다음처럼 완전한 라이선스와 flag를 재현할 수 있다.

```powershell
& '..\..\.venv\Scripts\python.exe' .\solve.py `
  --username '<username>' `
  --extension-hex '<optional-hex>' `
  --output .\license.generated.dat `
  --require-flag
```

현재 공유된 최종 결과에는 해당 사용자명/extension/AES key가 포함되지 않았으므로, 이 문서의 최종 flag는 팀원이 복호화해 전달한 값을 기록했다. 해당 tuple이 확보되면 위 명령만으로 AES 결과까지 독립 검증할 수 있다.

## 최종 결과

```text
BHFlagY{BPF_c4n_b3_b4d_Bu7_I_d0n'7_Th1nK_7thIs_()ne_1s_B4D?_6b117fca1597}
```

## 회고

이 문제의 핵심은 거대한 shellcode 전체를 한 번에 decompile하는 것이 아니라 검증 경계를 분리하는 것이었다. `SIGTRAP` dispatcher에서 stage를 덤프하고, 사용자명 PRNG와 Feistel을 순수 함수로 옮긴 다음, 512회 syscall oracle은 30개 cBPF 명령의 selector 값으로 치환했다. 이렇게 하면 커널의 eBPF 호환성 문제를 제거한 상태에서 라이선스 검증과 AES 입력까지 재현할 수 있다.

동시에 두 `rdtsc`의 역할을 구분해야 했다. `main`의 바깥쪽 검사는 단순 anti-debug timeout이지만 shellcode 안쪽의 `rdtsc`는 `EDX` clobber 때문에 validator 반환값 자체를 바꾼다. 이 차이를 놓치면 timing branch를 패치하고도 `0xbf2b0fa2` 비교가 계속 불안정해진다.
