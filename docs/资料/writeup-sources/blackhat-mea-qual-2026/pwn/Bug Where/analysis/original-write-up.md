# Bug Where

## 요약

- 분야: PWN / Linux kernel
- 취약점: Linux 7.2-rc3 `io_uring` provided-buffer bundle의 dangling iovec 및 반복 해제
- KASLR 우회: 문제에 포함된 QEMU `PREFETCH` 패치의 mapped/unmapped 시간 차이
- 권한 상승: 해제된 1 KiB iovec를 `pipe_buffer[16]`으로 재할당한 뒤 `pipe_buffer.ops` 변조
- 특이점: `CONFIG_KMALLOC_PARTITION_RANDOM=y`라 공격 iovec와 대상의 할당 call site가 같은 16개 파티션에 배치될 때 성공한다. exploit은 pipe를 만드는 서로 다른 두 경로를 함께 시도하고, 둘 다 불일치하면 새 VM에 재연결한다.

초기 단일 pipe 버전은 로컬 패치 QEMU의 23번째 새 부팅에서 실제 겹침을 확인했다. 두 pipe 재할당 후보로 강화한 최종 버전은 디버그 추적과 추가 커널 인자를 제거한 원본 조건의 첫 검증 부팅에서 다음 결과를 냈다.

```text
[+] commit_creds(init_cred) executed
[+] uid=0 flag=BHFlagY{LOCAL_TEST}
```

`BHFlagY{LOCAL_TEST}`는 로컬 검증 디스크에 넣은 테스트 문자열이다. 실제 원격 `tcp.flagyard.com:23514`에서는 여섯 번째 fresh VM에서 다음 결과를 얻었다.

```text
[+] commit_creds(init_cred) executed
[+] uid=0 flag=BHFlagY{ef2d81621299ed9b3a5d1f418cc352d2}
```

## 분석

### 실행 환경

initramfs의 `/init`은 `/drop_shell`을 통해 셸을 UID 1337로 내린다. 플래그는 root만 열 수 있는 `/dev/sda`에 있다. 커널은 `7.2.0-rc3-round100`이며 중요한 설정은 다음과 같다.

```text
CONFIG_RANDOMIZE_BASE=y
CONFIG_KMALLOC_PARTITION_CACHES=y
CONFIG_KMALLOC_PARTITION_RANDOM=y
# CONFIG_MEMCG is not set
CONFIG_SLAB_FREELIST_RANDOM=y
CONFIG_SLAB_FREELIST_HARDENED=y
```

QEMU CPU는 `qemu64`라 SMEP와 SMAP이 노출되지 않는다. 따라서 커널의 간접 호출 대상을 사용자 매핑의 함수로 바꾸는 ret2usr가 가능하다.

### KASLR oracle

`qemu-hardening.patch`는 ring 3의 `PREFETCH`도 kernel MMU index로 조회한다. 주소가 매핑되어 있으면 host 주소를 prefetch하고, 매핑되지 않았으면 256회 지연 루프를 돈다.

```c
int mmu_idx = cpu_mmu_index_kernel(env);
probe_access_flags(env, addr, 1, MMU_DATA_LOAD, mmu_idx, true, &host, GETPC());
if (host)
    __builtin_prefetch(host, 0, 0);
else
    for (unsigned i = 0; i < 256; i++)
        delay += i;
```

exploit은 먼저 자기 주소와 확실한 미매핑 주소로 시간을 보정한 뒤 `0xffffffff80000000`부터 2 MiB 단위로 탐색한다. 연속 세 페이지가 빠른 첫 위치를 `_text`로 잡는다. 로컬 측정에서는 64회 prefetch 기준 mapped가 약 0.7 µs, unmapped가 약 22 µs로 충분히 분리됐다.

복원한 `vmlinux`에서 필요한 심볼 오프셋은 다음과 같다.

```text
_text        = 0xffffffff81000000
commit_creds = 0xffffffff812dcfd0  (offset 0x002dcfd0)
init_cred    = 0xffffffff8300d700  (offset 0x0200d700)
```

### Root cause

취약한 `io_uring/kbuf.c::io_ring_buffers_peek()`는 이전 요청에서 캐시된 iovec 배열을 받으면 `KBUF_MODE_FREE`를 설정한다. 함수 끝에서 현재 `arg->iovs`를 무조건 해제한다.

```c
struct iovec *org_iovs = arg->iovs;
...
if (arg->mode & KBUF_MODE_FREE)
    kfree(arg->iovs);
```

원래 의도는 더 큰 새 배열로 교체한 경우에만 옛 배열 `org_iovs`를 버리는 것이다. upstream 수정은 다음 조건으로 바뀌었다.

```diff
- if (arg->mode & KBUF_MODE_FREE)
-     kfree(arg->iovs);
+ if (arg->iovs != org_iovs && (arg->mode & KBUF_MODE_FREE))
+     kfree(org_iovs);
```

