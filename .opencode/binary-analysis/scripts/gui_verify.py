"""summary: Win32 GUI 自动化验证脚本

description:
  自动化操作 Win32 GUI 对话框，支持四种模式：
  1. discover: 枚举控件，输出 ID/类型/类名
  2. standard: 标准 GUI 操作 + 多维行为观察
  3. hook-inject: Frida Hook 注入参数
  4. hook-result: Frida Hook 读取比较结果
  hook-inject 和 hook-result 可组合使用。
  仅支持 Windows 平台。通过 Win32 API (ctypes) 实现 GUI 操作。
  Hook 模式需要 frida 包（通过 $PYTHON_CMD 运行）。

usage:
  python gui_verify.py --exe TARGET.EXE --username "test" --license "XXXX" --output result.json
  python gui_verify.py --exe TARGET.EXE --discover --output discover.json
  python gui_verify.py --exe TARGET.EXE --hook-inject --hook-func-addr 0x401000 --hook-inputs-file inputs.json --output result.json
  python gui_verify.py --exe TARGET.EXE --username "test" --license "XXXX" --hook-result --hook-compare-addr 0x401200 --output result.json

level: intermediate
"""

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time

if sys.platform != "win32":
    print(json.dumps({"success": False, "error": "gui_verify.py 仅支持 Windows 平台"}))
    sys.exit(2)

import ctypes.wintypes

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

# kernel32 函数声明（用于进程检测）
kernel32.OpenProcess.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD]
kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
kernel32.WaitForSingleObject.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD]
kernel32.WaitForSingleObject.restype = ctypes.wintypes.DWORD
kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
kernel32.CloseHandle.restype = ctypes.wintypes.BOOL

# Win32 API 声明
FindWindowW = user32.FindWindowW
FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
FindWindowW.restype = ctypes.wintypes.HWND

GetDlgItem = user32.GetDlgItem
GetDlgItem.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
GetDlgItem.restype = ctypes.wintypes.HWND

SendMessageW = user32.SendMessageW
SendMessageW.argtypes = [ctypes.wintypes.HWND, ctypes.c_uint, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM]
SendMessageW.restype = ctypes.wintypes.LPARAM

PostMessageW = user32.PostMessageW
PostMessageW.argtypes = [ctypes.wintypes.HWND, ctypes.c_uint, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM]
PostMessageW.restype = ctypes.c_bool

EnumWindows = user32.EnumWindows
EnumWindows.argtypes = [ctypes.c_void_p, ctypes.wintypes.LPARAM]
EnumWindows.restype = ctypes.wintypes.BOOL

EnumChildWindows = user32.EnumChildWindows
EnumChildWindows.argtypes = [ctypes.wintypes.HWND, ctypes.c_void_p, ctypes.wintypes.LPARAM]
EnumChildWindows.restype = ctypes.wintypes.BOOL

GetWindowTextW = user32.GetWindowTextW
GetWindowTextW.argtypes = [ctypes.wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
GetWindowTextW.restype = ctypes.c_int

GetClassNameW = user32.GetClassNameW
GetClassNameW.argtypes = [ctypes.wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
GetClassNameW.restype = ctypes.c_int

GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowThreadProcessId.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.DWORD)]
GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD

GetDlgCtrlID = user32.GetDlgCtrlID
GetDlgCtrlID.argtypes = [ctypes.wintypes.HWND]
GetDlgCtrlID.restype = ctypes.c_int

GetWindowLongPtrW = user32.GetWindowLongPtrW
GetWindowLongPtrW.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
GetWindowLongPtrW.restype = ctypes.c_void_p

WM_SETTEXT = 0x000C
WM_COMMAND = 0x0111
BM_CLICK = 0x00F5
BN_CLICKED = 0

DEFAULT_EDIT1_ID = 1000
DEFAULT_EDIT2_ID = 1001
DEFAULT_BUTTON_ID = 1002

SUCCESS_KEYWORDS = ["success", "correct", "right", "congratulat", "ok", "注册成功", "验证成功", "正确", "well done", "bravo"]
FAIL_KEYWORDS = ["fail", "wrong", "error", "invalid", "incorrect", "失败", "错误", "无效"]
BUTTON_TEXT_KEYWORDS = ["verify", "check", "ok", "submit", "确认", "验证", "login", "test"]


# ============ 窗口查找 ============

