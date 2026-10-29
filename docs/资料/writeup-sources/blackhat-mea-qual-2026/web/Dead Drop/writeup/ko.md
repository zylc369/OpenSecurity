# Dead Drop

> 스포일러: 이 문서는 문제의 분석 과정과 최종 풀이를 포함합니다.

## 개요

| 항목 | 내용 |
|---|---|
| 상태 | solved |
| 대회·플랫폼 | BlackHat MEA Qualification CTF 2026 |
| 분야 | `web` |
| 난이도 | not provided |
| Flag 형식 | `BHFlagY{...}` |

CSS 검사기와 HTML 파서의 해석 차이를 이용해 비공개 픽업 로그를 유출하는 웹 문제다.

## 환경 및 초기 분석

신고 봇이 비공개 페이지를 방문하는 흐름과 CSS 저장 검사를 원본 분석에서 확인했다. 기존 속성 탐색과 접두사 복구 단계를 한 실행으로 정리했다.

## 핵심 분석

CSS 주석처럼 보이는 문자열이 HTML raw-text 종료 태그로 해석되게 만들어 새 스타일 블록을 삽입한다. 속성 선택자와 외부 배경 요청을 이용해 플래그 속성과 값을 접두사 단위로 복구한다.

```text
Breakout: /*</style><style>ATTACKER_CSS</style><style>*/
Target: private pickup log
Discovery: CSS attribute selectors
Exfiltration: external background requests
Recovery: prefix oracle over the value attribute
```

## 풀이 및 재현

[`../solve.py`](../solve.py)는 [`../instance.json`](../instance.json)의 HTTP 주소를 읽고 수집용 드롭 생성, 봇 신고, 속성 탐색, 값 복구를 자동화한다. 진행 상태는 `output/`에 기록한다.

```bash
python solve.py
```

## 결과

원본 풀이에서 검증된 결과를 루트의 `flag`와 대조했다.

```text
BHFlagY{c94c07c5096315b63847789d4976dc17}
```

## 정리 및 회고

필터가 허용한 문자열이 최종 HTML 컨텍스트에서도 같은 의미를 갖는다는 보장은 없다. 검증기와 브라우저의 파싱 경계를 함께 봐야 한다.

## 참고 자료

- [원본 분석](../analysis/original-write-up.md)
- [공식 배포물](../challenge/)

