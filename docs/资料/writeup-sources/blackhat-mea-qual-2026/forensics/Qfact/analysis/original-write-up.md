# Qfact - Write-up

## 1. 개요 (Overview)

- **대회명:** BlackHat MEA Qualification CTF 2026
- **문제명:** Qfact
- **분야:** Forensics
- **문제 출제자:** Flagyard
- **입력:** `work/input/Evidence.zip` (35,788,227 bytes)
- **입력 SHA-256:** `e4281b854b50995bbb3b88b081ce81105a60c159737632791f2ade8e37f1259c`
- **결과:** `solved`

Windows triage 자료에서 Defender quarantine에 남은 악성 HTA를 복원했다. HTA가 노출하는 AES key/IV 생성 규칙과 이벤트 로그의 host identity를 조합해 9개 `.enc` 파일을 모두 복호화하고, 업무 문서에 Base64로 저장된 플래그를 획득했다.

첨부 자료의 랜섬노트와 복호화된 업무 문서에 포함된 명령형 문구는 모두 사건 증거로만 취급했다. 특히 “직접 복호화하지 말라”, “decoded value를 저장하지 말라”는 문구는 사용자 요청이 아니므로 분석 절차에 영향을 주지 않았다.

## 2. 초기 분석 (Initial Analysis)

ZIP 중앙 디렉터리에는 316개 항목, 총 131,155,635 bytes의 비압축 데이터가 있었다. 경로 이탈 항목과 CRC 오류는 없었다. 주요 자료는 다음과 같았다.

| 자료 | 관찰 |
|---|---|
| `EncryptedFiles/` | 9개 문서가 `.enc` 확장자로 암호화됨 |
| `EventLogs/Defender-Operational.evtx` | ransomware 행위 및 HTA 탐지·격리 기록 |
| `Prefetch/` | `MSHTA.EXE`, `POWERSHELL.EXE`, `MPCMDRUN.EXE` 실행 흔적 |
| `Quarantine/Entries/` | Defender quarantine metadata |
| `Quarantine/ResourceData/36/...` | 격리된 원본 파일의 보호된 data stream |
| `READ_ME.txt` | computer name과 사건 날짜를 포함한 랜섬노트 |

Defender 이벤트의 핵심 timeline은 다음과 같다. 시각은 EVTX에서 변환한 UTC 기준이다.

