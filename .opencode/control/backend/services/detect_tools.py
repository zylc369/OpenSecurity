"""外部工具 + 编译器检测/自动安装收口模块（ToolsScanner / ToolsInstaller + 强类型状态）。

其他模块禁止直接 shutil.which 检测工具（grep 唯一性，本模块是工具检测的唯一入口）。

双模式（与 detect_py_deps.py 一致）：
  • CLI: python detect_tools.py <scan|install|list-installable> [options]
  • import: from services import detect_tools → detect_tools.install_all() 等

注意：
  • IDA_PRO_HOME 通过 config_store 读（配置收口）
  • 其他工具（apktool/jadx 等）通过 shutil.which 检测 PATH，未命中回落 BIN_DIR
  • 自动安装产物落 ~/bw-security-analysis/bin（插件注入 PATH）/ tools/（源码与 jar）
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

# CLI 直跑自举（detect_py_deps.py 同模式）: 把 backend 目录加 sys.path 使 services 可见
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import config_store  # noqa: E402 —— 自举后可见

# 安装目录（与 detect_py_deps.CACHE_DIR 同值；刻意本地定义不 import，避免服务模块间耦合）
CACHE_DIR = os.path.expanduser("~/bw-security-analysis")
BIN_DIR = os.path.join(CACHE_DIR, "bin")        # 二进制 + wrapper（插件注入 PATH）
TOOLS_SRC_DIR = os.path.join(CACHE_DIR, "tools")  # git clone / jar 存放


def _plat_key() -> str:
    """当前平台键: darwin-arm64 / darwin-amd64 / linux-arm64 / linux-amd64 / win-amd64。"""
    mach = platform.machine().lower()
    arch = "arm64" if mach in ("arm64", "aarch64") else "amd64"
    syst = {"darwin": "darwin", "linux": "linux", "windows": "win"}.get(
        platform.system().lower(), platform.system().lower())
    return f"{syst}-{arch}"


@dataclass
class ToolField:
    """工具元数据。"""
    name: str                                          # 工具标识名（ida_pro / apktool / ...）
    agents: list[str]                                  # 使用此工具的 agent 列表
    required: bool = True                              # 是否必需
    description: str = ""
    install_hint: str = ""                             # 通用安装提示
    platform_install_hint: dict[str, str] = field(default_factory=dict)  # 按 OS 的安装提示
    platforms: list[str] = field(default_factory=list)  # 适用平台（空=全平台）
    version_cmd: list[str] = field(default_factory=list)  # 版本检测命令
    # env_var 模式（仅 ida_pro 用）：从配置读路径，拼接 executable
    env_var: str = ""                                  # 配置 key（如 IDA_PRO_HOME）
    executable: str = ""                               # env_var 模式下的可执行文件名


@dataclass
class ToolStatus:
    """单个工具的检测状态。"""
    name: str
    description: str
    required: bool
    available: bool
    skipped: bool                # 当前平台不适用
    version: str | None
    path: str | None
    install_hint: str

    @classmethod
    def timeout(cls, tool: ToolField, hint: str) -> "ToolStatus":
        """检测超时的占位结果（available=False，不阻塞整体）。"""
        return cls(name=tool.name, description=tool.description, required=tool.required,
                   available=False, skipped=False, version=None, path=None,
                   install_hint=hint)

    @classmethod
    def skipped_platform(cls, tool: ToolField, hint: str) -> "ToolStatus":
        """平台不适用的占位结果。"""
        return cls(name=tool.name, description=tool.description, required=tool.required,
                   available=False, skipped=True, version=None, path=None,
                   install_hint=hint)


@dataclass
class CompilerInfo:
    """C/C++ 编译器检测结果（pip 安装 C 扩展需要）。"""
    available: bool
    type: str | None              # clang / gcc / msvc
    path: str | None
    vcvarsall: str | None         # 仅 MSVC

    @classmethod
    def unavailable(cls) -> "CompilerInfo":
        return cls(available=False, type=None, path=None, vcvarsall=None)


# ─── 自动安装配方（强类型 manifest） ─────────────────────
# plats 值: 逗号分隔关键词，每个关键词按正则（忽略大小写）匹配资产名，全部命中才选中;
#           关键词支持 | alternation（如 "macos|darwin"）。
# 通用排除词（不选中的资产）: checksums / .sig / 386 / freebsd / signed / sbom


@dataclass
class ReleaseRecipe:
    """GitHub Releases 下载配方。kind: single(归档→提取 bins) / raw(资产即二进制) / jar / tree(整树解压+wrapper)。"""
    name: str
    repo: str                       # owner/repo
    kind: str = "single"
    plats: dict[str, str] = field(default_factory=dict)
    bins: list[str] = field(default_factory=list)   # single/raw: 提取的产物名; tree: wrapper 入口
    entry: str = ""                 # tree kind: 解压后入口脚本相对路径
    jar_kw: str = "jar"             # jar kind: 资产匹配关键词
    prereq: str = ""                # "java": 需 java 运行时
    excl: str = ""                  # 额外排除关键词（逗号分隔）
    src_names: dict[str, str] = field(default_factory=dict)  # bin名 → 归档内实际文件名


@dataclass
class GitRecipe:
    """git clone 配方（python/bash 单文件工具）。"""
    name: str
    repo: str                       # owner/repo（https://github.com/ 前缀自动拼）
    entry: str                      # 入口脚本相对路径
    py: bool = True                 # True=python 入口; False=bash 入口
    req: str = ""                   # 入口依赖 requirements 文件相对路径（空=无）
    module: str = ""                # 非空=包布局（wrapper: cd 克隆目录 && python -m <module>）
    envp: str = ""                  # module 模式下额外 PYTHONPATH 相对路径（如 src-layout 的 src）
    pip_pkg: bool = False           # True=克隆后 pip install <目录>（依赖+console script 落 venv bin）


@dataclass
class UrlRecipe:
    """直链下载配方（非 GitHub 源，如 ffmpeg 静态构建）。"""
    name: str
    urls: dict[str, str] = field(default_factory=dict)  # 平台键 → 直链
    bins: list[str] = field(default_factory=list)       # 归档内提取产物


@dataclass
class DockerRecipe:
    """容器工具配方（调研见 knowledge-base/docker-toolbox.md）。

    wrapper 落 BIN_DIR: docker run（entrypoint 降权/卷挂载/路径重写/trap 防孤儿容器）。
    多工具共享镜像: image 相同的 recipe 只 build 一次（image_exists 幂等）。
    """
    name: str                        # 工具名（=容器内命令名）
    image: str                       # opensecurity/toolbox-core|full
    dockerfile: str = ""             # 相对 OPENCODE_ROOT 的 Dockerfile 路径（build 用）
    net_host: bool = False           # True: --network host（仅 Linux 宿主有意义）
    long_running: bool = False       # True: 长任务——wrapper 必须收到 --wrapper-timeout 才运行
    extra_args: list[str] = field(default_factory=list)  # 追加 docker run 参数


@dataclass
class InstallResult:
    """单个工具安装结果。"""
    name: str
    status: str                     # installed / skipped / failed
    detail: str = ""


# 平台关键词缩写（PD 系/常规 go 项目通用形态）
_GO_ALL = {
    "darwin-arm64": "macos|darwin,arm64|aarch64",
    "darwin-amd64": "macos|darwin,amd64|x86_64",
    "linux-arm64": "linux,arm64|aarch64",
    "linux-amd64": "linux,amd64|x86_64",
    "win-amd64": "windows|win,amd64|x86_64|win64|x64",
}

INSTALLABLE_TOOLS: list[ReleaseRecipe | GitRecipe | UrlRecipe | DockerRecipe] = [
    # ── Web 扫描（go 单二进制） ──
    ReleaseRecipe(name="nuclei", repo="projectdiscovery/nuclei", plats=_GO_ALL, bins=["nuclei"]),
    ReleaseRecipe(name="dalfox", repo="hahwul/dalfox", plats=_GO_ALL, bins=["dalfox"]),
    ReleaseRecipe(name="ffuf", repo="ffuf/ffuf", plats=_GO_ALL, bins=["ffuf"]),
    ReleaseRecipe(name="gobuster", repo="OJ/gobuster", plats=_GO_ALL, bins=["gobuster"]),
    ReleaseRecipe(name="gau", repo="lc/gau", plats=_GO_ALL, bins=["gau"]),
    ReleaseRecipe(name="feroxbuster", repo="epi052/feroxbuster", plats={
        "darwin-arm64": "macos,arm64|aarch64", "darwin-amd64": "macos,x86_64|amd64",
        "linux-arm64": "linux,arm64|aarch64", "linux-amd64": "linux,x86_64|amd64",
        "win-amd64": "windows|win,x64|amd64|x86_64"}, bins=["feroxbuster"]),
    ReleaseRecipe(name="subfinder", repo="projectdiscovery/subfinder", plats=_GO_ALL, bins=["subfinder"]),
    ReleaseRecipe(name="httpx", repo="projectdiscovery/httpx", plats=_GO_ALL, bins=["httpx"]),
    ReleaseRecipe(name="katana", repo="projectdiscovery/katana", plats=_GO_ALL, bins=["katana"]),
    ReleaseRecipe(name="naabu", repo="projectdiscovery/naabu", plats=_GO_ALL, bins=["naabu"]),
    ReleaseRecipe(name="dnsx", repo="projectdiscovery/dnsx", plats=_GO_ALL, bins=["dnsx"]),
    ReleaseRecipe(name="tlsx", repo="projectdiscovery/tlsx", plats=_GO_ALL, bins=["tlsx"]),
    # ── 隧道 / 内网（go） ──
    ReleaseRecipe(name="chisel", repo="jpillora/chisel", plats=_GO_ALL, bins=["chisel"]),
    ReleaseRecipe(name="ligolo-ng", repo="nicocha30/ligolo-ng", plats=_GO_ALL,
                  bins=["ligolo-ng"], src_names={"ligolo-ng": "agent"}),
    ReleaseRecipe(name="ligolo-proxy", repo="nicocha30/ligolo-ng", plats=_GO_ALL,
                  bins=["ligolo-proxy"], src_names={"ligolo-proxy": "proxy"}),
    ReleaseRecipe(name="frpc", repo="fatedier/frp", plats=_GO_ALL, bins=["frpc"]),
    ReleaseRecipe(name="frps", repo="fatedier/frp", plats=_GO_ALL, bins=["frps"]),
    # ── 逆向 / 隐写（C++/Rust 单二进制） ──
    ReleaseRecipe(name="bkcrack", repo="kimci86/bkcrack", plats=_GO_ALL, bins=["bkcrack"]),
    ReleaseRecipe(name="wabt", repo="WebAssembly/wabt", plats=_GO_ALL,
                  bins=["wasm-objdump", "wasm2c", "wat2wasm", "wasm-decompile"]),
    # ── Java（需 java 运行时） ──
    ReleaseRecipe(name="ysoserial", repo="frohoff/ysoserial", kind="jar", prereq="java", bins=["ysoserial"]),
    ReleaseRecipe(name="apktool", repo="iBotPeaches/apktool", kind="jar", prereq="java", bins=["apktool"]),
    ReleaseRecipe(name="jadx", repo="skylot/jadx", kind="tree", prereq="java",
                  entry="bin/jadx", excl="gui,win,with-jre", bins=["jadx"]),
    # ── git python/bash 单文件工具 ──
    GitRecipe(name="rsactftool", repo="RsaCtfTool/RsaCtfTool", entry="src/RsaCtfTool/__main__.py", req="requirements.txt", module="RsaCtfTool", envp="src"),
    GitRecipe(name="wesng", repo="bitsadmin/wesng", entry="wes.py"),
    GitRecipe(name="windapsearch", repo="ropnop/windapsearch", entry="windapsearch.py", req="requirements.txt"),
    GitRecipe(name="regeorg", repo="sensepost/reGeorg", entry="reGeorgSocksProxy.py"),
    GitRecipe(name="redis-rogue-server", repo="n0b0dyCN/redis-rogue-server", entry="redis-rogue-server.py"),
    GitRecipe(name="pyinstxtractor", repo="extremecoders-re/pyinstxtractor", entry="pyinstxtractor.py"),
    GitRecipe(name="pyarmor-1shot", repo="Lil-House/Pyarmor-Static-Unpack-1shot", entry="oneshot/shot.py"),
    GitRecipe(name="ajpshooter", repo="00theway/Ghostcat-CNVD-2020-10487", entry="ajpShooter.py"),
    GitRecipe(name="libcsearcher", repo="lieanu/LibcSearcher", entry="libcsearcher.py"),
    GitRecipe(name="ccupp", repo="WangYihang/ccupp", entry="pyproject.toml", pip_pkg=True),
    # ── 直链（非 GitHub 源） ──
    UrlRecipe(name="ffmpeg", urls={
        "linux-amd64": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
        "win-amd64": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    }, bins=["ffmpeg", "ffprobe"]),
    # ── 容器层（编译类; docker-toolbox.md §3.1 实测清单） ──
    DockerRecipe(name="steghide", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="stegseek", image="opensecurity/toolbox-core", long_running=True,
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="john", image="opensecurity/toolbox-core", long_running=True,
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="hashcat", image="opensecurity/toolbox-core", long_running=True,
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="nmap", image="opensecurity/toolbox-core", long_running=True,
                 dockerfile="control/docker/toolbox-core.Dockerfile", net_host=True),
    DockerRecipe(name="hydra", image="opensecurity/toolbox-core", long_running=True,
                 dockerfile="control/docker/toolbox-core.Dockerfile", net_host=True),
    DockerRecipe(name="medusa", image="opensecurity/toolbox-core", long_running=True,
                 dockerfile="control/docker/toolbox-core.Dockerfile", net_host=True),
    DockerRecipe(name="ncrack", image="opensecurity/toolbox-core", long_running=True,
                 dockerfile="control/docker/toolbox-core.Dockerfile", net_host=True),
    DockerRecipe(name="binwalk-full", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="nxc", image="opensecurity/toolbox-core", long_running=True,
                 dockerfile="control/docker/toolbox-core.Dockerfile", net_host=True),
    DockerRecipe(name="searchsploit", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="wpscan", image="opensecurity/toolbox-core", long_running=True,
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="fls", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="icat", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="istat", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="tshark", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="exiftool", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="x86_64-w64-mingw32-gcc", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="nasm", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="r2", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="one_gadget", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="seccomp-tools", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="phpggc", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="qemu-gdb", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="sox", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="identify", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="convert", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="mutool", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="boolector", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="qemu-system-x86_64", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="wrestool", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="pcapfix", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="xfs_db", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="cryptsetup", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="zsteg", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="arpspoof", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile", net_host=True),
    DockerRecipe(name="gdb", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="gdb-pwndbg", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="gdbserver", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="e2fsck", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="e2fsck64", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="debugfs", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="mkfs.ext4", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="btrfs", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="qemu-riscv64", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="upx", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="smtp-user-enum", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="marshalsec", image="opensecurity/toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    DockerRecipe(name="ghidra-headless", image="opensecurity/toolbox-full",
                 dockerfile="control/docker/toolbox-full.Dockerfile"),
    DockerRecipe(name="msfvenom", image="opensecurity/toolbox-full",
                 dockerfile="control/docker/toolbox-full.Dockerfile"),
]


# ─── 工具清单 ────────────────────────────────────────────
EXTERNAL_TOOLS: list[ToolField] = [
    ToolField(
        name="ida_pro",
        agents=["binary-analysis", "mobile-analysis", "crypto-analysis", "web-analysis"],
        required=True,
        description="反汇编/反编译平台（付费）",
        env_var="IDA_PRO_HOME",
        executable="idat",
        install_hint=(
            "IDA Pro 未检测到。解决方式：\n"
            "  1. 在控制台配置页设置 IDA_PRO_HOME（IDA Pro 安装目录）：\n"
            "     IDA_PRO_HOME=/Applications/IDA Professional 9.1.app/Contents/MacOS\n"
            "  2. 或修改 .opencode/.ai_env"
        ),
    ),
    ToolField(
        name="apktool",
        agents=["mobile-analysis"],
        required=True,
        version_cmd=["--version"],
        description="APK 解包+反汇编工具",
        install_hint="apktool 未找到。安装: brew install apktool (macOS)",
        platform_install_hint={
            "darwin": "brew install apktool",
            "linux":  "sudo apt install apktool 或从 https://ibotpeaches.github.io/Apktool/install/ 下载",
            "win32": "从 https://ibotpeaches.github.io/Apktool/install/ 下载（需要 Java）",
        },
    ),
    ToolField(
        name="jadx",
        agents=["mobile-analysis"],
        required=True,
        version_cmd=["--version"],
        description="DEX→Java 反编译器",
        install_hint="jadx 未找到。安装: brew install jadx (macOS)",
        platform_install_hint={
            "darwin": "brew install jadx",
            "linux":  "从 https://github.com/skylot/jadx/releases 下载最新 release zip",
            "win32": "从 https://github.com/skylot/jadx/releases 下载最新 release zip",
        },
    ),
    ToolField(
        name="adb",
        agents=["mobile-analysis"],
        required=True,
        version_cmd=["version"],
        description="Android Debug Bridge",
        install_hint="adb 未找到。安装: brew install --cask android-platform-tools (macOS)",
        platform_install_hint={
            "darwin": "brew install --cask android-platform-tools",
            "linux":  "sudo apt install adb",
            "win32": "从 https://developer.android.com/tools/releases/platform-tools 下载",
        },
    ),
    ToolField(
        name="otool",
        agents=["mobile-analysis"],
        required=False,
        description="Mach-O 文件查看器（macOS 自带）",
        install_hint="otool 未找到（macOS 自带，非 macOS 无需配置）",
        platforms=["darwin"],
    ),
    ToolField(
        name="ldid",
        agents=["mobile-analysis"],
        required=False,
        description="iOS 伪签名工具",
        install_hint="ldid 未找到。安装: brew install ldid (macOS)",
        platforms=["darwin"],
    ),
    ToolField(
        name="GoReSym",
        agents=["binary-analysis", "crypto-analysis"],
        required=False,
        description="Go 符号恢复工具",
        install_hint="GoReSym 未找到。参考 https://github.com/mandiant/GoReSym",
        platform_install_hint={
            "darwin": "从 https://github.com/mandiant/GoReSym/releases 下载 darwin 版本",
            "linux":  "从 https://github.com/mandiant/GoReSym/releases 下载 linux 版本",
            "win32": "从 https://github.com/mandiant/GoReSym/releases 下载 windows 版本",
        },
    ),
]

# ── 自动安装层工具（INSTALLABLE_TOOLS 覆盖; 安装方式 = install.sh / detect_tools.py install） ──
_AUTO_HINT = "自动安装: bash .opencode/install.sh 或 python control/backend/services/detect_tools.py install --tool {name}"
_WEB = ["web-analysis"]
_BIN = ["binary-analysis"]


def _auto(name: str, agents: list[str], desc: str, ver: list[str] | None = None) -> ToolField:
    return ToolField(name=name, agents=agents, required=False, description=desc,
                     version_cmd=ver or [], install_hint=_AUTO_HINT.format(name=name))


EXTERNAL_TOOLS.extend([
    _auto("nuclei", _WEB, "漏洞模板扫描（模板引擎+社区库）", ["-version"]),
    _auto("dalfox", _WEB, "XSS 专项扫描", ["-V"]),
    _auto("ffuf", _WEB, "web fuzz（多位置/过滤）", ["-V"]),
    _auto("gobuster", _WEB, "目录/子域爆破", ["--version"]),
    _auto("gau", _WEB, "历史 URL 拉取（wayback 等三源）"),
    _auto("feroxbuster", _WEB, "递归目录爆破"),
    _auto("subfinder", _WEB, "子域发现（被动聚合）"),
    _auto("httpx", _WEB, "存活探测/技术栈指纹"),
    _auto("katana", _WEB, "爬虫（含 JS 端点解析）"),
    _auto("naabu", _WEB, "端口扫描（SYN/CONNECT）"),
    _auto("dnsx", _WEB, "DNS 查询/反解/通配符过滤"),
    _auto("tlsx", _WEB, "TLS 证书 SAN 挖子域/JARM"),
    _auto("chisel", _BIN, "tcp/udp 隧道（http 双向）"),
    _auto("ligolo-ng", _BIN, "透明反向隧道（agent）"),
    _auto("ligolo-proxy", _BIN, "透明反向隧道（proxy 端）"),
    _auto("frpc", _BIN, "内网穿透客户端"),
    _auto("frps", _BIN, "内网穿透服务端"),
    _auto("bkcrack", _BIN, "ZIP 明文攻击"),
    _auto("e2fsck", _BIN, "ext2/3/4 文件系统检查修复"),
    _auto("e2fsck64", _BIN, "ext 文件系统检查（64bit 卷）"),
    _auto("debugfs", _BIN, "ext 文件系统底层编辑（删文件恢复/查 inode）"),
    _auto("mkfs.ext4", _BIN, "创建 ext4 镜像"),
    _auto("btrfs", _BIN, "btrfs 文件系统检查（subvolume/快照）"),
    _auto("qemu-riscv64", _BIN, "riscv64 ELF 用户态模拟运行"),
    _auto("upx", _BIN, "UPX 脱壳（upx -d）", ["--version"]),
    _auto("wasm-objdump", _BIN, "WASM 反汇编（wabt 套件）"),
    _auto("ysoserial", _WEB, "Java 反序列化 gadget 链生成（需 java）"),
    _auto("rsactftool", _BIN, "RSA 攻击聚合"),
    _auto("wesng", _BIN, "Windows 补丁缺失比对"),
    _auto("windapsearch", _BIN, "LDAP/AD 枚举"),
    _auto("regeorg", _BIN, "webshell 隧道（SOCKS）"),
    _auto("ffmpeg", _BIN, "音视频处理（隐写频谱/帧提取）"),
    _auto("ffprobe", _BIN, "音视频流/元数据分析"),
    _auto("steghide", _BIN, "JPEG/BMP 隐写（容器）"),
    _auto("stegseek", _BIN, "steghide 高速爆破（容器+rockyou）"),
    _auto("hashcat", _BIN, "哈希破解（容器 PoCL CPU 模式）", ["-I"]),
    _auto("nmap", _WEB + _BIN, "端口/服务扫描（容器; SYN 可用）"),
    _auto("hydra", _WEB + _BIN, "多协议爆破（容器）"),
    _auto("medusa", _WEB + _BIN, "多协议爆破第二实现（容器）"),
    _auto("ncrack", _WEB + _BIN, "网络服务爆破（容器）"),
    _auto("binwalk-full", _BIN, "binwalk 完整版（容器; magic 提取全功能）"),
    _auto("nxc", _BIN, "NetExec 内网批量执行（容器）", ["--version"]),
    _auto("searchsploit", _WEB, "exploit-db 离线检索（容器）"),
    _auto("wpscan", _WEB, "WordPress 扫描（容器，DB 预热）"),
    _auto("tshark", _BIN, "pcap 深度解析（容器）"),
    _auto("exiftool", _BIN, "元数据读写（容器）"),
    _auto("one_gadget", _BIN, "libc execve gadget 搜索（容器+multiarch）"),
    _auto("seccomp-tools", _BIN, "seccomp BPF 反汇编（容器）"),
    _auto("phpggc", _WEB, "PHP 反序列化链生成（容器）"),
    _auto("qemu-gdb", _BIN, "跨架构 gdb 调试（qemu gdbstub 模式）"),
    _auto("sox", _BIN, "音频处理/频谱图（容器）"),
    _auto("identify", _BIN, "图像信息/逐帧 delay（容器）"),
    _auto("convert", _BIN, "图像变换/拼接（容器）"),
    _auto("mutool", _BIN, "PDF 页渲染/解压（容器）"),
    _auto("boolector", _BIN, "SMT QF_BV 求解器（容器; angr/claripy 可切）"),
    _auto("qemu-system-x86_64", _BIN, "x86 全系统模拟（容器; 内核题启动）"),
    _auto("wrestool", _BIN, "PE 资源提取（容器）"),
    _auto("pcapfix", _BIN, "pcap 头修复（容器）"),
    _auto("xfs_db", _BIN, "xfs 文件系统检查（容器）"),
    _auto("cryptsetup", _BIN, "LUKS 容器处理（容器）"),
    _auto("zsteg", _BIN, "PNG/BMP LSB 隐写检测（容器）"),
    _auto("arpspoof", _BIN, "ARP 欺骗（容器; macOS 无 LAN L2 实际受限，Linux 宿主可用）"),
    _auto("gdb", _BIN, "arm64 ELF 原生调试（容器; amd64 走 qemu-gdb）"),
    _auto("gdb-pwndbg", _BIN, "带 pwndbg 的 gdb（堆调试: heap/vis_heap_chunks/tcache）"),
    _auto("gdbserver", _BIN, "远程调试服务端（容器）"),
    _auto("smtp-user-enum", _WEB + _BIN, "SMTP 用户枚举（VRFY/EXPN/RCPT）"),
    _auto("marshalsec", _BIN, "Java 反序列化链生成（容器, JDK21 编译）"),
    _auto("ghidra-headless", _BIN, "Ghidra 无头分析（full 层容器）"),
    _auto("msfvenom", _BIN, "payload 生成器（full 层容器）"),
])


class ToolsScanner:
    """外部工具 + 编译器扫描器。

    scan_all_parallel：全量并行扫描一次返回 {name: ToolStatus}
    （version 子进程并发，总耗时 = 最慢单项）；scan_agent/scan_all
    从总表按归属过滤，消掉多 agent 重复扫描。
    """

    PARALLEL_TIMEOUT_SEC = 15.0

    def scan_tool(self, tool: ToolField) -> ToolStatus:
        """扫描单个工具。"""
        if not self._platform_matches(tool):
            return ToolStatus.skipped_platform(tool, self.install_hint(tool))
        path, found = self.resolve_tool_path(tool)
        version = self.tool_version(path, tool.version_cmd) if found else None
        return ToolStatus(
            name=tool.name, description=tool.description, required=tool.required,
            available=found, skipped=False, version=version,
            path=path if found else None, install_hint=self.install_hint(tool),
        )

    def scan_all_parallel(self, timeout_sec: float | None = None) -> dict[str, ToolStatus]:
        """全量工具并行扫描：{tool_name: ToolStatus}。

        每个工具一个线程；version_cmd 子进程并发执行。
        整体超时的工具返回 timeout 占位（不阻塞整体返回）——
        tool_version 内部 subprocess 已有 10s 兜底，此处是第二道闸。
        """
        timeout_sec = timeout_sec or self.PARALLEL_TIMEOUT_SEC
        tools = [t for t in EXTERNAL_TOOLS if self._platform_matches(t)]
        results: dict[str, ToolStatus] = {
            t.name: ToolStatus.timeout(t, self.install_hint(t)) for t in tools
        }
        with ThreadPoolExecutor(max_workers=len(tools) or 1) as ex:
            futs = [ex.submit(self.scan_tool, t) for t in tools]
            try:
                for fut in as_completed(futs, timeout=timeout_sec):
                    status = fut.result()
                    results[status.name] = status
            except TimeoutError:
                pass  # 未完成的保留超时占位
        return results

    def scan_agent(self, agent_name: str) -> list[ToolStatus]:
        """指定 agent 的工具状态（总表过滤）。"""
        table = self.scan_all_parallel()
        return [table[t.name] for t in EXTERNAL_TOOLS
                if self._agent_has_tool(t, agent_name) and self._platform_matches(t)]

    def scan_all(self) -> dict[str, list[ToolStatus]]:
        """所有 agent 的工具状态：{agent_name: [ToolStatus, ...]}。"""
        table = self.scan_all_parallel()
        all_agents: set[str] = set()
        for t in EXTERNAL_TOOLS:
            all_agents.update(t.agents)
        return {
            agent: [table[t.name] for t in EXTERNAL_TOOLS
                    if self._agent_has_tool(t, agent) and self._platform_matches(t)]
            for agent in sorted(all_agents)
        }

    # ─── 编译器 ───────────────────────────────────────────

    def detect_compiler(self) -> CompilerInfo:
        """检测 C/C++ 编译器：Windows MSVC→gcc 降级 / macOS clang→gcc / Linux gcc。"""
        system = platform.system()
        if system == "Windows":
            msvc = self._detect_msvc()
            return msvc if msvc.available else self._detect_gcc_windows()
        if system == "Darwin":
            clang = self._detect_clang_macos()
            return clang if clang.available else self._detect_gcc_unix()
        return self._detect_gcc_unix()

    def _detect_msvc(self) -> CompilerInfo:
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
                        cl = self._find_exe(os.path.join(vs_path, "VC", "Tools", "MSVC"), "cl.exe")
                        if not cl:
                            cl = self._find_exe(vs_path, "cl.exe")
                        return CompilerInfo(True, "msvc", cl, vcvarsall)
            except (subprocess.TimeoutExpired, OSError):
                pass
        pfx86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        vs_dir = os.path.join(pfx86, "Microsoft Visual Studio")
        if os.path.isdir(vs_dir):
            for ver_dir in self._safe_listdir(vs_dir):
                for ed_dir in self._safe_listdir(os.path.join(vs_dir, ver_dir)):
                    ed_path = os.path.join(vs_dir, ver_dir, ed_dir)
                    vcvarsall = os.path.join(ed_path, "VC", "Auxiliary", "Build", "vcvarsall.bat")
                    if os.path.isfile(vcvarsall):
                        cl = self._find_exe(os.path.join(ed_path, "VC", "Tools", "MSVC"), "cl.exe")
                        if not cl:
                            cl = self._find_exe(ed_path, "cl.exe")
                        return CompilerInfo(True, "msvc", cl, vcvarsall)
        return CompilerInfo.unavailable()

    def _detect_gcc_windows(self) -> CompilerInfo:
        for name in ["gcc.exe", "g++.exe", "clang.exe"]:
            p = shutil.which(name)
            if p:
                return CompilerInfo(True, "gcc", p, None)
        return CompilerInfo.unavailable()

    def _detect_clang_macos(self) -> CompilerInfo:
        p = shutil.which("clang")
        return CompilerInfo(True, "clang", p, None) if p else CompilerInfo.unavailable()

    def _detect_gcc_unix(self) -> CompilerInfo:
        for name in ["gcc", "g++", "cc"]:
            p = shutil.which(name)
            if p:
                return CompilerInfo(True, "gcc", p, None)
        return CompilerInfo.unavailable()

    # ─── 内部 ─────────────────────────────────────────────

    @staticmethod
    def _platform_matches(tool: ToolField) -> bool:
        return not tool.platforms or sys.platform in tool.platforms

    @staticmethod
    def _agent_has_tool(tool: ToolField, agent: str) -> bool:
        return agent in tool.agents

    def install_hint(self, tool: ToolField) -> str:
        """当前 OS 的安装提示：platform_install_hint[sys.platform] 降级 install_hint。"""
        if tool.platform_install_hint:
            hint = tool.platform_install_hint.get(sys.platform)
            if hint:
                return hint
        return tool.install_hint or f"{tool.name} 未安装，请参考官方文档"

    def resolve_tool_path(self, tool: ToolField) -> tuple[str, bool]:
        """解析工具路径：env_var 模式（config_store 读）或 PATH which。"""
        if tool.env_var:
            home = config_store.read(tool.env_var) or ""
            if home:
                exe = tool.executable
                if os.name == "nt" and exe and not exe.endswith(".exe"):
                    exe += ".exe"
                cand = os.path.join(home, exe)
                if exe and os.path.isfile(cand):
                    return cand, True
            return "", False
        resolved = shutil.which(tool.name)
        if resolved:
            return resolved, True
        # 回落: BIN_DIR 安装的二进制/wrapper（后端进程无插件注入的 PATH，需显式查）
        bin_cand = os.path.join(BIN_DIR, tool.name + (".exe" if os.name == "nt" else ""))
        if os.path.isfile(bin_cand):
            return bin_cand, True
        return (tool.name, False)

    @staticmethod
    def tool_version(resolved_path: str, version_cmd: list[str]) -> str | None:
        """执行 version_cmd 获取版本字符串。空命令返回 None。"""
        if not version_cmd:
            return None
        try:
            r = subprocess.run(
                [resolved_path] + version_cmd,
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                raw = (r.stdout.strip() or r.stderr.strip()).split("\n")[0]
                import re as _re
                return _re.sub(r"\x1b\[[0-9;]*m", "", raw).strip() or None
        except (subprocess.TimeoutExpired, OSError):
            return None
        return None

    @staticmethod
    def _safe_listdir(path: str) -> list[str]:
        try:
            return [d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]
        except OSError:
            return []

    @staticmethod
    def _find_exe(base_dir: str, filename: str) -> str | None:
        if not os.path.isdir(base_dir):
            return None
        for root, _dirs, files in os.walk(base_dir):
            for f in files:
                if f.lower() == filename.lower():
                    return os.path.join(root, f)
        return None


# ─── 自动安装器 ──────────────────────────────────────────

_COMMON_EXCL = ["checksums", ".sig", "386", "freebsd", "signed", "sbom", ".dmg", "label"]
_GH_API = "https://api.github.com/repos/{repo}/releases/latest"
_GH_DL = "https://github.com/{repo}/releases/download/{tag}/{asset}"
_UA = {"User-Agent": "OpenSecurity-installer"}


class ToolsInstaller:
    """INSTALLABLE_TOOLS 清单的安装器（幂等; 单工具失败不中断整体）。

    产物布局: 二进制 → BIN_DIR; jar/克隆源码 → TOOLS_SRC_DIR/<name>/ + BIN_DIR wrapper。
    幂等: PATH 已有同名命令 或 BIN_DIR 产物齐全 → 跳过（--force 重装）。
    """

    TIMEOUT = 120  # 单请求超时（秒）——大文件下载分块流式写

    # wrapper 模板（占位 {NAME}/{IMAGE}/{NET}/{EXTRA}——shell 的 ${...} 不冲突）
    _WRAPPER_TMPL = r"""#!/bin/sh
