# free-agentic-tool

> 스포일러: 이 문서는 문제의 분석 과정과 최종 풀이를 포함합니다.

## 개요

| 항목 | 내용 |
|---|---|
| 상태 | solved |
| 대회·플랫폼 | BlackHat MEA Qualification CTF 2026 |
| 분야 | `reverse` |
| 난이도 | not provided |
| Flag 형식 | `BHFlagY{...}` |

Go로 작성된 Windows 실행 파일과 PCAP에서 결정적 X25519 세션과 최종 암호문을 복원하는 문제다.

## 환경 및 초기 분석

배포 ZIP의 실행 파일, 디버그 아카이브, 패킷 캡처를 원본 라이트업의 데이터 흐름에 맞춰 확인했다. 실행 위치에 의존하던 입력 경로를 문제 루트 기준으로 고정했다.

## 핵심 분석

내장 AES-CBC 키로 디버그 자료를 열어 사용자명과 호스트명을 얻는다. 이 값에서 결정적 X25519 개인키를 만들고 세션 패킷을 복호화하며, 캡처에 종속된 최종 스트림으로 Base64 평문을 복원한다.

```text
Input: dist.zip
Executable: Go 1.20.5 PE
Debug archive: AES-CBC
Key agreement: deterministic X25519(username + '_' + hostname)
Capture: init/session packets
Final t7 recovery: embedded capture-specific T7_STREAM
```

## 풀이 및 재현

[`../solve.py`](../solve.py)는 `challenge/dist.zip`을 직접 읽어 전체 복구 경로를 수행한다. 성공 출력은 플래그만 남기고 상세 값은 명시적 verbose 옵션에서만 표시한다.

```bash
python solve.py
```

## 결과

원본 풀이에서 검증된 결과를 루트의 `flag`와 대조했다.

```text
BHFlagY{wh4t_y0u_5Ee_15n't_wh4t_y0u_G3t_8cc56ad688964fd5f72f3c414971b1d6}
```

## 정리 및 회고

키 교환은 결정적이어서 재현 가능하지만 마지막 스트림은 해당 캡처에 종속된다. 일반 알고리즘과 인스턴스별 상수를 문서에서 분리해 설명해야 범위를 과장하지 않는다.

## 참고 자료

- [원본 분석](../analysis/original-write-up.md)
- [공식 배포물](../challenge/)

