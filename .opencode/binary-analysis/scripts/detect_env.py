"""summary: 跨平台环境自动检测脚本

description:
  检测安全分析所需的工具链和依赖包。
  支持 Windows/Linux/macOS。
  Python 包安装在 Plugin 管理的虚拟环境（~/bw-security-analysis/.venv）中。
  C/C++ 编译器缺失时通知用户。
  必需依赖缺失时返回 success: false，Plugin 终止并提示用户安装。

  两个子命令：
    install                安装全部依赖（install.sh 调用）
    check-preinstall <agent>  按 agent 检测依赖（plugin 每条消息调用，fail-fast）

usage:
  $PYTHON_CMD detect_env.py install
  $PYTHON_CMD detect_env.py check-preinstall <agent> [--output PATH]
  agent=all 时检测所有依赖（Coordinator 用）

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
VENV_DIR = os.path.join(CACHE_DIR, ".venv")


def _find_conda():
    """跨平台搜索 conda：PATH + 常见安装路径。返回 conda 可执行路径或 None。"""
    conda = shutil.which("conda")
    if conda:
        return conda
    home = os.path.expanduser("~")
    candidates = (
        [os.path.join(home, "miniforge3", "Scripts", "conda.exe"),
         os.path.join(home, "miniconda3", "Scripts", "conda.exe")]
        if os.name == "nt" else
        [os.path.join(home, "miniforge3", "bin", "conda"),
         os.path.join(home, "miniconda3", "bin", "conda"),
         "/opt/homebrew/Caskroom/miniforge/base/condabin/conda",
         "/opt/miniforge3/bin/conda",
         "/opt/miniconda3/bin/conda"]
    )
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _get_venv_python():
    """返回 venv Python 可执行路径（跨平台）。"""
    if os.name == "nt":
        return os.path.join(VENV_DIR, "Scripts", "python.exe")
    return os.path.join(VENV_DIR, "bin", "python")


def _bootstrap_venv():
    """检查当前是否在目标 venv 内，不在则创建并重启自己。

    前提：系统里有任意 Python 3.10+ + conda（miniforge/miniconda）。
    流程：
      1. sys.executable == venv Python → 已在 venv 内，直接返回
      2. 不在 venv → 搜 conda → 不存在 → 打印指引 + exit(1)
      3. conda 存在 → conda create → 校验 venv Python 存在
      4. 重启自己：Unix os.execv / Windows subprocess + sys.exit
    """
    venv_python = _get_venv_python()

    # 已在 venv 内
    if os.path.abspath(sys.executable) == os.path.abspath(venv_python):
        return

    # 防死循环：bootstrap 标记
    if os.environ.get("_DETECT_ENV_BOOTSTRAPPED") == "1":
        _log("[!] bootstrap 已执行过但仍在非 venv 环境，终止")
        sys.exit(1)

    _log(f"[*] 当前 Python: {sys.executable}")
    _log(f"[*] 目标 venv Python: {venv_python}")
    _log("[*] 不在目标 venv 内，开始 bootstrap...")

    # 搜 conda
    conda = _find_conda()
    if not conda:
        print("\n[ERROR] 未找到 conda（miniforge/miniconda）。", file=sys.stderr)
        print("请先安装 Miniforge：", file=sys.stderr)
        system = platform.system()
        if system == "Darwin":
            arch = os.uname().machine
            print(f"  curl -L -o /tmp/miniforge.sh https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-{arch}.sh", file=sys.stderr)
            print(f"  bash /tmp/miniforge.sh -b -p $HOME/miniforge3", file=sys.stderr)
        elif system == "Windows":
            print("  从 https://github.com/conda-forge/miniforge#download 下载安装", file=sys.stderr)
        else:
            arch = os.uname().machine
            print(f"  curl -L -o /tmp/miniforge.sh https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-{arch}.sh", file=sys.stderr)
            print(f"  bash /tmp/miniforge.sh -b -p $HOME/miniforge3", file=sys.stderr)
        print("\n安装后重新打开终端，再次运行安装脚本。", file=sys.stderr)
        sys.exit(1)

    _log(f"[+] conda: {conda}")

    # 创建 venv（不设超时——输出实时流到终端，用户能看到进度；
    # 用户可随时 Ctrl+C 终止，SIGINT 会传递给整个进程组包括 conda 子进程）
    if not os.path.isfile(venv_python):
        _log(f"[*] conda create -p {VENV_DIR} python=3.13 -y ...")
        import subprocess as sp
        result = sp.run(
            [conda, "create", "-p", VENV_DIR, "python=3.13", "-y"],
        )
        if result.returncode != 0:
            print(f"\n[ERROR] conda create 失败（退出码 {result.returncode}）", file=sys.stderr)
            sys.exit(1)
        _log("[+] venv 创建成功")
    else:
        _log("[+] venv 已存在，跳过创建")

    # 校验 venv Python 可执行
    if not os.path.isfile(venv_python):
        print(f"\n[ERROR] venv Python 不存在: {venv_python}", file=sys.stderr)
        print("可能 conda create 被中断。请删除目录后重试:", file=sys.stderr)
        print(f"  rm -rf {VENV_DIR}", file=sys.stderr)
        sys.exit(1)

    # 重启自己
    _log(f"[*] 重启到 venv Python: {venv_python}")
    os.environ["_DETECT_ENV_BOOTSTRAPPED"] = "1"
    if os.name == "nt":
        # Windows: os.execv 不可靠，用 subprocess + sys.exit
        import subprocess as sp
        result = sp.run([venv_python, os.path.abspath(__file__)] + sys.argv[1:])
        sys.exit(result.returncode)
    else:
        # Unix: 进程替换
        os.execv(venv_python, [venv_python, os.path.abspath(__file__)] + sys.argv[1:])


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
    # --- 跨平台 ---
    platforms: list[str] = field(default_factory=list)            # 空=全平台; ["darwin"]=仅 macOS
    platform_install_hint: dict[str, str] = field(default_factory=dict)
    # 按 OS 的安装描述。有当前 OS → 用它; 无 → 降级到 install_hint


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
    （check-preinstall 子命令 Plugin 用 JSON.parse(stdout)，诊断信息必须走 stderr）。
    msg: 操作描述；exc: 异常对象（附带类型名）；detail: 附加信息（如子进程 stderr 片段）。"""
    parts = [f"[!] {msg}"]
    if exc is not None:
        parts.append(f"{type(exc).__name__}: {exc}")
    if detail:
        parts.append(str(detail))
    print(": ".join(parts), file=sys.stderr)


