# Dead Drop - Write-up

## 개요

- 대회명: BlackHat MEA Qualification CTF 2026
- 문제명: Dead Drop
- 분야: web
- 환경 및 접속 정보: `vm.json`
- 현재 상태: solved

## 초기 분석

문제 화면은 익명 dead-drop 게시판 `Poste Restante`를 소개한다. 사용자가 메시지와 custom CSS를 남길 수 있고, 각 drop에 private pickup log가 있다는 설명을 확인했다. 제공된 화면 캡처는 `codex-clipboard-6ef8a586-b18d-4fdf-b31d-664ba4d7da4c.png`로 보존했다.

원격 인스턴스가 살아 있을 때 다음 정상 흐름을 실제로 확인했다.

| 요청 | 응답 및 관찰 |
|---|---|
| `GET /` | `200 OK`, Express 형식 ETag, 무작위 `sid` HttpOnly 쿠키 발급 |
| `POST /post` | `302`, `Location: /post/<id>` |
| `GET /post/<id>` | 제출한 custom CSS가 별도 `<style>`에 그대로 삽입되고 `<img src="/px/<id>">` pickup beacon이 존재 |
| `GET /post/<id>/views` | owner 세션에서 JSON 배열 반환, 최초 값 `[]` |
| `POST /report` | `200`, signed-in courier가 ordinary sender에게 없는 internal handling data와 함께 drop을 렌더한다는 큐 응답 |

페이지 footer에는 courier 환경이 `CHROME 143.0.7499.192 · LINUX/AMD64`라고 명시되어 있다. 응답에는 CSP가 없고 `Referrer-Policy: no-referrer`가 설정되어 있었다.

## 핵심 분석

### CSS validator와 HTML parser의 불일치

서버의 theme validator는 `url()`, `@` rule, custom property, `value` attribute selector 및 image를 만들 수 있는 선언을 거부했다. 반면 정상 CSS comment는 허용했다.

문제는 검사를 통과한 문자열을 HTML template이 그대로 `<style>` 안에 삽입한다는 점이다. CSS parser는 다음 payload 전체를 comment로 해석하지만, HTML raw-text tokenizer는 CSS comment 문법을 모르므로 comment 안의 `</style>`도 실제 종료 태그로 처리한다.

```css
/*</style><style>ATTACKER_CSS</style><style>*/
```

따라서 validator에는 무해한 comment 하나로 보이면서 Chrome에는 `ATTACKER_CSS`가 별도의 활성 stylesheet로 생성된다. 실제 원격 검증에서 단순 image breakout과 background URL breakout 모두 `302`로 저장됐다.

### Private pickup log를 이용한 self-exfiltration

`GET /px/<id>?m=<marker>`를 호출한 뒤 owner 전용 `/post/<id>/views`를 조회하면 다음 형태가 반환됐다.

```json
[{"beacon":"/px/15?m=markerABC&extra=hello","at":1788603016324}]
```

첫 drop을 collector로 만들면 이후 courier probe의 CSS 요청을 모두 `/px/<collector-id>`에 기록할 수 있다. 외부 webhook이나 callback 서버는 필요하지 않다.

breakout 안쪽에서 `body:has([<attribute>*="BHFlagY{"])`를 사용해 courier-only DOM을 탐색한 결과 flag-bearing attribute가 `value`임을 실제 marker로 확인했다. 다음으로 `[value^="<known-prefix><candidate>"]`를 `0-9a-f}` 후보마다 만들었다. 일치한 규칙만 고유 marker URL을 background image로 요청하므로 pickup log에서 다음 한 글자를 식별할 수 있다.

여러 후보 규칙이 같은 `body`에 적용될 때 cascade로 URL이 덮이지 않도록 각 후보를 CSS custom property에 저장하고, 마지막 `background-image`에서 모든 property를 layer로 합쳤다.

## Exploit 흐름

`solve.py`는 다음을 자동화한다.

1. collector drop 생성 및 직접 marker 요청으로 pickup log 동작 검증
2. style-comment breakout을 이용한 courier-only attribute discovery
3. 한 courier 방문당 한 글자씩 flag prefix 확장
4. transient HTTP 연결 종료 재시도 및 매 글자 `work/last-run.json` checkpoint 저장
5. `BHFlagY\{[0-9a-f]+\}` 형식 검증 후 flag 출력

## Solver 또는 Exploit

프로젝트 로컬 Python 3.12 가상환경과 `requests 2.34.2`를 사용한다.

```powershell
..\..\.venv\Scripts\python.exe .\solve.py `
  --url http://k84e2c92879e2e11c9a50a9313232ca0e.playat.flagyard.com `
  --wait 20
```

성공 시 마지막 줄에 flag를 출력한다. bot 큐가 느리면 `--wait 30`으로 courier 방문 대기 시간만 늘릴 수 있다.

연결이 끊긴 실행은 `work/last-run.json`의 `last_prefix`를 다음처럼 재사용할 수 있다.

```powershell
..\..\.venv\Scripts\python.exe .\solve.py `
  --url http://<instance>.playat.flagyard.com `
  --attribute value --prefix 'BHFlagY{verified-prefix'
```

## 검증 결과

- `ast.parse()` 구문 검사: `AST_OK`
- pickup log query marker: 원격에서 실제 확인
- courier-only attribute discovery: `value`
- 최초 복구: transient 연결 종료 후 checkpoint에서 재개하여 flag 완성
- 독립 재실행: 새 collector `76`, discovery post `77`, prefix probe posts `78`–`110`에서 동일 flag 완성
- `work/last-run.json`: collector health marker, 모든 복구 prefix와 post ID 보존, 세션 cookie 미포함
- `flag`: UTF-8, BOM·개행 없음, 41 bytes
- `validate_solution.py --expected-name "Dead Drop" --flag-format "BHFlagY{...}"`: `PASS`

검증된 flag:

```
BHFlagY{c94c07c5096315b63847789d4976dc17}
```

## 회고

CSS 문자열을 AST로 안전하게 검사하더라도 그 문자열을 HTML raw-text element에 직접 삽입하면 다른 parser가 먼저 경계를 결정한다. 방어하려면 user CSS를 별도 stylesheet resource로 격리하거나 `</style`을 HTML 문맥에 맞게 escape하고, courier-only secret을 DOM에 넣지 않아야 한다. pickup endpoint도 임의 query를 owner에게 노출하지 않도록 제한해야 한다.
