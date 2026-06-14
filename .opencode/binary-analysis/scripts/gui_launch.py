"""summary: 进程和窗口管理工具

description:
  管理目标进程：启动（launch）、查找窗口（find_window）、等待窗口（wait_window）、
  切前台（bring_to_front）、终止（kill）。
  P0 仅支持 Windows（ctypes Win32 API + tasklist/taskkill）。
  对外暴露统一接口，内部按平台分发。

usage:
  python gui_launch.py --action launch --exe TARGET.EXE
  python gui_launch.py --action find_window --pid 12345
  python gui_launch.py --action wait_window --pid 12345 --timeout 10
  python gui_launch.py --action bring_to_front --pid 12345
  python gui_launch.py --action kill --pid 12345

level: basic
"""

import argparse
import json
import os
import subprocess
import sys
import time

if sys.platform != "win32":
    print(json.dumps({"success": False, "error": "gui_launch.py P0 仅支持 Windows 平台"}))
    sys.exit(2)

import ctypes
import ctypes.wintypes

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

EnumWindows = user32.EnumWindows
EnumWindows.argtypes = [ctypes.c_void_p, ctypes.wintypes.LPARAM]
EnumWindows.restype = ctypes.wintypes.BOOL

GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowThreadProcessId.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.DWORD)]
GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD

GetWindowTextW = user32.GetWindowTextW
GetWindowTextW.argtypes = [ctypes.wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
GetWindowTextW.restype = ctypes.c_int

GetClassNameW = user32.GetClassNameW
GetClassNameW.argtypes = [ctypes.wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
GetClassNameW.restype = ctypes.c_int

IsWindowVisible = user32.IsWindowVisible
IsWindowVisible.argtypes = [ctypes.wintypes.HWND]
IsWindowVisible.restype = ctypes.wintypes.BOOL

SetForegroundWindow = user32.SetForegroundWindow
SetForegroundWindow.argtypes = [ctypes.wintypes.HWND]
SetForegroundWindow.restype = ctypes.wintypes.BOOL

ShowWindow = user32.ShowWindow
ShowWindow.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
ShowWindow.restype = ctypes.wintypes.BOOL

GetWindowRect = user32.GetWindowRect
GetWindowRect.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.RECT)]
GetWindowRect.restype = ctypes.wintypes.BOOL

SW_RESTORE = 9


def _fail(action, params, error):
    result = {"success": False, "action": action, "params": params, "error": error}
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(2)


def _output(result):
    print(json.dumps(result, indent=2, ensure_ascii=False))


def _log(msg):
    print(msg, file=sys.stderr)


def _find_windows_by_pid(pid, title_filter=None):
    CMPFUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    windows = []

    def callback(hwnd, lparam):
        if not IsWindowVisible(hwnd):
            return True
        win_pid = ctypes.wintypes.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
        if win_pid.value != pid:
            return True

        text = ctypes.create_unicode_buffer(512)
        GetWindowTextW(hwnd, text, 512)
        cls = ctypes.create_unicode_buffer(256)
        GetClassNameW(hwnd, cls, 256)

        rect = ctypes.wintypes.RECT()
        GetWindowRect(hwnd, ctypes.byref(rect))

        win_title = text.value
        if title_filter and title_filter.lower() not in win_title.lower():
            return True

        windows.append({
            "handle": hwnd,
            "title": win_title,
            "class": cls.value,
            "rect": [rect.left, rect.top, rect.right, rect.bottom],
        })
        return True

    cb = CMPFUNC(callback)
    EnumWindows(cb, ctypes.wintypes.LPARAM(0))
    return windows


def _kill_by_pid(pid):
    result = subprocess.call(
        ["taskkill", "/PID", str(pid), "/F"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=0x08000000,
    )
    return result == 0


def _is_process_running_by_name(basename):
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {basename}", "/NH", "/FO", "CSV"],
            capture_output=True, text=True, timeout=10,
            creationflags=0x08000000,
        )
        return basename.lower() in result.stdout.lower()
    except (OSError, subprocess.TimeoutExpired):
        _log(f"[!] 检查进程状态失败，假设未运行")
        return False