# Docker wrapper (auto-generated): {NAME} -> {IMAGE}
DIR="$(pwd)"; NAME="{NAME}-$$-$RANDOM$RANDOM"
# 参数中 $DIR 前缀绝对路径 → /work（容器视角）
ARGS=""; for a in "$@"; do ARGS="$ARGS $(printf %s "$a" | sed "s|^$DIR|/work|")"; done

# ── 超时策略（长短任务分流）──
# 短任务: 固定 1800s（30 分钟）; 长任务({LONGRUN}): 必须显式传 --wrapper-timeout <秒>
# --wrapper-timeout 由 wrapper 消费，不会透传给容器内命令（避免非法参数报错）
CTIMEOUT=1800
WT=""
NEW_ARGS=""
for a in "$@"; do
  if [ -n "$WT" ]; then CTIMEOUT="$a"; WT=""; continue; fi
  case "$a" in
    --wrapper-timeout) WT=1; EXPLICIT_WT=1 ;;
    -w|-w[0-9]*) HAS_W=1; NEW_ARGS="$NEW_ARGS $(printf %s "$a" | sed "s|^$DIR|/work|")" ;;
    --workload-profile) HAS_W=1; NEW_ARGS="$NEW_ARGS $a" ;;
    *) NEW_ARGS="$NEW_ARGS $(printf %s "$a" | sed "s|^$DIR|/work|")" ;;
  esac