def _find_main_window(pid, timeout=10):
    """查找指定 PID 的主窗口"""
    deadline = time.time() + timeout
    CMPFUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    result = {"handle": None, "text": None}

    def callback(hwnd, lparam):
        win_pid = ctypes.wintypes.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
        if win_pid.value == pid:
            text = ctypes.create_unicode_buffer(512)
            GetWindowTextW(hwnd, text, 512)
            if text.value:
                result["handle"] = hwnd
                result["text"] = text.value
                return False
        return True

    cb = CMPFUNC(callback)
    while time.time() < deadline:
        result["handle"] = None
        result["text"] = None
        EnumWindows(cb, ctypes.wintypes.LPARAM(pid))
        if result["handle"]:
            return result["handle"], result["text"]
        time.sleep(0.5)
    return None, None


def _find_all_windows(pid):
    """查找指定 PID 的所有窗口"""
    CMPFUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    windows = []

    def callback(hwnd, lparam):
        win_pid = ctypes.wintypes.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
        if win_pid.value == pid:
            text = ctypes.create_unicode_buffer(512)
            GetWindowTextW(hwnd, text, 512)
            cls = ctypes.create_unicode_buffer(256)
            GetClassNameW(hwnd, cls, 256)
            windows.append({
                "handle": hwnd,
                "text": text.value,
                "class": cls.value,
            })
        return True

    cb = CMPFUNC(callback)
    EnumWindows(cb, ctypes.wintypes.LPARAM(0))
    return windows


# ============ 控件枚举（discover 模式） ============

def _enum_children(parent_hwnd):
    """枚举父窗口的所有子控件"""
    CMPFUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    controls = []

    def callback(hwnd, lparam):
        ctrl_id = GetDlgCtrlID(hwnd)
        cls = ctypes.create_unicode_buffer(256)
        GetClassNameW(hwnd, cls, 256)
        text = ctypes.create_unicode_buffer(512)
        SendMessageW(hwnd, 0x000D, 512, ctypes.addressof(text))  # WM_GETTEXT

        class_lower = cls.value.lower()
        if "edit" in class_lower:
            ctrl_type = "edit"
        elif "button" in class_lower:
            ctrl_type = "button"
        elif "static" in class_lower:
            ctrl_type = "static"
        elif "combo" in class_lower:
            ctrl_type = "combobox"
        else:
            ctrl_type = "other"

        controls.append({
            "id": ctrl_id,
            "class": cls.value,
            "type": ctrl_type,
            "text": text.value,
        })
        return True

    cb = CMPFUNC(callback)
    EnumChildWindows(parent_hwnd, cb, ctypes.wintypes.LPARAM(0))
    return controls


def _suggest_controls(controls):
    """根据启发式规则推荐控件 ID"""
    edits = [c for c in controls if c["type"] == "edit"]
    buttons = [c for c in controls if c["type"] == "button"]
    notes = []

    # Edit: 按 ID 排序，前 2 个
    edits.sort(key=lambda c: c["id"])
    edit1_id = edits[0]["id"] if len(edits) >= 1 else DEFAULT_EDIT1_ID
    edit2_id = edits[1]["id"] if len(edits) >= 2 else DEFAULT_EDIT2_ID
    if len(edits) > 2:
        notes.append(f"检测到 {len(edits)} 个 Edit 控件，请根据实际用途选择")

    # Button: 优先文本匹配
    btn_id = DEFAULT_BUTTON_ID
    for kw in BUTTON_TEXT_KEYWORDS:
        for b in buttons:
            if b["text"] and kw in b["text"].lower():
                btn_id = b["id"]
                break
        if btn_id != DEFAULT_BUTTON_ID:
            break
    if btn_id == DEFAULT_BUTTON_ID and buttons:
        btn_id = buttons[0]["id"]

    suggested = f"--edit1-id {edit1_id} --edit2-id {edit2_id} --button-id {btn_id}"
    return suggested, notes


# ============ GUI 操作 ============

def _set_text(hwnd, text):
    SendMessageW(hwnd, WM_SETTEXT, 0, ctypes.c_wchar_p(text))
    time.sleep(0.1)


def _click_button(parent_hwnd, button_hwnd):
    ctrl_id = GetDlgCtrlID(button_hwnd)
    if ctrl_id == 0:
        ctrl_id = GetWindowLongPtrW(button_hwnd, -12)
    PostMessageW(parent_hwnd, WM_COMMAND, (BN_CLICKED << 16) | ctrl_id, button_hwnd)
    time.sleep(0.2)


def _find_button_by_heuristic(main_wnd, button_id):
    """尝试按 ID 或启发式找到按钮"""
    btn = GetDlgItem(main_wnd, button_id)
    if btn:
        return btn
    # 启发式：枚举子控件找 Button
    children = _enum_children(main_wnd)
    for kw in BUTTON_TEXT_KEYWORDS:
        for c in children:
            if c["type"] == "button" and c["text"] and kw in c["text"].lower():
                return GetDlgItem(main_wnd, c["id"])
    # 兜底：取第一个 button
    for c in children:
        if c["type"] == "button":
            return GetDlgItem(main_wnd, c["id"])
    return None