def do_launch(exe_path):
    import shutil
    resolved = shutil.which(exe_path) or exe_path
    if not os.path.isfile(resolved) and not shutil.which(exe_path):
        _fail("launch", {"exe": exe_path}, f"可执行文件不存在: {exe_path}")

    basename = os.path.basename(exe_path)
    if _is_process_running_by_name(basename):
        _log(f"[!] 检测到 {basename} 已在运行，先终止...")
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {basename}", "/NH", "/FO", "CSV"],
                capture_output=True, text=True, timeout=10,
                creationflags=0x08000000,
            )
            for line in result.stdout.strip().split("\n"):
                if basename.lower() in line.lower():
                    parts = line.split(",")
                    if len(parts) >= 2:
                        existing_pid = int(parts[1].strip('" '))
                        _kill_by_pid(existing_pid)
                        time.sleep(0.5)
                        break
        except (OSError, subprocess.TimeoutExpired) as e:
            _log(f"[!] 终止已存在进程失败: {e}")

    _log(f"[*] 启动目标进程: {exe_path}")
    try:
        proc = subprocess.Popen(
            [exe_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=0x08000000,
        )
    except OSError as e:
        _fail("launch", {"exe": exe_path}, f"启动失败: {e}")

    time.sleep(0.2)
    poll = proc.poll()
    if poll is not None:
        _, stderr_out = proc.communicate(timeout=2)
        stderr_text = stderr_out.decode("utf-8", errors="replace") if stderr_out else ""
        proc.stderr.close()
        _fail("launch", {"exe": exe_path}, f"程序立即退出（exit code {poll}）: {stderr_text[:500]}")

    proc.stderr.close()

    _log(f"[+] 进程已启动: PID={proc.pid}")
    _output({"success": True, "action": "launch", "pid": proc.pid, "exe": exe_path})


def do_find_window(pid, title_filter=None):
    _log(f"[*] 查找 PID={pid} 的窗口...")
    windows = _find_windows_by_pid(pid, title_filter)

    if not windows:
        _log(f"[!] 未找到窗口")
        _output({"success": True, "action": "find_window", "pid": pid, "windows": []})
        return

    _log(f"[+] 找到 {len(windows)} 个窗口")
    _output({"success": True, "action": "find_window", "pid": pid, "windows": windows})


def do_wait_window(pid, timeout, title_filter=None):
    _log(f"[*] 等待 PID={pid} 的窗口出现（超时 {timeout}s）...")
    deadline = time.time() + timeout

    while time.time() < deadline:
        windows = _find_windows_by_pid(pid, title_filter)
        if windows:
            _log(f"[+] 找到 {len(windows)} 个窗口")
            _output({"success": True, "action": "wait_window", "pid": pid, "windows": windows})
            return
        time.sleep(0.5)

    _fail("wait_window", {"pid": pid, "timeout": timeout}, f"等待窗口超时（{timeout}s）")


def do_bring_to_front(pid):
    windows = _find_windows_by_pid(pid)
    if not windows:
        _fail("bring_to_front", {"pid": pid}, f"PID={pid} 没有可见窗口")

    hwnd = windows[0]["handle"]
    _log(f"[*] 将窗口切到前台: {windows[0]['title']}")
    ShowWindow(hwnd, SW_RESTORE)
    SetForegroundWindow(hwnd)
    time.sleep(0.3)
    _output({"success": True, "action": "bring_to_front", "pid": pid, "window": windows[0]["title"]})


def do_kill(pid):
    _log(f"[*] 终止进程 PID={pid}")
    ok = _kill_by_pid(pid)
    if ok:
        _log(f"[+] 进程已终止")
        _output({"success": True, "action": "kill", "pid": pid})
    else:
        _output({"success": True, "action": "kill", "pid": pid, "warning": "taskkill 返回非零，进程可能已不存在"})


def main():
    parser = argparse.ArgumentParser(description="进程和窗口管理工具")
    parser.add_argument("--action", required=True,
                        choices=["launch", "find_window", "bring_to_front", "kill", "wait_window"])
    parser.add_argument("--exe", default=None, help="可执行文件路径（launch 模式）")
    parser.add_argument("--pid", type=int, default=None, help="进程 ID")
    parser.add_argument("--title", default=None, help="窗口标题过滤（子串匹配）")
    parser.add_argument("--timeout", type=int, default=10, help="等待窗口超时（秒，默认 10）")
    args = parser.parse_args()

    if args.action == "launch":
        if not args.exe:
            _fail("launch", {"exe": args.exe}, "launch 模式需要 --exe 参数")
        do_launch(args.exe)
    elif args.action == "find_window":
        if args.pid is None:
            _fail("find_window", {"pid": args.pid}, "find_window 模式需要 --pid 参数")
        do_find_window(args.pid, args.title)
    elif args.action == "wait_window":
        if args.pid is None:
            _fail("wait_window", {"pid": args.pid}, "wait_window 模式需要 --pid 参数")
        do_wait_window(args.pid, args.timeout, args.title)
    elif args.action == "bring_to_front":
        if args.pid is None:
            _fail("bring_to_front", {"pid": args.pid}, "bring_to_front 模式需要 --pid 参数")
        do_bring_to_front(args.pid)
    elif args.action == "kill":
        if args.pid is None:
            _fail("kill", {"pid": args.pid}, "kill 模式需要 --pid 参数")
        do_kill(args.pid)


if __name__ == "__main__":
    main()
