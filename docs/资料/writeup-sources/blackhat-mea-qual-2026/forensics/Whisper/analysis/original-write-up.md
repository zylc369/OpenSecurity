---
title: "Whisper"
ctf: "BlackHat MEA Qualification CTF 2026"
date: 2026-09-05
category: forensics
difficulty: "공식 정보 미제공"
points: "공식 정보 미제공"
flag_format: "BHFlagY{...}"
author: "Codex"
---

# Whisper - Write-up

## 1. 개요 (Overview)

- **대회명:** BlackHat MEA Qualification CTF 2026
- **문제명:** Whisper
- **분야:** Forensics
- **입력 파일:** `whisper_evidence.tar.zip`
- **입력 SHA-256:** `50E82592D55E12E452A87DDF8D59701E25366AF3073A34D2AEBE41573DFD2405`

Linux workstation의 triage package에서 로컬 AI 도구의 설치·사용 흔적을 찾고, 암호화된 업로드 대상에 들어 있던 삭제 파일과 플래그를 복구하는 문제다. 핵심은 Ollama history, Linux audit log, Trash에 남은 Python script, WinZip AES archive를 연결하는 것이다.

## 2. 초기 분석 (Initial Analysis)

바깥 ZIP에는 `whisper_evidence.tar.gz` 하나가 있었고, 이를 풀면 `home`, `var/log`, `system_info`, `data` 등이 포함된 root filesystem 수집본이 나온다. 사용자와 root의 `.bash_history`는 모두 0 byte였지만 다음 증거는 남아 있었다.

| 증거 | 관찰 내용 |
|---|---|
| `/etc/systemd/system/ollama.service` | `/usr/local/bin/ollama serve`를 실행 |
| audit event 589 | `curl -fsSL https://ollama.com/install.sh` |
| audit event 905, 908 | `ollama pull tinyllama`, `ollama run tinyllama` |
| Ollama manifest/syslog | Ollama `0.30.8`, model `TinyLlama` |
| `/home/dwright/.ollama/history` | CSV AES archive 생성, 원격 upload, script 삭제, shell history 삭제 요청과 passphrase 보존 |
| Trash의 `cache_mgr.py` | 실제 archive·upload 구현 복구 |

따라서 설치된 AI 도구는 **Ollama 0.30.8**, 사용한 model은 **TinyLlama**다. 단순 업무 질문도 있었지만, 결정적으로 사용자는 다음 기능의 script 작성을 요청했다.

1. `/data/reports/*.csv`를 AES-encrypted ZIP으로 묶기
2. `requests`로 원격 server에 upload하기
3. 성공 후 script와 shell history 흔적을 지우기

## 3. 포렌식 분석 (Forensic Analysis)

삭제된 `cache_mgr.py`는 `CACHE_KEY` 환경변수 값을 다음과 같이 변환했다.

```python
archive_password = hashlib.blake2b(
    raw_passphrase.encode(), digest_size=32
).hexdigest()[:20]
```

Ollama history의 raw passphrase는 `Gr33nF0x42!D1amond`다. 이를 적용하면 실제 ZIP password는 다음과 같다.

```text
d571fe77618f54b7fca8
```

동일 script는 결과를 `/home/dwright/.cache/fontconfig/session.zip`에 쓰고 `https://transfer.sh/backup.zip`으로 HTTP PUT을 시도한다. `except: pass`로 모든 network 오류를 숨기므로 server 수신 성공 여부는 수집본만으로 확정할 수 없지만, audit event 1092는 `python /home/dwright/cache_mgr.py` 실행을 기록했고 event 1099~1103은 이 process가 다섯 CSV를 실제로 연 것을 기록했다. event 1104에는 생성된 `session.zip` 확인이, event 1185~1186에는 `/data/reports/internal_api_keys.csv` 삭제가 남아 있다.

WinZip AES archive를 파생 password로 복호화한 결과는 다음과 같다.

| 파일 | 크기 | SHA-256 | 현존 `/data/reports`와 비교 |
|---|---:|---|---|
| `customers_2025.csv` | 805332 | `A3208B17E4084DD556DC4207B07F7A69977A3B1A4218C0E5A5F8B0396FED0481` | 일치 |
| `employee_directory.csv` | 192509 | `50DA64309691D11C2A2ACEBB4DF387472459A6916A5B4FB317AD0FEB724180C7` | 일치 |
| `internal_api_keys.csv` | 4704 | `CB8C7929E5637AA93DC8DE0FCBAC25DA088829EE26DFB2928123A38EF1FDC04D` | 원본 삭제됨 |
| `revenue_q3.csv` | 39861 | `1A5E832C3AD0C8A6600B555519D578B2273EAE6C0A0613812ECA8FF523F98B59` | 일치 |
| `vendor_contracts.csv` | 1077 | `A89104A710922EFCE96AED00A5FCFB174DF37FD21860300C68D56B08D9ACBC73` | 일치 |

즉 유출 시도 데이터는 위 다섯 report이며, 핵심 민감 데이터는 삭제된 `internal_api_keys.csv`다. 이 파일의 `service=master_vault` 행에서 `key_b64`를 strict Base64 decode하면 플래그가 나온다.

## 4. 재현 (Solver)

`solve.py`는 원본 challenge archive에서 필요한 세 파일만 읽어 다음 과정을 자동화한다.

1. Ollama history에서 raw passphrase 복구
2. 삭제 script의 BLAKE2b key derivation 확인 및 ZIP password 계산
3. `session.zip` 복호화와 `internal_api_keys.csv` 복구
4. `master_vault.key_b64` 디코드 및 `BHFlagY{...}` 형식 검증

```powershell
python -m pip install -r requirements.txt
python solve.py --recover-dir work\solver-recovered
```

실행 결과:

```text
BHFlagY{l0c4l_0ll4m4_llm_f4r3n51c5_2026}
```

## 5. 결과 및 플래그 (Result & Flag)

```text
BHFlagY{l0c4l_0ll4m4_llm_f4r3n51c5_2026}
```

## 6. 회고 (Retrospective)

shell history 삭제만으로는 행위를 숨길 수 없다. Ollama prompt history, systemd/journal, auditd `EXECVE`·file access, Trash, encrypted archive가 독립적인 증거로 남아 전체 행위를 재구성했다. 방어 측에서는 local LLM prompt data governance, 민감 directory DLP, outbound file-sharing 차단, audit log 원격 보존을 함께 적용해야 한다.