# ============ 多维行为观察 ============

def _observe_behavior(pid, main_wnd, proc, rounds=5, interval=0.5):
    """串行轮询多个观察维度。proc 为 subprocess.Popen 对象，用于检查进程状态。"""
    observations = {
        "new_windows": [],
        "title_changed": False,
        "static_texts": [],
        "exit_code": None,
        "process_running": True,
    }

    initial_title = ctypes.create_unicode_buffer(512)
    GetWindowTextW(main_wnd, initial_title, 512)

    for _ in range(rounds):
        time.sleep(interval)

        # 检查进程状态
        poll = proc.poll()
        if poll is not None:
            observations["exit_code"] = poll
            observations["process_running"] = False
            break

        # 检查新窗口
        windows = _find_all_windows(pid)
        for w in windows:
            text_lower = w["text"].lower()
            if w["handle"] != main_wnd and w["text"]:
                is_result = any(kw in text_lower for kw in SUCCESS_KEYWORDS + FAIL_KEYWORDS)
                if is_result and w["text"] not in observations["new_windows"]:
                    observations["new_windows"].append(w["text"])

        # 检查标题变化
        current_title = ctypes.create_unicode_buffer(512)
        GetWindowTextW(main_wnd, current_title, 512)
        if current_title.value != initial_title.value:
            observations["title_changed"] = True

        # 检查 Static 控件文本
        children = _enum_children(main_wnd)
        for c in children:
            if c["type"] == "static" and c["text"]:
                for kw in SUCCESS_KEYWORDS + FAIL_KEYWORDS:
                    if kw in c["text"].lower() and c["text"] not in observations["static_texts"]:
                        observations["static_texts"].append(c["text"])

    return observations


def _observe_frida_process(pid, rounds=5, interval=0.5):
    """Frida 管理的进程的行为观察（无 Popen 对象，通过 EnumWindows 和进程检测判断）"""
    observations = {
        "new_windows": [],
        "title_changed": False,
        "static_texts": [],
        "exit_code": None,
        "process_running": True,
    }

    # 检查进程是否仍在运行
    SYNCHRONIZE = 0x100000
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if handle:
        WAIT_TIMEOUT = 0x102
        result = kernel32.WaitForSingleObject(handle, 0)
        kernel32.CloseHandle(handle)
        if result != WAIT_TIMEOUT:
            observations["process_running"] = False
            return observations  # 进程已死，后续观察无意义

    # 查找该进程的窗口
    windows = _find_all_windows(pid)
    main_wnd = None
    initial_title = ""
    for w in windows:
        if w["text"]:
            main_wnd = w["handle"]
            initial_title = w["text"]
            break

    if not main_wnd:
        return observations

    for _ in range(rounds):
        time.sleep(interval)
        # 每轮检查进程存活
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            wait_result = kernel32.WaitForSingleObject(handle, 0)
            kernel32.CloseHandle(handle)
            if wait_result != WAIT_TIMEOUT:
                observations["process_running"] = False
                break
        all_wins = _find_all_windows(pid)
        for w in all_wins:
            text_lower = w["text"].lower()
            if w["handle"] != main_wnd and w["text"]:
                is_result = any(kw in text_lower for kw in SUCCESS_KEYWORDS + FAIL_KEYWORDS)
                if is_result and w["text"] not in observations["new_windows"]:
                    observations["new_windows"].append(w["text"])
        # 检查标题变化
        current_title = ctypes.create_unicode_buffer(512)
        GetWindowTextW(main_wnd, current_title, 512)
        if current_title.value != initial_title:
            observations["title_changed"] = True
        children = _enum_children(main_wnd)
        for c in children:
            if c["type"] == "static" and c["text"]:
                for kw in SUCCESS_KEYWORDS + FAIL_KEYWORDS:
                    if kw in c["text"].lower() and c["text"] not in observations["static_texts"]:
                        observations["static_texts"].append(c["text"])

    return observations


