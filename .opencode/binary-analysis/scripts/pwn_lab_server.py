#!/usr/bin/env python3
"""pwn 本地靶场服务端 — 在 Linux 容器内为靶标二进制提供"每连接一进程"的 TCP 服务，
模拟远程 nc 环境（主机 pwntools 用 remote('127.0.0.1', <port>) 直连）。

用法（容器内）:
    python3 pwn_lab_server.py --port 9999 --binary /w/service
    python3 pwn_lab_server.py --port 9998 --binary /w/service --strace   # 每连接落 /tmp/trace_N.log

典型宿主流程见 knowledge-base/pwn-methodology.md §5 "本地靶场（Docker amd64）"。
"""
import argparse
import os
import signal
import socket
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class LabConfig:
    """靶场服务端配置（一次性解析，全程只读）。"""
    bind: str
    port: int
    binary: str
    use_strace: bool
    logdir: str


def parse_args() -> LabConfig:
    ap = argparse.ArgumentParser(
        description="fork-per-connection TCP 服务端，把连接 dup2 到靶标的 stdin/stdout/stderr")
    ap.add_argument("--port", type=int, default=9999, help="监听端口（默认 9999）")
    ap.add_argument("--binary", required=True, help="靶标二进制绝对路径（容器内路径）")
    ap.add_argument("--strace", action="store_true",
                    help="每连接用 strace -f 包裹靶标，日志落 LOGDIR/trace_N.log")
    ap.add_argument("--logdir", default="/tmp", help="strace 日志目录（默认 /tmp）")
    ap.add_argument("--bind", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
    args = ap.parse_args()
    return LabConfig(bind=args.bind, port=args.port, binary=args.binary,
                     use_strace=args.strace, logdir=args.logdir)


def serve_child(conn_fd: int, cfg: LabConfig, conn_seq: int) -> None:
    """子进程: socket 接管 0/1/2 后 exec 靶标（或 strace 包裹的靶标）。成功不返回。"""
    os.dup2(conn_fd, 0)
    os.dup2(conn_fd, 1)
    os.dup2(conn_fd, 2)
    if conn_fd > 2:
        os.close(conn_fd)
    try:
        if cfg.use_strace:
            log_path = os.path.join(cfg.logdir, f"trace_{conn_seq}.log")
            os.execvp("strace", ["strace", "-f", "-o", log_path, "-s", "64", cfg.binary])
        else:
            os.execv(cfg.binary, [cfg.binary])
    except OSError as e:
        # exec 失败（strace 未装/靶标消失）: 单行错误消息（经 dup2 送达连接，便于诊断）+ 干净退出，不产生 traceback
        print(f"[!] exec failed: {e}", file=sys.stderr, flush=True)
        os._exit(127)


def main() -> int:
    cfg = parse_args()
    if not os.path.isfile(cfg.binary):
        print(f"[!] binary not found: {cfg.binary}", file=sys.stderr)
        return 1
    if not os.access(cfg.binary, os.X_OK):
        print(f"[!] binary not executable: {cfg.binary} (chmod +x)", file=sys.stderr)
        return 1

    if cfg.use_strace:
        # strace -o 不会自建目录，logdir 不存在时每连接都会 Can't fopen——启动时预建
        os.makedirs(cfg.logdir, exist_ok=True)

    signal.signal(signal.SIGCHLD, signal.SIG_IGN)  # 自动回收子进程，防僵尸
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((cfg.bind, cfg.port))
    except OSError as e:
        print(f"[!] bind {cfg.bind}:{cfg.port} failed: {e}", file=sys.stderr)
        return 1
    srv.listen(16)
    mode = "strace" if cfg.use_strace else "plain"
    print(f"[*] pwn_lab_server listening on {cfg.bind}:{cfg.port} "
          f"binary={cfg.binary} mode={mode}", flush=True)

    conn_seq = 0
    while True:
        try:
            conn, _addr = srv.accept()
        except OSError as e:
            print(f"[!] accept failed: {e}", file=sys.stderr)
            continue
        conn_seq += 1
        try:
            pid = os.fork()
        except OSError as e:
            print(f"[!] fork failed (conn#{conn_seq} dropped): {e}", file=sys.stderr, flush=True)
            conn.close()
            continue
        if pid == 0:
            srv.close()
            serve_child(conn.fileno(), cfg, conn_seq)
            return 127  # serve_child 不返回; 兜底
        conn.close()
        print(f"[*] conn#{conn_seq} pid={pid}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
