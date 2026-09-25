# spot

> 스포일러: 이 문서는 문제의 분석 과정과 최종 풀이를 포함합니다.

## 개요

| 항목 | 내용 |
|---|---|
| 상태 | solved |
| 대회·플랫폼 | K17 CTF 2026 / noCTF |
| 분야 | misc |
| 난이도 | hard |
| Flag 형식 | `K17{...}` |

클라이언트가 먼저 `r1`을 커밋하고 서버가 `r2`를 공개한 뒤 양쪽 값을 XOR하는 구조이므로 정상적인 클라이언트로는 결과 `67`을 사후 선택할 수 없다. 결정적인 관찰은 서버가 파이프의 64바이트를 실제로 읽지 않고 `FIONREAD`로 개수만 확인한 상태에서 `r2`를 공개한다는 점이다. `vmsplice`로 아직 소비되지 않은 커밋을 가변 사용자 페이지에 연결하면 공개된 `r2`에 맞춰 그 내용을 뒤늦게 바꿀 수 있다.

## 환경 및 초기 분석

공식 입력은 [handout.zip](../challenge/handout.zip)이며, 압축 내부의 [main.py](../challenge/spot/src/main.py), [client.py](../challenge/spot/src/client.py), [runner.c](../challenge/spot/src/runner.c), [Dockerfile](../challenge/spot/Dockerfile)을 분석했다. 원본 ZIP의 SHA-256은 `24f5202474305bf872b6f370df4e7e3ba8b0d7fec63b87223a4a5572fe7b9e44`이다.

`runner`는 두 개의 파이프로 privileged `main.py`와 사용자가 지정한 Python client를 연결한다. 클라이언트에서 서버 방향은 fd 4, 서버에서 클라이언트 방향은 fd 3이다. 서버는 커밋 32바이트와 reveal 32바이트를 각각 hex로 받으므로 최종 입력은 ASCII 128바이트다. 공용 환경은 [requirements.txt](../../../requirements.txt)로 복원하며 풀이 시 Python 3.12.10과 Paramiko 5.0.0을 사용했다. 제공 Dockerfile의 원격 Python 이미지는 `python:3.14.4-slim-trixie`이다.

## 핵심 분석

`main.py`의 순서는 다음과 같다.

1. fd 3의 `FIONREAD` 값이 64 이상이 될 때까지 기다린다.
2. `secrets.token_bytes(16)`으로 `r2`를 만들고 클라이언트에 보낸다.
3. fd 3의 `FIONREAD` 값이 128 이상이 될 때까지 기다린다.
4. 그제야 `f_read.read(128)`로 `commit || reveal`을 읽는다.
5. `SHA256(reveal) == commit`을 확인하고 `int(r1) XOR int(r2) == 67`이면 flag를 출력한다.

따라서 1단계는 커밋을 소비한 것이 아니라 파이프에 존재하는 길이만 확인한다. [vmsplice_client.py](../analysis/vmsplice_client.py)는 page-aligned `MAP_SHARED` 페이지의 첫 64바이트를 `vmsplice(fd=4)`로 파이프에 넣는다. 이 pipe buffer가 아직 소비되지 않은 동안 원본 페이지를 바꾸면 서버가 나중에 읽는 바이트도 바뀐다.

`r2`를 받은 뒤 다음 값을 계산한다.

```text
r1 = int(r2, big-endian) XOR 67
salt = 00 * 16
reveal = r1 || salt
commit = SHA256(reveal)
```

처음 `vmsplice`한 페이지를 `commit.hex()`로 덮고 `reveal.hex()` 64바이트를 일반 `write`로 추가한다. 서버가 읽는 전체 128바이트는 서로 일치하는 커밋과 reveal이고, 동시에 XOR 결과는 반드시 `67`이다. WSL2 Linux 6.18.33.2와 Python 3.12.3에서 수정한 로컬 runner로 검증했을 때 `It landed on 67.`이 출력되었다. 자세한 증거는 [evidence.md](../analysis/evidence.md)에 보존했다.

## 풀이 및 재현

[solve.py](../solve.py)는 [instance.json](../instance.json)의 SSH endpoint를 읽고 비밀번호는 `SPOT_SSH_PASSWORD` 환경 변수에서만 가져온다. Paramiko로 임시 client를 `/tmp`에 업로드하고 `/home/ctf/runner`로 실행한 뒤 임시 파일을 삭제한다. 원격 출력에서 flag를 검증해 stdout에는 flag byte만 기록한다.

대회 공용 `.venv`를 활성화하고 challenge root에서 실행한다.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
export SPOT_SSH_PASSWORD='<instance password>'
python solve.py
```

PowerShell에서는 세 번째 줄 대신 `$env:SPOT_SSH_PASSWORD = '<instance password>'`를 사용한다. 인스턴스가 갱신되면 접속 정보는 `instance.json`만 수정한다.

## 결과

원격 `python solve.py`는 exit code 0, 빈 stderr, 개행 없는 49바이트 stdout을 반환했다. 그 stdout을 공식 기록 도구에 직접 전달해 [flag](../flag)와 byte 단위로 일치함을 확인했다.

```text
K17{n3verm1nd_we're_br0ke_hav3_t#is_fl@g_in$tead}
```

## 정리 및 회고

commit-reveal의 암호학적 binding은 커밋 바이트가 서버에 의해 소비되거나 불변 저장소에 복사된 뒤에만 의미가 있다. `FIONREAD`는 메시지 경계나 데이터 불변성을 보장하지 않는다. 특히 `vmsplice`처럼 pipe buffer가 사용자 페이지를 참조할 수 있는 API와 조합되면 “이미 전송했다”는 애플리케이션의 가정이 깨진다. 프로토콜은 커밋 64바이트를 먼저 정확히 읽어 별도 immutable `bytes`로 보존한 뒤 `r2`를 생성해야 한다.

## 참고 자료

- 공식 제공 [main.py](../challenge/spot/src/main.py): 커밋 길이 확인, `r2` 공개, 최종 검증 순서의 근거.
- 공식 제공 [runner.c](../challenge/spot/src/runner.c): fd 3/4 파이프 배치와 사용자 client 실행 방식의 근거.
- 공식 제공 [Dockerfile](../challenge/spot/Dockerfile): 원격 권한 모델과 Python 이미지 버전의 근거.
- 외부 문서는 사용하지 않았으며 `vmsplice` 가설은 제공 코드와 로컬·원격 실행 결과로 검증했다.