def _judge_from_observations(observations):
    """从多维观察判断验证结果，返回 (passed_bool_or_none, message, confidence)"""
    # 优先检查新窗口
    for text in observations.get("new_windows", []):
        lower = text.lower()
        if any(kw in lower for kw in SUCCESS_KEYWORDS):
            return True, text, "high"
        if any(kw in lower for kw in FAIL_KEYWORDS):
            return False, text, "high"

    # 检查 Static 文本
    for text in observations.get("static_texts", []):
        lower = text.lower()
        if any(kw in lower for kw in SUCCESS_KEYWORDS):
            return True, text, "medium"
        if any(kw in lower for kw in FAIL_KEYWORDS):
            return False, text, "medium"

    # 检查标题变化
    if observations.get("title_changed"):
        return None, "主窗口标题发生变化", "low"

    # 无明确信号
    return None, "未检测到明确的验证结果信号", "low"


# ============ Frida Hook 相关 ============

def _check_frida():
    """检查 frida 是否可用"""
    try:
        import frida
        return True
    except ImportError:
        return False


def _build_inject_js(func_addr, inputs, calling_convention="auto"):
    """构建 Hook 注入参数的 JS 代码"""
    inputs_json = json.dumps(inputs)
    return f"""
'use strict';
var funcAddr = ptr("{func_addr}");
var inputs = {inputs_json};

Interceptor.attach(funcAddr, {{
    onEnter: function(args) {{
        for (var i = 0; i < inputs.length; i++) {{
            var inp = inputs[i];
            if (inp.type === "str") {{
                var buf = Memory.allocUtf8String(inp.value);
                args[inp.arg] = buf;
            }} else if (inp.type === "int") {{
                args[inp.arg] = ptr(inp.value);
            }} else if (inp.type === "wstr") {{
                var buf = Memory.allocUtf16String(inp.value);
                args[inp.arg] = buf;
            }}
        }}
        send({{type: "inject_done", args_count: inputs.length}});
    }}
}});
"""


def _build_result_js(compare_addrs, compare_type="auto"):
    """构建 Hook 读取比较结果的 JS 代码"""
    addrs_json = json.dumps([hex(a) for a in compare_addrs])
    return f"""
'use strict';
var compareAddrs = {addrs_json};
var compareType = "{compare_type}";
var results = [];

for (var idx = 0; idx < compareAddrs.length; idx++) {{
    (function(addrStr) {{
        var addr = ptr(addrStr);

        // 尝试 Hook 已知导入函数
        if (compareType === "memcmp" || compareType === "auto") {{
            try {{
                var memcmpAddr = Module.getGlobalExportByName("memcmp");
                if (memcmpAddr && memcmpAddr.equals(addr)) {{
                    Interceptor.attach(memcmpAddr, {{
                        onEnter: function(args) {{
                            this.buf1 = args[0];
                            this.buf2 = args[1];
                            this.size = args[2].toInt32();
                        }},
                        onLeave: function(retval) {{
                            var size = Math.min(this.size, 64);
                            var b1 = this.buf1.readByteArray(size);
                            var b2 = this.buf2.readByteArray(size);
                            send({{
                                type: "compare", addr: addrStr,
                                op1_hex: Array.from(new Uint8Array(b1)).map(function(b){{return ('0'+b.toString(16)).slice(-2)}}).join(' '),
                                op2_hex: Array.from(new Uint8Array(b2)).map(function(b){{return ('0'+b.toString(16)).slice(-2)}}).join(' '),
                                match: retval.toInt32() === 0
                            }});
                        }}
                    }});
                    return;
                }}
            }} catch(e) {{}}
        }}

        if (compareType === "strcmp" || compareType === "auto") {{
            try {{
                var strcmpAddr = Module.getGlobalExportByName("strcmp");
                if (strcmpAddr && strcmpAddr.equals(addr)) {{
                    Interceptor.attach(strcmpAddr, {{
                        onEnter: function(args) {{
                            this.s1 = args[0].readUtf8String();
                            this.s2 = args[1].readUtf8String();
                        }},
                        onLeave: function(retval) {{
                            send({{
                                type: "compare", addr: addrStr,
                                op1_str: this.s1,
                                op2_str: this.s2,
                                match: retval.toInt32() === 0
                            }});
                        }}
                    }});
                    return;
                }}
            }} catch(e) {{}}
        }}

        // 通用 Hook（无法获取返回值，match 为 null 表示未知）
        Interceptor.attach(addr, {{
            onEnter: function(args) {{
                try {{
                    var b1 = args[0].readByteArray(32);
                    var b2 = args[1].readByteArray(32);
                    send({{
                        type: "compare", addr: addrStr,
                        op1_hex: Array.from(new Uint8Array(b1)).map(function(b){{return ('0'+b.toString(16)).slice(-2)}}).join(' '),
                        op2_hex: Array.from(new Uint8Array(b2)).map(function(b){{return ('0'+b.toString(16)).slice(-2)}}).join(' '),
                        match: null
                    }});
                }} catch(e) {{
                    send({{type: "error", addr: addrStr, error: e.toString()}});
                }}
            }}
        }});
    }})(compareAddrs[idx]);
}}
"""


