#!/usr/bin/env python3
"""summary: Android 设备截图工具

description:
  通过 adb shell screencap 截取 Android 设备屏幕，pull 到本地，
  经 image_optimize.py 自动优化（PNG/JPEG 竞争取更小者），
  输出图片 + 元数据 JSON。
  适用于 WebView 等混合架构场景，配合 MCP 视觉工具识别控件。

usage:
  $PYTHON_CMD mobile_screenshot.py --output-dir $TASK_DIR/views --name step1_initial
  $PYTHON_CMD mobile_screenshot.py --output-dir $TASK_DIR/views --name step1_initial --serial emulator5554

level: basic
"""

import argparse
import json
import os
import re
import sys

# 脚本位于 mobile-analysis/scripts/，library 在同级目录，image_optimize 在 $SHARED_DIR/scripts/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from library import adb

# image_optimize.py 在 binary-analysis/scripts/（$SHARED_DIR/scripts/）
_SHARED_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "binary-analysis", "scripts")
sys.path.insert(0, _SHARED_SCRIPTS)
from image_optimize import optimize_for_mcp


def _fail(error):
    result = {"success": False, "error": error}
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(2)


def _log(msg):
    print(msg, file=sys.stderr)


def _parse_args():
    parser = argparse.ArgumentParser(description="Android 设备截图工具")
    parser.add_argument("--output-dir", required=True, help="输出目录")
    parser.add_argument("--name", default="screenshot", help="输出文件名前缀（不含扩展名）")
    parser.add_argument("--serial", default=None, help="设备序列号（多设备时必填，单设备自动检测）")
    return parser.parse_args()


def main():
    args = _parse_args()

    try:
        os.makedirs(args.output_dir, exist_ok=True)
    except OSError as e:
        _fail(f"创建输出目录失败: {e}")

    # 非交互设备检测（不调 resolve_device 避免 input() 挂起）
    _log("[*] 正在检测 Android 设备...")
    devices = adb.get_devices()
    if not devices:
        _fail("没有检测到连接的 Android 设备，请确保设备已连接并开启 USB 调试")

    if args.serial:
        if args.serial not in devices:
            _fail(f"指定的设备 '{args.serial}' 未找到。可用设备: {', '.join(devices)}")
        serial = args.serial
    elif len(devices) == 1:
        serial = devices[0]
        _log(f"[+] 检测到设备: {serial}")
    else:
        _fail(f"检测到多台设备 ({', '.join(devices)})，请用 --serial 指定目标设备")

    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', args.name)
    if safe_name != args.name:
        _log(f"[!] 文件名含特殊字符，已替换为: {safe_name}")
    remote_path = f"/sdcard/{safe_name}.png"

    # 截图到设备
    _log(f"[*] 正在截取设备屏幕（设备: {serial}）...")
    result = adb.adb_shell(serial, f"screencap -p {remote_path}")
    if result.returncode != 0:
        _fail(f"screencap 失败: {result.stderr.strip() or '未知错误'}")

    # pull 到本地临时文件
    tmp_png = os.path.join(args.output_dir, f"{safe_name}_raw.png")
    _log(f"[*] 正在拉取截图到本地...")
    try:
        adb.pull_file(serial, remote_path, tmp_png)
    except adb.AdbError as e:
        adb.adb_shell(serial, f"rm -f {remote_path}")
        _fail(f"拉取截图失败: {e}")

    # 清理设备临时文件
    adb.adb_shell(serial, f"rm -f {remote_path}")

    # 优化图片（PNG/JPEG 竞争）
    _log("[*] 正在优化图片...")
    opt = optimize_for_mcp(tmp_png, args.output_dir, safe_name)
    os.remove(tmp_png)

    _log(f"[+] 优化完成: {opt['format']} ({opt['size'] // 1024}KB)")

    # 输出元数据 JSON
    meta = {
        "success": True,
        "file": opt["file"],
        "format": opt["format"],
        "device": serial,
        "screenshot_path": opt["path"],
    }

    meta_path = os.path.join(args.output_dir, f"{safe_name}.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    _log(f"[+] 截图已保存: {opt['path']}")
    _log(f"[+] 元数据已保存: {meta_path}")
    print(json.dumps(meta, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
