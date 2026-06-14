"""summary: 跨平台环境自动检测脚本

description:
  检测逆向分析所需的工具链和依赖包，输出 JSON 格式结果。
  支持 Windows/Linux/macOS。
  Python 包安装在 Plugin 管理的虚拟环境（~/bw-security-analysis/.venv）中。
  C/C++ 编译器缺失时通知用户。
  结果缓存 24 小时。
  必需依赖缺失时返回 success: false，Agent 应停止并提示用户安装。

usage:
  $PYTHON_CMD detect_env.py [--output PATH] [--force] [--skip-install] [--agent AGENT_NAME]

level: intermediate

packages:
  必需: capstone, unicorn, gmpy2, frida, Pillow, pyautogui, pyperclip, playwright, markdownify, requests, beautifulsoup4, lxml
  playwright 需要额外安装浏览器二进制（playwright install chromium）
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time

CACHE_DIR = os.path.expanduser("~/bw-security-analysis")
CACHE_FILE = os.path.join(CACHE_DIR, "env_cache.json")
CACHE_TTL = 86400

REQUIRED_PACKAGES = {
    "capstone": {"required": True, "pip_name": "capstone"},
    "unicorn": {"required": True, "pip_name": "unicorn"},
    "gmpy2": {"required": True, "pip_name": "gmpy2"},
    "frida": {"required": True, "pip_name": "frida"},
    "PIL": {"required": True, "pip_name": "Pillow"},
    "pyautogui": {"required": True, "pip_name": "pyautogui"},
    "pyperclip": {"required": True, "pip_name": "pyperclip"},
    "playwright": {"required": True, "pip_name": "playwright", "post_install": True, "version_via": "importlib:playwright"},
    "markdownify": {"required": True, "pip_name": "markdownify", "version_via": "importlib:markdownify"},
    # Web 安全分析包
    "requests":      {"required": True,  "pip_name": "requests"},
    "bs4":           {"required": True,  "pip_name": "beautifulsoup4"},
    "lxml":          {"required": True,  "pip_name": "lxml"},
}

def _load_cache(force=False):
    if force:
        return None
    if not os.path.isfile(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
        if time.time() - cache.get("timestamp", 0) < CACHE_TTL:
            return cache.get("data")
    except (json.JSONDecodeError, KeyError):
        pass
    return None


def _save_cache(data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"timestamp": time.time(), "data": data}, f, indent=2, ensure_ascii=False)


def _detect_compiler():
    system = platform.system()
    result = {"available": False, "type": None, "path": None, "vcvarsall": None}

    if system == "Windows":
        result = _detect_msvc()
        if not result["available"]:
            result = _detect_gcc_windows()
    elif system == "Darwin":
        result = _detect_clang_macos()
        if not result["available"]:
            result = _detect_gcc_unix()
    else:
        result = _detect_gcc_unix()

    return result


def _safe_listdir(path):
    try:
        return os.listdir(path)
    except OSError:
        return []


def _detect_msvc():
    result = {"available": False, "type": None, "path": None, "vcvarsall": None}

    vs_where = shutil.which("vswhere.exe")
    if vs_where:
        try:
            out = subprocess.run(
                [vs_where, "-latest", "-property", "installationPath"],
                capture_output=True, text=True, timeout=10,
            )
            if out.returncode == 0 and out.stdout.strip():
                vs_path = out.stdout.strip().split("\n")[0].strip()
                vcvarsall = os.path.join(vs_path, "VC", "Auxiliary", "Build", "vcvarsall.bat")
                if os.path.isfile(vcvarsall):
                    cl_path = _find_cl_in_vs(vs_path)
                    result = {
                        "available": True,
                        "type": "msvc",
                        "path": cl_path,
                        "vcvarsall": vcvarsall,
                    }
                    return result
        except (subprocess.TimeoutExpired, OSError):
            pass

    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    vs_dir = os.path.join(program_files_x86, "Microsoft Visual Studio")
    if os.path.isdir(vs_dir):
        for version_dir in _safe_listdir(vs_dir):
            version_path = os.path.join(vs_dir, version_dir)
            if not os.path.isdir(version_path):
                continue
            for edition_dir in _safe_listdir(version_path):
                edition_path = os.path.join(version_path, edition_dir)
                vcvarsall = os.path.join(edition_path, "VC", "Auxiliary", "Build", "vcvarsall.bat")
                if os.path.isfile(vcvarsall):
                    cl_path = _find_cl_recursive(
                        os.path.join(edition_path, "VC", "Tools", "MSVC"), "cl.exe"
                    )
                    if not cl_path:
                        cl_path = _find_cl_recursive(edition_path, "cl.exe")
                    return {
                        "available": True,
                        "type": "msvc",
                        "path": cl_path,
                        "vcvarsall": vcvarsall,
                    }

    return result


def _find_cl_in_vs(vs_path):
    msvc_dir = os.path.join(vs_path, "VC", "Tools", "MSVC")
    if not os.path.isdir(msvc_dir):
        return None
    return _find_cl_recursive(msvc_dir, "cl.exe")


def _find_cl_recursive(base_dir, filename):
    if not os.path.isdir(base_dir):
        return None
    for root, dirs, files in os.walk(base_dir):
        for f in files:
            if f.lower() == filename.lower():
                return os.path.join(root, f)
    return None


def _detect_gcc_windows():
    for name in ["gcc.exe", "g++.exe", "clang.exe"]:
        path = shutil.which(name)
        if path:
            return {"available": True, "type": "gcc", "path": path, "vcvarsall": None}
    return {"available": False, "type": None, "path": None, "vcvarsall": None}


def _detect_clang_macos():
    path = shutil.which("clang")
    if path:
        return {"available": True, "type": "clang", "path": path, "vcvarsall": None}
    return {"available": False, "type": None, "path": None, "vcvarsall": None}


def _detect_gcc_unix():
    for name in ["gcc", "g++", "cc"]:
        path = shutil.which(name)
        if path:
            return {"available": True, "type": "gcc", "path": path, "vcvarsall": None}
    return {"available": False, "type": None, "path": None, "vcvarsall": None}


def _detect_package(name, version_via=None):
    """检测 Python 包是否已安装。
    version_via: None 表示用 name.__version__；"importlib:PIP_NAME" 表示用 importlib.metadata。
    使用 sys.executable（由 Plugin 保证为 venv Python）执行检测。"""
    try:
        if version_via and version_via.startswith("importlib:"):
            pip_name = version_via.split(":", 1)[1]
            result = subprocess.run(
                [sys.executable, "-c", f"import {name}; import importlib.metadata; print(importlib.metadata.version('{pip_name}'))"],
                capture_output=True, text=True, timeout=10,
            )
        else:
            result = subprocess.run(
                [sys.executable, "-c", f"import {name}; print(__import__('{name}').__version__)"],
                capture_output=True, text=True, timeout=10,
            )
        if result.returncode == 0:
            return {"available": True, "version": result.stdout.strip() or "unknown"}
    except (subprocess.TimeoutExpired, OSError):
        pass
    return {"available": False, "version": None}


def _install_package(pip_name, timeout=60):
    pip_cmd = [sys.executable, "-m", "pip", "install", pip_name]
    try:
        result = subprocess.run(pip_cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return True
        print(f"[!] pip install {pip_name} 失败: {result.stderr.strip()}", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print(f"[!] pip install {pip_name} 超时 ({timeout}s)", file=sys.stderr)
    except OSError as e:
        print(f"[!] pip install {pip_name} 异常: {e}", file=sys.stderr)
    return False


def _detect_playwright_browser():
    """检测 Playwright Chromium 浏览器是否已安装。"""
    try:
        result = subprocess.run(
            [sys.executable, "-c",
             "from playwright.sync_api import sync_playwright; "
             "import os; "
             "p = sync_playwright().start(); "
             "print(os.path.isfile(p.chromium.executable_path)); "
             "p.stop()"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and "True" in result.stdout:
            return True
    except (subprocess.TimeoutExpired, OSError):
        pass
    return False


def _post_install_playwright(timeout=300):
    """安装 Playwright Chromium 浏览器二进制（约 150-200MB）。"""
    print("[*] 正在安装 Playwright Chromium 浏览器（首次安装约 150-200MB）...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode == 0:
            print("[+] Playwright Chromium 安装成功")
            return True
        print(f"[!] Playwright 浏览器安装失败: {result.stderr.strip()}", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print(f"[!] Playwright 浏览器安装超时 ({timeout}s)", file=sys.stderr)
    except OSError as e:
        print(f"[!] Playwright 浏览器安装异常: {e}", file=sys.stderr)
    return False


def _detect_ida_pro():
    config_file = os.path.join(CACHE_DIR, "config.json")
    if not os.path.isfile(config_file):
        return {"available": False, "path": None}
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)
        ida_path = config.get("ida_path", "")
        idat_name = "idat.exe" if platform.system() == "Windows" else "idat"
        if ida_path and os.path.isfile(os.path.join(ida_path, idat_name)):
            return {"available": True, "path": ida_path}
    except (json.JSONDecodeError, OSError):
        pass
    return {"available": False, "path": None}


def _resolve_tool_path(path):
    """解析工具路径：绝对路径检查文件存在性，裸名通过 which 查找。
    跨平台：Windows 上 shutil.which 自动处理 PATHEXT。"""
    if os.path.isabs(path):
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return (path, True)
        if os.name == "nt":
            for ext in os.environ.get("PATHEXT", ".exe;.cmd;.bat").split(";"):
                candidate = path + ext
                if os.path.isfile(candidate):
                    return (candidate, True)
        return (path, False)
    resolved = shutil.which(path)
    if resolved:
        return (resolved, True)
    return (path, False)


def _get_tool_version(resolved_path, version_cmd):
    """执行 version_cmd 获取版本字符串。version_cmd 为空列表时返回 None。"""
    if not version_cmd:
        return None
    try:
        r = subprocess.run([resolved_path] + version_cmd, capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return (r.stdout.strip() or r.stderr.strip()).split("\n")[0] or None
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def _detect_tools(config, agent=None, errors=None):
    """从 config.json 读取 tools 配置，逐个检测可用性。"""
    if errors is None:
        errors = []
    tools = config.get("tools", {})
    result = {}
    for name, cfg in tools.items():
        if agent and cfg.get("agents") and agent not in cfg.get("agents", []):
            continue
        path = cfg.get("path", "")
        version_cmd = cfg.get("version_cmd", [])
        resolved, found = _resolve_tool_path(path)
        if found:
            version = _get_tool_version(resolved, version_cmd)
            result[name] = {"available": True, "version": version}
        else:
            result[name] = {"available": False, "version": None}
            if cfg.get("required", False):
                errors.append(f"必需工具 {name} 未找到: {path}")
    return result


def run_detection(skip_install=False, agent=None):
    errors = []

    print(f"[+] Python: {sys.executable}")

    print("[*] 正在检测 C/C++ 编译器...")
    compiler = _detect_compiler()
    if compiler["available"]:
        print(f"[+] 编译器: {compiler['type']} — {compiler['path']}")
    else:
        system = platform.system()
        if system == "Windows":
            hint = "请安装 VS Build Tools: https://visualstudio.microsoft.com/visual-cpp-build-tools/"
        elif system == "Darwin":
            hint = "请运行: xcode-select --install"
        else:
            hint = "请运行: sudo apt install build-essential (Debian/Ubuntu) 或 sudo yum groupinstall 'Development Tools' (RHEL/CentOS)"
        msg = f"C/C++ 编译器未找到。{hint}"
        errors.append(msg)
        print(f"[!] {msg}")

    print("[*] 正在检测 Python 架构...")
    python_arch = platform.architecture()[0]
    print(f"[+] Python 架构: {python_arch}")

    packages = {}
    for name, info in REQUIRED_PACKAGES.items():
        print(f"[*] 正在检测 {name}...")
        pkg_info = _detect_package(name, version_via=info.get("version_via"))
        if not pkg_info["available"] and not skip_install:
            print(f"[*] {name} 未安装，正在自动安装...")
            if _install_package(info["pip_name"]):
                pkg_info = _detect_package(name, version_via=info.get("version_via"))
                if pkg_info["available"]:
                    # 处理 post_install（如 playwright 需要额外安装浏览器）
                    if info.get("post_install") and name == "playwright":
                        if not _detect_playwright_browser():
                            if not _post_install_playwright():
                                errors.append(
                                    "Playwright 浏览器安装失败。请手动运行: "
                                    f"{sys.executable} -m playwright install chromium"
                                )
                    print(f"[+] {name} 安装成功: {pkg_info['version']}")
                else:
                    print(f"[!] {name} 安装后仍无法导入")
            else:
                manual_cmd = f"{sys.executable} -m pip install {info['pip_name']}"
                if info["required"]:
                    errors.append(f"{name} 安装失败，请手动运行: {manual_cmd}")
                else:
                    print(f"[!] {name} 安装失败（可选包，不影响核心流程）。手动安装: {manual_cmd}")
        elif pkg_info["available"]:
            # 已安装的包也需要检查 post_install
            if info.get("post_install") and name == "playwright":
                if not _detect_playwright_browser():
                    if not skip_install:
                        if not _post_install_playwright():
                            errors.append(
                                "Playwright 浏览器安装失败。请手动运行: "
                                f"{sys.executable} -m playwright install chromium"
                            )
                    else:
                        print("[!] Playwright 浏览器未安装（--skip-install）")
                        errors.append(
                            "Playwright 浏览器未安装。请运行: "
                            f"{sys.executable} -m playwright install chromium"
                        )
            print(f"[+] {name}: {pkg_info['version']}")
        else:
            if info["required"]:
                manual_cmd = f"{sys.executable} -m pip install {info['pip_name']}"
                errors.append(f"{name} 未安装。请运行: {manual_cmd}")
            print(f"[!] {name} 未安装（--skip-install）")
        packages[name] = pkg_info

    print("[*] 正在检测 IDA Pro...")
    ida_pro = _detect_ida_pro()
    if ida_pro["available"]:
        print(f"[+] IDA Pro: {ida_pro['path']}")
    else:
        print("[!] IDA Pro 未配置")

    print("[*] 正在检测外部工具...")
    config_file = os.path.join(CACHE_DIR, "config.json")
    tools = {}
    if os.path.isfile(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
            tools = _detect_tools(config, agent=agent, errors=errors)
            for name, info in tools.items():
                if info["available"]:
                    ver = info["version"] or "未知版本"
                    print(f"[+] {name}: {ver}")
                else:
                    print(f"[!] {name}: 未找到")
        except (json.JSONDecodeError, OSError) as e:
            print(f"[!] 读取工具配置失败: {e}")
    else:
        print("[*] config.json 不存在，跳过外部工具检测")

    data = {
        "compiler": compiler,
        "python_arch": python_arch,
        "packages": packages,
        "ida_pro": ida_pro,
        "tools": tools,
    }

    success = len(errors) == 0
    result = {"success": success, "data": data, "errors": errors}

    _save_cache(data)

    return result


def main():
    parser = argparse.ArgumentParser(description="逆向分析环境检测")
    parser.add_argument("--output", "-o", help="输出 JSON 文件路径")
    parser.add_argument("--force", "-f", action="store_true", help="强制重新检测（忽略缓存）")
    parser.add_argument("--skip-install", action="store_true", help="跳过自动安装缺失的包")
    parser.add_argument("--agent", help="仅检测指定 Agent 需要的工具（如 binary-analysis, mobile-analysis）",
                        default=os.environ.get("AGENT_NAME"))
    args = parser.parse_args()

    agent = args.agent

    cached = _load_cache(force=args.force)
    if cached and not args.force:
        if cached.get("packages"):
            result = {"success": True, "data": cached, "errors": []}
            print("[*] 使用缓存的环境检测结果（使用 --force 强制重新检测）")
        else:
            print("[!] 缓存数据不完整，重新检测...")
            cached = None

    if not cached or args.force:
        result = run_detection(skip_install=args.skip_install, agent=agent)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"\n[+] 结果已写入: {args.output}")
    else:
        print(f"\n{output_json}")

    if not result["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