def _log(msg):
    """正常进度日志，打到 stderr。
    stdout 独占给 JSON 输出（check-preinstall 子命令的 print(json.dumps)），
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
    # MCP 基础依赖（knowledge + events MCP server 共用）
    Dependency(name="mcp", kind="python", pip_name="mcp", preinstall=True,
               agents=["all"],
               description="MCP 协议库，knowledge/events MCP server 依赖"),
    Dependency(name="sentence_transformers", kind="python", pip_name="sentence-transformers", preinstall=True,
               agents=["all"],
               description="嵌入模型库，knowledge MCP 向量搜索依赖（BGE-M3 嵌入）"),
    Dependency(name="sqlite_vec", kind="python", pip_name="sqlite-vec", preinstall=True,
               agents=["all"],
               description="SQLite 向量扩展，knowledge MCP 向量存储依赖"),
    Dependency(name="graphiti_core", kind="python", pip_name="graphiti-core", preinstall=True,
               agents=["all"],
               description="Graphiti 时序知识图谱库，events MCP server 依赖"),
    # binary-analysis 逆向分析包
    Dependency(name="angr", kind="python", pip_name="angr", preinstall=True,
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis"],
               description="二进制分析/符号执行框架，用于程序状态探索、漏洞发现、自动利用生成"),
    Dependency(name="triton", kind="python", pip_name="triton-library", preinstall=True,
               platforms=["linux", "win32"],
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
               agents=["binary-analysis", "mobile-analysis"],
               description="Python 图像处理库，用于 GUI 截图保存/尺寸获取和移动端截图 JPEG 转换"),
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
    # 预装依赖（preinstall）：历史遗留标志，现在 install 和 check-preinstall 都处理全部包
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
            "  1. 在 .opencode/.ai_env 设置 IDA_PRO_HOME（IDA Pro 安装目录）：\n"
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
        platform_install_hint={
            "darwin": "brew install apktool",
            "linux":  "sudo apt install apktool 或从 https://ibotpeaches.github.io/Apktool/install/ 下载",
            "win32": "从 https://ibotpeaches.github.io/Apktool/install/ 下载（需要 Java）",
        },
    ),
    Dependency(
        name="jadx", kind="tool", preinstall=True,
        agents=["mobile-analysis"], required=True,
        version_cmd=["--version"],
        description="DEX→Java 反编译器",
        install_hint="jadx 未找到。安装: brew install jadx (macOS) / 参考 https://github.com/skylot/jadx",
        platform_install_hint={
            "darwin": "brew install jadx",
            "linux":  "从 https://github.com/skylot/jadx/releases 下载最新 release zip",
            "win32": "从 https://github.com/skylot/jadx/releases 下载最新 release zip",
        },
    ),
    Dependency(
        name="adb", kind="tool", preinstall=True,
        agents=["mobile-analysis"], required=True,
        version_cmd=["version"],
        description="Android Debug Bridge",
        install_hint="adb 未找到。安装: brew install --cask android-platform-tools (macOS) / 参考 https://developer.android.com/tools/adb",
        platform_install_hint={
            "darwin": "brew install --cask android-platform-tools",
            "linux":  "sudo apt install adb",
            "win32": "从 https://developer.android.com/tools/releases/platform-tools 下载",
        },
    ),
    Dependency(
        name="otool", kind="tool", preinstall=True,
        agents=["mobile-analysis"], required=False,
        description="Mach-O 文件查看器（macOS 自带）",
        install_hint="otool 未找到（macOS 自带，非 macOS 无需配置）",
        platforms=["darwin"],
    ),
    Dependency(
        name="ldid", kind="tool", preinstall=True,
        agents=["mobile-analysis"], required=False,
        description="iOS 伪签名工具",
        install_hint="ldid 未找到。安装: brew install ldid (macOS)",
        platforms=["darwin"],
    ),
    Dependency(
        name="GoReSym", kind="tool", preinstall=True,
        agents=["binary-analysis", "crypto-analysis"], required=False,
        description="Go 符号恢复工具",
        install_hint="GoReSym 未找到。参考 https://github.com/mandiant/GoReSym",
        platform_install_hint={
            "darwin": "从 https://github.com/mandiant/GoReSym/releases 下载 darwin 版本",
            "linux":  "从 https://github.com/mandiant/GoReSym/releases 下载 linux 版本",
            "win32": "从 https://github.com/mandiant/GoReSym/releases 下载 windows 版本",
        },
    ),
]


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
        _warn(f"检测 {name} 失败（退出码 {result.returncode}）")
    except subprocess.TimeoutExpired as e:
        _warn(f"检测 {name} 超时（import 可能较慢或卡死）", exc=e)
    except OSError as e:
        _warn(f"检测 {name} 异常", exc=e)
    return {"available": False, "version": None}


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


def _post_install_playwright():
    """安装 Playwright Chromium 浏览器二进制（约 150-200MB）。
    不设超时——输出实时流到终端，用户可 Ctrl+C 终止。"""
    _log("[*] 正在安装 Playwright Chromium 浏览器（首次安装约 150-200MB）...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
        )
        if result.returncode == 0:
            _log("[+] Playwright Chromium 安装成功")
            return True
        _warn(f"Playwright 浏览器安装失败（退出码 {result.returncode}）")
    except OSError as e:
        _warn("Playwright 浏览器安装异常", exc=e)
    return False



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




def _get_platform_install_hint(dep: Dependency) -> str:
    """返回当前 OS 的安装描述。优先 platform_install_hint[sys.platform]，降级到 install_hint。"""
    if dep.platform_install_hint:
        hint = dep.platform_install_hint.get(sys.platform)
        if hint:
            return hint
    return dep.install_hint or f"{dep.name} 未安装，请参考官方文档"


def _platform_matches(dep: Dependency) -> bool:
    """检查 dep 是否适用于当前 OS。空 platforms = 全平台。"""
    return not dep.platforms or sys.platform in dep.platforms


def _run_install():
    """安装全部依赖（install 子命令入口）。

    覆盖：bootstrap venv + Python 包（pip/conda）+ Playwright Chromium + 外部工具提示 + events MCP 基础设施。
    所有输出走 stderr（_log），与 check-preinstall 的 stdout JSON 输出不冲突。
    任何安装失败 → 立即 sys.exit(1)，不继续后续步骤。
    """
    import subprocess as sp

    # bootstrap：确保在目标 venv 内运行
    _bootstrap_venv()

    def _install_fail(msg):
        """安装失败 → 打印错误 → 立即中断。"""
        print(f"\n[ERROR] {msg}", file=sys.stderr)
        print("安装中断。请修复上述错误后重新运行此脚本。", file=sys.stderr)
        sys.exit(1)

    # 1. Python 包
    _log("[*] === 安装 Python 依赖包 ===")
    _log(f"[*] Python: {sys.executable}")
    _log("[*] 升级 pip...")
    pip_upgrade = sp.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    if pip_upgrade.returncode != 0:
        _install_fail("pip 升级失败")

    for dep in PYTHON_PACKAGES:
        if not _platform_matches(dep):
            _log(f"[*] 跳过 {dep.name}（当前平台不适用）")
            continue
        pkg = dep.pip_name or dep.name
        if dep.installer == "conda":
            conda_name = dep.conda_name or dep.pip_name
            conda_cmd = shutil.which("conda")
            if not conda_cmd:
                _install_fail(f"{dep.name} 需要 conda 安装（{conda_name}），但 conda 命令不存在。请先安装 Miniforge。")
            _log(f"[*] conda install {conda_name}...")
            result = sp.run(
                [conda_cmd, "install", "-p", sys.prefix, "-y", conda_name],
            )
            if result.returncode != 0:
                _install_fail(f"{dep.name} conda 安装失败")
            _log(f"[+] {dep.name} 安装成功")
            continue

        _log(f"[*] pip install {pkg}...")
        result = sp.run([sys.executable, "-m", "pip", "install", pkg])
        if result.returncode != 0:
            _install_fail(f"{dep.name} pip 安装失败")
        _log(f"[+] {dep.name} 安装成功")

    # 2. Playwright Chromium（post_install）
    _log("[*] === 安装 Playwright Chromium ===")
    if not _post_install_playwright():
        _install_fail("Playwright Chromium 安装失败")

    # 3. 外部工具（全量检测，缺失打印安装建议）
    _log("[*] === 检测外部工具 ===")
    for dep in EXTERNAL_TOOLS:
        if not _platform_matches(dep):
            continue
        resolved, found = _resolve_tool(dep)
        if found:
            ver = _get_tool_version(resolved, dep.version_cmd) or "已安装"
            _log(f"[+] {dep.name}: {ver}")
        else:
            hint = _get_platform_install_hint(dep)
            _log(f"[!] {dep.name}: 未安装")
            print(f"  → {hint}")

    # 4. events MCP 基础设施（ZHIPU_API_KEY 门控）
    _log("[*] === events MCP 基础设施 ===")
    mcp_servers = _detect_mcp_deps(auto_create=True)
    neo4j = mcp_servers.get("_neo4j", {})
    zhipu = mcp_servers.get("_zhipu_api_key", {})

    if not zhipu.get("available"):
        print("[!] ZHIPU_API_KEY 未配置。")
        print("  events MCP 的实体提取功能将不可用（无法写入新事件，已有事件仍可搜索）。")
        print("  请在 .opencode/.ai_env 中设置 ZHIPU_API_KEY=<your-key>")
    elif not neo4j.get("available"):
        print(f"[!] {neo4j.get('message', 'Neo4j 不可用')}")
    else:
        _log(f"[+] {neo4j.get('message', 'Neo4j 运行中')}")

    for name, info in mcp_servers.items():
        if name.startswith("_"):
            continue
        if info.get("available"):
            _log(f"[+] MCP/{name}: 依赖齐全")
        else:
            _log(f"[!] MCP/{name}: 缺少 {', '.join(info.get('missing', []))}")

    _log("[+] 安装完成")
    _log("[*] === 验证安装结果 ===")
    import subprocess as sp_verify
    verify = sp_verify.run(
        [sys.executable, os.path.abspath(__file__), "check-preinstall", "all"],
    )
    if verify.returncode != 0:
        _log("[!] 部分依赖未就绪（见上方输出），请按提示手动配置。")
    else:
        _log("[+] 全部检测通过！")


def _build_install_guide():
    """生成一键安装提示（当依赖检测不通过时返回给用户）。

    Plugin 的 env-check.ts 优先读取 install_guide 字段，
    展示这条简洁提示而非逐条列出所有缺失依赖。"""
    opencode_root = _get_opencode_root()
    import platform
    if platform.system() == "Windows":
        script = os.path.join(opencode_root, "install.ps1")
        cmd = f'powershell -ExecutionPolicy Bypass -File "{script}"'
    else:
        script = os.path.join(opencode_root, "install.sh")
        cmd = f'bash "{script}"'
    return (
        f"环境未完全配置。请运行一键安装脚本：\n"
        f"  {cmd}\n"
        f"安装完成后重新发送消息。"
    )


def _check_preinstall(agent):
    """检查指定 Agent 的依赖是否就绪（fail-fast：第一个缺失即返回 install_guide）。

    agent="all" 时不按 agent 过滤（Coordinator 用）。

    检测顺序：Python 包 → 编译器 → IDA Pro → 外部工具 → MCP 依赖（信息性）。
    任何必需依赖缺失 → 立即返回 {success: False, install_guide: ...}，不继续检测。
    全部通过 → 收集完整 data 写入 env_cache.json → 返回 {success: True, data: ...}。

    MCP 依赖（Neo4j/ZHIPU_API_KEY/MCP 包）是信息性的，不触发 fail-fast。
    """
    import importlib.util
    import importlib.metadata

    def _agent_matches(dep):
        if agent == "all":
            return True
        return not dep.agents or "all" in dep.agents or agent in dep.agents

    def _fail(item_name):
        """fail-fast：记录日志 + 返回 install_guide。"""
        _log(f"[!] 依赖未就绪: {item_name}")
        return {"success": False, "data": {}, "errors": [], "install_guide": _build_install_guide()}

    packages = {}

    # --- 1. Python 包（fail-fast，忽略 preinstall 标志）---
    for dep in PYTHON_PACKAGES:
        if not _platform_matches(dep):
            continue
        try:
            spec = importlib.util.find_spec(dep.name)
        except Exception as e:
            _warn(f"_check_preinstall: find_spec({dep.name}) 异常", exc=e)
            raise
        if spec is None:
            if dep.required and _agent_matches(dep):
                return _fail(dep.name)
            continue
        try:
            version = importlib.metadata.version(dep.pip_name or dep.name)
        except Exception:
            version = "unknown"
        packages[dep.name] = {"available": True, "version": version}

        # post_install：playwright 包通过后检测 chromium 二进制
        if dep.post_install and dep.name == "playwright" and dep.required and _agent_matches(dep):
            if not _detect_playwright_browser():
                return _fail("playwright chromium")

    # --- 2. 编译器（fail-fast）---
    compiler = _detect_compiler()
    if not compiler["available"]:
        return _fail("compiler")

    # --- 3. IDA Pro（fail-fast，按 agent 过滤）---
    ida_pro = _detect_ida_pro()
    if not ida_pro["available"]:
        ida_dep = next((d for d in EXTERNAL_TOOLS if d.name == "ida_pro"), None)
        if ida_dep and ida_dep.required and _agent_matches(ida_dep):
            return _fail("ida_pro")

    # --- 4. 外部工具（fail-fast，按 agent + platform 过滤）---
    tools = {}
    for dep in EXTERNAL_TOOLS:
        if dep.name == "ida_pro":
            continue
        if not _platform_matches(dep):
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
                return _fail(dep.name)

    # --- 5. events MCP 基础设施（ZHIPU_API_KEY 门控）---
    # ZHIPU_API_KEY 未配置 → 不阻塞（stderr 日志），跳过 Docker/容器检查。
    # ZHIPU_API_KEY 已配置 → Docker/容器不可用 → fail-fast。
    # 三者齐全时 _detect_mcp_deps 已静默自动启动容器。
    mcp_servers = _detect_mcp_deps()
    optional_warnings = []

    zhipu = mcp_servers.get("_zhipu_api_key", {})
    neo4j = mcp_servers.get("_neo4j", {})
    if not zhipu.get("available"):
        # ZHIPU_API_KEY 未配置 → 不阻塞
        _log(f"[!] zhipu_api_key: {zhipu.get('message', '未配置')}")
    elif not neo4j.get("available"):
        # ZHIPU 已配置但 Docker/容器不可用 → fail-fast
        return _fail(f"neo4j: {neo4j.get('message', '不可用')}")

    # --- 全部必需依赖通过 → 写 cache ---
    data = {
        "compiler": compiler,
        "packages": packages,
        "ida_pro": ida_pro,
        "tools": tools,
        "mcp_servers": mcp_servers,
    }
    _save_cache(data)
    result: dict = {"success": True, "data": data, "errors": []}
    if optional_warnings:
        result["optional_warnings"] = optional_warnings
    return result


def _ensure_docker_running(timeout=90):
    """确保 Docker daemon 运行；未运行则尝试自动启动。

    用 shutil.which("docker") 判断是否安装（不依赖硬编码安装路径）。
    macOS: open -a Docker；Linux: systemctl/service；Windows: 启动 Docker Desktop。
    返回 (running, message)。running=True 表示 daemon 已就绪可执行 docker 命令。
    """
    import subprocess as sp
    import time

    # docker CLI 不在 PATH = 未安装（通用判断，不依赖硬编码安装路径）
    if not shutil.which("docker"):
        return False, "未从 PATH 检测到 docker 命令，判定 Docker 未安装（events MCP 需要 Docker 运行 Neo4j）"

    def _daemon_up():
        try:
            sp.run(["docker", "info"], capture_output=True, timeout=10, check=True, text=True)
            return True
        except (sp.CalledProcessError, sp.TimeoutExpired):
            return False

    # 1. 已运行？
    if _daemon_up():
        return True, "Docker 已运行"

    # 2. 按平台自动启动 daemon（直接尝试，失败由 except 捕获；不预检安装路径）
    system = platform.system()
    try:
        if system == "Darwin":
            sp.run(["open", "-a", "Docker"], check=True)
            _log("[*] 正在启动 Docker Desktop（open -a Docker）...")
        elif system == "Linux":
            if shutil.which("systemctl"):
                sp.run(["systemctl", "start", "docker"])
            elif shutil.which("service"):
                sp.run(["service", "docker", "start"])
            else:
                return False, "Docker 未运行且无法自动启动（请手动启动 dockerd）"
            _log("[*] 正在启动 Docker...")
        elif system == "Windows":
            # 从 docker CLI 实际位置推断 Docker Desktop.exe（不硬编码安装路径）
            # 标准布局：…/Docker/Docker/resources/bin/docker.exe → 上三级即 …/Docker/Docker
            dd_exe = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(shutil.which("docker")))),
                "Docker Desktop.exe",
            )
            sp.run(["powershell", "-NoProfile", "-Command", f"Start-Process '{dd_exe}'"])
            _log("[*] 正在启动 Docker Desktop（Windows）...")
        else:
            return False, f"不支持的系统: {system}（请手动启动 Docker）"
    except Exception as e:
        return False, f"自动启动 Docker 失败（{system}）：{e}"

    # 3. 轮询等待 daemon 就绪
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3)
        if _daemon_up():
            _log("[+] Docker daemon 已就绪")
            return True, "Docker 已自动启动"
    return False, f"Docker 启动超时（等待 {timeout}s 未就绪，请手动启动 Docker）"


def _pull_image_with_progress(image, timeout=600):
    """docker pull 并实时把进度转发到 _log，避免长时间无反馈。

    docker pull 非 TTY（管道）模式输出行式日志（每层状态一行），逐行转发给用户。
    镜像已是最新则秒过（输出 'Image is up to date'）；首次下载时实时显示各层进度。
    """
    import subprocess as sp
    _log(f"[*] docker pull {image}（首次需下载镜像，请耐心等待）...")
    proc = sp.Popen(
        ["docker", "pull", image],
        stdout=sp.PIPE, stderr=sp.STDOUT, text=True, bufsize=1,
    )
    try:
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                _log(f"    {line}")
        proc.wait(timeout=timeout)
    except sp.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise
    if proc.returncode != 0:
        raise sp.CalledProcessError(proc.returncode, ["docker", "pull", image])
    _log(f"[+] {image} 镜像就绪")


def _detect_mcp_deps(auto_create=False):
    """检测 MCP server 的 Python 依赖包 + Neo4j + ZHIPU_API_KEY。

    auto_create=False（check-preinstall 用）：容器不存在 → 返回 unavailable（fail-fast）
    auto_create=True（install 用）：容器不存在 → docker run 创建+启动

    Docker daemon 未运行时自动启动（_ensure_docker_running），无需用户手动开 Docker Desktop。
    """
    import subprocess as sp

    opencode_root = _get_opencode_root()

    # 依赖包检测
    mcp_config = {
        "knowledge": {
            "script": os.path.join(opencode_root, "mcp-servers", "knowledge", "server.py"),
            "packages": ["mcp", "sentence_transformers", "sqlite_vec"],
        },
        "events": {
            "script": os.path.join(opencode_root, "mcp-servers", "events", "server.py"),
            "packages": ["mcp", "graphiti_core"],
        },
    }
    result = {}
    for name, cfg in mcp_config.items():
        missing = []
        for pkg in cfg["packages"]:
            try:
                __import__(pkg)
            except ImportError:
                missing.append(pkg)
        result[name] = {
            "available": len(missing) == 0,
            "missing": missing,
            "script": cfg["script"],
        }

    # ZHIPU_API_KEY 先检（门控：未配置则跳过全部 Docker/容器操作）
    zhipu_key = os.environ.get("ZHIPU_API_KEY", "")
    zhipu_ok = bool(zhipu_key.strip())

    # Docker + Neo4j：仅在 ZHIPU 已配置时才检查
    if not zhipu_ok:
        neo4j_status = {"available": False, "message": "ZHIPU_API_KEY 未配置，跳过 Docker/Neo4j 检查"}
    else:
        neo4j_status = {"available": False, "message": ""}
        try:
            # 确保 Docker daemon 运行（未运行则自动启动 Docker Desktop 等）
            _docker_ok, _docker_msg = _ensure_docker_running()
            if not _docker_ok:
                raise RuntimeError(_docker_msg)

            # 1. 容器已在运行？
            ps_result = sp.run(
                ["docker", "ps", "--filter", "name=neo4j-events", "--format", "{{.Names}}"],
                capture_output=True, timeout=10, text=True,
            )
            if ps_result.stdout.strip() == "neo4j-events":
                neo4j_status = {"available": True, "message": "Neo4j 容器已在运行"}

            # 2. 容器存在但停止？→ docker start
            else:
                psa_result = sp.run(
                    ["docker", "ps", "-a", "--filter", "name=neo4j-events", "--format", "{{.Names}}"],
                    capture_output=True, timeout=10, text=True,
                )
                if psa_result.stdout.strip() == "neo4j-events":
                    sp.run(["docker", "start", "neo4j-events"],
                           capture_output=True, timeout=30, check=True, text=True)
                    _log("[+] Neo4j 容器已启动（原已存在但停止）")
                    neo4j_status = {"available": True, "message": "Neo4j 容器已启动"}

                # 3. 容器不存在
                else:
                    if auto_create:
                        # install 模式：创建+启动
                        data_dir = os.path.join(os.path.expanduser("~"), "bw-security-analysis", "db", "events")
                        os.makedirs(data_dir, exist_ok=True)
                        # 先 pull 镜像并实时显示进度（避免 docker run 隐式 pull 时长时间无反馈）
                        _pull_image_with_progress("neo4j:5")
                        sp.run(
                            ["docker", "run", "-d", "--name", "neo4j-events",
                             "-p", "7474:7474", "-p", "7687:7687",
                             "-e", "NEO4J_AUTH=neo4j/neo4j_password",
                             "-v", f"{data_dir}:/data", "neo4j:5"],
                            capture_output=True, timeout=60, text=True, check=True,
                        )
                        _log(f"[+] Neo4j 容器已创建并启动，数据目录: {data_dir}")
                        neo4j_status = {"available": True, "message": "Neo4j 容器已创建并启动"}
                    else:
                        # check-preinstall 模式：不创建，返回 unavailable（→ fail-fast）
                        neo4j_status = {"available": False, "message": "Neo4j 容器不存在，请运行安装脚本"}

        except RuntimeError as e:
            # _ensure_docker_running 启动/确认失败（未安装、启动超时、无法自动启动）
            neo4j_status = {"available": False, "message": str(e)}
        except FileNotFoundError:
            neo4j_status = {"available": False, "message": "Docker 未安装（events MCP 需要 Docker 运行 Neo4j）"}
        except sp.CalledProcessError as e:
            neo4j_status = {"available": False, "message": f"Docker 命令失败: {e}"}
        except sp.TimeoutExpired:
            neo4j_status = {"available": False, "message": "Docker 操作超时"}
        except Exception as e:
            neo4j_status = {"available": False, "message": f"Docker 异常: {e}"}

    zhipu_status = {
        "available": zhipu_ok,
        "message": "已配置" if zhipu_ok else "未配置（请在 .opencode/.ai_env 中设置 ZHIPU_API_KEY）",
    }

    result["_neo4j"] = neo4j_status
    result["_zhipu_api_key"] = zhipu_status
    return result


def main():
    _ensure_ai_env_template()
    _load_ai_env()
    parser = argparse.ArgumentParser(
        description="安全分析环境检测与安装",
        usage="detect_env.py <command> [options]\n\n"
              "子命令:\n"
              "  install                      安装全部依赖（install.sh 调用）\n"
              "  check-preinstall <agent>     按 agent 检测依赖（plugin 调用）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # install 子命令
    sub.add_parser("install", help="安装全部依赖")

    # check-preinstall 子命令
    chk = sub.add_parser("check-preinstall", help="按 agent 检测依赖是否就绪")
    chk.add_argument("agent", help="Agent 名字（all=全部）")
    chk.add_argument("--output", "-o", help="输出 JSON 文件路径")

    args = parser.parse_args()

    if args.command == "install":
        _run_install()
        return

    if args.command == "check-preinstall":
        result = _check_preinstall(args.agent)
        output_json = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output_json)
            _log(f"[+] 结果已写入: {args.output}")
        print(output_json)
        if not result["success"]:
            sys.exit(1)
        return


if __name__ == "__main__":
    main()
