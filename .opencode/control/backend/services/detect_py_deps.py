"""Python 依赖检测 + 安装（清单唯一副本，检测/安装双子命令）。

设计约束：
  • 纔 stdlib——install.sh 在 venv 建立前运行本文件（清单+安装器一体，
    无跨文件动态加载），不得依赖任何第三方包/包内相对导入
  • 检测函数 scan(agent, python_exe) 同一签名服务两种入口：
      - 控制台 import 调用（routes/deps.py、scan 页）
      - CLI 子命令 scan（python detect_py_deps.py scan --agent X --json）
  • 安装子命令 install：找 conda 创建 venv → 装全部必需依赖
    （required=True 且当前平台适用；conda 安装器条目走 conda install 命令）。
    与检测端语义对齐：plugin 检查的就是全部必需依赖，装完即全部通过。
    控制台 Python 依赖页用于补装/修复单包，不是安装的主路径。

清单是唯一数据源：
  • routes/install.py 的 pip 白名单（经 detect_tools.pip_installable_packages 引用）
  • install 子命令的安装清单
  • 控制台 Python 依赖页的检测行
加包只改这里。

调用方：
  控制台 routes/deps.py / routes/install.py / scanner.py（import）
  install.sh / install.ps1（CLI: install 子命令）
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field

CACHE_DIR = os.path.expanduser("~/bw-security-analysis")
VENV_DIR = os.path.join(CACHE_DIR, ".venv")


@dataclass(frozen=True)
class PyPkgField:
    """Python 包元数据。"""
    name: str                     # import 名（mcp / sentence_transformers / ...）
    pip_name: str                 # pip 安装名（sentence-transformers / ...）
    agents: list[str]             # 使用方（["all"] = 全部）
    description: str = ""
    required: bool = True         # install 子命令装全部 required（与检测端判定一致）
    platforms: tuple[str, ...] = ()   # 空=全平台
    installer: str = "pip"        # pip / conda（conda 的不走 pip 白名单）
    conda_name: str = ""          # installer=conda 时的包名（空则用 pip_name）
    version_via_import: bool = False  # True: 版本经 import 探测（pip 名与 distribution 不一致特例）


PYTHON_PACKAGES: list[PyPkgField] = [
    # ── 控制台 + 基础设施（agents=all） ──
    PyPkgField(name="fastapi", pip_name="fastapi", agents=["all"],
               description="控制台 Web 框架"),
    PyPkgField(name="uvicorn", pip_name="uvicorn", agents=["all"],
               description="控制台 ASGI 服务器（fastapi 不自带，必须显式安装）"),
    PyPkgField(name="psutil", pip_name="psutil", agents=["all"],
               description="进程/内存监控库，控制台资源管理依赖"),
    PyPkgField(name="pywin32", pip_name="pywin32", agents=["all"], platforms=("win32",),
               description="Windows 命名管道（控制台 IPC 监听 + MCP 管道代理）"),
    PyPkgField(name="mlx-vlm", pip_name="mlx-vlm", agents=["all"], platforms=("darwin",),
               description="MLX 视觉模型库（OCR 进程内推理；Apple Silicon 专属）"),
    PyPkgField(name="numpy", pip_name="numpy", agents=["all"],
               description="数值计算库，embed 接口返回值"),
    PyPkgField(name="httpx", pip_name="httpx", agents=["all"],
               description="HTTP 客户端库，MCP→控制台通信"),
    PyPkgField(name="huggingface_hub", pip_name="huggingface_hub", agents=["all"],
               description="模型缓存扫描与下载（控制台模型资产页）"),
    PyPkgField(name="mcp", pip_name="mcp", agents=["all"],
               description="MCP 协议库，knowledge/events/ocr MCP server 依赖"),
    PyPkgField(name="sentence_transformers", pip_name="sentence-transformers", agents=["all"],
               description="嵌入模型库，加载 BGE-M3 模型依赖"),
    PyPkgField(name="sse_starlette", pip_name="sse-starlette", agents=["all"],
               description="控制台 SSE 推送（docker pull 进度）"),
    PyPkgField(name="sqlite_vec", pip_name="sqlite-vec", agents=["all"],
               description="SQLite 向量扩展，knowledge MCP 向量存储依赖"),
    PyPkgField(name="graphiti_core", pip_name="graphiti-core", agents=["all"],
               description="Graphiti 时序知识图谱库，events MCP server 依赖"),
    PyPkgField(name="pyautogui", pip_name="pyautogui", agents=["all"],
               description="GUI 自动化（鼠标/键盘模拟）"),
    PyPkgField(name="pyperclip", pip_name="pyperclip", agents=["all"],
               description="跨平台剪贴板操作"),
    PyPkgField(name="playwright", pip_name="playwright", agents=["all"],
               description="无头浏览器自动化框架"),
    PyPkgField(name="markdownify", pip_name="markdownify", agents=["all"],
               description="HTML 转 Markdown"),
    PyPkgField(name="requests", pip_name="requests", agents=["all"],
               description="HTTP 客户端库"),
    PyPkgField(name="bs4", pip_name="beautifulsoup4", agents=["all"],
               description="HTML/XML 解析库（BeautifulSoup4）"),
    PyPkgField(name="lxml", pip_name="lxml", agents=["all"],
               description="高性能 XML/HTML 解析器"),
    PyPkgField(name="sympy", pip_name="sympy", agents=["all"],
               description="符号数学库（CRT/数论构造）"),
    # ── 二进制/密码学分析包 ──
    PyPkgField(name="angr", pip_name="angr",
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis"],
               description="二进制分析/符号执行框架"),
    PyPkgField(name="triton", pip_name="triton-library", platforms=("linux", "win32"),
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis"],
               description="动态二进制分析框架（符号执行/污点分析）"),
    PyPkgField(name="z3", pip_name="z3-solver",
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis", "ai-security-analysis"],
               description="Z3 定理证明器（约束求解）"),
    PyPkgField(name="capstone", pip_name="capstone",
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis"],
               description="多架构反汇编框架"),
    PyPkgField(name="unicorn", pip_name="unicorn",
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis", "ai-security-analysis"],
               description="多架构 CPU 模拟器（Shellcode 测试）"),
    PyPkgField(name="gmpy2", pip_name="gmpy2",
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis", "ai-security-analysis"],
               description="高精度算术库（大整数/模幂/素性检测）"),
    PyPkgField(name="frida", pip_name="frida",
               agents=["binary-analysis", "mobile-analysis"],
               description="动态插桩工具包（Hook/内存读写）"),
    PyPkgField(name="PIL", pip_name="Pillow",
               agents=["binary-analysis", "mobile-analysis"],
               description="图像处理库（GUI 截图）"),
    # ── OCR 链路 ──
    PyPkgField(name="pymupdf", pip_name="pymupdf", agents=["all"],
               description="PDF 文本层提取与页面渲染（OCR 前置分流）"),
    # ── 知识库引用的分析依赖（knowledge-base 正文直接 import；随项目走） ──
    PyPkgField(name="pwn", pip_name="pwntools", agents=["binary-analysis"],
               description="pwn 全流程（ROP 构造/远程 IO/ELF 操作），pwn-methodology 主依赖"),
    PyPkgField(name="qiling", pip_name="qiling", agents=["binary-analysis"],
               description="OS 层模拟（PE/ELF 全系统仿真+syscall hook）"),
    PyPkgField(name="pefile", pip_name="pefile", agents=["binary-analysis"],
               description="PE 解析（malware-analysis 配置提取/节表分析）"),
    PyPkgField(name="lief", pip_name="lief", agents=["binary-analysis"],
               description="ELF/PE/Mach-O 程序化修补（process-patch-reference）"),
    PyPkgField(name="elftools", pip_name="pyelftools", agents=["binary-analysis"],
               description="ELF 解析（readelf 脚本化/符号表提取）"),
    PyPkgField(name="Crypto", pip_name="pycryptodome",
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis"],
               description="密码学算法复现（AES/RSA/哈希，crypto-validation-patterns）"),
    PyPkgField(name="volatility3", pip_name="volatility3", agents=["binary-analysis"],
               description="内存取证全命令族，disk-memory-forensics 主依赖"),
    PyPkgField(name="hashpumpy", pip_name="hashpumpy", agents=["web-analysis"],
               description="哈希长度扩展攻击"),
    PyPkgField(name="sqlmap", pip_name="sqlmap",
               agents=["web-analysis", "binary-analysis"],
               description="SQL 注入自动化"),
    PyPkgField(name="dirsearch", pip_name="dirsearch", agents=["web-analysis"],
               description="目录/路径爆破"),
    PyPkgField(name="wafw00f", pip_name="wafw00f", agents=["web-analysis"],
               description="WAF 产品指纹识别"),
    PyPkgField(name="arjun", pip_name="arjun", agents=["web-analysis"],
               description="HTTP 隐藏参数发现"),
    PyPkgField(name="flask_unsign", pip_name="flask-unsign", agents=["web-analysis"],
               description="Flask session cookie 解码/伪造/爆破，ssti/jwt-attacks"),
    PyPkgField(name="semgrep", pip_name="semgrep", agents=["web-analysis"],
               description="规则化代码审计（多语言源码审计）"),
    PyPkgField(name="pyotp", pip_name="pyotp", agents=["web-analysis"],
               description="TOTP/HOTP 生成（2FA 测试），jwt-attacks"),
    PyPkgField(name="dns", pip_name="dnspython",
               agents=["binary-analysis", "web-analysis"],
               description="DNS 协议库（AXFR/隧道解析脚本，network-forensics"),
    PyPkgField(name="impacket", pip_name="impacket", agents=["binary-analysis"],
               description="Windows 协议套件（psexec/secretsdump/ntlmrelayx 等）"),
    PyPkgField(name="binwalk", pip_name="binwalk", agents=["binary-analysis"],
               description="固件/文件签名扫描与提取（packer-handling/platform-reversing）"),
    PyPkgField(name="hashid", pip_name="hashid", agents=["binary-analysis"],
               description="哈希类型识别（ad-domain-attacks 哈希模式判别）"),
    PyPkgField(name="Registry", pip_name="python-registry", agents=["binary-analysis"],
               description="Windows 注册表 hive 程序化解析"),
    PyPkgField(name="mitmproxy", pip_name="mitmproxy", agents=["web-analysis", "mobile-analysis"],
               description="HTTP(S) 拦截代理（mitmdump CLI，CSP/移动抓包）"),
    PyPkgField(name="Evtx", pip_name="python-evtx", agents=["binary-analysis"],
               description="Windows EVTX 事件日志解析（forensics-methodology）"),
    PyPkgField(name="pytsk3", pip_name="pytsk3", agents=["binary-analysis"],
               description="Sleuth Kit 库（fls/icat/istat 磁盘镜像遍历提取，disk-memory-forensics）"),
    PyPkgField(name="yara", pip_name="yara-python", agents=["binary-analysis"],
               description="YARA 规则扫描（malware-analysis 特征匹配）"),
    PyPkgField(name="ropper", pip_name="ropper", agents=["binary-analysis"],
               description="ROP gadget"),
    PyPkgField(name="ROPgadget", pip_name="ROPgadget", agents=["binary-analysis"],
               description="ROP gadget"),
    PyPkgField(name="patchelf", pip_name="patchelf", agents=["binary-analysis"],
               description="ELF 修补（patchelf CLI，pwn-methodology ROP 链构建）"),
    PyPkgField(name="xortool", pip_name="xortool", agents=["binary-analysis", "crypto-analysis"],
               description="XOR 密钥长度/明文分析（classical-crypto/steganography）"),
    PyPkgField(name="pypykatz", pip_name="pypykatz", agents=["binary-analysis"],
               description="LSASS/注册表凭据提取（mimikatz 纯 python 等效，windows-forensics）"),
    PyPkgField(name="scapy", pip_name="scapy", agents=["binary-analysis", "web-analysis"],
               description="pcap 构造/解析（network-forensics，tshark 附录的 venv 路径）"),
    PyPkgField(name="reflutter", pip_name="reflutter", agents=["mobile-analysis"],
               description="Flutter SSL pinning 绕过重打包（cross-platform-frameworks）"),
    PyPkgField(name="hbctool", pip_name="hbctool", agents=["mobile-analysis"],
               description="Hermes 字节码反编译/disasm（cross-platform-frameworks）"),
    PyPkgField(name="frida", pip_name="frida-tools", agents=["binary-analysis", "mobile-analysis"],
               description="动态插桩全套 CLI（frida/frida-ps/frida-trace/frida-strace/frida-server 推送, frida 体系主依赖）"),
    PyPkgField(name="awscli", pip_name="awscli", agents=["web-analysis"],
               description="AWS CLI（S3 接管验证/桶操作, subdomain-takeover）"),
    PyPkgField(name="lsassy", pip_name="lsassy", agents=["binary-analysis"],
               description="LSASS 远程/本地凭据提取（纯 python，mimikatz 等效）"),
    PyPkgField(name="mitm6", pip_name="mitm6", agents=["binary-analysis"],
               description="IPv6 DNS 欺骗→NTLMv2 中继（AD 攻击链）"),
    PyPkgField(name="py7zr", pip_name="py7zr", agents=["binary-analysis"],
               description="7z 归档解压（hashcat 官方包/ImageMagick portable 处理）"),
    PyPkgField(name="uncompyle6", pip_name="uncompyle6", agents=["binary-analysis"],
               description="Python 字节码反编译（≤py3.8; 高版本用 pycdc 容器路径）"),
    # ── conda 安装器（必需；服务端按 installer 字段走 conda install 命令） ──
    PyPkgField(name="sage", pip_name="sagemath-standard", installer="conda",
               conda_name="sage",
               agents=["crypto-analysis"], version_via_import=True,
               description="数学软件系统（格归约/椭圆曲线）—— conda 安装"),
]


# ═══ 检测 ═════════════════════════════════════════════════


@dataclass
class PyPkgStatus:
    """单个 Python 包的检测状态。"""
    name: str
    pip_name: str
    kind: str                    # 恒 "python"
    description: str
    required: bool
    installer: str               # pip / conda
    agents: list[str]
    available: bool
    version: str | None


class PyDepsDetector:
    """Python 依赖检测器（import 调用与 CLI 子命令共用同一 scan）。"""

    def scan(self, agent: str = "all", python_exe: str | None = None) -> list[PyPkgStatus]:
        """检测 Python 包安装状态。

        Args:
            agent: 过滤归属（"all" = 全部）
            python_exe: 目标解释器。None = 当前解释器（控制台进程即在 venv 内）
        """
        python_exe = python_exe or sys.executable
        return [
            self._detect_one(pkg, python_exe)
            for pkg in PYTHON_PACKAGES
            if self._platform_matches(pkg) and self._agent_matches(pkg, agent)
        ]

    def _detect_one(self, pkg: PyPkgField, python_exe: str) -> PyPkgStatus:
        """检测单个包。

        优先 importlib.metadata（快，无子进程）；
        version_via_import 特例（sage）或跨解释器场景用子进程探测。
        """
        if sys.executable == python_exe and not pkg.version_via_import:
            version = self._metadata_version(pkg.pip_name)
            return self._status(pkg, version is not None, version)
        ok, version = self._probe_subprocess(pkg, python_exe)
        return self._status(pkg, ok, version)

    @staticmethod
    def _status(pkg: PyPkgField, available: bool, version: str | None) -> PyPkgStatus:
        return PyPkgStatus(
            name=pkg.name, pip_name=pkg.pip_name, kind="python",
            description=pkg.description, required=pkg.required,
            installer=pkg.installer, agents=list(pkg.agents),
            available=available, version=version,
        )

    @staticmethod
    def _metadata_version(pip_name: str) -> str | None:
        import importlib.metadata
        try:
            return importlib.metadata.version(pip_name)
        except importlib.metadata.PackageNotFoundError:
            return None

    @staticmethod
    def _probe_subprocess(pkg: PyPkgField, python_exe: str) -> tuple[bool, str | None]:
        """子进程探测（CLI 指定其他 python / sage 特例）。异常容错返回 (False, None)。"""
        code = (f"import importlib.util\n"
                f"print('OK' if importlib.util.find_spec('{pkg.name}') else 'MISSING')\n")
        try:
            r = subprocess.run([python_exe, "-c", code],
                               capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and r.stdout.strip() == "OK":
                vcode = (f"import importlib.metadata\n"
                         f"print(importlib.metadata.version('{pkg.pip_name}'))\n")
                vr = subprocess.run([python_exe, "-c", vcode],
                                    capture_output=True, text=True, timeout=10)
                version = vr.stdout.strip() if vr.returncode == 0 else "unknown"
                return True, version
        except (subprocess.TimeoutExpired, OSError):
            pass
        return False, None

    @staticmethod
    def _platform_matches(pkg: PyPkgField) -> bool:
        return not pkg.platforms or sys.platform in pkg.platforms

    @staticmethod
    def _agent_matches(pkg: PyPkgField, agent: str) -> bool:
        if agent == "all":
            return True
        return "all" in pkg.agents or agent in pkg.agents


_detector = PyDepsDetector()


def scan(agent: str = "all", python_exe: str | None = None) -> list[PyPkgStatus]:
    """模块级委托（兼容既有消费方）。"""
    return _detector.scan(agent, python_exe)


def required_packages() -> list[PyPkgField]:
    """必需包集（install 子命令的安装清单：required 且当前平台适用）。"""
    return [p for p in PYTHON_PACKAGES if p.required and PyDepsDetector._platform_matches(p)]


def one_click_installable() -> set[str]:
    """可一键安装的包名集合（/api/install 白名单的唯一数据源）。

    唯一清单中当前平台适用的全部包（必需包修复重装 + 可选包补装）。
    installer 字段（pip/conda）只决定服务端执行哪条安装命令，
    不影响"能否一键安装"——控制台环境本身就有 conda（venv 由它创建）。
    """
    return {
        pkg.pip_name
        for pkg in PYTHON_PACKAGES
        if PyDepsDetector._platform_matches(pkg)
    }


# ═══ 安装 ═════════════════════════════════════════════════


def _warn(msg, exc=None):
    """统一的 stderr 诊断日志。"""
    parts = [f"[!] {msg}"]
    if exc is not None:
        parts.append(f"{type(exc).__name__}: {exc}")
    print(": ".join(parts), file=sys.stderr)


def _log(msg):
    """正常进度日志，打到 stderr。"""
    print(msg, file=sys.stderr)


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

    # 防死循环：venv 重启标记
    if os.environ.get("_INSTALL_PY_DEPS_BOOTSTRAPPED") == "1":
        _log("[!] venv 重启已执行过但仍不在 venv 环境，终止")
        sys.exit(1)

    _log(f"[*] 当前 Python: {sys.executable}")
    _log(f"[*] 目标 venv Python: {venv_python}")
    _log("[*] 不在目标 venv 内，创建 venv 并重启自身...")

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
        result = subprocess.run(
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
    os.environ["_INSTALL_PY_DEPS_BOOTSTRAPPED"] = "1"
    if os.name == "nt":
        # Windows: os.execv 不可靠，用 subprocess + sys.exit
        result = subprocess.run([venv_python, os.path.abspath(__file__)] + sys.argv[1:])
        sys.exit(result.returncode)
    else:
        # Unix: 进程替换
        os.execv(venv_python, [venv_python, os.path.abspath(__file__)] + sys.argv[1:])


def _run_install(dry_run: bool):
    """安装全部必需依赖（install 子命令入口）。

    dry_run → 只打印将安装的清单，不执行（可在 venv 外跑，不进 venv）。
    """
    if dry_run:
        pkgs = required_packages()
        _log(f"[*] dry-run: 将安装 {len(pkgs)} 个包（全部必需依赖）")
        for p in pkgs:
            _log(f"    {p.pip_name}")
        return

    # 确保在目标 venv 内运行
    _bootstrap_venv()

    def _install_fail(msg):
        """安装失败 → 打印错误 → 立即中断。"""
        print(f"\n[ERROR] {msg}", file=sys.stderr)
        print("安装中断。请修复上述错误后重新运行此脚本。", file=sys.stderr)
        sys.exit(1)

    packages = required_packages()
    _log("[*] 模式: 全部必需依赖（与检测端 /api/deps 的 required 判定一致）")

    # 1. Python 包
    _log("[*] === 安装 Python 依赖包 ===")
    _log(f"[*] Python: {sys.executable}")
    _log("[*] 升级 pip...")
    pip_upgrade = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    if pip_upgrade.returncode != 0:
        _install_fail("pip 升级失败")

    for dep in packages:
        if not PyDepsDetector._platform_matches(dep):
            _log(f"[*] 跳过 {dep.name}（当前平台不适用）")
            continue
        if dep.installer == "conda":
            conda = _find_conda()
            if not conda:
                _install_fail(f"{dep.name} 需要 conda 安装，但 conda 命令不存在（请先装 Miniforge）")
            conda_name = dep.conda_name or dep.pip_name
            _log(f"[*] conda install {conda_name}（GB 级下载，可能较久）...")
            result = subprocess.run([conda, "install", "-p", sys.prefix, "-y", conda_name])
            if result.returncode != 0:
                _install_fail(f"{dep.name} conda 安装失败")
            _log(f"[+] {dep.name} 安装成功")
            continue
        pkg = dep.pip_name or dep.name
        _log(f"[*] pip install {pkg}...")
        result = subprocess.run([sys.executable, "-m", "pip", "install", pkg])
        if result.returncode != 0:
            _install_fail(f"{dep.name} pip 安装失败")
        _log(f"[+] {dep.name} 安装成功")

    _log("[+] 必需依赖安装完成。")

    # 收尾提示（检测在控制台）
    _log("[*] === 后续检查 ===")
    _log("[*] 外部工具、Docker 镜像、模型、Python 依赖 完整状态")
    _log("[*] 请启动 opencode 后访问控制台查看/修复。")


# ═══ CLI ══════════════════════════════════════════════════


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Python 依赖检测+安装（唯一清单）",
        usage="detect_py_deps.py <command> [options]\n\n"
              "子命令:\n"
              "  scan                    检测依赖状态\n"
              "  install                安装全部必需依赖（venv + required 包）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    chk = sub.add_parser("scan", help="检测依赖状态")
    chk.add_argument("--agent", default="all", help="agent 名（all=全部）")
    chk.add_argument("--python", default=None, help="目标解释器路径（默认当前）")
    chk.add_argument("--json", action="store_true", help="JSON 输出到 stdout")

    inst = sub.add_parser("install", help="安装全部必需依赖")
    inst.add_argument("--dry-run", action="store_true",
                      help="只打印将安装的清单，不执行")

    args = parser.parse_args()

    if args.command == "install":
        _run_install(dry_run=args.dry_run)
        return 0

    # scan
    result = scan(agent=args.agent, python_exe=args.python)
    if args.json:
        print(json.dumps({
            "agent": args.agent,
            "python": args.python or sys.executable,
            "platform": platform.platform(),
            "packages": [asdict(p) for p in result],
        }, ensure_ascii=False, indent=2))
    else:
        for p in result:
            mark = "+" if p.available else "-"
            ver = p.version or "?"
            print(f"[{mark}] {p.name:24s} {ver:16s} {p.description}")
    missing = [p.name for p in result if p.required and not p.available]
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(_main())
