# DeckForge - Write-up

## 개요

- 대회명: BlackHat MEA Qualification CTF 2026
- 문제명: DeckForge
- 분야: WEB
- 환경 및 접속 정보: `vm.json`
- 현재 상태: solved

## 초기 분석

`POST /html-to-image`는 `{"pages":["<HTML>"]}` 형식의 JSON을 받아 각 페이지를 Chromium으로 열고 `page_N.jpg`가 든 ZIP을 반환한다. 정상 HTML을 보냈을 때 HTTP 200, `Content-Type: application/zip`, `page_1.jpg`를 확인했다.

사용자 HTML의 JavaScript가 실행되며 `file://` 리소스 접근도 허용된다. 다음 두 결과를 원격 worker에서 실제로 확인했다.

- `<iframe src="file:///etc/passwd">`가 worker의 `/etc/passwd`를 JPEG에 표시했다.
- `fetch('file:///etc/hostname')`가 `debuerreotype`를 반환했다.

## 핵심 분석

`file:///app/` 디렉터리 인덱스를 통해 `server.py`, `html_to_image.py`, `renderer_daemon.py`, `local-run`, `supervisord.conf`를 확인했고, 파일 내용을 렌더 이미지로 읽었다.

`/app/local-run`의 핵심 동작은 다음과 같다.

1. 10자리 무작위 hex 문자열 `RAND`를 만든다.
2. 실제 flag를 `/runner/flag_${RAND}.txt`에 기록하고 소유권 `runner:runner`, mode `0400`을 설정한다.
3. `runner` 권한 ChromeDriver를 `38560 + (PORT_SEED % 8)` 포트에 `--allowed-ips=127.0.0.1 --allowed-origins='*'`로 실행한다.
4. 별도의 `app` 권한 ChromeDriver를 `40003`에서 실행한다. `/app/html_to_image.py`는 이 포트에 연결해 제출 HTML을 렌더한다.

따라서 직접 렌더되는 `app` Chromium은 `/runner/`의 파일명을 볼 수 없지만, 사용자 JavaScript는 loopback의 `runner` ChromeDriver에 요청할 수 있다. 실제로 `38560..38567`을 병렬 확인했을 때 `38566/status`에서 ChromeDriver 140.0.7339.185와 `ready: true`를 받았다.

의도된 권한 상승 체인은 다음과 같다.

1. 사용자 HTML에서 내부 `runner` ChromeDriver 포트를 찾는다.
2. WebDriver `POST /session`으로 `runner` 권한 Chromium을 만든다.
3. 새 세션을 `file:///runner/`로 이동시키고 `GET /session/{id}/source`에서 `flag_[0-9a-f]{10}.txt`를 찾는다.
4. 해당 파일로 이동한 뒤 page source에서 `BHFlagY{...}`를 추출한다.
5. 원래 페이지에 값을 표시해 반환 JPEG로 회수한다.

Root Cause는 공격자 JavaScript 실행과 `--disable-web-security`/로컬 파일 접근이 허용된 렌더러의 loopback에서, 더 높은 권한의 ChromeDriver가 임의 Origin을 허용한 채 노출된 점이다. 무작위 파일명과 Unix 권한은 내부 WebDriver 제어로 우회된다.

## Exploit

`solve.py`는 먼저 `38560..38567`의 `/status`를 병렬 조회한다. 응답 가능한 포트 인덱스를 JPEG의 회색 명도로 인코딩하고 로컬에서 픽셀값을 읽어 helper 포트를 결정한다. 이 방식은 OCR에 의존하지 않는다.

그다음 한 번의 8페이지 렌더 요청으로 다음 작업을 수행한다.

1. 첫 페이지에서 `POST /session`을 `keepalive` 요청으로 전송한다.
2. runner Chromium에는 정상 렌더러와 동일한 `--single-process`, `--no-zygote`, `--no-sandbox`, `--remote-debugging-pipe` 등의 옵션을 사용한다.
3. 각 후속 페이지에서는 하나의 WebDriver 명령만 동기적으로 실행해 페이지별 5초 제한을 피한다.
4. `/sessions`에서 세션 ID를 얻고, `file:///runner/`의 source에서 `flag_[0-9a-f]{10}.txt`를 찾는다.
5. 플래그 파일로 이동한 뒤 source에서 `BHFlagY{...}`를 추출한다.
6. 플래그 문자열을 화면 텍스트와 문자별 회색 막대에 함께 인코딩한다. `solve.py`가 막대의 중앙 픽셀을 읽어 플래그를 자동 복원한다.

실행 명령은 다음과 같다.

```powershell
& '.\.venv\Scripts\python.exe' '.\web\DeckForge\solve.py'
```

성공 출력:

```text
[+] runner helper: 127.0.0.1:38563
[+] flag: BHFlagY{879b9b8fccd447a6a1ac233f4971bd1e}
```

## 검증 결과

- 정상 렌더: PASS (`work/baseline.zip`)
- 로컬 파일 읽기: PASS (`work/local-probes/page_3.jpg`에 `/etc/passwd`)
- 내부 helper 탐색: PASS (`work/port-scan/page_1.jpg`에 `38566`, `ready: true`)
- flag end-to-end 회수: PASS (`work/exploit-20260905-204246/result/page_8.jpg`)
- 동일 exploit 재실행: PASS (`work/exploit-20260905-204338/result.json`)
- 두 실행의 flag 일치: PASS

초기 시도에서는 runner Chromium에 `--remote-debugging-pipe`가 빠져 ChromeDriver가 새 세션 생성 중 대기 상태에 빠졌다. `/app/html_to_image.py`에서 정상 렌더러의 전체 옵션을 확인해 동일하게 적용하자 세션 생성이 완료됐다. 외부 challenge URL은 인스턴스를 재시작해도 고정이며, 내부 helper 포트와 동적 플래그만 새로 생성된다.

## Flag

```text
BHFlagY{879b9b8fccd447a6a1ac233f4971bd1e}
```
