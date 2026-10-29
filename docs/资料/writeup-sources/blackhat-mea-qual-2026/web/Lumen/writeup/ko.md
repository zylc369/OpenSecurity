# Lumen

> 스포일러: 이 문서는 문제의 분석 과정과 최종 풀이를 포함합니다.

## 개요

| 항목 | 내용 |
|---|---|
| 상태 | solved |
| 대회·플랫폼 | BlackHat MEA Qualification CTF 2026 |
| 분야 | `web` |
| 난이도 | easy |
| Flag 형식 | `BHFlagY{...}` |

중복 URL 디코딩과 PHP 입력 제한 경고를 이용해 CSP를 제거하고 관리자 봇의 저장 값을 빼내는 웹 문제다.

## 환경 및 초기 분석

배포 소스에서 경로 필터, PHP 설정, 신고 봇의 localStorage 사용을 확인했다. 기존 페이로드를 동적 인스턴스 입력과 정확한 성공 출력에 맞게 정리했다.

## 핵심 분석

분할된 퍼센트 인코딩이 두 번 합쳐져 필터가 보지 못한 경로 문자를 만든다. 입력 변수 한도를 넘겨 헤더 설정 전에 경고 출력을 발생시키면 CSP가 적용되지 않고, 이미지 오류 이벤트에서 localStorage 값을 외부로 전송할 수 있다.

```text
Bypass: split %3 + c... across double URL decoding
PHP limit: max_input_vars = 1000
Payload variables: 1001
Buffering: output_buffering = 0
Execution: img onerror
Source: localStorage.flag
Sink: /trace
```

## 풀이 및 재현

[`../solve.py`](../solve.py)는 [`../instance.json`](../instance.json)의 HTTP 주소로 우회 URL을 만들고 봇을 호출한 뒤 추적 결과에서 플래그를 추출한다.

```bash
python solve.py
```

## 결과

원본 풀이에서 검증된 결과를 루트의 `flag`와 대조했다.

```text
BHFlagY{55a16ae096ae9c534c1ccf5b02cfef9f}
```

## 정리 및 회고

URL 필터는 실제 애플리케이션이 수행하는 전체 디코딩 횟수를 모델링해야 한다. 응답 헤더 보안은 헤더 이전 출력과 런타임 경고까지 포함해 검토해야 한다.

## 참고 자료

- [원본 분석](../analysis/original-write-up.md)
- [공식 배포물](../challenge/)

