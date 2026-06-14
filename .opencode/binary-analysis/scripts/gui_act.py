"""summary: 坐标级键鼠操作工具

description:
  通过 pyautogui + pyperclip 模拟人的键鼠操作。
  支持 click / double_click / type / hotkey / scroll 五种操作。
  type 模式下推荐使用 --paste 标志（剪贴板粘贴），支持中文和特殊字符。

usage:
  python gui_act.py --action click --x 460 --y 320
  python gui_act.py --action type --text "hello" --paste
  python gui_act.py --action hotkey --keys "ctrl+c"
  python gui_act.py --action scroll --direction down --clicks 3 --x 500 --y 400

level: basic
"""

import argparse
import json
import sys
import time


def _fail(action, params, error):
    result = {"success": False, "action": action, "params": params, "error": error}
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(2)


def _output(success, action, params, settle_seconds):
    result = {
        "success": success,
        "action": action,
        "params": params,
        "settle_seconds": settle_seconds,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


def _log(msg):
    print(msg, file=sys.stderr)


def _parse_args():
    parser = argparse.ArgumentParser(description="坐标级键鼠操作工具")
    parser.add_argument("--action", required=True,
                        choices=["click", "double_click", "type", "hotkey", "scroll"],
                        help="操作类型")
    parser.add_argument("--x", type=int, default=None, help="X 坐标")
    parser.add_argument("--y", type=int, default=None, help="Y 坐标")
    parser.add_argument("--text", default=None, help="要输入的文本（type 模式）")
    parser.add_argument("--keys", default=None, help="快捷键，+ 分隔（hotkey 模式）")
    parser.add_argument("--direction", default=None, choices=["up", "down"], help="滚动方向（scroll 模式）")
    parser.add_argument("--clicks", type=int, default=3, help="滚动次数（scroll 模式，默认 3）")
    parser.add_argument("--button", default="left", choices=["left", "right", "middle"], help="鼠标按钮")
    parser.add_argument("--paste", action="store_true", help="type 模式下用剪贴板粘贴")
    parser.add_argument("--settle", type=float, default=0.5, help="操作后等待时间（秒，默认 0.5）")
    return parser.parse_args()


def main():
    args = _parse_args()

    try:
        import pyautogui
    except ImportError:
        _fail(args.action, {}, "pyautogui 未安装，请运行: pip install pyautogui")

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05

    screen_w, screen_h = pyautogui.size()
    action = args.action
    settle = args.settle

    if action in ("click", "double_click"):
        params = {"x": args.x, "y": args.y, "button": args.button}
        if args.x is None or args.y is None:
            _fail(action, params, f"{action} 模式需要 --x 和 --y 参数")
        if not (0 <= args.x < screen_w and 0 <= args.y < screen_h):
            _fail(action, params, f"坐标 ({args.x}, {args.y}) 超出屏幕范围 ({screen_w}x{screen_h})")
        _log(f"[*] 执行 {action}: ({args.x}, {args.y})")
        if action == "click":
            pyautogui.click(args.x, args.y, button=args.button)
        else:
            pyautogui.doubleClick(args.x, args.y, button=args.button)
        time.sleep(settle)
        _output(True, action, params, settle)

    elif action == "type":
        params = {"text": args.text}
        if args.text is None or args.text == "":
            _fail(action, params, "type 模式需要非空 --text 参数")
        _log(f"[*] 输入文本: {args.text[:50]}{'...' if len(args.text) > 50 else ''}")

        has_non_ascii = any(ord(c) > 127 for c in args.text)
        use_paste = args.paste or has_non_ascii

        if use_paste:
            try:
                import pyperclip
            except ImportError:
                _fail(action, params, "pyperclip 未安装，请运行: pip install pyperclip")
            _log("[*] 使用剪贴板粘贴模式")
            pyperclip.copy(args.text)
            time.sleep(0.05)
            pyautogui.hotkey("ctrl", "v")
        else:
            _log("[*] 使用逐字输入模式")
            pyautogui.typewrite(args.text)

        time.sleep(settle)
        _output(True, action, {"text": args.text, "paste": use_paste}, settle)

    elif action == "hotkey":
        if args.keys is None:
            _fail(action, {"keys": None}, "hotkey 模式需要 --keys 参数")
        keys_list = [k.strip() for k in args.keys.split("+")]
        params = {"keys": keys_list}
        _log(f"[*] 执行快捷键: {'+'.join(keys_list)}")
        pyautogui.hotkey(*keys_list)
        time.sleep(settle)
        _output(True, action, params, settle)

    elif action == "scroll":
        params = {"direction": args.direction, "clicks": args.clicks, "x": args.x, "y": args.y}
        if args.direction is None:
            _fail(action, params, "scroll 模式需要 --direction 参数")
        scroll_amount = args.clicks if args.direction == "up" else -args.clicks
        scroll_x = args.x if args.x is not None else pyautogui.position()[0]
        scroll_y = args.y if args.y is not None else pyautogui.position()[1]
        if args.x is not None and not (0 <= scroll_x < screen_w):
            _fail(action, params, f"X 坐标 {scroll_x} 超出屏幕宽度 {screen_w}")
        if args.y is not None and not (0 <= scroll_y < screen_h):
            _fail(action, params, f"Y 坐标 {scroll_y} 超出屏幕高度 {screen_h}")
        _log(f"[*] 滚动: {args.direction} {args.clicks} 次")
        pyautogui.scroll(scroll_amount, x=scroll_x, y=scroll_y)
        time.sleep(settle)
        _output(True, action, {"direction": args.direction, "clicks": args.clicks, "x": scroll_x, "y": scroll_y}, settle)


if __name__ == "__main__":
    main()
