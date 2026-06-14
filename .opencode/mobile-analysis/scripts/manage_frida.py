#!/usr/bin/env python3
"""Frida-server 生命周期管理 CLI — 供 AI Agent 通过 bash 调用。

功能:
  install  — 下载 + 安装 frida-server 到 Android 设备（随机名 + 随机目录）
  start    — 启动 frida-server + 端口转发，输出 JSON（host_port, device_port, pid）
  stop     — 停止 frida-server + 清理端口转发
  status   — 检查 frida-server 状态，输出 JSON

数据存储在 ~/bw-frida/frida-server/install_record.json。
"""

import argparse
import json
import sys
from pathlib import Path

# library 模块已内置到本目录下
_LIBRARY_DIR = Path(__file__).parent / "library"
sys.path.insert(0, str(_LIBRARY_DIR))

from library import adb
from library import install_record
from library import port as port_mod
from library.random_name import generate_random_name
from library.log import log


def _output_json(data: dict) -> None:
    """输出 JSON 到 stdout（供 AI Agent 解析）。"""
    print(json.dumps(data, indent=2, ensure_ascii=False))


def action_install(serial: str, upgrade: bool = False) -> None:
    """下载并安装 frida-server 到设备。"""
    from library.frida_server_downloader import prepare_frida_server

    # 检查已有安装
    record = install_record.get_device_record(serial)
    if record and not upgrade:
        install_path = record.get("installPath")
        if install_path and adb.check_path_exists(serial, install_path):
            _output_json({
                "status": "already_installed",
                "device": serial,
                "install_path": install_path,
                "message": "frida-server 已安装，使用 --upgrade 强制更新",
            })
            return

    # 下载
    log.info("正在准备 frida-server...")
    try:
        source_path = prepare_frida_server(upgrade=upgrade)
    except Exception as e:
        _output_json({"status": "error", "device": serial, "message": f"下载失败: {e}"})
        sys.exit(1)

    if source_path is None:
        _output_json({"status": "error", "device": serial, "message": "无法获取 frida-server 二进制文件"})
        sys.exit(1)

    # 安装到设备
    dir_name = generate_random_name()
    file_name = generate_random_name()
    install_dir = f"/data/local/tmp/{dir_name}"
    install_path = f"{install_dir}/{file_name}"

    log.info("安装到设备 %s: %s", serial, install_path)
    try:
        adb.mkdir_p(serial, install_dir)
        adb.push_file(serial, str(source_path), install_path)
        adb.adb_shell(serial, f"chmod 755 {install_path}")
    except Exception as e:
        _output_json({"status": "error", "device": serial, "message": f"安装失败: {e}"})
        sys.exit(1)

    # 更新安装记录
    install_record.update_device_record(
        serial,
        sourcePath=str(source_path),
        installPath=install_path,
    )

    _output_json({
        "status": "installed",
        "device": serial,
        "install_path": install_path,
        "source": str(source_path),
    })


def action_start(serial: str) -> None:
    """启动 frida-server 并设置端口转发。"""
    record = install_record.get_device_record(serial)
    if not record:
        _output_json({
            "status": "error",
            "device": serial,
            "message": "未找到安装记录，请先执行 install",
        })
        sys.exit(1)

    install_path = record.get("installPath")
    if not install_path:
        _output_json({"status": "error", "device": serial, "message": "安装记录缺少 installPath"})
        sys.exit(1)

    if not adb.check_path_exists(serial, install_path):
        _output_json({"status": "error", "device": serial, "message": f"frida-server 不存在: {install_path}"})
        sys.exit(1)

    # 检查是否已在运行
    existing_host_port = record.get("hostTcpPort")
    existing_android_port = record.get("androidTcpPort")
    if existing_host_port and existing_android_port:
        # 验证是否真的在运行
        import frida
        try:
            device = frida.get_device_manager().add_remote_device(f"127.0.0.1:{existing_host_port}")
            device.enumerate_processes()
            pid = _get_remote_pid(serial, install_path)
            _output_json({
                "status": "already_running",
                "device": serial,
                "host_port": existing_host_port,
                "device_port": existing_android_port,
                "pid": pid,
                "install_path": install_path,
            })
            return
        except Exception:
            log.info("已有端口转发但连接失败，重新启动...")

    # 分配端口
    android_port = port_mod.find_free_android_port(serial)
    host_port = port_mod.find_free_host_port()

    # 启动
    log.info("启动 frida-server: %s -l 0.0.0.0:%d", install_path, android_port)
    process = adb.run_frida_server_bg(serial, install_path, android_port)
    adb.forward_port(serial, host_port, android_port)

    # 更新记录
    install_record.update_device_record(
        serial,
        hostTcpPort=host_port,
        androidTcpPort=android_port,
    )

    # 获取 PID
    import time
    pid = None
    basename = Path(install_path).name
    for _ in range(5):
        time.sleep(1)
        result = adb.adb_shell(serial, f"pidof {basename}")
        pid_str = result.stdout.strip()
        if pid_str:
            try:
                pid = int(pid_str.split()[0])
                break
            except (ValueError, IndexError):
                continue

    _output_json({
        "status": "started",
        "device": serial,
        "host_port": host_port,
        "device_port": android_port,
        "pid": pid,
        "install_path": install_path,
    })