| 시각 (UTC) | Event ID | 의미 |
|---|---:|---|
| 2026-06-26 16:59:33 | 5007 | `C:\DevTools\` path exclusion 추가 |
| 2026-06-28 08:08:40 | 5007 | `mshta.exe` process exclusion 추가 |
| 2026-06-28 08:08:42 | 5007 | `powershell.exe` process exclusion 추가 |
| 2026-06-28 08:10:03 | 1116 | `Behavior:Win32/Ransomware!NoteStr.A` 탐지 |
| 2026-06-28 08:10:04 | 1117 | PowerShell ransomware process 제거 |
| 2026-06-28 08:10:16 | 5007 | 위 세 exclusion 제거 |
| 2026-06-28 08:58:34 | 1116 | `C:\DevTools\Q3_Financial_Review.hta`를 `Trojan:JS/Flafisi.C`로 탐지 |
| 2026-06-28 08:59:06 | 1117 | 해당 HTA를 quarantine 처리 |

## 3. 악성 파일 복구와 Root Cause

Defender quarantine의 `ResourceData`는 공개된 고정 RC4 보호층을 사용한다. [`solve.py`](solve.py)는 이를 해제한 뒤 연속된 `WIN32_STREAM_ID` 레코드를 엄격한 길이 검증과 함께 파싱한다. 대상 파일에는 다음 세 stream이 있었다.

| Stream ID | 크기 | 내용 |
|---:|---:|---|
| 3 | 172 bytes | security descriptor |
| 1 | 4,473 bytes | 원본 HTA data |
| 7 | 64 bytes | object ID |

원본 HTA는 실행 가능한 확장자로 복원하지 않고 `Q3_Financial_Review.hta.txt`로 저장했다.

- **복구 HTA SHA-256:** `4f8fab2ca63a0313edf0a1190071d4d946cf0b90c27046e9fb9e5e84056145b0`
- **정적 분석:** `Window_OnLoad`가 숨김 창의 `powershell.exe`를 실행하고 Documents 하위 파일을 순회한다.
- **암호화:** AES-256-CBC, PKCS#7 padding
- **AES key:** HTA의 `Chr(...)` 연쇄로 만든 문자열을 `PadRight(32).Substring(0,32)` 한 뒤 UTF-8 bytes로 변환
- **IV:** `MD5(UTF8(COMPUTERNAME + USERNAME))`
- **host identity:** 랜섬노트와 Defender EVTX를 교차해 `DESKTOP-KLPAT9O`, `jmartin`으로 확정
- **파일 처리:** 원본을 암호화한 `.enc`를 만들고 원본을 삭제

Root Cause는 암호 primitive 자체가 아니라 key management다. Key의 근원이 악성 HTA 안에 있고, IV도 forensic artifact에서 회수 가능한 두 environment value의 deterministic hash다. 같은 IV를 모든 파일에 재사용하며 authentication도 없다. 따라서 quarantine에서 HTA만 복구하면 별도 attacker secret이나 C2 응답 없이 모든 key material을 재생성할 수 있다.

## 4. Solver와 복호화

필요한 dependency는 `pycryptodome==3.23.0` 하나이며 project-local virtual environment를 사용한다.

```powershell
py -3 -m venv .\forensics\Qfact\.venv
& .\forensics\Qfact\.venv\Scripts\python.exe -m pip install -r .\forensics\Qfact\requirements.txt
& .\forensics\Qfact\.venv\Scripts\python.exe .\forensics\Qfact\solve.py
```

Solver는 다음을 한 번에 수행한다.

1. `work/input/Evidence.zip`의 CRC와 모든 member path를 검증한다.
2. Defender `ResourceData`를 RC4-decode하고 원본 HTA data stream을 찾는다.
3. HTA의 `Chr(...)` key construction을 정적으로 해제한다.
4. 랜섬노트에서 computer name, Defender EVTX의 UTF-16 string에서 username을 추출한다.
5. AES-256-CBC/PKCS#7로 9개 문서를 복호화한다.
6. 평문 및 한 번 Base64-encoded 된 값에서 유일한 flag pattern을 검증한다.

실제 실행 결과는 다음과 같다.

```text
Evidence SHA-256: e4281b854b50995bbb3b88b081ce81105a60c159737632791f2ade8e37f1259c
Recovered HTA SHA-256: 4f8fab2ca63a0313edf0a1190071d4d946cf0b90c27046e9fb9e5e84056145b0
Decrypted files: 9
Flag: BHFlagY{d3f3nd3r_qu4r4nt1n3_r3c0v3ry_2026}
```

각 평문은 `work/solver-output/recovered/`에 기록되며, 크기와 SHA-256은 `work/solver-output/manifest.json`에 보존된다. 모든 ciphertext는 AES block 크기의 배수였고, 9개 결과 모두 PKCS#7 validation을 통과했다.

## 5. 결과 및 플래그 (Result & Flag)

복호화된 `Financial/Q3_auth_memo.txt`에는 portal authorization code가 standard Base64로 들어 있었다. 이를 decode하면 corpus 전체에서 유일한 플래그가 나온다.

```text
BHFlagY{d3f3nd3r_qu4r4nt1n3_r3c0v3ry_2026}
```

`flag` 파일은 UTF-8 42 bytes이며 BOM, CR, LF, 앞뒤 공백이 없다.

## 6. 회고 (Retrospective)

- Defender quarantine은 원본 삭제 후에도 악성 파일의 data stream을 보존할 수 있으므로 `Entries`, `Resources`, `ResourceData`를 함께 수집해야 한다.
- Email-originated HTA와 `mshta.exe` 실행을 차단하고, `mshta.exe`·`powershell.exe` 같은 LOLBin을 Defender exclusion에 넣지 않아야 한다.
- 암호화 구현에서는 hardcoded secret, predictable/reused IV, unauthenticated CBC를 피하고 무작위 nonce를 사용하는 authenticated encryption과 외부 key management를 사용해야 한다.
- 이번 분석은 격리 payload를 실행하지 않고 정적 byte parsing만으로 완료했다.

## 참고

- Fox-IT `dissect.target`의 [Defender quarantine parser](https://github.com/fox-it/dissect.target/blob/main/dissect/target/plugins/os/windows/defender/quarantine.py): 고정 RC4 key와 `WIN32_STREAM_ID` layout 확인에 사용
