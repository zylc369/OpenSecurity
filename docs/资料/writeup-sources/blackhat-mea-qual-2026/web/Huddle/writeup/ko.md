# Huddle

> 스포일러: 이 문서는 문제의 분석 과정과 최종 풀이를 포함합니다.

## 개요

| 항목 | 내용 |
|---|---|
| 상태 | solved |
| 대회·플랫폼 | BlackHat MEA Qualification CTF 2026 |
| 분야 | `web` |
| 난이도 | not provided |
| Flag 형식 | `BHFlagY{...}` |

접두사 MAC 길이 확장과 QuickTime 외부 데이터 참조를 이어 붙여 서버 파일을 읽는 웹 문제다.

## 환경 및 초기 분석

권한 토큰의 해시 구성과 썸네일 처리 파이프라인을 원본 분석에서 확인했다. 요청 생성, 영상 업로드, JPEG 복호화를 하나의 솔버로 유지했다.

## 핵심 분석

비밀 길이를 반영한 SHA-256 길이 확장으로 소유자 권한과 영상 기능을 활성화한다. 외부 데이터 참조를 가진 QuickTime 파일이 서버 파일을 프레임 데이터로 읽게 하고, 사용자 팔레트로 픽셀을 플래그 바이트에 매핑한다.

```text
MAC: SHA-256(secret || message)
Secret length: 12 bytes
Privilege: owner + video enabled
Container: QuickTime dref external reference
Target: /flag.txt
Decode: custom palette over JPEG
```

## 풀이 및 재현

[`../solve.py`](../solve.py)는 [`../instance.json`](../instance.json)의 HTTP 주소를 사용해 토큰 변조, 업로드, 썸네일 회수, 픽셀 복호화를 수행한다.

```bash
python solve.py
```

## 결과

원본 풀이에서 검증된 결과를 루트의 `flag`와 대조했다.

```text
BHFlagY{31919d590eb234e12dbb832889a70055}
```

## 정리 및 회고

각 취약점은 권한 상승과 파일 읽기라는 서로 다른 역할을 맡는다. 체인을 단계별로 검증하면 이미지 압축 오차와 권한 문제를 구분할 수 있다.

## 참고 자료

- [원본 분석](../analysis/original-write-up.md)
- [공식 배포물](../challenge/)

