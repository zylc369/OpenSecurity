"""summary: 跨平台环境自动检测脚本

description:
  检测逆向分析所需的工具链和依赖包，输出 JSON 格式结果。
  支持 Windows/Linux/macOS。
  Python 包安装在 Plugin 管理的虚拟环境（~/bw-security-analysis/.venv）中。
  C/C++ 编译器缺失时通知用户。
  --check-preinstall 模式不自动装包、不读缓存（实时检测），Plugin chat.message 用此模式。
  默认模式读 24h 缓存；--force 强制重新检测。
  必需依赖缺失时返回 success: false，Plugin 终止并提示用户安装。

usage:
  $PYTHON_CMD detect_env.py [--output PATH] [--force] [--check-preinstall AGENT]
  AGENT=all 时检测所有依赖（Coordinator 用）

level: intermediate

packages:
  必需: capstone, unicorn, gmpy2, frida, angr, triton, z3-solver, Pillow, pyautogui, pyperclip, playwright, markdownify, requests, beautifulsoup4, lxml
  playwright 需要额外安装浏览器二进制（playwright install chromium）
  每个 Python 包在 PYTHON_PACKAGES 里标记 agents（按 agent 过滤检测）
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Literal

CACHE_DIR = os.path.expanduser("~/bw-security-analysis")
CACHE_FILE = os.path.join(CACHE_DIR, "env_cache.json")
CACHE_TTL = 86400


@dataclass
class Dependency:
    """统一的依赖元数据结构，驱动 Python 包和外部工具的检测分发。

    kind="python": pip/conda 安装的包，用 import/find_spec 检测
    kind="tool":   外部可执行工具，用 env_var(IDA Pro) 或 PATH which(apktool 等) 定位
    """
    name: str                              # python: import名; tool: 标识名(ida_pro/apktool)
    kind: Literal["python", "tool"]
    required: bool = True
    preinstall: bool = False               # True=用户预装只检测不自动装; False=自动安装
    agents: list[str] = field(default_factory=list)   # 空=所有 agent
    description: str = ""
    install_hint: str = ""                 # 缺失时展示给用户的具体指引
    # --- python 专属 ---
    pip_name: str | None = None
    conda_name: str | None = None
    installer: Literal["pip", "conda"] = "pip"
    post_install: bool = False
    version_via: str | None = None         # None | "importlib:PKG"
    # --- tool 专属 ---
    version_cmd: list[str] = field(default_factory=list)
    env_var: str = ""                      # 路径来源(空=靠 PATH which; IDA=IDA_PRO_HOME)
    executable: str = ""                   # env_var 模式下拼接的可执行名(如 idat); 空=靠 PATH which


def _get_opencode_root() -> str:
    """获取 OPENCODE_ROOT。优先环境变量（Plugin 启动时写入 process.env.OPENCODE_ROOT），
    fallback 从脚本位置推导（脚本位于 OPENCODE_ROOT/binary-analysis/scripts/detect_env.py，
    往上三级即 OPENCODE_ROOT）。两条调用路径都覆盖：agent bash 跑（环境变量在）+
    Plugin checkPreinstall 直接 spawn（环境变量由 process.env 传播）。"""
    env = os.environ.get("OPENCODE_ROOT")
    if env and os.path.isdir(env):
        return env
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


AI_ENV_FILE = os.path.join(_get_opencode_root(), ".ai_env")


def _warn(msg, exc=None, detail=None):
    """统一的 stderr 诊断日志。
    所有失败/异常诊断走此函数，确保：格式一致 + 不污染 stdout 的 JSON 输出
    （--check-preinstall 模式 Plugin 用 JSON.parse(stdout)，诊断信息必须走 stderr）。
    msg: 操作描述；exc: 异常对象（附带类型名）；detail: 附加信息（如子进程 stderr 片段）。"""
    parts = [f"[!] {msg}"]
    if exc is not None:
        parts.append(f"{type(exc).__name__}: {exc}")
    if detail:
        parts.append(str(detail))
    print(": ".join(parts), file=sys.stderr)


def _log(msg):
    """正常进度日志，打到 stderr。
    stdout 独占给 JSON 输出（默认模式末尾 print(output_json)、--check-preinstall 的 print(json.dumps)），
    供 Plugin JSON.parse(stdout)。所有 [*]/[+]/[!] 进度必须走 _log 或 _warn，不能直接 print 到 stdout。"""
    print(msg, file=sys.stderr)


_STDERR_TAIL = 600  # 子进程 stderr 诊断截断长度（防日志过长）


def _stderr_tail(result):
    """提取 subprocess 结果的 stderr 前 _STDERR_TAIL 字符（去首尾空白）。
    用于 _warn 的 detail 参数，统一截断逻辑。"""
    return (result.stderr or "").strip()[:_STDERR_TAIL]


_AI_ENV_TEMPLATE = """\
# bw-security-analysis 环境变量配置
# 按需填写，填完保存即可（detect_env 下次自动读取）

