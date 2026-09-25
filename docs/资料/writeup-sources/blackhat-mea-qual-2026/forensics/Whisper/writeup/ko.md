# Whisper

> 스포일러: 이 문서는 문제의 분석 과정과 최종 풀이를 포함합니다.

## 개요

| 항목 | 내용 |
|---|---|
| 상태 | solved |
| 대회·플랫폼 | BlackHat MEA Qualification CTF 2026 |
| 분야 | `forensics` |
| 난이도 | not provided |
| Flag 형식 | `BHFlagY{...}` |

Ollama 사용 흔적과 삭제된 스크립트에서 암호화 세션의 비밀번호를 재구성하는 포렌식 문제다.

## 환경 및 초기 분석

배포 아카이브 내부의 모델 대화 기록, 휴지통 스크립트, 캐시 ZIP을 원본 라이트업의 순서대로 대조했다. 필요한 항목만 메모리에서 읽도록 솔버 경로를 정리했다.

## 핵심 분석

대화 기록에서 스크립트가 입력받은 문구를 확인하고 삭제된 코드의 BLAKE2b 파생 방식을 재현한다. 얻은 비밀번호로 WinZip AES 세션을 열고 내부 CSV의 Base64 값을 해석한다.

```text
Input: whisper_evidence.tar.zip
History: .ollama/history
Deleted script: cache_mgr.py
Derivation: BLAKE2b
Container: WinZip AES session.zip
Recovered record: internal_api_keys.csv -> master_vault
```

## 풀이 및 재현

[`../solve.py`](../solve.py)는 `challenge/whisper_evidence.tar.zip`을 읽고 중간 결과를 `output/` 아래에 저장할 수 있다. 기본 성공 출력은 플래그뿐이다.

```bash
python solve.py
```

## 결과

원본 풀이에서 검증된 결과를 루트의 `flag`와 대조했다.

```text
BHFlagY{l0c4l_0ll4m4_llm_f4r3n51c5_2026}
```

## 정리 및 회고

삭제 파일, 모델 기록, 애플리케이션 캐시가 하나의 암호 파생 경로로 이어졌다. 시간순 흔적보다 데이터 의존 관계를 따라간 것이 빠른 복구에 유리했다.

## 참고 자료

- [원본 분석](../analysis/original-write-up.md)
- [공식 배포물](../challenge/)