done
{W3CHECK}
ARGS="$NEW_ARGS"
{LONGCHECK}
trap 'docker kill "$NAME" 2>/dev/null' EXIT INT TERM
WL="$HOME/bw-security-analysis/wordlists"
[ -d "$WL" ] || WL=""
WL_ARG=""; [ -n "$WL" ] && WL_ARG="-v $WL:/usr/share/wordlists-host:ro"
# 容器内 timeout: 容器 1 号进程到时必死 → 容器退出 → --rm 生效（wrapper 被 SIGKILL 也不失联堆积）
# 注: timeout 必须是 shell 子进程——entrypoint 的 env-exec 链下 "exec timeout" 形态有 coreutils bug
{HASHCAT_ENV}exec docker run --rm -i --name "$NAME" {NET}{EXTRA} $HC_ENV \
  -e PUID=$(id -u) -e PGID=$(id -g) \
  -v "$DIR":/work $WL_ARG -w /work \
  {IMAGE} sh -c "timeout \"$CTIMEOUT\" {NAME} \"\$@\"" _ $ARGS
"""

    _QEMU_TMPL = r"""#!/bin/sh
# 跨架构 gdb 调试 wrapper (auto-generated; docker-toolbox.md §4)
# 用法: qemu-gdb <binary> [gdb 参数...]  例: qemu-gdb ./pwn -ex "break main" -ex c
# 架构路由: arm64 ELF（容器同架构）→ gdb 直接调（ptrace 原生可用）
#           amd64 ELF → qemu gdbstub（binfmt 下 ptrace 失效的唯一可行模式; 动态自动 -L sysroot）
BIN="${1:-./a.out}"; shift
case "$BIN" in /*) ;; *) BIN="./$BIN" ;; esac
DIR="$(pwd)"; NAME="qemu-gdb-srv-$$"; PROBE="qemu-gdb-probe-$$"
trap 'docker kill "$NAME" 2>/dev/null' EXIT INT TERM
FILEOUT=$(docker run --rm --name "$PROBE" -e PUID=$(id -u) -e PGID=$(id -g) -v "$DIR":/work -w /work {IMAGE} sh -c "file $BIN")
ARCH=$(echo "$FILEOUT" | grep -oE 'x86-64|aarch64|ARM' | head -1)
if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "ARM" ]; then
  # 同架构: gdb 直接运行被调程序（容器内原生 ptrace）
  exec docker run --rm -i -e PUID=$(id -u) -e PGID=$(id -g) \
    -v "$DIR":/work -w /work {IMAGE} \
    gdb-multiarch -q "$BIN" "$@"
fi
# amd64: qemu gdbstub 模式（静态直跑; 动态 -L sysroot）
PORT=$((20000 + RANDOM % 20000))
LARG=""
echo "$FILEOUT" | grep -q "statically" || LARG="-L /usr/x86_64-linux-gnu"
docker run -d --rm --name "$NAME" -e PUID=$(id -u) -e PGID=$(id -g) \
  -v "$DIR":/work -w /work {IMAGE} \
  qemu-x86_64 $LARG -g $PORT "$BIN" >/dev/null
sleep 1
docker run --rm -i -e PUID=$(id -u) -e PGID=$(id -g) \
  -v "$DIR":/work -w /work --network "container:$NAME" {IMAGE} \
  gdb-multiarch -q "$BIN" -ex "set sysroot /usr/x86_64-linux-gnu" -ex "target remote :$PORT" "$@"
"""

    # ── 对外入口 ──

    def install_all(self, force: bool = False, progress=None) -> list[InstallResult]:
        """按清单顺序安装全部; progress(name) 回调用于 UI 进度。"""
        results: list[InstallResult] = []
        for recipe in INSTALLABLE_TOOLS:
            if progress:
                progress(recipe.name)
            results.append(self.install_recipe(recipe, force=force))
        return results

    def install_tool(self, name: str, force: bool = False) -> InstallResult:
        """按名安装单个工具。"""
        for recipe in INSTALLABLE_TOOLS:
            if recipe.name == name:
                return self.install_recipe(recipe, force=force)
        return InstallResult(name=name, status="failed", detail="不在 INSTALLABLE_TOOLS 清单")

    def install_recipe(self, recipe, force: bool) -> InstallResult:
        """分发到各配方类型。"""
        try:
            if isinstance(recipe, ReleaseRecipe):
                return self._install_release(recipe, force)
            if isinstance(recipe, GitRecipe):
                return self._install_git(recipe, force)
            if isinstance(recipe, UrlRecipe):
                return self._install_url(recipe, force)
            if isinstance(recipe, DockerRecipe):
                return self._install_docker(recipe, force)
            return InstallResult(name=recipe.name, status="failed", detail="未知配方类型")
        except Exception as exc:  # noqa: BLE001 —— 安装器兜底: 单工具失败不中断整体
            return InstallResult(name=recipe.name, status="failed", detail=f"{type(exc).__name__}: {exc}")

    # ── 幂等判断 ──

    def _already(self, name: str, bins: list[str], force: bool) -> str | None:
        """返回跳过原因; None=需要安装。"""
        if force:
            return None
        if shutil.which(name):
            return f"PATH 已有 {name}（brew/系统安装）"
        if bins and all(os.path.exists(self._bin_path(b)) for b in bins):
            return f"{BIN_DIR} 产物已齐全"
        return None

    @staticmethod
    def _bin_path(bin_name: str) -> str:
        """BIN_DIR 产物路径（Windows 自动补 .exe）。"""
        if os.name == "nt" and not bin_name.endswith(".exe") and "." not in bin_name:
            bin_name += ".exe"
        return os.path.join(BIN_DIR, bin_name)

    # ── GitHub Releases ──

    def _install_release(self, r: ReleaseRecipe, force: bool) -> InstallResult:
        skip = self._already(r.name, r.bins, force)
        if skip:
            return InstallResult(r.name, "skipped", skip)
        if r.prereq == "java" and not shutil.which("java"):
            return InstallResult(r.name, "skipped", "需要 java 运行时（未检测到）")
        plat = _plat_key()
        if r.kind != "jar" and plat not in r.plats:
            return InstallResult(r.name, "skipped", f"平台 {plat} 无配方")
        if r.kind == "jar":
            return self._install_jar(r, force)
        assets, tag = self._gh_assets(r.repo)
        cands = self._match_assets(assets, r.plats[plat].split(","), r.excl)
        if not cands:
            return InstallResult(r.name, "failed", f"{r.repo}@{tag} 无匹配资产（plats={r.plats.get(plat)}）")
        # 同 repo 多产物（ligolo-ng/proxy 同前缀）: 逐候选试到 bins 命中
        last_err = ""
        for asset in cands:
            url = _GH_DL.format(repo=r.repo, tag=tag, asset=asset)
            if r.kind == "tree":
                return self._install_tree(r, url, asset)
            try:
                self._place_from_archive(r, self._download(url), asset)
                return InstallResult(r.name, "installed", f"{asset} → {', '.join(r.bins)}")
            except RuntimeError as exc:
                last_err = f"{asset}: {exc}"
        return InstallResult(r.name, "failed", last_err or "全部候选资产无 bins")

    def _install_jar(self, r: ReleaseRecipe, force: bool) -> InstallResult:
        assets, tag = self._gh_assets(r.repo)
        asset = self._match_assets(assets, [r.jar_kw], r.excl)[0] if self._match_assets(assets, [r.jar_kw], r.excl) else None
        if not asset:
            return InstallResult(r.name, "failed", f"{r.repo}@{tag} 无 jar 资产")
        dst_dir = os.path.join(TOOLS_SRC_DIR, r.name)
        os.makedirs(dst_dir, exist_ok=True)
        jar_path = os.path.join(dst_dir, asset)
        wrapper = os.path.join(BIN_DIR, r.name)
        if os.path.exists(jar_path) and not force:
            if not os.path.exists(wrapper):  # jar 在而 wrapper 缺 → 补 wrapper
                self._wrapper(r.name, ["java", "-jar", jar_path])
                return InstallResult(r.name, "installed", "补生成 wrapper（jar 已存在）")
            return InstallResult(r.name, "skipped", f"jar 已存在 {asset}")
        self._write(self._download(_GH_DL.format(repo=r.repo, tag=tag, asset=asset)), jar_path)
        self._wrapper(r.name, ["java", "-jar", jar_path])
        return InstallResult(r.name, "installed", f"{asset} + wrapper")

    def _install_tree(self, r: ReleaseRecipe, url: str, asset: str) -> InstallResult:
        """整归档解压到 TOOLS_SRC_DIR/<name>/，wrapper 指向 entry。"""
        dst = os.path.join(TOOLS_SRC_DIR, r.name)
        if os.path.isdir(dst) and os.path.exists(os.path.join(dst, r.entry)):
            return InstallResult(r.name, "skipped", "源码树已存在")
        data = self._download(url)
        extract_dir = tempfile.mkdtemp(prefix=f"inst-{r.name}-")
        self._extract(data, asset, extract_dir)
        # 归档可能带顶层目录 → 取包含 entry 的根
        src_root = extract_dir
        if not os.path.exists(os.path.join(src_root, r.entry)):
            for d in os.listdir(extract_dir):
                if os.path.exists(os.path.join(extract_dir, d, r.entry)):
                    src_root = os.path.join(extract_dir, d)
                    break
        if not os.path.exists(os.path.join(src_root, r.entry)):
            return InstallResult(r.name, "failed", f"归档内未找到入口 {r.entry}")
        shutil.copytree(src_root, dst, dirs_exist_ok=True)
        entry_abs = os.path.join(dst, r.entry)
        os.chmod(entry_abs, 0o755)
        self._wrapper(r.name, [entry_abs])
        return InstallResult(r.name, "installed", f"{asset} → wrapper {r.name}")

    # ── git / pip ──

    def _install_git(self, r: GitRecipe, force: bool) -> InstallResult:
        dst = os.path.join(TOOLS_SRC_DIR, r.name)
        entry_abs = os.path.join(dst, r.entry)
        if r.pip_pkg:  # 包模式: 克隆后 pip install（console script 直接落 venv bin）
            if not force and shutil.which(r.name):
                return InstallResult(r.name, "skipped", f"PATH 已有 {r.name}")
            if not os.path.isdir(dst):
                if not shutil.which("git"):
                    return InstallResult(r.name, "failed", "git 命令不存在")
                self._run(["git", "clone", "--depth", "1",
                           f"https://github.com/{r.repo}", dst])
            self._run([self._venv_python(), "-m", "pip", "install", "-q", dst])
            return InstallResult(r.name, "installed", f"clone {r.repo} + pip install")
        wrapper = os.path.join(BIN_DIR, r.name)
        if os.path.exists(entry_abs) and not force:
            if not os.path.exists(wrapper):  # 克隆在而 wrapper 缺（历史失败残留）→ 只补 wrapper
                self._install_git_wrapper(r, dst, entry_abs)
                return InstallResult(r.name, "installed", "补生成 wrapper（克隆已存在）")
            return InstallResult(r.name, "skipped", "克隆已存在")
        if not shutil.which("git"):
            return InstallResult(r.name, "failed", "git 命令不存在")
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        self._run(["git", "clone", "--depth", "1",
                   f"https://github.com/{r.repo}", dst])
        if not os.path.exists(entry_abs):
            return InstallResult(r.name, "failed", f"克隆后未找到入口 {r.entry}")
        self._install_git_wrapper(r, dst, entry_abs)
        return InstallResult(r.name, "installed", f"clone {r.repo} + wrapper")

    def _install_git_wrapper(self, r: GitRecipe, dst: str, entry_abs: str) -> None:
        """生成 wrapper（+ 可选 requirements 安装）。"""
        if r.req:  # python 依赖装进 venv
            venv_py = self._venv_python()
            self._run([venv_py, "-m", "pip", "install", "-q", "-r",
                       os.path.join(dst, r.req)])
        if r.module:
            self._wrapper(r.name, [self._venv_python(), "-m", r.module], cwd=dst, envp=r.envp)
        elif r.py:
            self._wrapper(r.name, [self._venv_python(), entry_abs])
        else:
            self._wrapper(r.name, ["bash", entry_abs])

    # ── 直链 ──

    def _install_url(self, r: UrlRecipe, force: bool) -> InstallResult:
        skip = self._already(r.name, r.bins, force)
        if skip:
            return InstallResult(r.name, "skipped", skip)
        plat = _plat_key()
        url = r.urls.get(plat)
        if not url:
            hint = "brew install ffmpeg（macOS）" if plat.startswith("darwin") else ""
            return InstallResult(r.name, "skipped", f"平台 {plat} 无直链配方{(' → ' + hint) if hint else ''}")
        asset = url.rsplit("/", 1)[-1]
        self._place_from_archive(r, self._download(url), asset)
        return InstallResult(r.name, "installed", f"{asset} → {', '.join(r.bins)}")

    # ── 容器层 ──

    def _install_docker(self, r: DockerRecipe, force: bool) -> InstallResult:
        """容器工具: docker 缺失→skip 提示; 镜像缺→build（同镜像幂等一次）; 生成 wrapper。"""
        wrapper = os.path.join(BIN_DIR, r.name)
        if not force and os.path.exists(wrapper):
            return InstallResult(r.name, "skipped", "wrapper 已存在")
        if not shutil.which("docker"):
            return InstallResult(r.name, "skipped",
                                 "docker 不存在——装 Docker Desktop/OrbStack 后重跑（docker-toolbox.md §0）")
        if not self._docker_image_exists(r.image):
            built = self._docker_build(r)
            if built.status != "installed":
                return InstallResult(r.name, "failed", f"镜像构建失败: {built.detail[:150]}")
        if r.name == "qemu-gdb":
            self._qemu_gdb_wrapper(r)
        else:
            self._docker_wrapper(r)
        return InstallResult(r.name, "installed", f"wrapper → {r.image} 容器")

    @staticmethod
    def _docker_image_exists(image: str) -> bool:
        """镜像存在性（指定 tag 或 latest）。"""
        for cand in (image, image.split(":")[0] + ":latest"):
            try:
                rr = subprocess.run(["docker", "image", "inspect", cand],
                                    capture_output=True, timeout=15)
                if rr.returncode == 0:
                    return True
            except (subprocess.TimeoutExpired, OSError):
                return False
        return False

    @staticmethod
    def _docker_build(r: DockerRecipe) -> InstallResult:
        """docker build（context = Dockerfile 所在目录）。"""
        df = os.path.join(_opencode_root(), r.dockerfile)
        if not os.path.isfile(df):
            return InstallResult(r.name, "failed", f"Dockerfile 不存在: {r.dockerfile}")
        try:
            rr = subprocess.run(["docker", "build", "-f", df, "-t", r.image, os.path.dirname(df)],
                                capture_output=True, text=True, timeout=2400)
            if rr.returncode != 0:
                tail = (rr.stderr or rr.stdout).strip().split("\n")[-1][:150]
                return InstallResult(r.name, "failed", tail)
        except subprocess.TimeoutExpired:
            return InstallResult(r.name, "failed", "docker build 超时（40min）")
        return InstallResult(r.name, "installed", f"built {r.image}")

    def _docker_wrapper(self, r: DockerRecipe) -> None:
        """docker run wrapper（docker-toolbox.md §6 蓝本: 唯一名+trap/降权/路径重写/wordlists）。"""
        os.makedirs(BIN_DIR, exist_ok=True)
        net = "--network host " if r.net_host else ""
        extra = (" ".join(r.extra_args) + " ") if r.extra_args else ""
        # 统一 sh wrapper（Windows 走 Git Bash/WSL 执行——与 install.sh 同前提;
        # 历史 .cmd 分支已删: 双语言维护腐化快且无法实测，见 docker-toolbox.md）
        path = os.path.join(BIN_DIR, r.name)
        if r.long_running:
            longcheck = (
                'if [ -z "$EXPLICIT_WT" ]; then\n'
                f'  echo "ERROR[{r.name}]: 长任务工具必须传 --wrapper-timeout <秒>（容器存活上限，防失联堆积）。" >&2\n'
                f'  echo "用法示例: {r.name} --wrapper-timeout 7200 <正常参数...>" >&2\n'
                '  exit 64\n'
                'fi')
        else:
            longcheck = ':'
        if r.name == "hashcat":
            # 核数计算在容器内做（探测容器继承 cgroup 限额+架构差异; 大小核按逻辑核对称调度）
            hashcat_env = (
                'POCL_THREADS=$(docker run --rm ' + r.image + ' sh -c '
                '"N=$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN); '
                '[ \\"\\$N\\" -gt 1 ] && echo \\$((N/2)) || echo 1")\n'
                'HC_ENV="-e POCL_MAX_PTHREAD_COUNT=$POCL_THREADS"\n'
            )
        else:
            hashcat_env = ""
        if r.name == "hashcat":
            w3check = '[ -z "$HAS_W" ] && ARGS="$ARGS -w 3"   # 未显式给 -w → 全力模式默认'
        else:
            w3check = ":"
        body = self._WRAPPER_TMPL.replace("{NAME}", r.name).replace(
            "{IMAGE}", r.image).replace(
            "{NET}", "--network host " if r.net_host else "").replace(
            "{EXTRA}", (" ".join(r.extra_args) + " ") if r.extra_args else "").replace(
            "{LONGCHECK}", longcheck).replace(
            "{HASHCAT_ENV}", hashcat_env).replace(
            "{W3CHECK}", w3check)
        with open(path, "w", encoding="utf-8",
                  newline=None if os.name == "nt" else "\n") as f:
            f.write(body)
        self._chmodx(path)

    def _qemu_gdb_wrapper(self, r: DockerRecipe) -> None:
        """qemu gdbstub 调试 wrapper（docker-toolbox.md §4: binfmt ptrace 失效的唯一可行模式）。"""
        path = os.path.join(BIN_DIR, r.name)
        body = self._QEMU_TMPL.replace("{IMAGE}", r.image)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        self._chmodx(path)

    # ── 底层操作 ──

    def _place_from_archive(self, r, data: bytes, asset: str) -> None:
        """归档/裸二进制 → 提取 r.bins 到 BIN_DIR（归档内递归按名查找）。"""
        os.makedirs(BIN_DIR, exist_ok=True)
        lower = asset.lower()
        is_archive = any(lower.endswith(s) for s in
                         (".tar.gz", ".tgz", ".tar.xz", ".zip", ".gz"))
        if not is_archive:  # raw 二进制资产
            dst = self._bin_path(r.bins[0])
            self._write(data, dst)
            return
        if lower.endswith(".gz") and not lower.endswith(".tar.gz"):
            # 裸 gzip 单文件: 内部文件名通常带版本/平台后缀 → 直接落到 bins[0]
            dst = self._bin_path(r.bins[0])
            self._write(gzip.decompress(data), dst)
            return
        tmp = tempfile.mkdtemp(prefix=f"ext-{r.name}-")
        self._extract(data, asset, tmp)
        for b in r.bins:
            found = self._find_file(tmp, r.src_names.get(b, b))
            if not found:
                raise RuntimeError(f"归档 {asset} 内未找到 {b}")
            dst = self._bin_path(b)
            shutil.copyfile(found, dst)
            self._chmodx(dst)

    def _gh_assets(self, repo: str) -> tuple[list[str], str]:
        req = urllib.request.Request(_GH_API.format(repo=repo), headers=_UA)
        with urllib.request.urlopen(req, timeout=30) as resp:
            d = json.loads(resp.read().decode())
        assets = [a["name"] for a in d.get("assets", [])]
        if not assets:
            raise RuntimeError(f"{repo} 最新 release 无二进制资产")
        return assets, d["tag_name"]

    @staticmethod
    def _match_assets(assets: list[str], keywords: list[str], extra_excl: str) -> list[str]:
        """全部关键词命中（忽略大小写）且不含排除词的资产，按 release 顺序。"""
        excl = _COMMON_EXCL + [k.strip() for k in extra_excl.split(",") if k.strip()]
        matched: list[str] = []
        for a in assets:
            la = a.lower()
            if any(x in la for x in excl):
                continue
            # 每个关键词是一个 alternation 组（"macos|darwin" 任一命中即可），全部组命中才选中
            if all(any(alt in la for alt in kw.strip().lower().split("|"))
                   for kw in keywords if kw.strip()):
                matched.append(a)
        return matched

    @staticmethod
    def _find_file(root: str, name: str) -> str | None:
        """递归按文件名查找（win 下 .exe 也接受原名+.exe）。"""
        want = {name.lower()}
        if os.name == "nt":
            want.add(name.lower() + ".exe")
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if f.lower() in want:
                    return os.path.join(dirpath, f)
        return None

    @staticmethod
    def _download(url: str) -> bytes:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=ToolsInstaller.TIMEOUT) as resp:
            return resp.read()

    @staticmethod
    def _write(data: bytes, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        ToolsInstaller._chmodx(path)

    @staticmethod
    def _extract(data: bytes, asset: str, dest: str) -> None:
        lower = asset.lower()
        if lower.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                z.extractall(dest)
        elif lower.endswith((".tar.gz", ".tgz", ".tar.xz")):
            with tarfile.open(fileobj=io.BytesIO(data)) as t:
                try:  # 3.12+ 建议 filter（path traversal 防护）; 旧版无此参数
                    t.extractall(dest, filter="data")
                except TypeError:
                    t.extractall(dest)  # noqa: S202 —— 官方 release 资产
        elif lower.endswith(".gz"):  # 裸 gzip 单文件（如 chisel）
            inner = gzip.decompress(data)
            with open(os.path.join(dest, asset[:-3]), "wb") as f:
                f.write(inner)
        else:
            raise RuntimeError(f"不支持的归档类型 {asset}")

    @staticmethod
    def _chmodx(path: str) -> None:
        mode = os.stat(path).st_mode
        os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def _wrapper(self, name: str, argv: list[str], cwd: str = "", envp: str = "") -> None:
        """生成 BIN_DIR sh wrapper，幂等覆盖; cwd 先 cd; envp 附加 PYTHONPATH。

        统一 sh（Windows 走 Git Bash/WSL 执行——与 docker wrapper/install.sh 同前提，单语言维护）。
        """
        os.makedirs(BIN_DIR, exist_ok=True)
        path = os.path.join(BIN_DIR, name)
        body = "#!/bin/sh\n"
        if cwd:
            body += f'cd "{cwd}"\n'
        if envp:
            body += f'export PYTHONPATH="{envp}:$PYTHONPATH"\n'
        body += "exec " + " ".join(f'"{a}"' if " " in a else a for a in argv) + ' "$@"\n'
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        self._chmodx(path)

    @staticmethod
    def _venv_python() -> str:
        """venv 解释器路径（与 detect_py_deps.VENV_DIR 同值推导; 无 venv 时回落当前解释器）。"""
        if os.name == "nt":
            cand = os.path.join(CACHE_DIR, ".venv", "Scripts", "python.exe")
        else:
            cand = os.path.join(CACHE_DIR, ".venv", "bin", "python")
        return cand if os.path.exists(cand) else sys.executable

    @staticmethod
    def _run(cmd: list[str]) -> None:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError(f"命令失败: {' '.join(cmd[:4])}...: {r.stderr.strip()[:200]}")


# 模块级单例 + 兼容委托（既有消费方零改动）
_scanner = ToolsScanner()


def scan_tool(tool: ToolField) -> ToolStatus:
    return _scanner.scan_tool(tool)


def scan_agent(agent_name: str) -> list[ToolStatus]:
    return _scanner.scan_agent(agent_name)


def scan_all() -> dict[str, list[ToolStatus]]:
    return _scanner.scan_all()


def scan_all_parallel() -> dict[str, ToolStatus]:
    return _scanner.scan_all_parallel()


def detect_compiler() -> CompilerInfo:
    return _scanner.detect_compiler()


# 安装器模块级单例 + 兼容委托
_installer = ToolsInstaller()


def install_tool(name: str, force: bool = False) -> InstallResult:
    return _installer.install_tool(name, force=force)


def install_all(force: bool = False) -> list[InstallResult]:
    return _installer.install_all(force=force)


def list_installable() -> list[str]:
    return [r.name for r in INSTALLABLE_TOOLS]


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="外部工具检测 + 自动安装",
        usage="detect_tools.py <command> [options]\n\n"
              "子命令:\n"
              "  scan                检测工具状态（按 agent）\n"
              "  install             安装 INSTALLABLE_TOOLS 清单（幂等）\n"
              "  list-installable    列出可自动安装的工具",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sc = sub.add_parser("scan", help="检测工具状态")
    sc.add_argument("--agent", default="all", help="agent 名（all=全部）")

    ic = sub.add_parser("install", help="安装全部可自动安装工具")
    ic.add_argument("--tool", default=None, help="只装指定工具（默认全部）")
    ic.add_argument("--force", action="store_true", help="忽略幂等跳过条件重装")

    sub.add_parser("list-installable", help="列出可自动安装清单")

    args = parser.parse_args()

    if args.command == "list-installable":
        for n in list_installable():
            print(n)
        return 0

    if args.command == "install":
        if args.tool:
            results = [install_tool(args.tool, force=args.force)]
        else:
            print("[*] 开始安装 INSTALLABLE_TOOLS 清单（单工具失败不中断）...")
            results = install_all(force=args.force)
        ok = sum(1 for r in results if r.status == "installed")
        skip = sum(1 for r in results if r.status == "skipped")
        fail = [r for r in results if r.status == "failed"]
        for r in results:
            mark = {"installed": "+", "skipped": "*", "failed": "-"}[r.status]
            print(f"[{mark}] {r.name:20s} {r.status:10s} {r.detail}")
        print(f"[*] 完成: 安装 {ok} / 跳过 {skip} / 失败 {len(fail)}")
        return 0  # 工具层是可选增强，失败不返回非零（install.sh 语义）

    # scan
    if args.agent == "all":
        for agent, statuses in scan_all().items():
            print(f"── {agent}")
            for s in statuses:
                mark = "+" if s.available else ("*" if s.skipped else "-")
                print(f"  [{mark}] {s.name:20s} {s.version or '':16s} {s.description}")
    else:
        for s in scan_agent(args.agent):
            mark = "+" if s.available else ("*" if s.skipped else "-")
            print(f"[{mark}] {s.name:20s} {s.version or '':16s} {s.description}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