def action_stop(serial: str) -> None:
    """停止 frida-server 并清理端口转发。"""
    record = install_record.get_device_record(serial)
    if not record:
        _output_json({"status": "not_running", "device": serial, "message": "无安装记录"})
        return

    install_path = record.get("installPath")
    host_port = record.get("hostTcpPort")

    # 终止远程进程
    if install_path:
        basename = Path(install_path).name
        adb.adb_shell(serial, f"su -c 'pkill -9 -f {basename}' 2>/dev/null || pkill -9 -f {basename} 2>/dev/null")

    # 清理端口转发
    if host_port:
        adb.remove_forward(serial, host_port)

    # 更新记录
    install_record.update_device_record(serial, hostTcpPort=None, androidTcpPort=None)

    _output_json({
        "status": "stopped",
        "device": serial,
    })


def action_status(serial: str) -> None:
    """检查 frida-server 状态。"""
    record = install_record.get_device_record(serial)

    if not record:
        _output_json({
            "status": "not_installed",
            "device": serial,
            "message": "未找到安装记录，请先执行 install",
        })
        return

    install_path = record.get("installPath")
    host_port = record.get("hostTcpPort")
    android_port = record.get("androidTcpPort")

    # 检查进程是否运行
    pid = _get_remote_pid(serial, install_path) if install_path else None

    # 检查连接是否可用
    connection_ok = False
    if host_port:
        import frida
        try:
            device = frida.get_device_manager().add_remote_device(f"127.0.0.1:{host_port}")
            device.enumerate_processes()
            connection_ok = True
        except Exception:
            pass

    _output_json({
        "status": "running" if (pid and connection_ok) else "stopped",
        "device": serial,
        "install_path": install_path,
        "host_port": host_port,
        "device_port": android_port,
        "pid": pid,
        "connection": "ok" if connection_ok else "failed",
    })


def _get_remote_pid(serial: str, install_path: str) -> int | None:
    """获取远程 frida-server 的 PID。"""
    if not install_path:
        return None
    basename = Path(install_path).name
    result = adb.adb_shell(serial, f"pidof {basename}")
    pid_str = result.stdout.strip()
    if pid_str:
        try:
            return int(pid_str.split()[0])
        except (ValueError, IndexError):
            return None
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Frida-server 生命周期管理 CLI（供 AI Agent 调用）"
    )
    parser.add_argument(
        "--action",
        choices=["install", "start", "stop", "status"],
        required=True,
        help="操作类型",
    )
    parser.add_argument(
        "-s", "--serial",
        metavar="SERIAL",
        help="设备序列号（省略则自动选择）",
    )
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="强制重新下载 frida-server（仅 install 操作）",
    )
    args = parser.parse_args()

    serial = args.serial
    if args.action != "status" or serial is None:
        serial = adb.resolve_device(serial)

    if args.action == "install":
        action_install(serial, upgrade=args.upgrade)
    elif args.action == "start":
        action_start(serial)
    elif args.action == "stop":
        action_stop(serial)
    elif args.action == "status":
        if serial is None:
            _output_json({"status": "no_device", "message": "未检测到设备"})
            return
        action_status(serial)


if __name__ == "__main__":
    main()