def _run_frida_hook(target_path, js_code, timeout=30, need_click=False, button_id=DEFAULT_BUTTON_ID, need_gui_input=False, username=None, license_code=None, edit1_id=DEFAULT_EDIT1_ID, edit2_id=DEFAULT_EDIT2_ID, observe_rounds=3):
    """通用 Frida Hook 执行框架
    
    need_click: resume 后是否需要点击按钮触发验证
    need_gui_input: 是否需要先通过 GUI 输入数据
    """
    import frida

    try:
        pid = frida.spawn(target_path)
    except Exception as e:
        return {"success": False, "error": f"Frida spawn 失败: {e}。请检查目标程序路径和架构"}

    try:
        session = frida.attach(pid)
    except Exception as e:
        _kill_process(pid)
        return {"success": False, "error": f"Frida attach 失败: {e}。建议：1. 检查架构 2. 管理员权限 3. 切换 IDA 调试器"}

    try:
        script = session.create_script(js_code)
    except Exception as e:
        _kill_process(pid)
        return {"success": False, "error": f"Hook 脚本加载失败: {e}"}

    messages = []
    def on_message(msg, data):
        if msg["type"] == "send":
            messages.append(msg["payload"])
        elif msg["type"] == "error":
            messages.append({"type": "error", "error": msg.get("stack", str(msg))})

    script.on("message", on_message)

    observations = {}
    try:
        script.load()
        frida.resume(pid)

        # resume 后等待窗口出现并进行 GUI 操作
        if need_click or need_gui_input:
            time.sleep(2)
            main_wnd, wnd_text = _find_main_window(pid, timeout=10)
            if main_wnd:
                if need_gui_input and username and license_code:
                    edit1 = GetDlgItem(main_wnd, edit1_id)
                    edit2 = GetDlgItem(main_wnd, edit2_id)
                    button = _find_button_by_heuristic(main_wnd, button_id)
                    if edit1 and edit2:
                        _set_text(edit1, username)
                        _set_text(edit2, license_code)
                    if button:
                        _click_button(main_wnd, button)
                elif need_click:
                    button = _find_button_by_heuristic(main_wnd, button_id)
                    if button:
                        _click_button(main_wnd, button)

            # 在 sleep 期间收集 observations
            observations = _observe_frida_process(pid, rounds=observe_rounds, interval=0.5)

        time.sleep(timeout)
    except KeyboardInterrupt:
        pass
    finally:
        # sleep 后做最终一轮观察（捕获延迟弹窗等慢响应）
        if need_click or need_gui_input:
            final_obs = _observe_frida_process(pid, rounds=2, interval=0.5)
            for key in ["new_windows", "static_texts"]:
                for item in final_obs.get(key, []):
                    if item not in observations.get(key, []):
                        observations.setdefault(key, []).append(item)
            if final_obs.get("title_changed"):
                observations["title_changed"] = True
        try:
            session.detach()
        except Exception:
            pass
        _kill_process(pid)

    return {"success": True, "messages": messages, "pid": pid, "observations": observations}


