"""summary: 全屏截图工具

description:
  全屏截图并输出图片文件 + 元数据 JSON。
  默认 JPEG quality=50（实测 3440x1920 约 216KB，MCP 识别零损失）。
  截图和操作统一使用 pyautogui，坐标系统一致，无需映射。

usage:
  python gui_capture.py --output-dir /tmp/view --name step1_initial
  python gui_capture.py --output-dir /tmp/view --name step1_initial --format png

level: basic
"""

import argparse
import json
import os
import sys


def _fail(error):
    result = {"success": False, "error": error}
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(2)


def _log(msg):
    print(msg, file=sys.stderr)


def _parse_args():
    parser = argparse.ArgumentParser(description="全屏截图工具")
    parser.add_argument("--output-dir", required=True, help="输出目录")
    parser.add_argument("--name", default="screenshot", help="输出文件名前缀（不含扩展名）")
    parser.add_argument("--format", default="jpeg", choices=["jpeg", "png"], help="图片格式")
    parser.add_argument("--quality", type=int, default=50, help="JPEG 质量（1-100）")
    return parser.parse_args()


def main():
    args = _parse_args()

    try:
        import pyautogui
    except ImportError:
        _fail("pyautogui 未安装，请运行: pip install pyautogui")

    if args.quality < 1 or args.quality > 100:
        _fail("--quality 必须在 1-100 范围内")

    try:
        os.makedirs(args.output_dir, exist_ok=True)
    except OSError as e:
        _fail(f"创建输出目录失败: {e}")

    img_format = args.format
    quality = args.quality

    if img_format == "jpeg":
        ext = "jpg"
    else:
        ext = "png"

    img_filename = f"{args.name}.{ext}"
    img_path = os.path.join(args.output_dir, img_filename)

    _log(f"[*] 正在截图（格式: {img_format}, quality: {quality}）...")

    try:
        screenshot = pyautogui.screenshot()
        if img_format == "jpeg":
            screenshot.save(img_path, "JPEG", quality=quality)
        else:
            screenshot.save(img_path, "PNG")
    except Exception as e:
        _fail(f"截图或保存失败: {e}")

    img_size = screenshot.size
    screen_w, screen_h = pyautogui.size()

    meta = {
        "success": True,
        "file": img_filename,
        "format": img_format,
        "quality": quality if img_format == "jpeg" else None,
        "screen_resolution": [screen_w, screen_h],
        "screenshot_size": [img_size[0], img_size[1]],
    }

    meta_path = os.path.join(args.output_dir, f"{args.name}.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    _log(f"[+] 截图已保存: {img_path}")
    _log(f"[+] 元数据已保存: {meta_path}")
    print(json.dumps(meta, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