수정 커밋은 Linux upstream의 [`f1596ba3e6b3` — io_uring/kbuf: don't free the cached buffer vec](https://github.com/torvalds/linux/commit/f1596ba3e6b390aa0fef8466afce44efecf39d8d)이다.

## 익스플로잇

### 1. dangling iovec 만들기

256-entry provided-buffer ring과 UNIX socketpair를 만든다. 첫 multishot `IORING_OP_RECV`에는 아래 플래그를 사용한다.

```text
IOSQE_BUFFER_SELECT
IORING_RECVSEND_BUNDLE
IORING_RECV_MULTISHOT
```

64개의 1-byte 버퍼와 64 bytes의 socket data를 공급하면 fast iovec 하나로는 부족하므로 `64 * sizeof(struct iovec) = 1024` bytes가 할당된다. 첫 CQE는 `res=64`, `IORING_CQE_F_MORE`이고 이 배열은 async message에 캐시된다.

두 번째 shot의 64개 버퍼 주소는 읽기 전용 사용자 페이지를 가리킨다. `access_ok()`는 주소 범위만 검사하므로 통과하고, 취약한 끝부분에서 캐시된 1 KiB 배열이 해제된다. 이후 receive copy는 `-EFAULT`로 끝나지만 async message에는 해제된 배열 포인터가 남는다.

```text
multishot #1: res=64 flags=0x3
multishot #2: res=-14 flags=0x0 (iovec freed)
```

### 2. pipe_buffer로 재할당

미리 pipe 용량을 4096 bytes로 줄여 기본 `pipe_buffer[16]` 배열을 해제한다. dangling iovec을 만든 직후 용량을 65536 bytes로 키우면 `pipe_resize_ring()`이 다음 크기를 할당한다.

```text
16 * sizeof(struct pipe_buffer) = 16 * 40 = 640 bytes
```

이는 iovec와 같은 `kmalloc-1k` 크기다. `CONFIG_MEMCG=n`이므로 pipe의 `GFP_KERNEL_ACCOUNT`도 별도 cgroup cache가 아닌 일반 partition cache를 사용한다.

다만 cache index는 `hash_64(call_site ^ random_kmalloc_seed, 4)`로 정해진다. 특정 대상 하나만 보면 `io_ring_buffers_peek`와 대상의 call site가 같은 index가 될 확률은 약 `1/16`이다.

최종 exploit은 1 KiB pipe 대상도 두 call site로 만든다. 하나는 미리 만든 pipe를 `F_SETPIPE_SZ`로 키우는 `pipe_resize_ring()`, 다른 하나는 UAF 뒤 새 pipe를 만드는 `alloc_pipe_info()`이다. 둘 중 같은 파티션에 들어온 첫 배열이 dangling iovec 주소를 회수한다.

### 3. pipe ops 덮어쓰기

두 번째 shot은 EFAULT라 `[64, 128)` provided-buffer 구간을 소비하지 않았다. 이 구간을 pipe 배열 모양에 맞춰 다시 쓴 뒤 같은 io_uring의 단발 bundle receive를 제출한다. async-message cache가 dangling iovec를 다시 사용하므로 `io_ring_buffers_peek()`가 공격자가 지정한 `(iov_base, iov_len)` 쌍을 pipe 배열 위에 직접 기록한다.

`struct pipe_buffer` 크기는 40 bytes이고 `ops`는 각 객체의 offset 16에 있다. pipe의 head/tail을 미리 두 번 진행시켜 index 2를 live slot으로 만든 뒤 `pipe_buffer[2].ops`만 사용자 공간의 가짜 ops 테이블을 가리키게 한다.

```c
struct pipe_buf_operations fake_ops = {
    .confirm = (void *)kernel_text_base, /* 사용자 배열에 base 보관 */
    .release = get_root,
};
```

pipe를 닫으면 `pipe_buf_release()`가 `fake_ops->release()`를 CPL0에서 호출한다. SMEP/SMAP이 없으므로 사용자 코드 `get_root()`가 실행되고 다음 호출 후 정상 반환한다.

```c
commit_creds(kernel_text_base + 0x0200d700); /* init_cred */
```

마지막으로 `/dev/sda`를 열어 플래그를 읽는다.

두 pipe call site가 공격 iovec와 같은 bucket에 배치되는 사건은 완전히 독립적이지 않다. 해당 커널의 실제 token 주소와 `hash_64()`로 균일한 64-bit seed를 표본화하면 둘 중 하나가 일치하는 비율은 약 12%였다. 실패가 안전하게 관측되도록 만들고 uploader가 최대 64개의 fresh VM을 시도한다.

## 실행법

게스트 바이너리를 다시 빌드하려면 Linux/WSL에서 다음을 실행한다.

```sh
gcc -static -O2 -Wall -Wextra -fno-stack-protector -no-pie \
  -o exploit exploit.c
```

`solve.py`는 직접 게스트 셸을 제공하는 인스턴스와 계산 게이트가 붙은 인스턴스를 모두 감지한다. 게이트가 있으면 32-bit 키의 SHA-256 앞 64 bit가 주어지고, `work/gpu_pow.py`가 OpenCL GPU로 원문 키를 탐색한다. 이후 각 연결에서 새 VM을 받아 자동 재시도한다. 계산 게이트를 통과해야 하는 Windows 환경에서는 프로젝트 가상환경에 `pyopencl`과 `numpy`가 필요하다.

```sh
python3 solve.py HOST PORT --attempts 64 --retry-delay 2
```

로컬에서 문제의 패치 QEMU 빌드와 검증 initramfs가 준비되어 있다면 다음 명령으로 원본 커널 인자 조건을 반복 검증할 수 있다.

```sh
python3 solve.py --local
```

## 파일

- `exploit.c`: KASLR oracle, io_uring UAF trigger, pipe overlap, ret2usr 권한 상승
- `exploit`: 정적 링크한 x86-64 게스트 실행 파일
- `solve.py`: 원격 업로드 및 fresh-VM 재시도, 로컬 재현 진입점
- `work/gpu_pow.py`: 원격 게이트의 32-bit SHA-256 PoW용 OpenCL GPU 탐색기
- `work/run-qemu-native.sh`: 패치 QEMU 네이티브 실행기
- `work/retry-local.sh`: randomized partition collision 자동 재시도
