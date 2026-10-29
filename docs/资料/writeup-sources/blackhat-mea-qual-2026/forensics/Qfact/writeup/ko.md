# Qfact

> 스포일러: 이 문서는 문제의 분석 과정과 최종 풀이를 포함합니다.

## 개요

| 항목 | 내용 |
|---|---|
| 상태 | solved |
| 대회·플랫폼 | BlackHat MEA Qualification CTF 2026 |
| 분야 | `forensics` |
| 난이도 | not provided |
| Flag 형식 | `BHFlagY{...}` |

Windows Defender 격리 저장소에서 악성 HTA와 암호화 파일의 복호 정보를 복구하는 포렌식 문제다.

## 환경 및 초기 분석

원본 증거 ZIP을 변경하지 않고 격리 메타데이터와 리소스를 파싱했다. 복구된 HTA는 실행하지 않고 문자열과 암호 루틴만 정적으로 분석했다.

## 핵심 분석

Defender의 고정 RC4 계층을 해제해 HTA를 복원한다. 스크립트의 문자 코드 배열에서 AES 키를 만들고 호스트 정보에서 IV를 계산해 암호화 파일을 복호화한 뒤 Base64 값을 해석한다.

```text
Input: Evidence.zip
Quarantine layer: fixed Microsoft Defender RC4 key
Payload: HTA
File cipher: AES-256-CBC
IV: MD5(computer_name + username)
Recovered encrypted files: 9
```

## 풀이 및 재현

[`../solve.py`](../solve.py)는 `challenge/Evidence.zip`을 읽고 결과를 `output/`에 기록한다. 성공 시 표준 출력에는 플래그만 기록된다.

```bash
python solve.py
```

## 결과

원본 풀이에서 검증된 결과를 루트의 `flag`와 대조했다.

```text
BHFlagY{d3f3nd3r_qu4r4nt1n3_r3c0v3ry_2026}
```

## 정리 및 회고

증거 파일을 직접 실행하지 않고 컨테이너 형식과 암호 루틴을 분리해 복원했다. 원본 해시와 복구 산출물을 함께 남기면 분석 경로를 다시 검증하기 쉽다.

## 참고 자료

- [원본 분석](../analysis/original-write-up.md)
- [공식 배포물](../challenge/)

