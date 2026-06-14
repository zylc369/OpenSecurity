import subprocess

from .log import log


from .errors import BwFridaError, ErrorCode


class AdbError(BwFridaError):
    def __init__(self, message: str, error_code: ErrorCode) -> None:
        super().__init__(message, error_code)


def restart_adb_server() -> None:
    """Kill and restart the local ADB server. Raises AdbError on failure."""
    log.info("正在重启 ADB Server...")
    kill_result = subprocess.run(
        ["adb", "kill-server"], capture_output=True, text=True, timeout=10
    )
    if kill_result.returncode != 0:
        msg = f"adb kill-server 失败: {kill_result.stderr.strip()}"
        log.error(msg)
        raise AdbError(msg, ErrorCode.ADB_CMD_FAILED)

    start_result = subprocess.run(
        ["adb", "start-server"], capture_output=True, text=True, timeout=15
    )
    if start_result.returncode != 0:
        msg = f"adb start-server 失败: {start_result.stderr.strip()}"
        log.error(msg)
        raise AdbError(msg, ErrorCode.ADB_CMD_FAILED)

    log.info("ADB Server 重启成功")


def get_devices() -> list[str]:
    """Run `adb devices`, parse output, return list of serial IDs.

    Excludes lines starting with '*', daemon messages, empty lines.
    """
    result = subprocess.run(
        ["adb", "devices"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.error("adb devices 命令失败: %s", result.stderr)
        return []

    devices = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("*") or line.startswith("List"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def select_device_interactive(devices: list[str]) -> str:
    """Arrow-key device selection using curses. Falls back to numbered input."""
    try:
        import curses

        def _curses_pick(stdscr: curses.window) -> int:
            curses.curs_set(0)
            selected = 0
            while True:
                stdscr.clear()
                stdscr.addstr(0, 0, "检测到多台 Android 设备 (上下键选择，回车确认):")
                for i, device in enumerate(devices):
                    prefix = " > " if i == selected else "   "
                    stdscr.addstr(i + 2, 0, f"{prefix}{device}")
                stdscr.refresh()

                key = stdscr.getch()
                if key == curses.KEY_UP and selected > 0:
                    selected -= 1
                elif key == curses.KEY_DOWN and selected < len(devices) - 1:
                    selected += 1
                elif key in (curses.KEY_ENTER, 10, 13):
                    return selected
                elif key == ord("q"):
                    sys.exit(0)

        idx = curses.wrapper(_curses_pick)
        return devices[idx]
    except (ImportError, Exception):
        pass

    print("检测到多台 Android 设备:")
    for i, device in enumerate(devices, start=1):
        print(f"  {i}) {device}")

    while True:
        try:
            choice = input("请选择设备 (输入序号): ")
            index = int(choice.strip())
            if 1 <= index <= len(devices):
                return devices[index - 1]
            print(f"无效的序号，请输入 1-{len(devices)} 之间的数字")
        except ValueError:
            print("请输入有效的数字")


def resolve_device(serial: str | None) -> str:
    """Determine which device to use.

    - No devices -> log error, raise SystemExit
    - Multiple devices and no serial -> interactive selection
    - Single device and no serial -> return that device's serial
    - Serial specified -> verify it's in device list, else raise SystemExit
    """
    devices = get_devices()

    if not devices:
        log.error("没有检测到连接的 Android 设备，请确保设备已连接并开启 USB 调试")
        sys.exit(1)

    if serial is None:
        if len(devices) == 1:
            log.info("检测到设备: %s", devices[0])
            return devices[0]
        else:
            log.info("检测到多台 Android 设备:")
            return select_device_interactive(devices)

    if serial not in devices:
        log.error(
            "指定的设备 ID '%s' 未找到。可用设备: %s",
            serial,
            ", ".join(devices),
        )
        sys.exit(1)

    log.info("使用指定设备: %s", serial)
    return serial


def _adb_base_args(serial: str) -> list[str]:
    """Return base adb args with serial."""
    return ["adb", "-s", serial]


def adb_shell(serial: str, cmd: str, **kwargs) -> subprocess.CompletedProcess:
    """Run: adb -s <serial> shell <cmd>

    Returns CompletedProcess. Does NOT raise on non-zero exit (caller checks).
    """
    args = _adb_base_args(serial) + ["shell", cmd]
    return subprocess.run(args, capture_output=True, text=True, **kwargs)


def check_path_exists(serial: str, path: str) -> bool:
    """Run: adb -s <serial> shell "test -e '<path>' && echo EXISTS"

    Returns True if EXISTS appears in stdout.
    """
    result = adb_shell(serial, f"test -e '{path}' && echo EXISTS")
    return "EXISTS" in result.stdout


def mkdir_p(serial: str, path: str) -> None:
    """Run: adb -s <serial> shell mkdir -p <path>

    Raises AdbError on failure.
    """
    result = adb_shell(serial, f"mkdir -p {path}")
    if result.returncode != 0:
        msg = f"创建目录失败 '{path}': {result.stderr}"
        log.error(msg)
        raise AdbError(msg)
    log.info("目录创建成功: %s", path)


def push_file(serial: str, local_path: str, remote_path: str) -> None:
    """Run: adb -s <serial> push <local_path> <remote_path>

    Raises AdbError on failure.
    """
    args = _adb_base_args(serial) + ["push", str(local_path), remote_path]
    log.info("正在推送文件到设备: %s -> %s", local_path, remote_path)
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        msg = f"推送文件失败: {result.stderr}"
        log.error(msg)
        raise AdbError(msg)
    log.info("文件推送成功")


def check_su_available(serial: str) -> bool:
    """Run: adb -s <serial> shell which su

    Returns True if `su` binary is found on the device.
    """
    result = adb_shell(serial, "which su")
    return result.returncode == 0 and bool(result.stdout.strip())


def run_frida_server_bg(serial: str, frida_path: str, port: int) -> subprocess.Popen:
    """Start frida-server in background via adb shell.

    Returns Popen object for lifecycle management.
    Checks if adb shell already has root privileges (uid 0).
    If already root, runs frida-server directly.
    If not root and `su` is available, prefixes the command with `su -c`.
    Command: adb -s <serial> shell <frida_path> -l 0.0.0.0:<port>
    """
    result = adb_shell(serial, "id -u")
    is_root = result.stdout.strip() == "0"

    if is_root:
        cmd = f"{frida_path} -l 0.0.0.0:{port}"
    else:
        use_su = check_su_available(serial)
        if use_su:
            cmd = f"su -c '{frida_path} -l 0.0.0.0:{port}'"
            log.info("设备支持 su，将以 root 权限启动 frida-server")
        else:
            cmd = f"{frida_path} -l 0.0.0.0:{port}"

    args = _adb_base_args(serial) + ["shell", cmd]
    log.info("正在启动 frida-server: %s -l 0.0.0.0:%d", frida_path, port)
    return subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def forward_port(serial: str, host_port: int, android_port: int) -> None:
    """Run: adb -s <serial> forward tcp:<host_port> tcp:<android_port>

    Raises AdbError on failure.
    """
    args = _adb_base_args(serial) + [
        "forward",
        f"tcp:{host_port}",
        f"tcp:{android_port}",
    ]
    log.info("正在设置端口转发: tcp:%d -> tcp:%d", host_port, android_port)
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        msg = f"端口转发失败: {result.stderr}"
        log.error(msg)
        raise AdbError(msg, ErrorCode.PORT_FORWARD_FAILED)
    log.info("端口转发设置成功")


def remove_forward(serial: str, host_port: int) -> None:
    """Run: adb -s <serial> forward --remove tcp:<host_port>

    Logs warning on failure (best-effort cleanup).
    """
    args = _adb_base_args(serial) + [
        "forward",
        "--remove",
        f"tcp:{host_port}",
    ]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        log.warning("移除端口转发失败 (可忽略): %s", result.stderr)
    else:
        log.info("端口转发已移除: tcp:%d", host_port)


def check_android_port_used(serial: str, port: int) -> bool:
    """Run: adb -s <serial> shell "netstat -an | grep :<port>"

    Returns True if port appears to be in LISTEN or ESTABLISHED state.
    """
    result = adb_shell(serial, f"netstat -an 2>/dev/null | grep ':{port} '")
    output = result.stdout.strip()
    if not output:
        return False
    # Check if any line shows the port in use (LISTEN or ESTABLISHED)
    for line in output.splitlines():
        # Match patterns like "tcp  0  0  :::6655  :::*  LISTEN" or similar
        if f":{port} " in line:
            return True
    return False