def _kill_process(pid):
    if sys.platform == "win32":
        subprocess.call(
            ["taskkill", "/PID", str(pid), "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=0x08000000  # CREATE_NO_WINDOW
        )


# ============ 模式实现 ============

def run_discover(exe_path, timeout):
    """discover 模式：枚举控件"""
    if not os.path.isfile(exe_path):
        return {"success": False, "error": f"可执行文件不存在: {exe_path}"}

    print(f"[*] 启动目标进程: {exe_path}")
    try:
        proc = subprocess.Popen([exe_path])
    except OSError as e:
        return {"success": False, "error": f"启动失败: {e}"}

    pid = proc.pid
    try:
        print(f"[*] 等待主窗口出现（超时 {timeout}s）...")
        main_wnd, wnd_text = _find_main_window(pid, timeout=timeout)
        if not main_wnd:
            return {"success": False, "error": "未找到主窗口", "pid": pid}

        print(f"[+] 找到主窗口: {wnd_text}")
        controls = _enum_children(main_wnd)
        suggested, notes = _suggest_controls(controls)

        print(f"[+] 发现 {len(controls)} 个控件")
        return {
            "success": True,
            "mode": "discover",
            "controls": controls,
            "suggested_args": suggested,
            "notes": notes,
        }
    finally:
        _terminate_proc(proc)


def run_standard(exe_path, username, license_code, edit1_id, edit2_id, button_id, timeout, observe_rounds):
    """standard 模式：GUI 操作 + 多维观察"""
    if not os.path.isfile(exe_path):
        return {"success": False, "error": f"可执行文件不存在: {exe_path}"}

    print(f"[*] 启动目标进程: {exe_path}")
    try:
        proc = subprocess.Popen([exe_path])
    except OSError as e:
        return {"success": False, "error": f"启动失败: {e}"}

    pid = proc.pid
    try:
        print(f"[*] 等待主窗口出现（超时 {timeout}s）...")
        main_wnd, wnd_text = _find_main_window(pid, timeout=timeout)
        if not main_wnd:
            return {"success": False, "error": "未找到主窗口", "pid": pid}

        print(f"[+] 找到主窗口: {wnd_text}")

        edit1 = GetDlgItem(main_wnd, edit1_id)
        edit2 = GetDlgItem(main_wnd, edit2_id)
        button = _find_button_by_heuristic(main_wnd, button_id)

        if not edit1:
            return {"success": False, "error": f"未找到编辑框1 (ID={edit1_id})", "pid": pid}
        if not edit2:
            return {"success": False, "error": f"未找到编辑框2 (ID={edit2_id})", "pid": pid}
        if not button:
            return {"success": False, "error": f"未找到按钮 (ID={button_id})", "pid": pid}

        print(f"[*] 输入用户名: {username}")
        _set_text(edit1, username)
        print(f"[*] 输入 License: {license_code}")
        _set_text(edit2, license_code)
        print("[*] 点击验证按钮...")
        _click_button(main_wnd, button)

        print(f"[*] 多维行为观察（{observe_rounds} 轮）...")
        observations = _observe_behavior(pid, main_wnd, proc, rounds=observe_rounds)

        passed, message, confidence = _judge_from_observations(observations)

        result = {
            "success": True,
            "mode": "standard",
            "verification_passed": passed,
            "message": message,
            "confidence": confidence,
            "observations": observations,
        }

        if passed is True:
            print(f"[+] 验证通过: {message}")
        elif passed is False:
            print(f"[-] 验证失败: {message}")
        else:
            print(f"[?] 结果不确定: {message}")

        return result
    finally:
        _terminate_proc(proc)


def run_hook_inject(exe_path, func_addr, inputs, trigger_addr=None, calling_convention="auto", timeout=30, compare_addrs=None, observe_rounds=5, button_id=DEFAULT_BUTTON_ID):
    """hook-inject 模式（可组合 hook-result）"""
    if not _check_frida():
        return {"success": False, "error": "frida 未安装，请运行: $PYTHON_CMD -m pip install frida"}

    if not os.path.isfile(exe_path):
        return {"success": False, "error": f"可执行文件不存在: {exe_path}"}

    # 构建 JS — 组合模式时先设 compare hook，再设 inject hook（需求 Branch C）
    js_code = ""
    if compare_addrs:
        js_code = _build_result_js(compare_addrs, "auto")

    js_code += _build_inject_js(func_addr, inputs, calling_convention)

    # 如果有 trigger_addr，追加触发逻辑（Branch B: 监控 trigger 点入口/出口）
    if trigger_addr:
        js_code += f"""
var triggerAddr = ptr("{hex(trigger_addr)}");
Interceptor.attach(triggerAddr, {{
    onEnter: function(args) {{
        send({{type: "trigger_hit", addr: "{hex(trigger_addr)}"}});
    }},
    onLeave: function(retval) {{
        send({{type: "trigger_return", retval: retval.toInt32()}});
    }}
}});
"""

    print(f"[*] Hook inject 模式: func={hex(func_addr)}, inputs={len(inputs)} 个参数")
    if trigger_addr:
        print(f"[*] 使用 trigger-addr: {hex(trigger_addr)}")
    if compare_addrs:
        print(f"[*] 组合 hook-result: {len(compare_addrs)} 个比较地址")

    frida_result = _run_frida_hook(
        exe_path, js_code, timeout=timeout,
        need_click=(trigger_addr is None),
        button_id=button_id,
        observe_rounds=observe_rounds,
    )

    if not frida_result["success"]:
        return frida_result

    messages = frida_result.get("messages", [])

    # 提取比较结果
    compare_results = []
    for m in messages:
        if m.get("type") == "compare":
            compare_results.append(m)

    if compare_results:
        non_none = [c for c in compare_results if c.get("match") is not None]
        if non_none:
            all_match = all(c["match"] for c in non_none)
        else:
            all_match = None  # 所有比较结果均为未知
        confidence = "high" if all_match else "medium" if all_match is False else "low"
        return {
            "success": True,
            "mode": "hook_inject",
            "compare_results": compare_results,
            "verification_passed": all_match,
            "confidence": confidence,
            "aggregation_rule": "all",
            "observations": frida_result.get("observations", {}),
        }

    # 无比较结果，检查 inject_done 消息
    inject_done = any(m.get("type") == "inject_done" for m in messages)
    if inject_done:
        return {
            "success": True,
            "mode": "hook_inject",
            "verification_passed": None,
            "message": "Hook 注入成功，但无比较结果可读",
            "confidence": "low",
            "observations": frida_result.get("observations", {}),
        }

    return {
        "success": True,
        "mode": "hook_inject",
        "verification_passed": None,
        "message": "Hook 未触发或无消息返回",
        "confidence": "low",
        "observations": frida_result.get("observations", {}),
    }


def run_hook_result(exe_path, username, license_code, compare_addrs, compare_type, edit1_id, edit2_id, button_id, timeout, observe_rounds):
    """hook-result 模式：标准 GUI 输入 + Hook 读取比较结果"""
    if not _check_frida():
        return {"success": False, "error": "frida 未安装，请运行: $PYTHON_CMD -m pip install frida"}

    if not os.path.isfile(exe_path):
        return {"success": False, "error": f"可执行文件不存在: {exe_path}"}

    js_code = _build_result_js(compare_addrs, compare_type)

    print(f"[*] Hook result 模式: {len(compare_addrs)} 个比较地址，通过 GUI 输入触发")

    frida_result = _run_frida_hook(
        exe_path, js_code, timeout=timeout,
        need_click=True,
        button_id=button_id,
        need_gui_input=True,
        username=username,
        license_code=license_code,
        edit1_id=edit1_id,
        edit2_id=edit2_id,
        observe_rounds=observe_rounds,
    )

    if not frida_result["success"]:
        return frida_result

    messages = frida_result.get("messages", [])

    # 提取比较结果
    compare_results = []
    for m in messages:
        if m.get("type") == "compare":
            compare_results.append(m)

    if compare_results:
        non_none = [c for c in compare_results if c.get("match") is not None]
        if not non_none:
            return {
                "success": True,
                "mode": "hook_result",
                "compare_results": compare_results,
                "verification_passed": None,
                "message": "比较结果均为未知（通用 Hook 无法判断匹配状态）",
                "confidence": "low",
                "observations": frida_result.get("observations", {}),
            }
        all_match = all(c["match"] for c in non_none)
        return {
            "success": True,
            "mode": "hook_result",
            "compare_results": compare_results,
            "verification_passed": all_match,
            "confidence": "high",
            "aggregation_rule": "all",
            "observations": frida_result.get("observations", {}),
        }

    return {
        "success": True,
        "mode": "hook_result",
        "compare_results": [],
        "verification_passed": None,
        "message": "比较点未命中，无比较结果",
        "confidence": "low",
        "observations": frida_result.get("observations", {}),
    }


def _terminate_proc(proc):
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


# ============ 参数解析与入口 ============

def main():
    parser = argparse.ArgumentParser(description="Win32 GUI 自动化验证")

    # 基础参数
    parser.add_argument("--exe", required=True, help="目标可执行文件路径")
    parser.add_argument("--username", required=False, help="用户名")
    parser.add_argument("--license", required=False, help="License 代码")
    parser.add_argument("--output", "-o", help="输出 JSON 文件路径")
    parser.add_argument("--timeout", type=int, default=30, help="standard/discover 模式为窗口查找超时；hook 模式为 Hook 消息等待时间（默认 30）")
    parser.add_argument("--edit1-id", type=int, default=DEFAULT_EDIT1_ID, help="用户名编辑框控件 ID")
    parser.add_argument("--edit2-id", type=int, default=DEFAULT_EDIT2_ID, help="License 编辑框控件 ID")
    parser.add_argument("--button-id", type=int, default=DEFAULT_BUTTON_ID, help="验证按钮控件 ID")
    parser.add_argument("--observe-rounds", type=int, default=5, help="多维观察轮数（默认 5）")

    # discover 模式
    parser.add_argument("--discover", action="store_true", help="探测模式：枚举控件")

    # hook-inject 模式
    parser.add_argument("--hook-inject", action="store_true", help="Hook 注入参数模式")
    parser.add_argument("--hook-func-addr", type=lambda x: int(x, 0), help="验证函数地址（十六进制）")
    parser.add_argument("--hook-inputs", help="注入参数 JSON（如 [{\"arg\":0,\"type\":\"str\",\"value\":\"KCTF\"}]）")
    parser.add_argument("--hook-inputs-file", help="从文件读取注入参数 JSON")
    parser.add_argument("--hook-trigger-addr", type=lambda x: int(x, 0), help="触发验证的地址（十六进制，可选）")
    parser.add_argument("--hook-calling-convention", choices=["cdecl", "stdcall", "fastcall", "auto"], default="auto", help="调用约定")

    # hook-result 模式
    parser.add_argument("--hook-result", action="store_true", help="Hook 读取比较结果模式")
    parser.add_argument("--hook-compare-addr", action="append", type=lambda x: int(x, 0), help="比较地址（十六进制，可多次指定）")
    parser.add_argument("--hook-compare-type", choices=["memcmp", "strcmp", "custom", "auto"], default="auto", help="比较类型")

    args = parser.parse_args()

    # 参数校验
    mode = "standard"
    if args.discover:
        if args.hook_inject or args.hook_result:
            print(json.dumps({"success": False, "error": "--discover 不能与 --hook-inject/--hook-result 同时使用"}))
            sys.exit(2)
        if args.hook_func_addr or args.hook_compare_addr:
            print("[!] discover 模式不使用 hook 参数，已忽略", file=sys.stderr)
        mode = "discover"
    elif args.hook_inject or args.hook_result:
        mode = "hook"

    if mode == "standard":
        if not args.username or not args.license:
            parser.error("标准模式需要 --username 和 --license")

    if args.hook_inject:
        if not args.hook_func_addr:
            parser.error("--hook-inject 需要 --hook-func-addr")
        if not args.hook_inputs and not args.hook_inputs_file:
            parser.error("--hook-inject 需要 --hook-inputs 或 --hook-inputs-file")

    if args.hook_result:
        if not args.hook_compare_addr:
            parser.error("--hook-result 需要 --hook-compare-addr")
        # hook-result 独立模式（不含 hook-inject）需要 username/license
        if not args.hook_inject and (not args.username or not args.license):
            parser.error("hook-result 独立模式需要 --username 和 --license（用于 GUI 输入触发验证）")

    if args.hook_inject and args.hook_result:
        if not args.hook_trigger_addr and args.button_id == DEFAULT_BUTTON_ID:
            print("[!] 组合模式未指定 --hook-trigger-addr，将使用默认按钮 ID 尝试触发")

    # 执行
    if mode == "discover":
        result = run_discover(args.exe, args.timeout)
    elif mode == "standard":
        result = run_standard(
            args.exe, args.username, args.license,
            args.edit1_id, args.edit2_id, args.button_id,
            args.timeout, args.observe_rounds,
        )
    elif mode == "hook":
        # 解析 inputs
        inputs = []
        if args.hook_inputs:
            try:
                inputs = json.loads(args.hook_inputs)
            except json.JSONDecodeError as e:
                result = {"success": False, "error": f"--hook-inputs JSON 解析失败: {e}"}
                _output_result(result, args.output)
                sys.exit(2)
        elif args.hook_inputs_file:
            try:
                with open(args.hook_inputs_file, "r", encoding="utf-8") as f:
                    inputs = json.load(f)
            except Exception as e:
                result = {"success": False, "error": f"读取 --hook-inputs-file 失败: {e}"}
                _output_result(result, args.output)
                sys.exit(2)

        compare_addrs = args.hook_compare_addr if args.hook_compare_addr else None

        if args.hook_inject:
            result = run_hook_inject(
                args.exe, args.hook_func_addr, inputs,
                trigger_addr=args.hook_trigger_addr,
                calling_convention=args.hook_calling_convention,
                timeout=args.timeout,
                compare_addrs=compare_addrs,
                observe_rounds=args.observe_rounds,
                button_id=args.button_id,
            )
        else:
            # 仅 hook-result
            result = run_hook_result(
                args.exe, args.username, args.license,
                args.hook_compare_addr, args.hook_compare_type,
                args.edit1_id, args.edit2_id, args.button_id,
                args.timeout, args.observe_rounds,
            )
    else:
        result = {"success": False, "error": f"未知模式: {mode}"}

    _output_result(result, args.output)

    # 退出码
    if not result.get("success", False):
        sys.exit(2)
    elif result.get("verification_passed") is False:
        sys.exit(1)
    else:
        sys.exit(0)


def _output_result(result, output_path):
    output_json = json.dumps(result, indent=2, ensure_ascii=False, default=str)
    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"\n[+] 结果已写入: {output_path}")
    else:
        print(f"\n{output_json}")


if __name__ == "__main__":
    main()