# IDA Pro 安装目录（你安装 IDA Pro 的位置，该目录下需有 idat 可执行文件）
# macOS: /Applications/IDA Professional 9.1.app/Contents/MacOS
# Linux: /opt/ida-9.0
# Windows: C:\\Program Files\\IDA Pro 9.0
IDA_PRO_HOME=
"""


def _ensure_ai_env_template() -> None:
    """检测到 .ai_env 不存在时自动创建带注释模板（存在则跳过，不重写用户内容）。"""
    if os.path.isfile(AI_ENV_FILE):
        return
    try:
        os.makedirs(os.path.dirname(AI_ENV_FILE), exist_ok=True)
        with open(AI_ENV_FILE, "w", encoding="utf-8") as f:
            f.write(_AI_ENV_TEMPLATE)
        _log(f"[+] 已创建环境变量配置模板: {AI_ENV_FILE}（按需填写后保存）")
    except OSError as e:
        _warn("创建 .ai_env 模板失败", exc=e)


def _load_ai_env() -> None:
    """读取 .ai_env（KEY=VALUE），用 setdefault 合并进 os.environ。
    系统 env 优先级高于 .ai_env（setdefault 不覆盖已存在的 key）。
    忽略空行和 # 注释行。"""
    if not os.path.isfile(AI_ENV_FILE):
        return
    try:
        with open(AI_ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key:
                    os.environ.setdefault(key, value)
    except OSError as e:
        _warn("读取 .ai_env 失败（环境变量未加载，IDA_PRO_HOME 等配置不生效）", exc=e)

PYTHON_PACKAGES: list[Dependency] = [
    # binary-analysis 逆向分析包
    Dependency(name="angr", kind="python", pip_name="angr", preinstall=True,
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis"],
               description="二进制分析/符号执行框架，用于程序状态探索、漏洞发现、自动利用生成"),
    Dependency(name="triton", kind="python", pip_name="triton", preinstall=True,
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis"],
               description="动态二进制分析框架，用于符号执行、污点分析、约束求解"),
    Dependency(name="z3", kind="python", pip_name="z3-solver", preinstall=True,
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis", "ai-security-analysis"],
               description="Microsoft Z3 定理证明器，用于约束求解、符号执行中的路径条件判定"),
    Dependency(name="capstone", kind="python", pip_name="capstone", preinstall=True,
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis"],
               description="轻量级多架构反汇编框架，支持 x86/ARM/MIPS/PowerPC 等主流指令集"),
    Dependency(name="unicorn", kind="python", pip_name="unicorn", preinstall=True,
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis", "ai-security-analysis"],
               description="轻量级多架构 CPU 模拟器（基于 QEMU），用于指令级模拟执行与 Shellcode 测试"),
    Dependency(name="gmpy2", kind="python", pip_name="gmpy2", preinstall=True,
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis", "ai-security-analysis"],
               description="高精度算术库（GMP C 库的 Python 封装），用于大整数运算、模幂/模逆、素性检测"),
    Dependency(name="frida", kind="python", pip_name="frida", preinstall=True,
               agents=["binary-analysis", "mobile-analysis"],
               description="动态插桩工具包，用于运行时 Hook、函数追踪、内存读写、进程注入"),
    Dependency(name="PIL", kind="python", pip_name="Pillow", preinstall=True,
               agents=["binary-analysis"],
               description="Python 图像处理库（pyautogui 的传递依赖），用于 GUI 截图保存与尺寸获取"),
    Dependency(name="pyautogui", kind="python", pip_name="pyautogui", preinstall=True,
               agents=["binary-analysis"],
               description="GUI 自动化控制库，用于模拟鼠标/键盘操作、窗口定位与屏幕交互"),
    Dependency(name="pyperclip", kind="python", pip_name="pyperclip", preinstall=True,
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis", "ai-security-analysis"],
               description="跨平台剪贴板操作库，用于自动化流程中的文本/数据复制粘贴"),
    # web 安全分析包
    Dependency(name="playwright", kind="python", pip_name="playwright", preinstall=True,
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis", "ai-security-analysis"],
               post_install=True, version_via="importlib:playwright",
               description="无头浏览器自动化框架，用于网页渲染、SPA 页面抓取、浏览器交互测试"),
    Dependency(name="markdownify", kind="python", pip_name="markdownify", preinstall=True,
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis", "ai-security-analysis"],
               version_via="importlib:markdownify",
               description="HTML 转 Markdown 转换工具，用于将网页内容转换为结构化纯文本"),
    Dependency(name="requests", kind="python", pip_name="requests", preinstall=True,
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis", "ai-security-analysis"],
               description="HTTP 客户端库，用于 Web 请求发送、API 交互、漏洞探测与数据抓取"),
    Dependency(name="bs4", kind="python", pip_name="beautifulsoup4", preinstall=True,
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis", "ai-security-analysis"],
               description="HTML/XML 解析库(BeautifulSoup4)，用于网页内容提取、DOM 遍历与结构化解析"),
    Dependency(name="lxml", kind="python", pip_name="lxml", preinstall=True,
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis", "ai-security-analysis"],
               description="高性能 XML/HTML 解析器(C 扩展)，BeautifulSoup 的底层解析引擎"),
    # crypto 专用依赖
    Dependency(name="sympy", kind="python", pip_name="sympy", preinstall=True,
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis", "ai-security-analysis"],
               description="符号数学库，用于代数方程求解、中国剩余定理(CRT)、数论构造"),
    # 预装依赖（preinstall）：体积大、不自动装，由 --check-preinstall 按需检查；仅特定 agent 需要
    Dependency(name="sage", kind="python", required=False, pip_name="sagemath-standard",
               conda_name="sage", agents=["crypto-analysis"], preinstall=True, installer="conda",
               description="数学软件系统，用于密码学攻击中的代数运算、格基归约、椭圆曲线计算"),
]


EXTERNAL_TOOLS: list[Dependency] = [
    Dependency(
        name="ida_pro", kind="tool", preinstall=True,
        agents=["binary-analysis", "mobile-analysis", "crypto-analysis", "web-analysis"], required=True,
        description="反汇编/反编译平台（付费）",
        env_var="IDA_PRO_HOME",
        executable="idat",
        install_hint=(
            "IDA Pro 未检测到。解决方式：\n"
            "  1. 在 .ai_env 设置 IDA_PRO_HOME（IDA Pro 安装目录）：\n"
            "     IDA_PRO_HOME=/Applications/IDA Professional 9.1.app/Contents/MacOS\n"
            "  2. 或设置系统环境变量 IDA_PRO_HOME（shell export，优先级高于 .ai_env）"
        ),
    ),
    Dependency(
        name="apktool", kind="tool", preinstall=True,
        agents=["mobile-analysis"], required=True,
        version_cmd=["--version"],
        description="APK 解包+反汇编工具",
        install_hint="apktool 未找到。安装: brew install apktool (macOS) / 参考 https://ibotpeaches.github.io/Apktool/install/",
    ),
    Dependency(
        name="jadx", kind="tool", preinstall=True,
        agents=["mobile-analysis"], required=True,
        version_cmd=["--version"],
        description="DEX→Java 反编译器",
        install_hint="jadx 未找到。安装: brew install jadx (macOS) / 参考 https://github.com/skylot/jadx",
    ),
    Dependency(
        name="adb", kind="tool", preinstall=True,
        agents=["mobile-analysis"], required=True,
        version_cmd=["version"],
        description="Android Debug Bridge",
        install_hint="adb 未找到。安装: brew install --cask android-platform-tools (macOS) / 参考 https://developer.android.com/tools/adb",
    ),
    Dependency(
        name="otool", kind="tool", preinstall=True,
        agents=["mobile-analysis"], required=False,
        description="Mach-O 文件查看器（macOS 自带）",
        install_hint="otool 未找到（macOS 自带，非 macOS 无需配置）",
    ),
    Dependency(
        name="ldid", kind="tool", preinstall=True,
        agents=["mobile-analysis"], required=False,
        description="iOS 伪签名工具",
        install_hint="ldid 未找到。安装: brew install ldid (macOS)",
    ),
    Dependency(
        name="GoReSym", kind="tool", preinstall=True,
        agents=["binary-analysis", "crypto-analysis"], required=False,
        description="Go 符号恢复工具",
        install_hint="GoReSym 未找到。参考 https://github.com/mandiant/GoReSym",
    ),
]

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
    except (json.JSONDecodeError, KeyError) as e:
        _warn("env_cache.json 解析失败或字段缺失，将重新检测", exc=e)
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
        except (subprocess.TimeoutExpired, OSError) as e:
            _warn("vswhere 执行失败，改用目录扫描 fallback", exc=e)

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
    使用 sys.executable（由 Plugin 保证为 conda env Python）执行检测。"""
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
        # returncode≠0：记录 stderr 帮助区分"未安装"和"包损坏"
        _warn(f"检测 {name} 失败（退出码 {result.returncode}）", detail=_stderr_tail(result))
    except subprocess.TimeoutExpired as e:
        _warn(f"检测 {name} 超时（import 可能较慢或卡死）", exc=e)
    except OSError as e:
        _warn(f"检测 {name} 异常", exc=e)
    return {"available": False, "version": None}


def _install_package(pip_name, timeout=60):
    pip_cmd = [sys.executable, "-m", "pip", "install", pip_name]
    try:
        result = subprocess.run(pip_cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return True
        _warn(f"pip install {pip_name} 失败（退出码 {result.returncode}）", detail=_stderr_tail(result))
    except subprocess.TimeoutExpired as e:
        _warn(f"pip install {pip_name} 超时（{timeout}s）", exc=e)
    except OSError as e:
        _warn(f"pip install {pip_name} 异常", exc=e)
    return False


def _build_install_cmd(dep: Dependency):
    """根据 dep 的 installer 字段生成安装命令（配置驱动，不硬编码包名）。
    用于 _check_preinstall 生成给用户看的 install_hint。
    sys.prefix 在 conda env 里指向 env 根目录（跨平台）。"""
    if dep.installer == "conda":
        name = dep.conda_name or dep.pip_name
        conda_cmd = os.environ.get("CONDA_CMD", "conda")
        return f"{conda_cmd} install -p '{sys.prefix}' -y {name}"
    return f"{sys.executable} -m pip install {dep.pip_name}"


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
        if result.returncode != 0:
            _warn("Playwright 浏览器检测失败（退出码非 0）", detail=_stderr_tail(result))
    except subprocess.TimeoutExpired as e:
        _warn("Playwright 浏览器检测超时（启动可能较慢）", exc=e)
    except OSError as e:
        _warn("Playwright 浏览器检测异常", exc=e)
    return False


def _post_install_playwright(timeout=300):
    """安装 Playwright Chromium 浏览器二进制（约 150-200MB）。"""
    _log("[*] 正在安装 Playwright Chromium 浏览器（首次安装约 150-200MB）...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode == 0:
            _log("[+] Playwright Chromium 安装成功")
            return True
        _warn(f"Playwright 浏览器安装失败（退出码 {result.returncode}）", detail=_stderr_tail(result))
    except subprocess.TimeoutExpired as e:
        _warn(f"Playwright 浏览器安装超时（{timeout}s）", exc=e)
    except OSError as e:
        _warn("Playwright 浏览器安装异常", exc=e)
    return False


def _check_playwright_post_install(skip_install, errors):
    """检测并按需安装 Playwright Chromium 浏览器（post_install 步骤）。
    包已安装但浏览器二进制可能缺失（需额外 playwright install chromium）。
    skip_install=True 时仅检测不装，缺失记 error 提示用户手动安装。"""
    if _detect_playwright_browser():
        return
    manual_cmd = f"{sys.executable} -m playwright install chromium"
    if skip_install:
        _log("[!] Playwright 浏览器未安装（--skip-install）")
        errors.append(f"Playwright 浏览器未安装。请运行: {manual_cmd}")
    else:
        if not _post_install_playwright():
            errors.append(f"Playwright 浏览器安装失败。请手动运行: {manual_cmd}")


def _resolve_tool(dep: Dependency) -> tuple[str, bool]:
    """统一的工具路径解析，由 dep 字段驱动。
    有 env_var: 读环境变量（系统 env > .ai_env，_load_ai_env 已 setdefault 合并）指向的目录，
                拼接 dep.executable（如 ida_pro 拼 idat）
    无 env_var: 靠 PATH which（apktool/jadx 等）
    返回 (resolved_path, found)。"""
    if dep.env_var:
        home = os.environ.get(dep.env_var, "")
        if home:
            exe = dep.executable  # env_var 模式由 dep.executable 提供可执行名（如 ida_pro="idat"）
            if os.name == "nt" and exe and not exe.endswith(".exe"):
                exe += ".exe"
            cand = os.path.join(home, exe)
            if exe and os.path.isfile(cand):
                return (cand, True)
        return ("", False)
    resolved = shutil.which(dep.name)
    if resolved:
        return (resolved, True)
    return (dep.name, False)


def _detect_ida_pro():
    """检测 IDA Pro。路径来自 IDA_PRO_HOME 环境变量（系统 env > .ai_env）。
    返回 idat_path（供 Plugin 拼 $IDAT）。"""
    ida_dep = next((d for d in EXTERNAL_TOOLS if d.name == "ida_pro"), None)
    if not ida_dep:
        return {"available": False, "path": None, "idat_path": None}
    resolved, found = _resolve_tool(ida_dep)
    if found:
        return {"available": True, "path": os.path.dirname(resolved), "idat_path": resolved}
    return {"available": False, "path": None, "idat_path": None}


def _get_tool_version(resolved_path, version_cmd):
    """执行 version_cmd 获取版本字符串。version_cmd 为空列表时返回 None。"""
    if not version_cmd:
        return None
    try:
        r = subprocess.run([resolved_path] + version_cmd, capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return (r.stdout.strip() or r.stderr.strip()).split("\n")[0] or None
    except subprocess.TimeoutExpired as e:
        _warn(f"{resolved_path} 版本检测超时", exc=e)
    except OSError as e:
        _warn(f"{resolved_path} 版本检测异常", exc=e)
    return None


def _detect_tools():
    """遍历 EXTERNAL_TOOLS registry 全量检测可用性（写入 env_cache 供 Plugin 读取）。
    IDA Pro 由 _detect_ida_pro 单独处理，此处跳过。
    env_cache 是全局共享的，故全量检测（不按 agent 过滤）；必需性检查由 --check-preinstall 按 agent 负责。"""
    result = {}
    for dep in EXTERNAL_TOOLS:
        if dep.name == "ida_pro":
            continue  # IDA Pro 由 _detect_ida_pro 单独处理
        resolved, found = _resolve_tool(dep)
        if found:
            version = _get_tool_version(resolved, dep.version_cmd)
            result[dep.name] = {"available": True, "version": version,
                                "description": dep.description, "resolved_path": resolved}
        else:
            result[dep.name] = {"available": False, "version": None,
                                "description": dep.description, "resolved_path": None}
    return result


def _build_install_hint(dep):
    """生成缺失依赖的安装提示。
    优先用 dep.install_hint（EXTERNAL_TOOLS 自带），否则动态生成。"""
    if dep.install_hint:
        return dep.install_hint
    install_cmd = _build_install_cmd(dep)
    agents_str = "/".join(dep.agents)
    pkg_name = dep.conda_name or dep.pip_name
    preinstall_desc_part1 = f"预装依赖 {dep.name}（{dep.installer}: {pkg_name}）未安装"
    desc = f"{agents_str} 需要的{preinstall_desc_part1}" if agents_str else preinstall_desc_part1
    return f"{desc}\n安装命令：{install_cmd}"


def _check_preinstall(agent):
    """检查指定 Agent 的所有依赖是否就绪 + 生成 env_cache。

    agent="all" 时检测所有依赖（errors 不做 agent 过滤），用于 Coordinator。

    检测范围：Python 包（find_spec + 版本）+ 编译器 + IDA Pro + 外部工具。
    不自动装、不读缓存（实时检测，每次反映最新状态）。
    data 全量写入 env_cache.json（供 Plugin buildEnvSection/shell.env 读取）；
    errors 按当前 agent 过滤（只报该 agent 缺的包）。"""
    import importlib.util
    import importlib.metadata
    errors = []
    packages = {}
    tools = {}

    def _agent_matches(dep):
        """all = 不过滤；否则 dep.agents 为空或包含当前 agent 即匹配"""
        if agent == "all":
            return True
        return not dep.agents or agent in dep.agents

    # --- Python 包检测（全量检测写 cache，errors 按 agent 过滤）---
    for dep in PYTHON_PACKAGES:
        if not dep.preinstall:
            continue
        try:
            spec = importlib.util.find_spec(dep.name)
        except Exception as e:
            _warn(f"_check_preinstall: find_spec({dep.name}) 异常", exc=e)
            raise
        if spec is None:
            if dep.required and _agent_matches(dep):
                errors.append({"package": dep.name, "install_hint": _build_install_hint(dep)})
            continue
        # 版本收集（importlib.metadata 只查 distribution metadata，不 import 包本身）
        try:
            version = importlib.metadata.version(dep.pip_name or dep.name)
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
        except Exception:
            version = "unknown"
        packages[dep.name] = {"available": True, "version": version}

    # --- 编译器 ---
    compiler = _detect_compiler()

    # --- IDA Pro（全量检测写 cache，errors 按 agent 过滤）---
    ida_pro = _detect_ida_pro()
    if not ida_pro["available"]:
        ida_dep = next((d for d in EXTERNAL_TOOLS if d.name == "ida_pro"), None)
        if ida_dep and ida_dep.required and _agent_matches(ida_dep):
            errors.append({"package": "ida_pro", "install_hint": _build_install_hint(ida_dep)})

    # --- 外部工具（跳过 ida_pro，已单独处理；全量检测写 cache，errors 按 agent 过滤）---
    for dep in EXTERNAL_TOOLS:
        if not dep.preinstall:
            continue
        if dep.name == "ida_pro":
            continue
        resolved, found = _resolve_tool(dep)
        if found:
            version = _get_tool_version(resolved, dep.version_cmd)
            tools[dep.name] = {"available": True, "version": version,
                               "description": dep.description, "resolved_path": resolved}
        else:
            tools[dep.name] = {"available": False, "version": None,
                               "description": dep.description, "resolved_path": None}
            if dep.required and _agent_matches(dep):
                errors.append({"package": dep.name, "install_hint": _build_install_hint(dep)})

    # --- 组装 data + 写 cache ---
    data = {
        "compiler": compiler,
        "packages": packages,
        "ida_pro": ida_pro,
        "tools": tools,
    }
    _save_cache(data)

    return {"success": len(errors) == 0, "data": data, "errors": errors}


def run_detection(skip_install=False):
    errors = []

    _log(f"[+] Python: {sys.executable}")

    _log("[*] 正在检测 C/C++ 编译器...")
    compiler = _detect_compiler()
    if compiler["available"]:
        _log(f"[+] 编译器: {compiler['type']} — {compiler['path']}")
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
        _log(f"[!] {msg}")

    _log("[*] 正在检测 Python 架构...")
    python_arch = platform.architecture()[0]
    _log(f"[+] Python 架构: {python_arch}")

    packages = {}
    for dep in PYTHON_PACKAGES:
        if dep.preinstall:
            continue  # 预装依赖不在此处自动装，由 --check-preinstall 单独检查
        _log(f"[*] 正在检测 {dep.name}...")
        pkg_info = _detect_package(dep.name, version_via=dep.version_via)
        if not pkg_info["available"] and not skip_install:
            _log(f"[*] {dep.name} 未安装，正在自动安装...")
            if _install_package(dep.pip_name):
                pkg_info = _detect_package(dep.name, version_via=dep.version_via)
                if not pkg_info["available"]:
                    # 首次 import 可能因动态库初始化延迟失败（如 macOS PyObjC），重试一次
                    time.sleep(1)
                    pkg_info = _detect_package(dep.name, version_via=dep.version_via)
                if pkg_info["available"]:
                    # 处理 post_install（如 playwright 需要额外安装浏览器）
                    if dep.post_install and dep.name == "playwright":
                        _check_playwright_post_install(skip_install, errors)
                    _log(f"[+] {dep.name} 安装成功: {pkg_info['version']}")
                else:
                    _log(f"[!] {dep.name} 安装后仍无法导入")
            else:
                manual_cmd = f"{sys.executable} -m pip install {dep.pip_name}"
                if dep.required:
                    errors.append(f"{dep.name} 安装失败，请手动运行: {manual_cmd}")
                else:
                    _log(f"[!] {dep.name} 安装失败（可选包，不影响核心流程）。手动安装: {manual_cmd}")
        elif pkg_info["available"]:
            # 已安装的包也需要检查 post_install
            if dep.post_install and dep.name == "playwright":
                _check_playwright_post_install(skip_install, errors)
            _log(f"[+] {dep.name}: {pkg_info['version']}")
        else:
            if dep.required:
                manual_cmd = f"{sys.executable} -m pip install {dep.pip_name}"
                errors.append(f"{dep.name} 未安装。请运行: {manual_cmd}")
            _log(f"[!] {dep.name} 未安装（--skip-install）")
        packages[dep.name] = pkg_info

    _log("[*] 正在检测 IDA Pro...")
    ida_pro = _detect_ida_pro()
    if ida_pro["available"]:
        _log(f"[+] IDA Pro: {ida_pro['path']}")
    else:
        _log("[!] IDA Pro 未配置")

    _log("[*] 正在检测外部工具...")
    tools = _detect_tools()
    for name, info in tools.items():
        if info["available"]:
            ver = info["version"] or "未知版本"
            _log(f"[+] {name}: {ver}")
        else:
            _log(f"[!] {name}: 未找到")

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
    _ensure_ai_env_template()
    _load_ai_env()
    parser = argparse.ArgumentParser(description="逆向分析环境检测")
    parser.add_argument("--output", "-o", help="输出 JSON 文件路径")
    parser.add_argument("--force", "-f", action="store_true", help="强制重新检测（忽略缓存）")
    parser.add_argument("--check-preinstall", metavar="AGENT",
                        help="检查指定 Agent 的依赖是否就绪（不自动装、不缓存），输出 JSON 后退出。"
                             "AGENT=all 时检测所有依赖（Coordinator 用）")
    args = parser.parse_args()

    # --check-preinstall：按 agent 的依赖检查模式，早退（Plugin chat.message 用此模式）
    if args.check_preinstall:
        result = _check_preinstall(args.check_preinstall)
        output_json = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output_json)
            _log(f"[+] 结果已写入: {args.output}")
        print(output_json)
        return

    # 默认模式：缓存命中时用缓存；未命中/--force 时全量实时检测
    cached = _load_cache(force=args.force)
    if cached and not args.force:
        if cached.get("packages"):
            result = {"success": True, "data": cached, "errors": []}
            _log("[*] 使用缓存的环境检测结果（使用 --force 强制重新检测）")
        else:
            _log("[!] 缓存数据不完整，重新检测...")
            cached = None

    if not cached or args.force:
        result = _check_preinstall("all")

    output_json = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        _log(f"[+] 结果已写入: {args.output}")

    # stdout 始终输出 JSON（--output 文件是额外副本，两者内容相同）
    print(output_json)

    if not result["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
