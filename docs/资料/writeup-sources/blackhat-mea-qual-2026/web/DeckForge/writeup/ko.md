# DeckForge

> 스포일러: 이 문서는 문제의 분석 과정과 최종 풀이를 포함합니다.

## 개요

| 항목 | 내용 |
|---|---|
| 상태 | solved |
| 대회·플랫폼 | BlackHat MEA Qualification CTF 2026 |
| 분야 | `web` |
| 난이도 | not provided |
| Flag 형식 | `BHFlagY{...}` |

HTML 이미지 변환 기능에서 실행되는 JavaScript와 내부 ChromeDriver를 연결해 파일을 읽는 웹 문제다.

## 환경 및 초기 분석

렌더러가 JavaScript와 file URL을 허용하고 내부 러너가 여러 ChromeDriver 포트를 사용함을 원본 실험 자료에서 확인했다. 최종 경로에 필요한 증거만 남기도록 출력을 정리했다.

## 핵심 분석

렌더러 안에서 내부 포트를 탐색해 WebDriver 세션을 만들고 더 높은 권한의 러너 컨텍스트를 얻는다. 로컬 디렉터리에서 플래그 파일명을 찾고 내용을 밝기 막대로 인코딩한 JPEG를 반환시켜 복호화한다.

```text
Entry point: /html-to-image
Browser capabilities: JavaScript + file://
Internal service: ChromeDriver
Candidate ports: 38560..38567
Chrome option: --allowed-origins=*
Exfiltration: JPEG grayscale bars
```

## 풀이 및 재현

[`../solve.py`](../solve.py)는 [`../instance.json`](../instance.json)의 HTTP 주소를 사용해 헬퍼 포트 식별, 세션 생성, 파일 탐색, 이미지 디코딩을 수행한다. 증거는 `output/`에 저장한다.

```bash
python solve.py
```

## 결과

원본 풀이에서 검증된 결과를 루트의 `flag`와 대조했다.

```text
BHFlagY{879b9b8fccd447a6a1ac233f4971bd1e}
```

## 정리 및 회고

낮은 권한 렌더러와 높은 권한 자동화 러너 사이의 경계가 공격면이었다. 이미지 출력만 허용돼도 정량적인 픽셀 값으로 임의 데이터를 전달할 수 있다.

## 참고 자료

- [원본 분석](../analysis/original-write-up.md)
- [공식 배포물](../challenge/)

