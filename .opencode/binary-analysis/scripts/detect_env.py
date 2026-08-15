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
VENV_DIR = os.path.join(CACHE_DIR, ".venv")

# 注：events MCP Docker 基础设施（NEO4J_IMAGE、NEO4J_CONTAINER_NAME、Docker 检测）
# 已迁移到控制台 services/docker_manager.py。
# 注：EXTERNAL_TOOLS（IDA Pro、apktool、jadx 等）已迁移到控制台 services/tools_detector.py。
# 注：embed_server 检测/启动已迁移到控制台 server.py。


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

# DeepSeek API Key（events MCP 实体提取用，https://platform.deepseek.com 申请）
DEEPSEEK_API_KEY=
# events MCP 模型配置（可选，按需修改）
# DEEPSEEK_MODEL=deepseek-v4-pro        # 核心提取模型（费用吃不消时改成 deepseek-v4-flash）
# DEEPSEEK_SMALL_MODEL=deepseek-v4-flash # 时间戳推断模型
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

    注意：本函数在控制台架构改造后仅供 _run_install 内部使用（install.sh 调用路径）。
    check-preinstall 子命令不再依赖 .ai_env（IDA_PRO_HOME / DEEPSEEK_API_KEY 等检测
    已迁移到控制台 config_store）。
    """
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
               description="嵌入模型库，embed_server 加载 BGE-M3 模型依赖"),
    Dependency(name="psutil", kind="python", pip_name="psutil", preinstall=True,
               agents=["all"],
               description="进程/内存监控库，embed_server 和诊断工具依赖"),
    # 控制台后端依赖（opencode-control，所有 agent 共用）
    Dependency(name="fastapi", kind="python", pip_name="fastapi", preinstall=True,
               agents=["all"],
               description="控制台 Web 框架（embed_server 超集 + 资源管理 + 配置管理）"),
    Dependency(name="portalocker", kind="python", pip_name="portalocker", preinstall=True,
               agents=["all"],
               description="控制台跨平台文件锁（统一 fcntl/msvcrt 抽象）"),
    Dependency(name="sse_starlette", kind="python", pip_name="sse-starlette", preinstall=True,
               agents=["all"],
               description="控制台 SSE 推送（docker pull 进度）"),
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

    # 3. 外部工具 / events MCP / embed_server 检测已迁移到控制台
    # 用户跑完 install.sh 后启动 opencode，控制台会显示工具/Docker/模型 完整状态。
    # 控制台访问地址：http://localhost:9776
    _log("[*] === 后续检查 ===")
    _log("[*] 外部工具（IDA Pro、apktool 等）、Docker 镜像、events MCP 状态")
    _log("[*] 请启动 opencode 后访问控制台查看：http://localhost:9776")

    _log("[+] 安装完成")
    _log("[*] === 验证安装结果（仅第二层 Python 包 + 编译器） ===")
    import subprocess as sp_verify
    verify = sp_verify.run(
        [sys.executable, os.path.abspath(__file__), "check-preinstall", "all"],
    )
    if verify.returncode != 0:
        _log("[!] 部分依赖未就绪（见上方输出），请按提示手动配置。")
    else:
        _log("[+] 第二层检测全部通过！")
        _log("[*] 第三~五层（外部工具、Docker、配置）请在控制台查看。")


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

    改造后检测范围（只查第二层）：
      Python 包 → 编译器

    外部工具（IDA Pro、apktool）、Docker 镜像、配置（DEEPSEEK_API_KEY）等
    已迁移到控制台（services/tools_detector.py、docker_manager.py、config_store.py）。
    控制台提供更友好的 GUI + 一键修复，不再走 fail-fast 文字流。

    任何必需依赖缺失 → 立即返回 {success: False, install_guide: ...}。
    全部通过 → 返回 {success: True, data: ...}。
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

    # --- 2. 编译器（fail-fast，pip 安装 C 扩展需要）---
    compiler = _detect_compiler()
    if not compiler["available"]:
        return _fail("compiler")

    # --- 全部必需依赖通过 → 组装 data ---
    data = {
        "compiler": compiler,
        "packages": packages,
    }
    result: dict = {"success": True, "data": data, "errors": []}
    return result























def main():
    # 注意：_ensure_ai_env_template + _load_ai_env 只在 install 子命令内调用，
    # check-preinstall 不需要（第二层检测不依赖 .ai_env 配置）。
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
        # install 流程：先确保 .ai_env 模板存在 + 加载到 os.environ（供 pip 安装日志等使用）
        _ensure_ai_env_template()
        _load_ai_env()
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
