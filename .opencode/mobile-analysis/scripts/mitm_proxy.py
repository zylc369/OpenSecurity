#!/usr/bin/env python3
"""
HTTPS MITM 代理 — 拦截并篡改指定 JSON 字段

通用工具：用于移动端安全分析中拦截 HTTPS API 响应。
自签 CA 安装到设备系统 CA 目录后，配合 Frida 流量重定向使用。

用法:
    # 生成证书（首次）
    python3 mitm_proxy.py --gen-ca --workdir /tmp/mitm

    # 启动代理
    python3 mitm_proxy.py \\
        --workdir /tmp/mitm \\
        --listen-port 44300 \\
        --target-host api.target.com \\
        --tamper-field text \\
        --tamper-value "HACKED!"

    # 查看帮助
    python3 mitm_proxy.py --help
"""

import argparse
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time


def parse_args():
    p = argparse.ArgumentParser(
        description="HTTPS MITM 代理 — 拦截并篡改 JSON 响应字段",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 1. 生成 CA 证书
  %(prog)s --gen-ca --workdir ./mitm_work

  # 2. 安装 CA 到设备系统目录
  HASH=$(openssl x509 -subject_hash_old -noout -in ./mitm_work/ca.crt)
  adb push ./mitm_work/${HASH}.0 /system/etc/security/cacerts/

  # 3. 启动代理
  %(prog)s --workdir ./mitm_work --target-host api.example.com --tamper-field text --tamper-value "HACKED!"

  # 4. adb reverse 端口映射
  adb reverse tcp:44300 tcp:44300
""",
    )
    p.add_argument("--workdir", required=True, help="工作目录（存放 CA 密钥、证书等）")
    p.add_argument("--gen-ca", action="store_true", help="生成自签 CA 密钥和证书")
    p.add_argument("--target-host", help="目标 API 域名（用于生成站点证书和转发请求）")
    p.add_argument("--target-port", type=int, default=443, help="目标 API 端口（默认 443）")
    p.add_argument("--listen-host", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
    p.add_argument("--listen-port", type=int, default=44300, help="监听端口（默认 44300）")
    p.add_argument("--tamper-field", default="text", help="要篡改的 JSON 字段名（默认 text）")
    p.add_argument("--tamper-value", default="MITM HACKED! SSL Pinning BYPASSED!", help="篡改后的值")
    p.add_argument("--timeout", type=int, default=600, help="代理无连接超时秒数（默认 600）")
    return p.parse_args()


def run_openssl(cmd, check=True):
    """执行 openssl 命令"""
    result = subprocess.run(cmd, capture_output=True, check=check)
    if result.returncode != 0 and check:
        print(f"[ERROR] openssl 命令失败: {' '.join(cmd)}", file=sys.stderr)
        print(result.stderr.decode(), file=sys.stderr)
        sys.exit(1)
    return result


def generate_ca(workdir):
    """生成自签 CA 密钥和证书"""
    os.makedirs(workdir, exist_ok=True)
    ca_key = os.path.join(workdir, "ca.key")
    ca_crt = os.path.join(workdir, "ca.crt")

    if os.path.exists(ca_key) and os.path.exists(ca_crt):
        print(f"[CA] 已存在: {ca_crt}")
        return ca_key, ca_crt

    print("[CA] 生成自签 CA...")
    run_openssl(["openssl", "genrsa", "-out", ca_key, "2048"])
    run_openssl([
        "openssl", "req", "-new", "-x509", "-days", "3650",
        "-key", ca_key, "-out", ca_crt,
        "-subj", "/CN=MITM CA/O=Security Research",
    ])

    # 计算系统 CA 文件名
    result = run_openssl(["openssl", "x509", "-subject_hash_old", "-noout", "-in", ca_crt])
    hash_val = result.stdout.decode().strip()
    system_cert = os.path.join(workdir, f"{hash_val}.0")

    shutil.copy2(ca_crt, system_cert)
    print(f"[CA] CA 证书: {ca_crt}")
    print(f"[CA] 系统证书文件: {system_cert}")
    print(f"[CA] 安装命令: adb push {system_cert} /system/etc/security/cacerts/")
    return ca_key, ca_crt


def generate_server_cert(workdir, ca_key, ca_crt, target_host):
    """用 CA 签发站点证书"""
    srv_key = os.path.join(workdir, "server.key")
    srv_crt = os.path.join(workdir, "server.crt")

    # 复用已生成的证书（1 小时内有效）
    if os.path.exists(srv_crt) and (time.time() - os.path.getmtime(srv_crt)) < 3600:
        return srv_crt, srv_key

    print(f"[CERT] 生成站点证书: {target_host}")
    srv_csr = os.path.join(workdir, "server.csr")
    run_openssl(["openssl", "genrsa", "-out", srv_key, "2048"])
    run_openssl([
        "openssl", "req", "-new", "-key", srv_key, "-out", srv_csr,
        "-subj", f"/CN={target_host}/O=Security Research",
    ])

    extfile = os.path.join(workdir, "san.ext")
    with open(extfile, "w") as f:
        f.write("authorityKeyIdentifier=keyid,issuer\n")
        f.write("basicConstraints=CA:FALSE\n")
        f.write("keyUsage=digitalSignature,keyEncipherment\n")
        f.write("extendedKeyUsage=serverAuth\n")
        f.write(f"subjectAltName=DNS:{target_host},DNS:*.{target_host}\n")

    run_openssl([
        "openssl", "x509", "-req", "-in", srv_csr,
        "-CA", ca_crt, "-CAkey", ca_key, "-CAcreateserial",
        "-out", srv_crt, "-days", "365", "-extfile", extfile,
    ])
    return srv_crt, srv_key


def tamper_json(body_bytes, field, value):
    """篡改 JSON 响应中的指定字段"""
    try:
        body = json.loads(body_bytes.decode("utf-8"))
        original = body.get(field, "(无)")
        body[field] = value
        tampered = json.dumps(body, ensure_ascii=False).encode("utf-8")
        print(f"[TAMPER] {field}: \"{original[:60]}...\" → \"{value[:60]}...\"", flush=True)
        return tampered
    except Exception as e:
        print(f"[TAMPER] 篡改失败（非 JSON？）: {e}", flush=True)
        return body_bytes


def forward_request(request_data, target_host, target_port):
    """转发请求到真实服务器并获取响应"""
    ctx = ssl.create_default_context()
    with socket.create_connection((target_host, target_port), timeout=15) as sock:
        with ctx.wrap_socket(sock, server_hostname=target_host) as tls:
            tls.sendall(request_data)
            response = b""
            tls.settimeout(10.0)
            while True:
                try:
                    chunk = tls.recv(8192)
                    if not chunk:
                        break
                    response += chunk
                except socket.timeout:
                    break
    return response


def modify_response(response_data, field, value):
    """修改 HTTP 响应：解析 headers，篡改 JSON body"""
    if b"\r\n\r\n" not in response_data:
        return response_data

    header_part, body_part = response_data.split(b"\r\n\r\n", 1)
    tampered_body = tamper_json(body_part, field, value)

    # 更新 Content-Length
    new_headers = ""
    for line in header_part.decode("utf-8", errors="replace").split("\r\n"):
        if line.lower().startswith("content-length:"):
            new_headers += f"Content-Length: {len(tampered_body)}\r\n"
        else:
            new_headers += line + "\r\n"

    return new_headers.encode("utf-8") + b"\r\n" + tampered_body


def handle_client(client_sock, client_addr, target_host, target_port, field, value):
    """处理单个客户端连接"""
    try:
        print(f"[CONN] {client_addr}", flush=True)
        client_sock.settimeout(10.0)

        # 读取 HTTP 请求
        data = b""
        while b"\r\n\r\n" not in data:
            try:
                chunk = client_sock.recv(4096)
                if not chunk:
                    return
                data += chunk
            except socket.timeout:
                break

        if not data:
            return

        req_line = data.split(b"\r\n")[0].decode("utf-8", errors="replace")
        print(f"[REQ] {req_line}", flush=True)

        # 转发到真实服务器
        response = forward_request(data, target_host, target_port)
        if not response:
            print("[RESP] 无响应", flush=True)
            return

        # 篡改并返回
        modified = modify_response(response, field, value)
        client_sock.sendall(modified)
        print("[RESP] 篡改后的响应已发送", flush=True)

    except Exception as e:
        print(f"[ERROR] {e}", flush=True)
    finally:
        client_sock.close()


def main():
    args = parse_args()
    os.makedirs(args.workdir, exist_ok=True)

    # 仅生成 CA
    if args.gen_ca:
        generate_ca(args.workdir)
        return

    # 启动代理需要 target_host
    if not args.target_host:
        print("[ERROR] 启动代理需要 --target-host", file=sys.stderr)
        sys.exit(1)

    # 确保证书存在
    ca_key, ca_crt = generate_ca(args.workdir)
    srv_crt, srv_key = generate_server_cert(
        args.workdir, ca_key, ca_crt, args.target_host
    )

    # 创建 SSL context
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(srv_crt, srv_key)

    # 启动监听
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.listen_host, args.listen_port))
    server.listen(5)
    server.settimeout(args.timeout)

    print(f"[PROXY] 监听 {args.listen_host}:{args.listen_port}", flush=True)
    print(f"[PROXY] 目标: {args.target_host}:{args.target_port}", flush=True)
    print(f"[PROXY] 篡改: {args.tamper_field} → \"{args.tamper_value}\"", flush=True)
    print(f"[PROXY] 等待连接（超时 {args.timeout}s）...", flush=True)

    while True:
        try:
            client_sock, client_addr = server.accept()
            tls_sock = ctx.wrap_socket(client_sock, server_side=True)
            t = threading.Thread(
                target=handle_client,
                args=(tls_sock, client_addr, args.target_host, args.target_port,
                      args.tamper_field, args.tamper_value),
                daemon=True,
            )
            t.start()
        except socket.timeout:
            print("[PROXY] 超时退出", flush=True)
            break
        except KeyboardInterrupt:
            print("[PROXY] 中断", flush=True)
            break
        except ssl.SSLError as e:
            print(f"[PROXY] SSL 错误: {e}", flush=True)
        except Exception as e:
            print(f"[PROXY] 错误: {e}", flush=True)

    server.close()


if __name__ == "__main__":
    main()
