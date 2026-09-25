# extended-license

> 스포일러: 이 문서는 문제의 분석 과정과 최종 풀이를 포함합니다.

## 개요

| 항목 | 내용 |
|---|---|
| 상태 | solved |
| 대회·플랫폼 | BlackHat MEA Qualification CTF 2026 |
| 분야 | `reverse` |
| 난이도 | not provided |
| Flag 형식 | `BHFlagY{...}` |

다단계 SIGTRAP 셸코드, cBPF 선택기, 라이선스 기반 AES 복호를 추적하는 리버싱 문제다.

## 환경 및 초기 분석

PIE 실행 파일이 복사하는 셸코드와 트랩 단계, 라이선스 구문을 원본 분석에서 정리했다. 보존된 테스트 라이선스와 최종 플래그는 확인되지만 실제 제출에 사용한 사용자명과 확장 바이트는 원본 기록에 남아 있지 않다.

## 핵심 분석

사용자명에서 PRNG와 Feistel 경로를 거쳐 선택기 값을 만들고, 라이선스 앞부분과 사용자명을 해시해 AES 키를 만든다. cBPF 프로그램이 선택한 페이로드 제약을 만족하면 내장 암호문을 복호화할 수 있다.

```text
Binary: PIE ELF
Staging: SIGTRAP shellcode
Selector: static cBPF
License grammar: BHLCNS_ || payload || ! || extension
Key: SHA-256(license[:120] + username)
Cipher: AES-ECB
```

## 풀이 및 재현

[`../solve.py`](../solve.py)는 `challenge/extended-license.tar.zip`에서 실행 파일을 임시로 꺼내 분석하고 명시한 사용자명과 확장 바이트로 라이선스를 생성·검증한다. 현재 보존 자료만으로는 실제 제출 입력을 기본값으로 복원할 수 없으므로 해당 인자를 제공해야 한다.

```bash
python solve.py
```

## 결과

원본 풀이에서 검증된 결과를 루트의 `flag`와 대조했다.

```text
BHFlagY{BPF_c4n_b3_b4d_Bu7_I_d0n'7_Th1nK_7thIs_()ne_1s_B4D?_6b117fca1597}
```

## 정리 및 회고

최종 플래그와 일반 복호 절차는 보존됐지만 제출 입력이 누락되면 무인 재현 계약은 완성되지 않는다. 이후에는 사용자명, 확장 바이트, 생성 라이선스를 함께 기록해야 한다.

## 참고 자료

- [원본 분석](../analysis/original-write-up.md)
- [공식 배포물](../challenge/)
