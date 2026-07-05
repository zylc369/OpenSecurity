"""summary: 全屏截图工具

description:
  全屏截图并输出优化后的图片文件 + 元数据 JSON。
  图片经 image_optimize.py 自动优化（PNG/JPEG 竞争取更小者）。
  截图和操作统一使用 pyautogui，坐标系统一致，无需映射。

usage:
  python gui_capture.py --output-dir $TASK_DIR/views --name step1_initial

level: basic
"""

import argparse
import json
import os
import sys

# image_optimize.py 在同级目录
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from image_optimize import optimize_for_mcp


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
    return parser.parse_args()


def main():
    args = _parse_args()

    try:
        import pyautogui
    except ImportError:
        _fail("pyautogui 未安装，请运行: pip install pyautogui")

    try:
        os.makedirs(args.output_dir, exist_ok=True)
    except OSError as e:
        _fail(f"创建输出目录失败: {e}")

    _log("[*] 正在截图...")

    # 截图到临时 PNG
    tmp_png = os.path.join(args.output_dir, f"{args.name}_raw.png")
    try:
        screenshot = pyautogui.screenshot()
        screenshot.save(tmp_png, "PNG")
    except Exception as e:
        _fail(f"截图失败: {e}")

    screen_w, screen_h = pyautogui.size()
    img_w, img_h = screenshot.size

    # 优化图片（PNG/JPEG 竞争）
    _log("[*] 正在优化图片...")
    opt = optimize_for_mcp(tmp_png, args.output_dir, args.name)
    os.remove(tmp_png)  # 删除临时文件

    _log(f"[+] 优化完成: {opt['format']} ({opt['size'] // 1024}KB)")

    # 输出元数据 JSON
    meta = {
        "success": True,
        "file": opt["file"],
        "format": opt["format"],
        "screen_resolution": [screen_w, screen_h],
        "screenshot_size": [img_w, img_h],
        "screenshot_path": opt["path"],
    }

    meta_path = os.path.join(args.output_dir, f"{args.name}.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    _log(f"[+] 截图已保存: {opt['path']}")
    _log(f"[+] 元数据已保存: {meta_path}")
    print(json.dumps(meta, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
