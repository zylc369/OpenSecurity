# Huddle - Write-up

## 개요

- 대회명: BlackHat MEA Qualification CTF 2026
- 문제명: Huddle
- 분야: web
- 접속 정보: [`vm.json`](vm.json)의 HTTP endpoint
- 결과: `solved`

Huddle은 가입 사용자를 기본 `member`로 만들고, 서명된 초대 링크를 통해 역할을 갱신한다. `owner`만 `video_messages`를 켜고 업로드 파일의 thumbnail을 생성할 수 있다. 풀이 체인은 취약한 초대 MAC을 이용한 `owner` 승격과 FFmpeg QuickTime external data reference를 이용한 `/flag.txt` 읽기 두 단계다.

## 초기 분석

제공된 문제 이미지는 SHA-256 `0417824298dc84a6264a9585beb3e45d36273fe02b15f306f2857e8208f60cde`이며, 문제명과 다음 흐름을 제시했다.

1. 일반 member로 시작한다.
2. workspace owner 권한을 얻는다.
3. owner-only 추가 기능을 서버를 보는 창으로 이용한다.

루트 페이지는 React SPA이고 `/bundle.js`의 SHA-256은 `a58d8db595d5122b11d4c8fe20d0530d3c0c152a40766ac04de2508e59a71574`였다. bundle에서 확인한 주요 API는 다음과 같다.

| 기능 | 요청 |
|---|---|
| 가입/로그인 | `POST /api/register`, `POST /api/login` |
| 현재 사용자/workspace | `GET /api/me`, `GET /api/workspace` |
| 초대 발급/사용 | `GET /api/invite`, `POST /api/join` |
| owner 설정 | `POST /api/workspace/settings` |
| 파일 업로드/thumbnail | `POST /api/files/upload`, `POST /api/files/thumbnail` |

정상 가입 후 `/api/me`는 `role: member`를 반환했고, member가 settings를 변경하면 `403 {"error":"owner only"}`였다. 초대 응답의 `token`을 Base64 decode하면 다음 형식이었다.

```text
team=main&email=<가입 이메일>&role=member
```

`sig`는 64자리 SHA-256 계열 hex 문자열이었다.

## 핵심 분석

### 1. SHA-256 prefix-MAC 길이 확장으로 owner 승격

단순히 payload의 `role=member`를 `role=owner`로 바꾸고 기존 서명을 재사용하면 `403 invalid invite signature`가 발생했다. register/join JSON에 별도 `role` 필드를 넣는 mass assignment도 역할을 바꾸지 못했다.

반면 알려진 서명과 원문에 SHA-256 Merkle-Damgård padding 및 `&role=owner`를 붙이는 length-extension을 적용하고, 가정한 secret 길이를 1부터 64까지 검사했을 때 길이 12에서 서버가 초대를 승인했다.

위조된 decode payload의 구조는 다음과 같다.

```text
team=main&email=<email>&role=member || SHA256-padding || &role=owner
```

서버 응답과 `/api/me`가 모두 `role: owner`를 반환했다. 이 결과로부터 초대 MAC이 HMAC이 아니라 `SHA256(secret || payload)` 형태이고 secret 길이가 12바이트임을 확인했다. 파서는 마지막 `role`을 채택하므로 추가한 `owner`가 적용된다.

### 2. QuickTime external data reference로 임의 파일 읽기

owner로 `video_messages`를 켠 뒤 파일 처리 동작을 비교했다.

- PNG, GIF, text, MPEG-TS: thumbnail 생성 실패
- 정상 MP4: JPEG thumbnail 생성 성공
- 생성 JPEG comment: `Lavc59.37.100`

QuickTime/MOV의 `dref`를 self-contained `url ` 항목 대신 `alis` external reference로 바꾸고, video sample의 chunk offset을 0으로 설정했다. `/etc/passwd`를 가리킨 PoC에서 thumbnail이 생성됐고, `/flag`는 실패했지만 `/flag.txt`는 성공했다. 절대경로 external track이 실제로 열린다는 점에서 thumbnailer가 FFmpeg MOV demuxer의 external data reference와 absolute path 옵션을 허용함을 검증했다. FFmpeg 문서도 `enable_drefs`와 `use_absolute_path`가 정보 노출 위험 때문에 기본적으로 꺼져 있어야 하는 옵션임을 명시한다.

MOV video track은 외부 파일의 처음 41바이트를 `41x1` paletted rawvideo frame으로 해석한다. 일반 grayscale palette를 JPEG로 변환하면 픽셀당 약 ±1 오차가 생겨 flag의 정확성을 보장할 수 없다. 따라서 exploit은 flag 허용 문자 각각을 10단계 간격의 grayscale codeword로 배치한 inline QuickTime color table을 넣는다. 원격 JPEG의 최대 codeword 오차는 2였고, nearest-codeword decode 결과가 전체 `BHFlagY\{[0-9a-f]{32}\}` 형식과 일치했다.

## Exploit

[`solve.py`](solve.py)는 중간 파일이나 기존 세션 없이 다음을 모두 수행한다.

1. 무작위 일회용 member 계정을 가입한다.
2. 초대 payload와 signature를 받아 secret 길이 1..64의 SHA-256 length extension을 시도한다.
3. 길이 12에서 owner 승격을 확인한다.
4. `video_messages`를 활성화한다.
5. `/flag.txt`를 external `alis` dref로 가리키고 custom palette를 포함하는 MOV를 메모리에서 만든다.
6. 업로드 및 thumbnail 생성을 요청한다.
7. JPEG 픽셀을 nearest codeword로 복호화하고 flag 형식을 검증한다.

필요한 Python 패키지는 `requests`와 `Pillow`다. 프로젝트 로컬 `.venv`에서 다음과 같이 실행한다.

```powershell
.\.venv\Scripts\python.exe -m pip install requests Pillow
.\.venv\Scripts\python.exe "web\Huddle\solve.py"
```

실패하면 nonzero로 종료하며, 계정 password와 session cookie는 메모리에만 둔다.

## 검증 결과

`solve.py`를 독립적으로 두 번 실행한 결과는 다음과 같았다.

```text
[+] owner escalation accepted with secret length 12
[+] thumbnail file_id=F00000033 url=/thumbnails/2cb91fb62be7c32b.jpg
[+] palette decode maximum JPEG error=2
BHFlagY{31919d590eb234e12dbb832889a70055}
```

```text
[+] owner escalation accepted with secret length 12
[+] thumbnail file_id=F00000034 url=/thumbnails/929b5ee18e46b387.jpg
[+] palette decode maximum JPEG error=2
BHFlagY{31919d590eb234e12dbb832889a70055}
```

검증된 flag는 다음과 같다.

```text
BHFlagY{31919d590eb234e12dbb832889a70055}
```

## 회고

- 임의 prefix-MAC으로 `SHA256(secret || message)`를 쓰지 말고 HMAC-SHA-256 또는 서명된 구조화 토큰을 사용해야 한다.
- 서명 대상은 canonical serialization이어야 하며, 역할은 초대 사용자 입력이 아니라 서버 정책으로 고정해야 한다.
- 비신뢰 media에 FFmpeg `enable_drefs`/`use_absolute_path`를 켜면 로컬 파일이 external track으로 열릴 수 있다. 해당 옵션을 끄고 demuxer/protocol allowlist, 격리된 worker, 최소 권한 filesystem을 함께 적용해야 한다.
