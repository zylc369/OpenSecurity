"""外部工具 + 编译器检测/自动安装收口模块（ToolsScanner / ToolsInstaller + 强类型状态）。

其他模块禁止直接 shutil.which 检测工具（grep 唯一性，本模块是工具检测的唯一入口）。

双模式（与 detect_py_deps.py 一致）：
  • CLI: python detect_tools.py <scan|install|list-installable> [options]
  • import: from services import detect_tools → detect_tools.install_all() 等

注意：
  • IDA_PRO_HOME 通过 config_store 读（配置收口）
  • 其他工具（apktool/jadx 等）通过 shutil.which 检测 PATH，未命中回落 CMD_DIR
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
CMD_DIR = os.path.join(CACHE_DIR, "bin")         # 命令目录: 可执行入口（wrapper+单二进制，插件注入 PATH）; 与 TOOLS_HOME_DIR 平级
TOOLS_HOME_DIR = os.path.join(CACHE_DIR, "tools")  # 工具"家"目录: 克隆仓库/jar/运行时（node/dotnet/...），非源码
WORDLISTS_DIR = os.path.join(CACHE_DIR, "wordlists")  # 字典统一落点（插件注入 $WORDLISTS_DIR; 容器 wrapper 挂载）


def _opencode_root() -> str:
    """OPENCODE_ROOT 推导: 环境变量 → 从本文件路径回溯（backend/services → .opencode）。"""
    env = os.environ.get("OPENCODE_ROOT")
    if env:
        return env
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


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
    java_min: int = 0               # java 主版本下限（如 ghidra 12.x 需 21; 0=不校验）
    tag: str = ""                   # 固定版本 tag（空=latest; repo 的 latest 被其他工具占用时必须指定，如 chaitin/xray）
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
    platforms: tuple[str, ...] = () # 平台前缀门控（空=全平台; 如 ("linux",) 仅 linux——
                                    #   其他平台回落同名 docker 配方，见 install_all 同名去重）
    setup: str = ""                 # 克隆后先执行的构建脚本（如 pwndbg setup.sh）
    prereq_cmd: str = ""            # 入口运行所需解释器（如 php）——缺失即 failed 给手动提示


@dataclass
class UrlRecipe:
    """直链下载配方（非 GitHub 源，如 ffmpeg 静态构建）。

    name: str
    urls: dict[str, str]  平台键 → 直链
    bins: list[str]       归档内提取产物（多 bin 一次解出，如 ffmpeg+ffprobe）
    src_names: dict[str, str]  bin名 → 归档内实际文件名（win .exe / 特殊命名如 exiftool(-k).exe）
    entries: dict[str, str]    平台键 → entry（非空=该平台整树安装，保持目录布局;
                               适用于依赖相对目录结构的产物，如 exiftool perl 脚本依赖同级 lib/）
    """

    name: str
    urls: dict[str, str] = field(default_factory=dict)  # 平台键 → 直链
    bins: list[str] = field(default_factory=list)       # 归档内提取产物
    src_names: dict[str, str] = field(default_factory=dict)
    entries: dict[str, str] = field(default_factory=dict)


@dataclass
class NodeRecipe:
    """Node.js 运行时配方（目录结构安装: node + npm + npx 三 wrapper）。

    npm 是目录树（lib/node_modules/npm），单文件 bins 机制装不了——
    解包整个官方归档到 TOOLS_HOME_DIR/node/，CMD_DIR 下生成三个 wrapper。
    版本锁 LTS（npm 10 要求 node >= 18.17）。
    """
    version: str
    name: str = "node"


@dataclass
class DirRecipe:
    """直链归档 → 内容平铺解压到 TOOLS_HOME_DIR/<dest>/（官方文件布局原样，PATH 由 plugin 注入）。

    适用: 官方 zip 内含顶层目录（如 platform-tools/）但要求落点是跨平台固定目录名的工具。
    不变式: <dest>/ 目录存在 ⟺ 安装时 PATH 无该工具（skip 分支清理残留维护，同 NodeRecipe）。
    """
    name: str
    urls: dict[str, str] = field(default_factory=dict)  # 平台键前缀（darwin/linux/win）→ 直链
    dest: str = ""                                      # TOOLS_HOME_DIR 下固定目录名
    marker: str = ""                                    # 目录内标志性文件（幂等/plugin 探测，win 自动补 .exe）
    strip_top: bool = True                              # True=剥掉归档顶层目录，内容平铺


@dataclass
class DotnetRecipe:
    """dotnet runtime + nuget 工具组合（.NET 生态 CLI 工具的本机跨平台方案）。

    runtime 官方归档解压 TOOLS_HOME_DIR/dotnet/（官方目录原样，NodeRecipe 同模式；
    多工具共享同一 runtime 目录，第二个 .NET 工具只装 nupkg 部分）。
    nuget 包（nupkg=zip）取 tools/<net_target>/any/ 解包到 TOOLS_HOME_DIR/<name>/。
    CMD_DIR wrapper: exec dotnet <name>.dll。net6.0 目标在 runtime 8（LTS→2026-11）roll-forward 可跑。
    """
    name: str
    nuget_name: str                  # nuget 包名
    nuget_version: str               # 钉死版本
    net_target: str = "net6.0"       # nupkg 内目标框架目录
    runtime_version: str = "8.0.11"  # dotnet runtime 版本（LTS）

    # 官方直链格式（三平台 200 已验）：tar.gz（posix）/ zip（win）
    _RUNTIME_URL = "https://builds.dotnet.microsoft.com/dotnet/Runtime/{ver}/dotnet-runtime-{ver}-{plat}.{ext}"
    _NUGET_URL = "https://www.nuget.org/api/v2/package/{name}/{ver}"

    def runtime_url(self, plat_key: str) -> str | None:
        """按平台键生成 runtime 直链; 无映射返回 None。"""
        mapping = {"darwin-arm64": "osx-arm64", "darwin-amd64": "osx-x64",
                   "linux-arm64": "linux-arm64", "linux-amd64": "linux-x64",
                   "win-amd64": "win-x64"}
        plat = mapping.get(plat_key)
        if not plat:
            return None
        ext = "zip" if plat.startswith("win") else "tar.gz"
        return self._RUNTIME_URL.format(ver=self.runtime_version, plat=plat, ext=ext)


@dataclass
class WordlistRecipe:
    """字典下载配方（数据文件，非命令）。落点 WORDLISTS_DIR/<target>。

    三源（互斥）: repo=git clone --depth 1（目录型）; url=直链下载（文件型）;
    source=仓库内目录复制（随 git 走的精选数据，如 .opencode/wordlists/cn/）。
    感知通道: 插件 shell.env 注入 $WORDLISTS_DIR; 容器 wrapper 自动挂载
    wordlists/seclists → /usr/share/seclists（kali 惯例路径）。
    """
    name: str
    target: str          # WORDLISTS_DIR 下落点（目录名或文件名）
    repo: str = ""       # git clone 源（owner/repo）
    url: str = ""        # 直链（文件型）
    source: str = ""     # 仓库内相对路径（OPENCODE_ROOT 起，目录型）


@dataclass
class GitBashRecipe:
    """Windows 专用: Git Bash 便携版自举（体系全部 sh 资产的执行前提）。

    opencode 在 Windows 默认 shell = PowerShell（vendor shell.ts: pwsh > powershell >
    GitBash > cmd），而 AI 命令语法（$VAR）/ sh wrapper / install.sh / sed 全依赖 bash
    ——本配方下载最新 PortableGit（.7z.exe 自解压，无需 7-Zip）到 CMD_DIR/git-portable/
    （官方目录原样，约 300MB），并把项目级 opencode.json 的 shell 配置为便携版 bash.exe。

    不探测系统 Git（自己装自己的——版本统一、行为确定）;
    按 CPU 架构选资产: win-amd64 → "PortableGit-*-64-bit.7z.exe"，win-arm64 → "*-arm64.7z.exe"
    （资产名匹配 latest API，规避 tag→文件名版本号转换差异 windows.5→.5）。
    """
    name: str = "git-bash"
    repo: str = "git-for-windows/git"


@dataclass
class JdkRecipe:
    """Temurin JDK 便携运行时配方（ Adoptium API 免版本直链，三平台 tar.gz/zip，
    零 root 零系统侵入，落 TOOLS_HOME_DIR/jdk/）。消费方（ghidra 等 java 工具）的
    wrapper 注入 JAVA_HOME 指向此目录；不生成 bin wrapper（避免遮蔽系统 java）。
    同 DotnetRecipe 先例: 共享目录，多 java 工具只装一次。
    """
    feature: int = 21          # LTS 特性版本（21/25...）
    name: str = "jdk"

    def url(self, plat_key: str) -> str | None:
        syst, arch = plat_key.split("-")
        os_map = {"darwin": "mac", "linux": "linux", "win": "windows"}.get(syst)
        arch_map = {"amd64": "x64", "arm64": "aarch64"}.get(arch)
        if not os_map or not arch_map:
            return None
        return (f"https://api.adoptium.net/v3/binary/latest/{self.feature}/ga/"
                f"{os_map}/{arch_map}/jdk/hotspot/normal/eclipse")


@dataclass
class DockerRecipe:
    """容器工具配方（调研见 knowledge-base/docker-toolbox.md）。

    wrapper 落 CMD_DIR: docker run（entrypoint 降权/卷挂载/路径重写/trap 防孤儿容器）。
    多工具共享镜像: image 相同的 recipe 只 build 一次（image_exists 幂等）。
    """
    name: str                        # 工具名（=容器内命令名）
    image: str                       # zylc369/opensecurity-toolbox-core|full
    dockerfile: str = ""             # 相对 OPENCODE_ROOT 的 Dockerfile 路径（build 用）
    net_host: bool = False           # True: --network host（仅 Linux 宿主有意义）
    long_running: bool = False       # True: 长任务——wrapper 必须收到 --wrapper-timeout 才运行
    extra_args: list[str] = field(default_factory=list)  # 追加 docker run 参数


@dataclass
class PrebuiltRecipe:
    """随仓库携带的预编译二进制（macOS Xcode/clang 编译产物，放 .opencode/tools/）。

    适用: 必须 macOS 工具链编译、容器无法构建的工具（class-dump/optool 类 Mach-O 工具）。
    安装 = 拷贝到 CMD_DIR + chmod。
    platforms 默认 ["darwin"]: Mach-O 产物在 linux/win 上无法执行——
    安装守卫跳过 + 检测层 ToolField 需同标 platforms（防假可用）。
    """
    name: str
    source: str                       # 相对 OPENCODE_ROOT 的二进制路径
    platforms: list[str] = field(default_factory=lambda: ["darwin"])
    jar: bool = False                 # True: 产物是自包含 jar → 拷 TOOLS_HOME_DIR +
                                      #   java wrapper（便携 JDK 优先; 三平台可跑）
    jar_cp: bool = False              # True: jar 无 Main-Class（marshalsec 类）→ -cp 模式，
                                      #   调用方首参为主类（对齐上游 README 用法）


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

# ── 包管理器层（Phase 0 强制检查; install_all 最先执行）─────────────────────
# 各 PM 安装命令前缀（子命令与非交互参数不统一: pacman 无 install 用 -S --noconfirm，
# apk 用 add 且默认非交互，zypper 用长参数——故存"完整前缀"而非 PM 名）。
_PM_INSTALL_PREFIX = {
    "apt": "sudo apt install -y",
    "apt-get": "sudo apt-get install -y",
    "dnf": "sudo dnf install -y",
    "yum": "sudo yum install -y",
    "pacman": "sudo pacman -S --noconfirm",
    "apk": "sudo apk add",
    "zypper": "sudo zypper --non-interactive install",
}
PM_PREFIX: str = ""   # linux 命中的完整安装命令前缀（check_package_manager 赋值; 空=非 linux/未检）


def check_package_manager() -> None:
    """平台包管理器强制检查（全量工具箱哲学: 清单必含 PM 源工具，PM 是硬前置）。

    darwin: 必须 brew（brew install 是自动安装法; brew 本身只此一次需用户手动装）
    linux:  依序检测 apt→apt-get→dnf→yum→pacman→apk→zypper，命中 → PM_PREFIX 全局赋值
    win:    跳过（win 走便携包/docker）
    失败 → sys.exit 报错不继续（幂等: 用户装完重跑）。
    """
    global PM_PREFIX
    syst = platform.system().lower()
    if syst == "darwin":
        if not shutil.which("brew"):
            sys.exit(
                "错误[macOS]: 必须先安装 Homebrew（工具箱的 mac 自动安装依赖它）:\n"
                '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com'
                '/Homebrew/install/HEAD/install.sh)"\n'
                "  装完后重跑 install.sh，将自动完成全部工具安装")
    elif syst == "linux":
        for pm, prefix in _PM_INSTALL_PREFIX.items():
            if shutil.which(pm):
                PM_PREFIX = prefix
                return
        sys.exit("错误[linux]: 未找到受支持的包管理器"
                 "(apt/apt-get/dnf/yum/pacman/apk/zypper)，无法继续")
    # windows: 无操作


@dataclass
class ManualItem:
    """一条手动检测项: which 检测目标 + 提醒行里的包名（不同 PM 包名偶有差异时覆盖）。"""
    command: str          # which 检测的命令名
    pkg: str = ""         # 安装包名（空 = 与 command 同名）


@dataclass
class ManualCheck:
    """手动安装检测（当前仅 linux 需要——apt/yum 需密码无法自动执行）。

    一个结构持多条命令 → 缺失子集天然合并成一行安装命令（输出用 PM_PREFIX 拼装，
    无聚合特判）。mac 有 brew 即全自动，无需此结构。
    """
    platforms: tuple[str, ...] = ("linux",)
    items: list[ManualItem] = field(default_factory=list)
    note: str = ""        # 附加说明（如"个别包需 Kali 源"）


def run_manual_checks(checks: list[ManualCheck]) -> None:
    """批量 which 检测 → 缺失合并一行报错退出。幂等: 用户执行后重跑即过。"""
    syst = platform.system().lower()
    prefix = {"darwin": "darwin", "linux": "linux", "windows": "win"}.get(syst, syst)
    for chk in checks:
        if prefix not in chk.platforms:
            continue
        missing = [(i.command, i.pkg or i.command) for i in chk.items
                   if not shutil.which(i.command)]
        if missing:
            seen_pkgs: list[str] = []
            for _c, p in missing:      # 多命令同包（fls/icat/istat→sleuthkit）去重保序
                if p not in seen_pkgs:
                    seen_pkgs.append(p)
            pkgs = " ".join(seen_pkgs)
            cmds = ",".join(c for c, _p in missing)
            lines = [f"错误[linux]: 缺 {len(missing)} 个需手动安装的工具（命令: {cmds}）:",
                     f"  {PM_PREFIX} {pkgs}",
                     "  （需要 sudo 密码，无法自动执行; 完成后重跑 install.sh 自动续装）"]
            if chk.note:
                lines.append(f"  注: {chk.note}")
            sys.exit("\n".join(lines))


@dataclass
class PkgToolRecipe:
    """包管理器源工具: mac=brew 自动安装 / linux=进 ManualCheck 手动提醒 / win=docker 回落。

    目标: docker 里 PM 能装的全部迁到 PM（最大程度消解 wrapper 问题——PM 产物落
    系统 PATH，无 wrapper）。pkg_brew/pkg_linux 为空表示该平台 PM 无此包 → 该平台
    回落 docker（嵌入字段合成 DockerRecipe，行为与原容器配方一致）。
    包名与命令名不一致的工具（tshark←wireshark、msfvenom←metasploit、
    x86_64-w64-mingw32-gcc←apt: gcc-mingw-w64-x86-64）在此显式声明。
    """
    name: str
    pkg_brew: str = ""    # 空=brew 无此包（mac 回落 docker）; 特殊名显式写
    pkg_linux: str = ""   # 空=linux PM 无此包（回落 docker）; 特殊名显式写
    # docker 回落字段（仅当对应平台 PM 不可用时使用）
    image: str = "zylc369/opensecurity-toolbox-core"
    dockerfile: str = "control/docker/toolbox-core.Dockerfile"
    long_running: bool = False
    net_host: bool = False

    def docker_spec(self) -> "DockerRecipe":
        return DockerRecipe(name=self.name, image=self.image,
                            dockerfile=self.dockerfile,
                            long_running=self.long_running, net_host=self.net_host)


@dataclass
class GemRecipe:
    """ruby gem 工具（zsteg/seccomp-tools 类）。

    mac: 系统 ruby/gem（--user-install 免 sudo 装入 ~/.gem，wrapper 指向真实 bin）。
    linux: ruby 经手动清单提供（install_all 静态补 ruby 检测项）。
    """
    name: str
    gem: str = ""              # gem 名（空=同名）


@dataclass
class SrcRecipe:
    """源码编译工具（无预编译产物、PM 无包: pycdc/pcapfix 类）。

    build_sys: "cmake" | "autotools"; 产物 bins 从构建树递归定位到 CMD_DIR。
    前置: gcc/make（CLT 或 PM）; cmake 类工具另需 cmake（PkgToolRecipe 提供）。
    """
    name: str
    repo: str
    build_sys: str = "cmake"   # cmake: cmake . && make | autotools: ./configure && make
    bins: list[str] = field(default_factory=list)


@dataclass
class ScriptRecipe:
    """内联编排脚本配方（无产物下载——纯组合宿主已有工具，如 qemu-gdb）。

    body 写入 CMD_DIR/<name> + chmod; prereq_cmds 缺任一 → failed 给 PM 安装提示。
    适用: 组合调试/联动类工具（价值在编排逻辑而非二进制）。
    """
    name: str
    body: str
    prereq_cmds: list[str] = field(default_factory=list)


_INSTALLABLE_TOOLS: list[ReleaseRecipe | GitRecipe | UrlRecipe | DockerRecipe | PrebuiltRecipe | NodeRecipe | DirRecipe | DotnetRecipe | WordlistRecipe | JdkRecipe | PkgToolRecipe] | None = None


def installable_tools() -> "list":
    """INSTALLABLE_TOOLS 的惰性构建入口。

    封装为函数的原因: 清单内配方可引用 PM_PREFIX 等"检测后才有值"的全局变量
    （check_package_manager 必先于本函数调用——install_all 已保证; 直接调用的
    消费方需自行先跑 check）。模块级缓存避免重复构建。
    """
    global _INSTALLABLE_TOOLS
    if _INSTALLABLE_TOOLS is not None:
        return _INSTALLABLE_TOOLS
    _INSTALLABLE_TOOLS = [
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
    GitRecipe(name="jwt_tool", repo="ticarpi/jwt_tool", entry="jwt_tool.py", req="requirements.txt"),
    GitRecipe(name="weevely", repo="epinna/weevely3", entry="weevely.py", pip_pkg=True),
    GitRecipe(name="sstv", repo="colaclanth/sstv", entry="sstv/__main__.py", pip_pkg=True),
    GitRecipe(name="aleapp", repo="markmckinnon/ALEAPP", entry="aleapp.py", req="requirements.txt"),
    GitRecipe(name="ileapp", repo="markmckinnon/iLEAPP", entry="ileapp.py", req="requirements.txt"),
    # ── 内网综合扫描（go 单二进制; excl 排除 web/nolocal 变体，标准版 fscan_<ver>_<os>_<arch>） ──
    ReleaseRecipe(name="fscan", repo="shadow1ng/fscan", plats={
        "darwin-arm64": "mac,arm64", "darwin-amd64": "mac,x64",
        "linux-arm64": "linux,arm64", "linux-amd64": "linux,x64",
        "win-amd64": "windows,x64"}, excl="web,nolocal", bins=["fscan"]),
    # ── RSA 大 N 分解（仅 linux/win 有预编译; mac 走 factordb/rsactftool 替代） ──
    ReleaseRecipe(name="yafu", repo="bbuhrow/yafu", plats={
        "linux-amd64": "linux,avx2", "win-amd64": "windows,avx2"}, bins=["yafu"]),
    # ── Go 符号恢复（zip 单二进制; mac 资产是 x86_64 构建——arm64 mac 走 Rosetta 2 可跑） ──
    ReleaseRecipe(name="GoReSym", repo="mandiant/GoReSym", plats={
        "darwin-arm64": "mac", "darwin-amd64": "mac",
        "linux-amd64": "linux", "win-amd64": "windows"}, bins=["GoReSym"]),
    # ── .NET 反编译（dotnet runtime 8 LTS + nuget nupkg net6.0 目标） ──
    DotnetRecipe(name="ilspycmd", nuget_name="ilspycmd", nuget_version="8.2.0.7535"),
    # ── 字典（$WORDLISTS_DIR 落点; 容器 wrapper 挂载 seclists → /usr/share/seclists） ──
    WordlistRecipe(name="seclists", target="seclists", repo="danielmiessler/SecLists"),
    WordlistRecipe(name="rockyou", target="rockyou.txt",
                   url="https://github.com/brannondorsey/naive-hashcat/releases/download/data/rockyou.txt"),
    WordlistRecipe(name="cn-dicts", target="cn", source="wordlists/cn"),
    # ── Windows 专用: Git Bash 运行时自举（写 opencode.json shell 键; 系统版优先，便携版兜底） ──
    GitBashRecipe(),
    # ── ffmpeg/ffprobe（便携静态构建: win=gyan.dev / linux=johnvansickle 双架构 /
    #     mac-arm=osxexperts 原生 / mac-x64+ffprobe-arm(Rosetta)=evermeet——同 GoReSym 先例。
    #     ffprobe 与 ffmpeg 同包（win/linux），独立 recipe 会重下载一次——一次性代价可接受）──
    UrlRecipe(name="ffmpeg", urls={
        "darwin-arm64": "https://www.osxexperts.net/ffmpeg71arm.zip",
        "darwin-amd64": "https://evermeet.cx/ffmpeg/ffmpeg-9.0.1.zip",
        "linux-amd64": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
        "linux-arm64": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz",
        "win-amd64": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    }, bins=["ffmpeg"]),  # win 归档内 ffmpeg.exe 由 _find_file 的 nt .exe 分支自动匹配
    UrlRecipe(name="ffprobe", urls={
        "darwin-arm64": "https://evermeet.cx/ffmpeg/ffprobe-9.0.1.zip",  # x86_64 构建，Rosetta 2 运行
        "darwin-amd64": "https://evermeet.cx/ffmpeg/ffprobe-9.0.1.zip",
        "linux-amd64": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
        "linux-arm64": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz",
        "win-amd64": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    }, bins=["ffprobe"]),  # win .exe 同上自动匹配
    ReleaseRecipe(name="xray", repo="chaitin/xray", tag="1.9.11", plats=_GO_ALL, bins=["xray"]),
    # ── 运行时层（目录结构安装: node + npm + npx） ──
    NodeRecipe(version="22.14.0"),
    # ── Android platform-tools（adb/fastboot; 腾讯云镜像，google 直链需翻墙） ──
    DirRecipe(name="adb", urls={
        "darwin": "https://mirrors.cloud.tencent.com/AndroidSDK/platform-tools-latest-darwin.zip",
        "linux": "https://mirrors.cloud.tencent.com/AndroidSDK/platform-tools-latest-linux.zip",
        "win": "https://mirrors.cloud.tencent.com/AndroidSDK/platform-tools-latest-windows.zip",
    }, dest="android-platform-tools", marker="adb"),
    # ── 预编译层（macOS 工具链产物，随 git 仓库走） ──
    PrebuiltRecipe(name="class-dump", source="tools/class-dump"),
    PrebuiltRecipe(name="ldid", source="tools/ldid"),
    PrebuiltRecipe(name="insert_dylib", source="tools/insert_dylib"),
    PrebuiltRecipe(name="optool", source="tools/optool"),
    # ── 容器层（编译类; toolbox-design.md §3.1 实测清单） ──
    PkgToolRecipe(name="steghide", pkg_brew="", pkg_linux="steghide"),  # brew 核心已移除 → mac docker
    DockerRecipe(name="stegseek", image="zylc369/opensecurity-toolbox-core", long_running=True,
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    PkgToolRecipe(name="john", pkg_brew="john-jumbo", long_running=True),  # apt: john
    PkgToolRecipe(name="hashcat", long_running=True),  # mac=brew(Metal) / linux=apt 手动
    # hashcat win: 官方便携 .7z（自带 dll+内核+rules; 资产名带版本→动态 latest 匹配;
    # 与上行同名按平台择一——install_all 同名去重，先 installed 者占名）
    ReleaseRecipe(name="hashcat", repo="hashcat/hashcat", kind="tree",
                  plats={"win-amd64": ".7z"}, entry="hashcat.exe", bins=["hashcat"]),
    PkgToolRecipe(name="nmap", long_running=True, net_host=True),
    PkgToolRecipe(name="hydra", long_running=True, net_host=True),
    PkgToolRecipe(name="medusa", long_running=True, net_host=True),
    PkgToolRecipe(name="ncrack", long_running=True, net_host=True),
    PkgToolRecipe(name="binwalk"),  # 原 binwalk-full; PM 包名 binwalk
    GitRecipe(name="nxc", repo="Pennyw0rth/NetExec", entry="netexec", pip_pkg=True,
              platforms=("linux",)),  # mac 无 rust wheel(aardwolf) 无 brew formula → 下方 docker
    DockerRecipe(name="nxc", image="zylc369/opensecurity-toolbox-core", long_running=True,
                 dockerfile="control/docker/toolbox-core.Dockerfile", net_host=True),
    PkgToolRecipe(name="searchsploit", pkg_brew="exploitdb", pkg_linux="exploitdb"),
    PkgToolRecipe(name="wpscan", long_running=True),  # apt 需 Kali 源
    PkgToolRecipe(name="fls", pkg_brew="sleuthkit", pkg_linux="sleuthkit"),
    PkgToolRecipe(name="icat", pkg_brew="sleuthkit", pkg_linux="sleuthkit"),
    PkgToolRecipe(name="istat", pkg_brew="sleuthkit", pkg_linux="sleuthkit"),
    PkgToolRecipe(name="tshark", pkg_brew="wireshark", pkg_linux="tshark"),  # 包名跨 PM 不同
    # ── exiftool（便携: unix=官方 perl 树（脚本依赖同级 lib/，整树安装）/
    #     win=官方 standalone 单 exe。sourceforge 镜像，/download 尾段非文件名→asset 覆盖）──
    UrlRecipe(name="exiftool", urls={
        "darwin-arm64": "https://sourceforge.net/projects/exiftool/files/Image-ExifTool-13.59.tar.gz/download",
        "darwin-amd64": "https://sourceforge.net/projects/exiftool/files/Image-ExifTool-13.59.tar.gz/download",
        "linux-amd64": "https://sourceforge.net/projects/exiftool/files/Image-ExifTool-13.59.tar.gz/download",
        "linux-arm64": "https://sourceforge.net/projects/exiftool/files/Image-ExifTool-13.59.tar.gz/download",
        "win-amd64": "https://sourceforge.net/projects/exiftool/files/exiftool-13.59_64.zip/download",
    }, bins=["exiftool"], entries={p: "exiftool" for p in
        ("darwin-arm64", "darwin-amd64", "linux-amd64", "linux-arm64")},
       src_names={"exiftool": "exiftool(-k).exe"}),  # win 走单文件提取分支
    PkgToolRecipe(name="x86_64-w64-mingw32-gcc", pkg_brew="mingw-w64", pkg_linux="gcc-mingw-w64-x86-64"),
    PkgToolRecipe(name="nasm"),
    PkgToolRecipe(name="r2", pkg_brew="radare2", pkg_linux="radare2"),
    PkgToolRecipe(name="one_gadget", pkg_brew="one_gadget", pkg_linux=""),  # apt 无 → linux docker
    DockerRecipe(name="seccomp-tools", image="zylc369/opensecurity-toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),  # gem 需 ruby>=3, 系统 ruby 过老
    GitRecipe(name="phpggc", repo="s0md3v/phpggc", entry="phpggc", py=False, prereq_cmd="php",
              platforms=("linux",)),  # mac 无系统 php → 同名 DockerRecipe 兜底（mac/win）
    PkgToolRecipe(name="sox"),
    PkgToolRecipe(name="identify", pkg_brew="imagemagick", pkg_linux="imagemagick"),
    PkgToolRecipe(name="convert", pkg_brew="imagemagick", pkg_linux="imagemagick"),
    PkgToolRecipe(name="mutool", pkg_brew="mupdf", pkg_linux="mupdf-tools"),
    DockerRecipe(name="boolector", image="zylc369/opensecurity-toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),
    PkgToolRecipe(name="qemu-system-x86_64", pkg_brew="qemu", pkg_linux="qemu-system-x86"),
    PkgToolRecipe(name="wrestool", pkg_brew="icoutils", pkg_linux="icoutils"),
    SrcRecipe(name="pcapfix", repo="Rup0rt/pcapfix", build_sys="autotools", bins=["pcapfix"]),
    PkgToolRecipe(name="xfs_db", pkg_brew="", pkg_linux="xfsprogs"),
    PkgToolRecipe(name="cryptsetup", pkg_brew="", pkg_linux="cryptsetup"),
    GemRecipe(name="zsteg"),
    PkgToolRecipe(name="arpspoof", pkg_brew="dsniff", pkg_linux="dsniff", net_host=True),
    PkgToolRecipe(name="gdb"),
    # qemu-gdb 原生编排（docker-toolbox.md §4 语义原样; 架构判断跟随宿主而非固定容器）
ScriptRecipe(name="qemu-gdb", body=r"""#!/bin/sh
# 跨架构 gdb 调试（原生: 系统 file/qemu/gdb 编排）
# 用法: qemu-gdb <binary> [gdb 参数...]  例: qemu-gdb ./pwn -ex "break main" -ex c
# 架构路由: ELF 架构 == 宿主架构 → gdb 直调（原生 ptrace）
#           跨架构 → qemu-<arch> -g <port> gdbstub + gdb target remote
# 动态跨架构二进制需目标根文件系统: export QEMU_SYSROOT=/path/to/sysroot（静态二进制无需）
BIN="${1:-./a.out}"; shift
case "$BIN" in /*) ;; *) BIN="./$BIN" ;; esac
GDB="${QEMU_GDB:-gdb}"; command -v "$GDB" >/dev/null 2>&1 || GDB=gdb-multiarch
FILEOUT=$(file "$BIN" 2>/dev/null)
HOSTARCH=$(uname -m)
# 宿主/ELF 架构归一（arm64==aarch64, x86_64/amd64==x86-64）
_norm() { case "$1" in arm64|aarch64|ARM) echo aarch64;; x86_64|amd64|x86-64) echo x86-64;; *) echo "$1";; esac; }
HOST_N=$(_norm "$HOSTARCH")
# universal2 双架构 fat binary 时 file 会列出多个切片——宿主架构优先匹配
case "$HOST_N" in
  aarch64) HPAT='aarch64|arm64|ARM';;
  x86-64) HPAT='x86-64|x86_64';;
  *) HPAT='';;
esac
if [ -n "$HPAT" ] && echo "$FILEOUT" | grep -qE "$HPAT"; then
  ELF_N="$HOST_N"
else
  ELFARCH=$(echo "$FILEOUT" | grep -oE 'x86-64|x86_64|aarch64|arm64|ARM' | head -1)
  ELF_N=$(_norm "$ELFARCH")
fi
[ -z "$ELF_N" ] && { echo "qemu-gdb: 无法识别架构: $BIN" >&2; exit 1; }
if [ "$ELF_N" = "$HOST_N" ]; then
  exec "$GDB" -q "$BIN" "$@"
fi
# 跨架构: qemu-user gdbstub
case "$ELF_N" in
  x86-64) QEMU_BIN=qemu-x86_64; QEMU_PKG="qemu-user(apt)/qemu(brew)";;
  aarch64) QEMU_BIN=qemu-aarch64; QEMU_PKG="qemu-user(apt)/qemu(brew)";;
  *) echo "qemu-gdb: 架构 $ELF_N 无 qemu-user 映射" >&2; exit 1;;
esac
command -v "$QEMU_BIN" >/dev/null 2>&1 || { echo "qemu-gdb: 缺 $QEMU_BIN（$QEMU_PKG）" >&2; exit 1; }
PORT=$((20000 + RANDOM % 20000))
LARG=""
echo "$FILEOUT" | grep -q "statically" || { [ -n "$QEMU_SYSROOT" ] && LARG="-L $QEMU_SYSROOT" || \
  echo "qemu-gdb: 动态二进制未设 QEMU_SYSROOT（尝试裸跑; 依赖库加载失败时 export QEMU_SYSROOT=目标sysroot）" >&2; }
"$QEMU_BIN" $LARG -g "$PORT" "$BIN" &
QPID=$!
trap 'kill $QPID 2>/dev/null' EXIT INT TERM
sleep 1
exec "$GDB" -q "$BIN" -ex "set architecture $ELF_N" -ex "target remote :$PORT" "$@"
""",
             prereq_cmds=["file", "gdb"]),
    GitRecipe(name="gdb-pwndbg", repo="pwndbg/pwndbg", entry="gdb", py=False, setup="setup.sh",
              platforms=("linux",)),  # 官方已弃 macOS（setup.sh 拒跑）→ mac/win 落下行 docker
    DockerRecipe(name="gdb-pwndbg", image="zylc369/opensecurity-toolbox-core",
                 dockerfile="control/docker/toolbox-core.Dockerfile"),  # mac/win 兜底
    PkgToolRecipe(name="gdbserver", pkg_brew="", pkg_linux="gdb"),  # brew gdb 无 gdbserver → mac docker
    PkgToolRecipe(name="e2fsck", pkg_brew="", pkg_linux="e2fsprogs"),  # mac 分析 linux fs → docker
    PkgToolRecipe(name="e2fsck64", pkg_brew="", pkg_linux="e2fsprogs"),
    PkgToolRecipe(name="debugfs", pkg_brew="", pkg_linux="e2fsprogs"),
    PkgToolRecipe(name="mkfs.ext4", pkg_brew="", pkg_linux="e2fsprogs"),
    PkgToolRecipe(name="btrfs", pkg_brew="", pkg_linux="btrfs-progs"),
    PkgToolRecipe(name="qemu-riscv64", pkg_brew="qemu", pkg_linux="qemu-system-misc"),
    PkgToolRecipe(name="upx"),
    PkgToolRecipe(name="bloodhound", pkg_brew="bloodhound", pkg_linux="bloodhound"),  # apt 需 Kali
    GitRecipe(name="smtp-user-enum", repo="pentestmonkey/smtp-user-enum", entry="smtp-user-enum.pl", py=False),  # 系统 perl
    PrebuiltRecipe(name="marshalsec", source="tools/marshalsec-0.0.3-SNAPSHOT-all.jar",
                 platforms=["darwin", "linux", "win"], jar=True, jar_cp=True),  # 预编译自包含 jar; 首参=主类
    # ── ghidra-headless（便携: 官方单一 zip 三平台通用。
    #     替代 full 层容器（镜像数 GB → 便携 zip 一次性 ~570MB 且零容器开销）。
    #     JDK 由 JdkRecipe 便携供给（prereq java_min 21; wrapper 注入 JAVA_HOME））──
    JdkRecipe(feature=21),
    ReleaseRecipe(name="ghidra-headless", repo="NationalSecurityAgency/ghidra", kind="tree",
                  plats={p: "PUBLIC" for p in
                         ("darwin-arm64", "darwin-amd64", "linux-amd64", "linux-arm64", "win-amd64")},
                  entry="support/analyzeHeadless", bins=["ghidra-headless"],
                  prereq="java", java_min=21),
    PkgToolRecipe(name="msfvenom", pkg_brew="metasploit", pkg_linux="metasploit-framework",
                  image="zylc369/opensecurity-toolbox-full",
                  dockerfile="control/docker/toolbox-full.Dockerfile"),  # apt 需 Kali
    # ── v1.1 增量: 网络基础/隐写补充/无线/取证/web 扫描/查壳/pyc 反编译 ──
    PkgToolRecipe(name="socat", net_host=True),
    PkgToolRecipe(name="stegsnow", pkg_brew="", pkg_linux="stegsnow"),
    PkgToolRecipe(name="foremost"),
    PkgToolRecipe(name="aircrack-ng", long_running=True),
    PkgToolRecipe(name="testdisk", long_running=True),
    PkgToolRecipe(name="photorec", pkg_brew="testdisk", pkg_linux="testdisk"),
    PkgToolRecipe(name="nikto", long_running=True),
    PkgToolRecipe(name="cmake"),  # SrcRecipe(cmake 类) 的构建前置; brew/apt 均有
    SrcRecipe(name="pycdc", repo="zrax/pycdc", build_sys="cmake", bins=["pycdc", "pycdas"]),
]
    return _INSTALLABLE_TOOLS


# ─── 工具清单 ────────────────────────────────────────────
_AUTO_HINT = "自动安装: bash .opencode/install.sh 或 python control/backend/services/detect_tools.py install --tool {name}"
_WEB = ["web-analysis"]
_BIN = ["binary-analysis"]

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
        install_hint=_AUTO_HINT.format(name="apktool"),
    ),
    ToolField(
        name="jadx",
        agents=["mobile-analysis"],
        required=True,
        version_cmd=["--version"],
        description="DEX→Java 反编译器",
        install_hint=_AUTO_HINT.format(name="jadx"),
    ),
    ToolField(
        name="adb",
        agents=["mobile-analysis"],
        required=True,
        version_cmd=["version"],
        description="Android Debug Bridge",
        install_hint=_AUTO_HINT.format(name="adb"),
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
        name="GoReSym",
        agents=["binary-analysis", "crypto-analysis"],
        required=False,
        description="Go 符号恢复工具",
        install_hint=_AUTO_HINT.format(name="GoReSym"),
    ),
]

# ── 自动安装层工具（INSTALLABLE_TOOLS 覆盖; 安装方式 = install.sh / detect_tools.py install） ──
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
    _auto("xray", _WEB, "Web 漏洞扫描器（被动代理/语义分析; GitHub 1.9.11）"),
    ToolField(name="class-dump", agents=["mobile-analysis"], required=False,
              version_cmd=[], description="ObjC 类信息导出（Mach-O）", platforms=["darwin"],
              install_hint="自动安装（预编译二进制，macOS 专用）"),
    ToolField(name="ldid", agents=["mobile-analysis"], required=False,
              version_cmd=[], description="iOS 伪签名/entitlements", platforms=["darwin"],
              install_hint="自动安装（预编译二进制，macOS 专用）"),
    ToolField(name="insert_dylib", agents=["mobile-analysis"], required=False,
              version_cmd=[], description="Mach-O 动态库注入（LC_LOAD_DYLIB）", platforms=["darwin"],
              install_hint="自动安装（预编译二进制，macOS 专用）"),
    ToolField(name="optool", agents=["mobile-analysis"], required=False,
              version_cmd=[], description="Mach-O load command 编辑（注入/卸载 dylib）", platforms=["darwin"],
              install_hint="自动安装（预编译二进制，macOS 专用）"),
    _auto("wasm-objdump", _BIN, "WASM 反汇编（wabt 套件）"),
    _auto("ysoserial", _WEB, "Java 反序列化 gadget 链生成（需 java）"),
    _auto("rsactftool", _BIN, "RSA 攻击聚合"),
    _auto("wesng", _BIN, "Windows 补丁缺失比对"),
    _auto("windapsearch", _BIN, "LDAP/AD 枚举"),
    _auto("regeorg", _BIN, "webshell 隧道（SOCKS）"),
    _auto("ffmpeg", _BIN, "音视频处理（隐写频谱/帧提取; 便携静态构建）"),
    _auto("ffprobe", _BIN, "音视频流/元数据分析（便携静态构建）"),
    _auto("steghide", _BIN, "JPEG/BMP 隐写（容器）"),
    _auto("stegseek", _BIN, "steghide 高速爆破（容器; 仅 Kali 源可原生）"),
    _auto("hashcat", _BIN, "哈希破解（brew Metal GPU / apt 原生）", ["-I"]),
    _auto("nmap", _WEB + _BIN, "端口/服务扫描（brew/apt 原生）"),
    _auto("hydra", _WEB + _BIN, "多协议爆破（brew/apt 原生）"),
    _auto("medusa", _WEB + _BIN, "多协议爆破第二实现（brew/apt 原生）"),
    _auto("ncrack", _WEB + _BIN, "网络服务爆破（brew/apt 原生）"),
    _auto("binwalk-full", _BIN, "binwalk（brew/apt 原生; magic 提取全功能）"),
    _auto("nxc", _BIN, "NetExec 内网批量执行（linux pip / mac 容器）", ["--version"]),
    _auto("searchsploit", _WEB, "exploit-db 离线检索（brew/apt 原生）"),
    _auto("wpscan", _WEB, "WordPress 扫描（brew 原生，DB 预热）"),
    _auto("tshark", _BIN, "pcap 深度解析（brew wireshark / apt tshark 原生）"),
    _auto("exiftool", _BIN, "元数据读写（便携官方构建）"),
    _auto("one_gadget", _BIN, "libc execve gadget 搜索（brew one_gadget / linux 容器）"),
    _auto("seccomp-tools", _BIN, "seccomp BPF 反汇编（容器; gem 需 ruby>=3）"),
    _auto("phpggc", _WEB, "PHP 反序列化链生成（容器）"),
    _auto("qemu-gdb", _BIN, "跨架构 gdb 调试（qemu gdbstub 模式）"),
    _auto("sox", _BIN, "音频处理/频谱图（brew/apt 原生）"),
    _auto("identify", _BIN, "图像信息/逐帧 delay（imagemagick 原生）"),
    _auto("convert", _BIN, "图像变换/拼接（imagemagick 原生）"),
    _auto("mutool", _BIN, "PDF 页渲染/解压（mupdf 原生）"),
    _auto("boolector", _BIN, "SMT QF_BV 求解器（容器; angr/claripy 可切）"),
    _auto("qemu-system-x86_64", _BIN, "x86 全系统模拟（qemu 原生; 内核题启动）"),
    _auto("wrestool", _BIN, "PE 资源提取（icoutils 原生）"),
    _auto("pcapfix", _BIN, "pcap 头修复（源码编译原生）"),
    _auto("xfs_db", _BIN, "xfs 文件系统检查（linux xfsprogs / mac 容器）"),
    _auto("cryptsetup", _BIN, "LUKS 处理（linux cryptsetup / mac 容器）"),
    _auto("zsteg", _BIN, "PNG/BMP LSB 隐写检测（ruby gem 原生）"),
    _auto("arpspoof", _BIN, "ARP 欺骗（dsniff 原生; macOS 无 LAN L2 实际受限，Linux 可用）"),
    _auto("gdb", _BIN, "gdb 调试（brew/apt 原生; 跨架构走 qemu-gdb）"),
    _auto("gdb-pwndbg", _BIN, "带 pwndbg 的 gdb（堆调试: heap/vis_heap_chunks/tcache）"),
    _auto("gdbserver", _BIN, "远程调试服务端（linux gdb / mac 容器）"),
    _auto("bloodhound", _BIN, "AD 关系图谱分析（brew/apt 原生; 采集端 nxc --bloodhound）"),
    _auto("smtp-user-enum", _WEB + _BIN, "SMTP 用户枚举（VRFY/EXPN/RCPT）"),
    _auto("marshalsec", _BIN, "Java 反序列化链生成（预编译 jar+便携 JDK）"),
    _auto("ghidra-headless", _BIN, "Ghidra 无头分析（官方便携 zip，需 JDK）"),
    _auto("msfvenom", _BIN, "payload 生成器（brew metasploit / apt 原生）"),
    _auto("socat", _BIN, "双向数据流/端口转发/反弹中继（brew/apt 原生）"),
    _auto("stegsnow", _BIN, "snow 空格/TAB 隐写（linux 原生 / mac 容器）"),
    _auto("foremost", _BIN, "按文件头雕刻分离（brew/apt 原生）"),
    _auto("aircrack-ng", _BIN, "WPA 握手包爆破+无线全套（brew/apt 原生）"),
    _auto("testdisk", _BIN, "磁盘分区恢复（brew/apt 原生）"),
    _auto("photorec", _BIN, "被删文件雕刻恢复（testdisk 原生）"),
    _auto("nikto", _WEB, "web 服务器配置扫描（brew/apt 原生）"),
    _auto("pycdc", _BIN, "Python 3.9+ pyc 反编译（源码编译原生）"),
    _auto("fscan", _WEB + _BIN, "内网综合扫描: 端口+服务+弱口令+漏洞一键扫"),
    _auto("yafu", _BIN, "RSA 大 N 本地分解 ECM/SIQS（linux/win; mac 用 rsactftool/factordb）"),
    _auto("jwt_tool", _WEB, "JWT 解析/伪造/alg 混淆攻击/弱密爆破"),
    _auto("weevely", _WEB, "加密混淆 Webshell 生成+管理（CLI）"),
    _auto("sstv", _BIN, "SSTV 音频转图像（MISC 音频隐写）"),
    _auto("aleapp", _BIN, "Android 取证工件解析（时间线/应用数据）"),
    _auto("ileapp", _BIN, "iOS 取证工件解析"),
    _auto("ilspycmd", _BIN, ".NET 反编译（dnSpy 的 CLI 等价; dotnet runtime 8）"),
    ToolField(name="git-bash", agents=["all"], required=False, version_cmd=[],
              description="Git Bash 运行时自举（仅 Windows: opencode shell 前提，系统版优先便携版兜底）",
              platforms=["win32"],
              install_hint="自动安装（Windows）: python control/backend/services/detect_tools.py install --tool git-bash"),
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
        """所有 agent 的工具状态：{agent_name: [ToolStatus, ...]}。

        "all" 键 = 当前平台全部工具（scanner/前端全量视图用）——
        不能依赖 t.agents 里出现 "all" 值（如 git-bash 是 win32-only，
        mac/linux 上平台过滤后匹配为空，导致 all 恒为空列表的 bug）。
        """
        table = self.scan_all_parallel()
        all_agents: set[str] = {"all"}
        for t in EXTERNAL_TOOLS:
            all_agents.update(t.agents)
        return {
            agent: [table[t.name] for t in EXTERNAL_TOOLS
                    if (agent == "all" or self._agent_has_tool(t, agent))
                    and self._platform_matches(t)]
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
        # 回落: CMD_DIR 安装的二进制/wrapper（后端进程无插件注入的 PATH，需显式查）
        bin_cand = os.path.join(CMD_DIR, tool.name + (".exe" if os.name == "nt" else ""))
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

    产物布局: 二进制 → CMD_DIR; jar/克隆仓库 → TOOLS_HOME_DIR/<name>/ + CMD_DIR wrapper。
    幂等: PATH 已有同名命令 或 CMD_DIR 产物齐全 → 跳过（--force 重装）。
    """

    TIMEOUT = 120  # 单请求超时（秒）——大文件下载分块流式写

    # wrapper 模板（占位 {NAME}/{IMAGE}/{NET}/{EXTRA}——shell 的 ${...} 不冲突）
    _WRAPPER_TMPL = r"""#!/bin/sh
# Docker wrapper (auto-generated): {NAME} -> {IMAGE}
# ── MSYS (Git Bash) 兼容 ──
# 1) 禁用 MSYS 参数自动转换: 否则 -v 的容器侧路径 /work、/usr/share/... 会被改写成
#    C:\Program Files\Git\work（Git Bash + docker 著名坑，挂载全烂）
# 2) 挂载源转 Windows 形态: docker.exe（native 程序）不认 /c/Users/x 形态，cygpath -w 转 C:/Users/x
#    （macOS/Linux 无 cygpath 且 uname 非 MINGW/MSYS → 分支不触发，行为不变）
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"
DIR="$(pwd)"
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*)
  command -v cygpath >/dev/null 2>&1 && DIR="$(cygpath -w "$DIR")"
  ;; esac
NAME="{NAME}-$$-$(date +%s)-$(od -An -N2 -tu2 /dev/urandom 2>/dev/null | tr -d " ")"
# 参数中工作目录/字典目录前缀 → 容器视角路径
# （AI 统一写 $WORDLISTS_DIR/xxx 一套心智，wrapper 自动重写——容器内无需该环境变量）
# 多形式匹配: AI 传参可能是 $(pwd) 的 MSYS 形态、$WORDLISTS_DIR 的 Windows 形态、或 $HOME 形态
# ⚠ 空模式防护: 变量为空（如 wrapper 在无 plugin 注入的手动终端跑）时 s|^|repl| 会给所有参数
#   加前缀——必须动态构造 sed 表达式，空变量规则自动跳过
WL_MSYS="$HOME/bw-security-analysis/wordlists"
WL_WIN="$WL_MSYS"
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*)
  command -v cygpath >/dev/null 2>&1 && WL_WIN="$(cygpath -w "$WL_MSYS")"
  ;; esac
_rw_add() { [ -n "$2" ] && RW_SED="${RW_SED:+$RW_SED;}s|^$(printf %s "$2" | sed 's/[\\&|]/\\&/g')|$3|"; }
RW_SED=""
_rw_add w "$DIR" /work
_rw_add wl "$WL_MSYS" /usr/share/wordlists-host
_rw_add wlw "$WL_WIN" /usr/share/wordlists-host
_rw_add envwl "$WORDLISTS_DIR" /usr/share/wordlists-host
rw_path() { if [ -n "$RW_SED" ]; then printf %s "$1" | sed "$RW_SED"; else printf %s "$1"; fi; }
ARGS=""; for a in "$@"; do ARGS="$ARGS $(rw_path "$a")"; done

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
    -w|-w[0-9]*) HAS_W=1; NEW_ARGS="$NEW_ARGS $(rw_path "$a")" ;;
    --workload-profile) HAS_W=1; NEW_ARGS="$NEW_ARGS $a" ;;
    *) NEW_ARGS="$NEW_ARGS $(rw_path "$a")" ;;
  esac
done
{W3CHECK}
ARGS="$NEW_ARGS"
{LONGCHECK}
trap 'docker kill "$NAME" 2>/dev/null' EXIT INT TERM
# 挂载源用 Windows 形态（WL_WIN; MSYS 下已 cygpath 转换，docker.exe 只认此形态;
# 非 MSYS 平台 WL_WIN = WL_MSYS 同值）。已知边界: 路径含空格（用户名 John Doe 类）时
# unquoted 展开会碎——历史既有形态，修复需模板数组化重构（shebang bash + 数组），待 Windows 真机验证时一并做
[ -d "$WL_MSYS" ] || WL_WIN=""
WL_ARG=""; [ -n "$WL_WIN" ] && WL_ARG="-v $WL_WIN:/usr/share/wordlists-host:ro"
# seclists 精确挂载到 kali 惯例路径（容器内工具/文档按 /usr/share/seclists 直接引用）
SECL_ARG=""; [ -n "$WL_WIN" ] && [ -d "$WL_MSYS/seclists" ] && SECL_ARG="-v $WL_WIN/seclists:/usr/share/seclists:ro"
# 容器内 timeout: 容器 1 号进程到时必死 → 容器退出 → --rm 生效（wrapper 被 SIGKILL 也不失联堆积）
# 注: timeout 必须是 shell 子进程——entrypoint 的 env-exec 链下 "exec timeout" 形态有 coreutils bug
{HASHCAT_ENV}exec docker run --rm -i --name "$NAME" {NET}{EXTRA} $HC_ENV $SECL_ARG \
  -e PUID=$(id -u) -e PGID=$(id -g) \
  -v "$DIR":/work $WL_ARG -w /work \
  {IMAGE} sh -c "timeout \"$CTIMEOUT\" {NAME} \"\$@\"" _ $ARGS
"""

    _QEMU_TMPL = r"""#!/bin/sh
# 跨架构 gdb 调试 wrapper (auto-generated; docker-toolbox.md §4)
# 用法: qemu-gdb <binary> [gdb 参数...]  例: qemu-gdb ./pwn -ex "break main" -ex c
# 架构路由: arm64 ELF（容器同架构）→ gdb 直接调（ptrace 原生可用）
#           amd64 ELF → qemu gdbstub（binfmt 下 ptrace 失效的唯一可行模式; 动态自动 -L sysroot）
# MSYS (Git Bash) 兼容: 禁自动路径转换（防 -w /work 被改写）+ 挂载源转 Windows 形态（同 _WRAPPER_TMPL）
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"
BIN="${1:-./a.out}"; shift
case "$BIN" in /*) ;; *) BIN="./$BIN" ;; esac
DIR="$(pwd)"
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*)
  command -v cygpath >/dev/null 2>&1 && DIR="$(cygpath -w "$DIR")"
  ;; esac
# 容器名唯一性三重保证（与 _WRAPPER_TMPL 同标准）: PID + epoch + urandom
_rand_suffix() { od -An -N2 -tu2 /dev/urandom 2>/dev/null | tr -d " "; }
NAME="qemu-gdb-srv-$$-$(date +%s)-$(_rand_suffix)"
PROBE="qemu-gdb-probe-$$-$(date +%s)-$(_rand_suffix)"
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
        """按清单顺序安装全部; progress(name) 回调用于 UI 进度。

        Phase 0（逐工具循环前）: ①包管理器强制检查 ②linux 手动清单批量 which 检测
        （缺失合并一行命令报错退出——幂等，用户执行后重跑即过）。
        同名配方去重: 先 installed 者占名（如 hashcat: win 便携 UrlRecipe 与
        mac/linux PkgToolRecipe 并存，按平台各自命中）。
        """
        check_package_manager()
        tools = installable_tools()
        manual = ManualCheck(
            items=[ManualItem(r.name, r.pkg_linux)
                   for r in tools if isinstance(r, PkgToolRecipe) and r.pkg_linux] + [
                # 脚本生态运行时/构建链前置（GemRecipe/GitRecipe(prereq_cmd)/SrcRecipe(cmake) 的宿主依赖）
                ManualItem("ruby", "ruby"),      # zsteg/seccomp-tools
                ManualItem("php", "php"),        # phpggc
                ManualItem("cmake", "cmake"),    # pycdc
                ManualItem("git", "git"),        # 源码类克隆
                ManualItem("gcc", "build-essential"),  # 源码编译
                ManualItem("qemu-x86_64", "qemu-user"),  # qemu-gdb 跨架构用户态模拟
            ],
            note="个别安全工具仅在 Kali 源中（如 wpscan/netexec），Debian/Ubuntu 无对应包时跳过该项重跑即可")
        run_manual_checks([manual])
        results: list[InstallResult] = []
        seen: set[str] = set()
        for recipe in tools:
            if recipe.name in seen:
                continue
            if progress:
                progress(recipe.name)
            res = self.install_recipe(recipe, force=force)
            results.append(res)
            if res.status == "installed":
                seen.add(recipe.name)
        return results

    def install_tool(self, name: str, force: bool = False) -> InstallResult:
        """按名安装单个工具。"""
        for recipe in installable_tools():
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
            if isinstance(recipe, PkgToolRecipe):
                return self._install_pkgtool(recipe, force)
            if isinstance(recipe, GemRecipe):
                return self._install_gem(recipe, force)
            if isinstance(recipe, SrcRecipe):
                return self._install_src(recipe, force)
            if isinstance(recipe, ScriptRecipe):
                return self._install_script(recipe, force)
            if isinstance(recipe, PrebuiltRecipe):
                return self._install_prebuilt(recipe, force)
            if isinstance(recipe, NodeRecipe):
                return self._install_node(recipe, force)
            if isinstance(recipe, DirRecipe):
                return self._install_dir(recipe, force)
            if isinstance(recipe, DotnetRecipe):
                return self._install_dotnet(recipe, force)
            if isinstance(recipe, JdkRecipe):
                return self._install_jdk(recipe, force)
            if isinstance(recipe, WordlistRecipe):
                return self._install_wordlist(recipe, force)
            if isinstance(recipe, GitBashRecipe):
                return self._install_gitbash(recipe, force)
            return InstallResult(name=recipe.name, status="failed", detail="未知配方类型")
        except Exception as exc:  # noqa: BLE001 —— 安装器兜底: 单工具失败不中断整体
            return InstallResult(name=recipe.name, status="failed", detail=f"{type(exc).__name__}: {exc}")

    # ── 幂等判断 ──

    def _already(self, name: str, bins: list[str], force: bool) -> str | None:
        """返回跳过原因; None=需要安装。"""
        if force:
            return None
        if shutil.which(name):
            return f"PATH 已有 {name}（已安装，跳过）"
        if bins and all(os.path.exists(self._bin_path(b)) for b in bins):
            return f"{CMD_DIR} 产物已齐全"
        return None

    @staticmethod
    def _bin_path(bin_name: str) -> str:
        """CMD_DIR 产物路径（Windows 自动补 .exe）。"""
        if os.name == "nt" and not bin_name.endswith(".exe") and "." not in bin_name:
            bin_name += ".exe"
        return os.path.join(CMD_DIR, bin_name)

    # ── GitHub Releases ──

    def _install_release(self, r: ReleaseRecipe, force: bool) -> InstallResult:
        skip = self._already(r.name, r.bins, force)
        if skip:
            return InstallResult(r.name, "skipped", skip)
        if r.prereq == "java":
            jerr = self._java_check(getattr(r, "java_min", 0))
            if jerr:
                return InstallResult(r.name, "skipped", jerr)
        plat = _plat_key()
        if r.kind != "jar" and plat not in r.plats:
            return InstallResult(r.name, "skipped", f"平台 {plat} 无配方")
        if r.kind == "jar":
            return self._install_jar(r, force)
        assets, tag = self._gh_assets(r.repo, r.tag)
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
        assets, tag = self._gh_assets(r.repo, r.tag)
        asset = self._match_assets(assets, [r.jar_kw], r.excl)[0] if self._match_assets(assets, [r.jar_kw], r.excl) else None
        if not asset:
            return InstallResult(r.name, "failed", f"{r.repo}@{tag} 无 jar 资产")
        dst_dir = os.path.join(TOOLS_HOME_DIR, r.name)
        os.makedirs(dst_dir, exist_ok=True)
        jar_path = os.path.join(dst_dir, asset)
        wrapper = os.path.join(CMD_DIR, r.name)
        # java 解析: 便携 tools/jdk 优先（绝对路径硬编码进 wrapper，无系统 java 的机器也能跑）
        javabin, _ = self._resolve_java()
        java_argv = [javabin, "-jar", jar_path] if javabin else ["java", "-jar", jar_path]
        if os.path.exists(jar_path) and not force:
            if not os.path.exists(wrapper):  # jar 在而 wrapper 缺 → 补 wrapper
                self._wrapper(r.name, java_argv)
                return InstallResult(r.name, "installed", "补生成 wrapper（jar 已存在）")
            return InstallResult(r.name, "skipped", f"jar 已存在 {asset}")
        self._write(self._download(_GH_DL.format(repo=r.repo, tag=tag, asset=asset)), jar_path)
        self._wrapper(r.name, java_argv)
        return InstallResult(r.name, "installed", f"{asset} + wrapper")

    def _install_tree(self, r: ReleaseRecipe, url: str, asset: str, data: bytes | None = None,
                      entry: str = "") -> InstallResult:
        """整归档解压到 TOOLS_HOME_DIR/<name>/，wrapper 指向 entry（默认取 r.entry）。"""
        entry = entry or r.entry
        dst = os.path.join(TOOLS_HOME_DIR, r.name)
        if os.path.isdir(dst) and os.path.exists(os.path.join(dst, entry)):
            return InstallResult(r.name, "skipped", "源码树已存在")
        if data is None:
            data = self._download(url)
        extract_dir = tempfile.mkdtemp(prefix=f"inst-{r.name}-")
        self._extract(data, asset, extract_dir)
        # 归档可能带顶层目录 → 取包含 entry 的根
        src_root = extract_dir
        if not os.path.exists(os.path.join(src_root, entry)):
            for d in os.listdir(extract_dir):
                if os.path.exists(os.path.join(extract_dir, d, entry)):
                    src_root = os.path.join(extract_dir, d)
                    break
        if not os.path.exists(os.path.join(src_root, entry)):
            return InstallResult(r.name, "failed", f"归档内未找到入口 {r.entry}")
        shutil.copytree(src_root, dst, dirs_exist_ok=True)
        entry_abs = os.path.join(dst, entry)
        self._chmodx(entry_abs)
        # zip/tar 提取可能丢失执行位: 入口内部调用的 .sh（如 ghidra launch.sh）也要可执行
        for dp, _dn, fns in os.walk(dst):
            for fn in fns:
                if fn.endswith(".sh"):
                    self._chmodx(os.path.join(dp, fn))
        exports = None
        if getattr(r, "prereq", "") == "java":
            _jb, jhome = self._resolve_java()
            if jhome:
                exports = {"JAVA_HOME": jhome}  # 便携 tools/jdk 优先，系统 java 兜底
        self._wrapper(r.name, [entry_abs], exports=exports)
        return InstallResult(r.name, "installed", f"{asset} → wrapper {r.name}")

    # ── git / pip ──

    def _install_git(self, r: GitRecipe, force: bool) -> InstallResult:
        prefix = _plat_key().split("-")[0]
        if r.platforms and prefix not in r.platforms:
            return InstallResult(r.name, "skipped", f"平台 {prefix} 非本配方目标（回落 docker）")
        if r.prereq_cmd and not shutil.which(r.prereq_cmd):
            return InstallResult(r.name, "failed",
                                 f"需要 {r.prereq_cmd} 运行时（linux: {PM_PREFIX or '<PM>'} install -y {r.prereq_cmd}; "
                                 f"mac: brew install {r.prereq_cmd}）")
        dst = os.path.join(TOOLS_HOME_DIR, r.name)
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
        wrapper = os.path.join(CMD_DIR, r.name)
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
        self._run_git_setup(r, dst)  # setup 可能生成入口（如 pwndbg setup.sh 生成 ./gdb）——先跑再校验
        if not os.path.exists(entry_abs):
            return InstallResult(r.name, "failed", f"克隆/构建后未找到入口 {r.entry}")
        self._install_git_wrapper(r, dst, entry_abs)
        return InstallResult(r.name, "installed", f"clone {r.repo} + wrapper")

    def _run_git_setup(self, r: GitRecipe, dst: str) -> None:
        """可选克隆后构建脚本（如 pwndbg setup.sh; 幂等由脚本自身保证，失败抛出）。"""
        if not r.setup:
            return
        sp = os.path.join(dst, r.setup)
        self._chmodx(sp)
        saved = os.getcwd()
        os.chdir(dst)
        try:
            self._run([f"./{r.setup}"])
        finally:
            os.chdir(saved)

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
            return InstallResult(r.name, "skipped", f"平台 {plat} 无直链配方（需为该平台补充 urls）")
        tail = url.rsplit("/", 1)[-1]
        # sourceforge 等 "/download" 尾段非真实文件名 → 取倒数第二段推断扩展名
        asset = tail if tail != "download" else url.rsplit("/", 2)[-2]
        data = self._download(url)
        entry = r.entries.get(plat, "")
        if entry:  # 整树安装（保持目录布局; entry 依赖相对路径的产物，按平台指定）
            return self._install_tree(r, url, asset, data=data, entry=entry)
        self._place_from_archive(r, data, asset)
        return InstallResult(r.name, "installed", f"{asset} → {', '.join(r.bins)}")

    # ── 预编译层 ──

    # ── Node.js 运行时（目录结构安装） ──

    def _install_node(self, r: NodeRecipe, force: bool) -> InstallResult:
        """解包官方归档到 TOOLS_HOME_DIR/node/，CMD_DIR 生成 node/npm/npx wrapper。"""
        if not force:
            skip = self._node_skip_reason()
            if skip:
                # 本机 node 合格: 清理历史残留（tools/node 目录 + bin/ 三个 wrapper）
                # —— 保证"tools/node 目录存在 ⟺ 本机 node 不可用"，plugin 据此决定是否注入 PATH
                stale = os.path.join(TOOLS_HOME_DIR, "node")
                if os.path.isdir(stale):
                    shutil.rmtree(stale)
                for b in ("node", "npm", "npx"):
                    p = self._bin_path(b)
                    if os.path.exists(p):
                        os.remove(p)
                return InstallResult("node", "skipped", skip + "; 已清理历史残留")
            if os.path.isdir(os.path.join(TOOLS_HOME_DIR, "node")):
                return InstallResult("node", "skipped", "tools/node 官方目录已解包")

        syst, arch = _plat_key().split("-")
        arch = {"amd64": "x64", "arm64": "arm64"}.get(arch, arch)
        if syst == "win":
            asset = f"node-v{r.version}-win-{arch}.zip"
            node_bin = "node.exe"
            npm_cli = os.path.join("node_modules", "npm", "bin", "npm-cli.js")
        else:
            asset = f"node-v{r.version}-{syst}-{arch}.tar.gz"
            node_bin = os.path.join("bin", "node")
            npm_cli = os.path.join("lib", "node_modules", "npm", "bin", "npm-cli.js")
        plat_dir = asset[:-(".zip" if syst == "win" else ".tar.gz").__len__()]

        url = f"https://nodejs.org/dist/v{r.version}/{asset}"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, asset)
            self._write(self._download(url), path)
            dest = os.path.join(TOOLS_HOME_DIR, "node")
            if os.path.isdir(dest):
                shutil.rmtree(dest)
            os.makedirs(dest, exist_ok=True)
            if asset.endswith(".zip"):
                with zipfile.ZipFile(path) as zf:
                    zf.extractall(dest)
            else:
                subprocess.run(["tar", "-xzf", path, "-C", dest], check=True)
            root = os.path.join(dest, plat_dir)
            for rel in (node_bin, npm_cli):
                if not os.path.exists(os.path.join(root, rel)):
                    return InstallResult("node", "failed", f"归档内未找到 {rel}")

        # 官方目录原样使用（不生成 wrapper）: darwin/linux 的 bin/ 内 node 与 npm/npx 软链同目录
        # （shebang #!/usr/bin/env node 在同目录命中）; win 的 npm.cmd 优先同目录 node.exe（官方兜底）。
        # PATH 注入由 plugin shell.env 完成: 检测本目录存在 → 注入 bin/（posix）或根目录（win）。
        inst_dir = os.path.join(TOOLS_HOME_DIR, "node", plat_dir)
        return InstallResult("node", "installed", f"v{r.version} LTS 官方目录 → {inst_dir}（plugin 注入 PATH）")

    # npm 10（v22 LTS 配套）要求的最低 node 版本; 更老的 node 会被跳过逻辑静默接受导致 npm install 失败
    NODE_MIN = (18, 17, 0)

    def _node_skip_reason(self) -> str | None:
        """PATH 有 node+npm 且版本 >= 18.17 才跳过; 老版本返回 None（继续装 v22 到 CMD_DIR，PATH 遮蔽老 node）。"""
        node, npm = shutil.which("node"), shutil.which("npm")
        if not (node and npm):
            return None
        try:
            out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=15).stdout.strip()
            ver = tuple(int(x) for x in out.lstrip("v").split(".")[:3])
        except (ValueError, subprocess.SubprocessError):
            return f"PATH node 版本不可解析，装 v22 到 {CMD_DIR}"
        if ver >= self.NODE_MIN:
            return f"PATH 已有 node {out} + npm（>= 18.17 满足 npm 10）"
        return None  # 老版本: 不跳过，CMD_DIR 装 v22（plugin PATH 序 toolBin 在前，遮蔽老 node）

    # ── 直链归档 → 固定目录（官方布局原样） ──

    def _install_dir(self, r: DirRecipe, force: bool) -> InstallResult:
        """adb 类工具: PATH 无命令 → 下载官方 zip 内容平铺到 TOOLS_HOME_DIR/<dest>/。"""
        dest = os.path.join(TOOLS_HOME_DIR, r.dest)
        if not force:
            if shutil.which(r.name):
                # 本机已有（系统/手动安装）: 清理残留，维护"目录存在 ⟺ PATH 无该工具"（plugin 据此注入）
                if os.path.isdir(dest):
                    shutil.rmtree(dest)
                return InstallResult(r.name, "skipped", f"PATH 已有 {r.name}（{shutil.which(r.name)}）; 已清理历史残留")
            marker = r.marker + (".exe" if os.name == "nt" else "")
            if os.path.isdir(dest) and os.path.exists(os.path.join(dest, marker)):
                return InstallResult(r.name, "skipped", f"{dest} 已解包")

        syst = _plat_key().split("-")[0]
        url = r.urls.get(syst) or r.urls.get(syst.split("-")[0])
        if not url:
            return InstallResult(r.name, "failed", f"平台 {_plat_key()} 无下载直链")

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dl.zip")
            self._write(self._download(url), path)
            extract_dir = os.path.join(tmp, "x")
            with zipfile.ZipFile(path) as zf:
                zf.extractall(extract_dir)
                # Python zipfile 不恢复可执行位——按 external_attr 恢复（0 则兜底 755，否则 adb 无法执行）
                for zi in zf.infolist():
                    if zi.is_dir():
                        continue
                    mode = (zi.external_attr >> 16) & 0o7777
                    if mode == 0:
                        mode = 0o755
                    out = os.path.join(extract_dir, zi.filename)
                    if os.path.exists(out):
                        os.chmod(out, mode)
            if os.path.isdir(dest):
                shutil.rmtree(dest)
            os.makedirs(dest, exist_ok=True)
            # strip_top: 归档顶层单一目录 → 其内容平铺到 dest
            src = extract_dir
            if r.strip_top:
                entries = [e for e in os.listdir(extract_dir) if not e.startswith("__MACOSX")]
                if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
                    src = os.path.join(extract_dir, entries[0])
            for e in os.listdir(src):
                shutil.move(os.path.join(src, e), os.path.join(dest, e))
            marker = r.marker + (".exe" if os.name == "nt" else "")
            if not os.path.exists(os.path.join(dest, marker)):
                return InstallResult(r.name, "failed", f"解包后未找到 {marker}")
        return InstallResult(r.name, "installed", f"官方目录 → {dest}（plugin 注入 PATH）")

    def _install_prebuilt(self, r: PrebuiltRecipe, force: bool) -> InstallResult:
        """仓库内预编译二进制 → 拷贝 CMD_DIR（平台不匹配跳过——Mach-O 跨平台不可执行）。"""
        if r.platforms and sys.platform not in r.platforms:
            return InstallResult(r.name, "skipped", f"平台 {sys.platform} 不适用（{'/'.join(r.platforms)} 专用）")
        if not force and os.path.exists(self._bin_path(r.name)):
            return InstallResult(r.name, "skipped", "CMD_DIR 已存在")
        src = os.path.join(_opencode_root(), r.source)
        if not os.path.isfile(src):
            return InstallResult(r.name, "failed", f"预编译产物缺失: {r.source}（需 macOS 环境执行 tools/build-class-dump.sh 重建）")
        if r.jar:  # 自包含 jar: 拷 tools/<name>/ + java -jar wrapper（跨平台）
            javabin, _ = self._resolve_java()
            if not javabin:
                return InstallResult(r.name, "skipped", "需要 java（install.sh 会装便携 JDK）")
            dst_dir = os.path.join(TOOLS_HOME_DIR, r.name)
            os.makedirs(dst_dir, exist_ok=True)
            jar_path = os.path.join(dst_dir, os.path.basename(r.source))
            if r.jar_cp:
                self._wrapper(r.name, [javabin, "-cp", jar_path])
            else:
                self._wrapper(r.name, [javabin, "-jar", jar_path])
            return InstallResult(r.name, "installed", f"{r.source} + java wrapper")
        os.makedirs(CMD_DIR, exist_ok=True)
        shutil.copyfile(src, self._bin_path(r.name))
        self._chmodx(self._bin_path(r.name))
        return InstallResult(r.name, "installed", f"{r.source} → CMD_DIR")

    # ── .NET runtime + nuget 工具 ──

    def _install_dotnet(self, r: DotnetRecipe, force: bool) -> InstallResult:
        """runtime（共享目录）+ nupkg 工具 + wrapper。"""
        wrapper = self._bin_path(r.name)
        dll = os.path.join(TOOLS_HOME_DIR, r.name, f"{r.name}.dll")
        if not force and os.path.exists(wrapper) and os.path.exists(dll):
            return InstallResult(r.name, "skipped", "wrapper + dll 已存在")
        dotnet_exe = os.path.join(TOOLS_HOME_DIR, "dotnet",
                                  "dotnet.exe" if os.name == "nt" else "dotnet")
        # 1. runtime（共享: 已解包则跳过，多 .NET 工具只装一次）
        if not os.path.exists(dotnet_exe):
            url = r.runtime_url(_plat_key())
            if not url:
                return InstallResult(r.name, "failed", f"平台 {_plat_key()} 无 runtime 直链")
            data = self._download(url)
            dest = os.path.join(TOOLS_HOME_DIR, "dotnet")
            os.makedirs(dest, exist_ok=True)
            if url.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    zf.extractall(dest)
            else:
                with tarfile.open(fileobj=io.BytesIO(data)) as t:
                    try:
                        t.extractall(dest, filter="data")
                    except TypeError:
                        t.extractall(dest)  # noqa: S202 —— 官方 runtime 归档
            if not os.path.exists(dotnet_exe):
                return InstallResult(r.name, "failed", "runtime 解包后未找到 dotnet 可执行")
        # 2. nupkg（zip 格式; nuget v2 对 HEAD 404 但 GET 正常）
        nupkg_url = r._NUGET_URL.format(name=r.nuget_name, ver=r.nuget_version)
        if not os.path.exists(dll):
            data = self._download(nupkg_url)
            tool_dir = os.path.join(TOOLS_HOME_DIR, r.name)
            os.makedirs(tool_dir, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                prefix = f"tools/{r.net_target}/any/"
                members = [m for m in zf.namelist() if m.startswith(prefix)]
                if not members:
                    return InstallResult(r.name, "failed",
                                         f"nupkg 无 {prefix} 目标（检查 net_target）")
                for m in members:
                    rel = m[len(prefix):]
                    if not rel:
                        continue
                    out = os.path.join(tool_dir, rel)
                    if m.endswith("/"):
                        os.makedirs(out, exist_ok=True)
                        continue
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    with zf.open(m) as src, open(out, "wb") as fh:
                        shutil.copyfileobj(src, fh)
            if not os.path.exists(dll):
                return InstallResult(r.name, "failed", f"nupkg 解包后未找到 {r.name}.dll")
        # 3. wrapper: exec dotnet <name>.dll
        #     DOTNET_ROLL_FORWARD=LatestMajor: net6.0 目标 dll 在 runtime 8 上跨两个大版本
        #     前滚的必要条件（默认 Minor 只允许 6→7; 微软官方支持场景）
        os.makedirs(CMD_DIR, exist_ok=True)
        wpath = os.path.join(CMD_DIR, r.name)
        body = ("#!/bin/sh\n"
                "export DOTNET_ROLL_FORWARD=LatestMajor\n"
                f'exec "{dotnet_exe}" "{dll}" "$@"\n')
        with open(wpath, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        self._chmodx(wpath)
        return InstallResult(r.name, "installed",
                             f"runtime {r.runtime_version} + {r.nuget_name} {r.nuget_version} → wrapper")

    # ── 字典 ──

    def _install_wordlist(self, r: WordlistRecipe, force: bool) -> InstallResult:
        """字典三源: repo 克隆 / url 下载 / 仓库内目录复制 → WORDLISTS_DIR/<target>。"""
        dest = os.path.join(WORDLISTS_DIR, r.target)
        if not force:
            if r.url:  # 文件型: 存在且非空
                if os.path.isfile(dest) and os.path.getsize(dest) > 0:
                    return InstallResult(r.name, "skipped", f"{dest} 已存在")
            elif os.path.isdir(dest) and os.listdir(dest):  # 目录型: 非空
                return InstallResult(r.name, "skipped", f"{dest} 已存在")
        os.makedirs(WORDLISTS_DIR, exist_ok=True)
        if r.repo:
            if not shutil.which("git"):
                return InstallResult(r.name, "failed", "git 命令不存在")
            if os.path.isdir(dest):
                shutil.rmtree(dest)
            self._run(["git", "clone", "--depth", "1",
                       f"https://github.com/{r.repo}", dest])
            return InstallResult(r.name, "installed", f"clone {r.repo} → {dest}")
        if r.url:
            data = self._download(r.url)
            self._write(data, dest)
            return InstallResult(r.name, "installed",
                                 f"下载 {len(data) // 1048576}MB → {dest}")
        if r.source:
            src = os.path.join(_opencode_root(), r.source)
            if not os.path.isdir(src):
                return InstallResult(r.name, "failed", f"仓库内源缺失: {r.source}")
            if os.path.isdir(dest):
                shutil.rmtree(dest)
            shutil.copytree(src, dest)
            return InstallResult(r.name, "installed", f"复制 {r.source} → {dest}")
        return InstallResult(r.name, "failed", "repo/url/source 三源均未配置")

    # ── Windows Git Bash 自举 ──

    @staticmethod
    def _configure_opencode_shell(bash_exe: str) -> str:
        """写项目级 opencode.json 的 shell 键（JSON 合并保留其他键）。返回结果描述。"""
        path = os.path.join(_opencode_root(), "opencode.json")
        cfg: dict = {}
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    cfg = json.load(fh)
            except (json.JSONDecodeError, OSError):
                cfg = {}
        if cfg.get("shell") == bash_exe:
            return f"shell 已配置为 {bash_exe}"
        cfg["shell"] = bash_exe
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        return f"已写入 opencode.json: shell = {bash_exe}"

    def _install_gitbash(self, r: GitBashRecipe, force: bool) -> InstallResult:
        """Windows: 下载最新 PortableGit 便携版（按 CPU 架构）+ 写 shell 配置。"""
        if sys.platform != "win32":
            return InstallResult(r.name, "skipped", f"平台 {sys.platform} 无需 Git Bash")
        portable_dir = os.path.join(CMD_DIR, "git-portable")
        portable_bash = os.path.join(portable_dir, "bin", "bash.exe")
        if os.path.isfile(portable_bash) and not force:
            note = self._configure_opencode_shell(portable_bash)
            return InstallResult(r.name, "skipped", f"便携版已就绪; {note}")
        plat = _plat_key()   # win-amd64 / win-arm64
        kw = {"win-amd64": ["portablegit", "64-bit"],
              "win-arm64": ["portablegit", "arm64"]}.get(plat)
        if not kw:
            return InstallResult(r.name, "failed", f"平台 {plat} 无 PortableGit 资产映射")
        assets, tag = self._gh_assets(r.repo, "")
        cands = self._match_assets(assets, kw, "")
        if not cands:
            return InstallResult(r.name, "failed", f"{r.repo}@{tag} 无匹配资产（kw={kw}）")
        url = _GH_DL.format(repo=r.repo, tag=tag, asset=cands[0])
        with tempfile.TemporaryDirectory(prefix="gitbash-") as tmp:
            sfx = os.path.join(tmp, "portable-git.exe")
            self._write(self._download(url), sfx)
            if os.path.isdir(portable_dir):
                shutil.rmtree(portable_dir)
            result = subprocess.run([sfx, "-o", portable_dir, "-y"],
                                    capture_output=True, text=True, timeout=900)
        if result.returncode != 0 or not os.path.isfile(portable_bash):
            tail = (result.stderr or "").strip()[-150:]
            return InstallResult(r.name, "failed", f"PortableGit 自解压失败: {tail}")
        note = self._configure_opencode_shell(portable_bash)
        return InstallResult(r.name, "installed", f"{cands[0]} → {portable_dir}; {note}")

    # ── 容器层 ──

    @staticmethod
    def _java_check(min_major: int) -> str | None:
        """java 存在性+主版本检查。返回跳过原因; None=通过。

        优先便携 tools/jdk/（_resolve_java），无则查系统 java。
        min_major>0 时校验主版本（如 ghidra 12.x 需 JDK 21+——版本不足时装出的是
        运行时必挂的残骸，必须在安装期拦截）。
        """
        javabin, _home = ToolsInstaller._resolve_java()
        if not javabin:
            return "需要 java 运行时（未检测到; install.sh 会自动装便携 Temurin）"
        if min_major <= 0:
            return None
        try:
            rr = subprocess.run([javabin, "-version"], capture_output=True, text=True, timeout=15)
            ver = (rr.stderr or rr.stdout).split('"')[1] if '"' in (rr.stderr or rr.stdout) else ""
            major = int(ver.split(".")[0]) if ver else 0
            if major and major < min_major:
                return f"需要 JDK {min_major}+（当前 {ver}，重跑 install.sh 自动装便携版）"
        except (subprocess.TimeoutExpired, OSError, ValueError, IndexError):
            pass  # 解析失败不阻塞（存在性已过; 运行时问题交给工具自身报错）
        return None

    @staticmethod
    def _resolve_java() -> tuple[str | None, str | None]:
        """解析 java 可执行: ①便携 tools/jdk/（含一层版本目录容错）②系统 PATH。

        返回 (java_bin, java_home); 无则 (None, None)。
        """
        home = os.path.join(TOOLS_HOME_DIR, "jdk")
        java_name = "java.exe" if os.name == "nt" else "java"
        if os.path.isdir(home):
            cands = [home] + [os.path.join(home, d) for d in os.listdir(home)
                              if os.path.isdir(os.path.join(home, d))]
            for root in cands:
                jb = os.path.join(root, "bin", java_name)
                if os.path.exists(jb):
                    return jb, root
        sysjava = shutil.which("java")
        if sysjava:
            return sysjava, os.path.dirname(os.path.dirname(sysjava))
        return None, None

    # ── JDK 便携运行时 ──

    def _install_jdk(self, r: JdkRecipe, force: bool) -> InstallResult:
        """Adoptium 免版本直链 → 解包 TOOLS_HOME_DIR/jdk/（共享，已装则跳过）。"""
        java_name = "java.exe" if os.name == "nt" else "java"
        dest = os.path.join(TOOLS_HOME_DIR, "jdk")
        marker = None
        if os.path.isdir(dest):
            jb, _ = self._resolve_java()
            if jb and not force:
                return InstallResult(r.name, "skipped", f"便携 JDK 已存在（{jb}）")
        url = r.url(_plat_key())
        if not url:
            return InstallResult(r.name, "skipped", f"平台 {_plat_key()} 无 Adoptium 配方")
        asset = "jdk.zip" if url.endswith(".zip") else ("jdk.tar.gz" if "windows" not in url else "jdk.zip")
        data = self._download(url)  # Adoptium API 302 → 实际归档
        tmp = tempfile.mkdtemp(prefix="inst-jdk-")
        self._extract(data, asset, tmp)
        # 归档顶层为 jdk-21.x.x+jdk/ 类目录 → 平铺进 dest（幂等重建）
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        # 递归找 bin/java（macOS Temurin 为 <顶>/Contents/Home/bin/java 多层嵌套）
        java_name = "java.exe" if os.name == "nt" else "java"
        roots = []
        for dp, _dn, fn in os.walk(tmp):
            if java_name in fn and dp.endswith("bin"):
                roots.append(os.path.dirname(dp))
                break
        if not roots:
            return InstallResult(r.name, "failed", "解包后未找到 bin/java")
        os.makedirs(dest, exist_ok=True)
        shutil.copytree(roots[0], dest, dirs_exist_ok=True)
        return InstallResult(r.name, "installed",
                             f"Temurin {r.feature} → {dest}（JAVA_HOME 由消费方 wrapper 注入）")

    # ── gem / 源码编译 ──

    def _install_gem(self, r: GemRecipe, force: bool) -> InstallResult:
        """gem install --user-install（免 sudo）→ wrapper 指向 ~/.gem 真实 bin。"""
        if shutil.which(r.name):
            self._remove_stale_wrapper(r.name)
            return InstallResult(r.name, "skipped", f"PATH 已有 {r.name}")
        if not shutil.which("gem"):
            return InstallResult(r.name, "failed",
                                 "需要 ruby/gem（linux: "
                                 f"{PM_PREFIX or '<PM>'} install -y ruby; mac: brew install ruby）")
        self._run(["gem", "install", "--user-install", "--no-document", r.gem or r.name])
        # --user-install 落 ~/.gem/ruby/<ver>/bin/（三层; 用递归 glob 防层级差异）→ 定位真实 bin
        import glob as _g
        home = os.path.expanduser("~/.gem")
        hits = sorted(_g.glob(os.path.join(home, "**", "bin", r.name), recursive=True)
                      or _g.glob(os.path.join(home, "*", "bin", r.name)))
        if not hits:
            return InstallResult(r.name, "failed", "gem 安装后未在 ~/.gem 找到 bin")
        self._wrapper(r.name, [hits[-1]])
        return InstallResult(r.name, "installed", f"gem {r.gem or r.name} → {hits[-1]}")

    def _install_src(self, r: SrcRecipe, force: bool) -> InstallResult:
        """git clone → 构建（cmake|autotools）→ bins 递归定位到 CMD_DIR。"""
        if shutil.which(r.name):
            self._remove_stale_wrapper(r.name)
            return InstallResult(r.name, "skipped", f"PATH 已有 {r.name}")
        for tool in ("git", "gcc", "make"):
            if not shutil.which(tool):
                return InstallResult(r.name, "failed",
                                     f"构建链缺 {tool}（mac: CLT; linux: {PM_PREFIX or '<PM>'} install -y build-essential）")
        if r.build_sys == "cmake" and not shutil.which("cmake"):
            return InstallResult(r.name, "failed",
                                 f"需要 cmake（{PM_PREFIX or '<PM>'} install -y cmake / brew install cmake）")
        dst = os.path.join(TOOLS_HOME_DIR, r.name)
        if os.path.isdir(dst) and not force:
            return InstallResult(r.name, "skipped", "源码树已存在")
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        self._run(["git", "clone", "--depth", "1", f"https://github.com/{r.repo}", dst])
        saved = os.getcwd()
        os.chdir(dst)
        try:
            if r.build_sys == "cmake":
                self._run(["cmake", "."])
            else:
                cfg = os.path.join(dst, "configure")
                if os.path.exists(cfg):
                    self._chmodx(cfg)
                    self._run([f"./{r.setup or 'configure'}"] if False else ["./configure"])
            self._run(["make", "-j{}".format(os.cpu_count() or 2)])
        finally:
            os.chdir(saved)
        os.makedirs(CMD_DIR, exist_ok=True)
        placed = []
        for b in r.bins:
            found = self._find_file(dst, b)
            if not found:
                return InstallResult(r.name, "failed", f"构建产物未找到 {b}")
            dst_bin = self._bin_path(b)
            shutil.copyfile(found, dst_bin)
            self._chmodx(dst_bin)
            placed.append(b)
        return InstallResult(r.name, "installed", f"build {r.repo} → {','.join(placed)}")

    def _install_script(self, r: ScriptRecipe, force: bool) -> InstallResult:
        """内联脚本 → CMD_DIR（prereq 缺失给精确安装提示）。"""
        missing = [c for c in r.prereq_cmds if not shutil.which(c)]
        if missing:
            hint = {"darwin": f"brew install {' '.join(missing)}",
                    "linux": f"{PM_PREFIX or 'sudo <PM> install -y'} {' '.join(missing)}"}.get(
                        _plat_key().split('-')[0], "请安装: " + ' '.join(missing))
            return InstallResult(r.name, "failed", f"缺 {'/'.join(missing)} → {hint}")
        path = os.path.join(CMD_DIR, r.name)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(r.body)
        self._chmodx(path)
        return InstallResult(r.name, "installed", f"脚本 wrapper → {path}")

    # ── 包管理器源工具 ──

    def _install_pkgtool(self, r: PkgToolRecipe, force: bool) -> InstallResult:
        """按平台分发: mac=brew 自动安装（失败回落 docker）/ linux=手动（Phase0 已保证
        或单工具模式给命令提示）/ win 与"该平台 PM 无包"=docker 回落。"""
        prefix = _plat_key().split("-")[0]
        if shutil.which(r.name):
            self._remove_stale_wrapper(r.name)
            return InstallResult(r.name, "skipped", f"PATH 已有 {r.name}（系统/PM 安装）")
        if prefix == "darwin" and r.pkg_brew:
            try:
                rr = subprocess.run(["brew", "install", r.pkg_brew],
                                    capture_output=True, text=True, timeout=1800)
            except subprocess.TimeoutExpired:
                rr = None
            if rr and rr.returncode == 0:
                self._remove_stale_wrapper(r.name)
                return InstallResult(r.name, "installed", f"brew install {r.pkg_brew}")
            why = ((rr.stderr or rr.stdout or "超时").strip().splitlines() or ["?"])[-1][:120] if rr else "超时"
            res = self._install_docker(r.docker_spec(), force)
            return InstallResult(r.name, res.status,
                                 f"brew 失败({why}) → {res.detail}")
        if prefix == "linux" and r.pkg_linux:
            # 全量路径下 Phase0 已拦截缺失; 走到这里通常是 --tool 单装 → 给出精确命令
            return InstallResult(r.name, "failed",
                                 f"需手动安装: {PM_PREFIX or 'sudo <包管理器> install -y'} {r.pkg_linux}"
                                 "（完成后重跑 install.sh）")
        return self._install_docker(r.docker_spec(), force)

    def _remove_stale_wrapper(self, name: str) -> None:
        """系统/PM 已提供真身时，清理 CMD_DIR 的陈旧 docker wrapper。

        关键: CMD_DIR 在 PATH 首段，残留 wrapper 会永久遮蔽系统原生版
        （性能陷阱实例: brew Metal hashcat 被容器 CPU 版遮蔽 17 倍差距）。
        仅当"排除 CMD_DIR 后 PATH 仍能解析到真身"才清理。
        """
        w = self._bin_path(name)
        if not os.path.exists(w):
            return
        exe = name + (".exe" if os.name == "nt" else "")
        for d in os.environ.get("PATH", "").split(os.pathsep):
            if not d or os.path.abspath(d or ".") == os.path.abspath(CMD_DIR):
                continue
            cand = os.path.join(d, exe)
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                os.remove(w)
                return

    def _install_docker(self, r: DockerRecipe, force: bool) -> InstallResult:
        """容器工具: docker 缺失→skip 提示; 镜像缺→build（同镜像幂等一次）; 生成 wrapper。"""
        wrapper = os.path.join(CMD_DIR, r.name)
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
        os.makedirs(CMD_DIR, exist_ok=True)
        net = "--network host " if r.net_host else ""
        extra = (" ".join(r.extra_args) + " ") if r.extra_args else ""
        # 统一 sh wrapper（Windows 走 Git Bash/WSL 执行——与 install.sh 同前提;
        # 历史 .cmd 分支已删: 双语言维护腐化快且无法实测，见 docker-toolbox.md）
        path = os.path.join(CMD_DIR, r.name)
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
        path = os.path.join(CMD_DIR, r.name)
        body = self._QEMU_TMPL.replace("{IMAGE}", r.image)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        self._chmodx(path)

    # ── 底层操作 ──

    def _place_from_archive(self, r, data: bytes, asset: str) -> None:
        """归档/裸二进制 → 提取 r.bins 到 CMD_DIR（归档内递归按名查找）。"""
        os.makedirs(CMD_DIR, exist_ok=True)
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
                # 归档内唯一文件时按目标名落盘（上游命名带平台后缀的场景，如 xray_darwin_arm64）
                import os as _os
                files = [_os.path.join(dp, f) for dp, _, fs in _os.walk(tmp) for f in fs]
                if len(files) == 1:
                    found = files[0]
                else:
                    raise RuntimeError(f"归档 {asset} 内未找到 {b}")
            dst = self._bin_path(b)
            shutil.copyfile(found, dst)
            self._chmodx(dst)

    @staticmethod
    def _github_token() -> str:
        """GitHub API 认证（防未认证 60 次/小时配额耗尽——冷装一次全量会打满）。
        优先 GITHUB_TOKEN 环境变量，兜底 gh auth token（已登录 gh 的机器零配置）。"""
        tok = os.environ.get("GITHUB_TOKEN")
        if tok:
            return tok
        try:
            rr = subprocess.run(["gh", "auth", "token"], capture_output=True,
                                text=True, timeout=10)
            if rr.returncode == 0 and rr.stdout.strip():
                return rr.stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            pass
        return ""

    def _gh_assets(self, repo: str, tag: str = "") -> tuple[list[str], str]:
        url = (_GH_API.format(repo=repo) if not tag
               else f"https://api.github.com/repos/{repo}/releases/tags/{tag}")
        headers = dict(_UA)
        tok = self._github_token()
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            d = json.loads(resp.read().decode())
        assets = [a["name"] for a in d.get("assets", [])]
        if not assets:
            raise RuntimeError(f"{repo}@{tag or 'latest'} 无二进制资产")
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
        elif lower.endswith(".7z"):  # 官方 7z 归档（如 hashcat win 便携包）
            import py7zr  # 声明于 detect_py_deps（PyPkgField），venv 必有
            with py7zr.SevenZipFile(io.BytesIO(data)) as z:
                z.extractall(dest)
        else:
            raise RuntimeError(f"不支持的归档类型 {asset}")

    @staticmethod
    def _chmodx(path: str) -> None:
        mode = os.stat(path).st_mode
        os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def _wrapper(self, name: str, argv: list[str], cwd: str = "", envp: str = "",
                 exports: dict[str, str] | None = None) -> None:
        """生成 CMD_DIR sh wrapper，幂等覆盖; cwd 先 cd; envp 附加 PYTHONPATH;
        exports 追加任意环境变量（如 ghidra 的 JAVA_HOME → 便携 JDK）。

        统一 sh（Windows 走 Git Bash/WSL 执行——与 docker wrapper/install.sh 同前提，单语言维护）。
        """
        os.makedirs(CMD_DIR, exist_ok=True)
        path = os.path.join(CMD_DIR, name)
        body = "#!/bin/sh\n"
        if cwd:
            body += f'cd "{cwd}"\n'
        if envp:
            body += f'export PYTHONPATH="{envp}:$PYTHONPATH"\n'
        for k, v in (exports or {}).items():
            body += f'export {k}="{v}"\n'
            if k == "JAVA_HOME":  # jdk bin 优先于系统（便携优先路由）
                body += 'export PATH="$JAVA_HOME/bin:$PATH"\n'
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
    return [r.name for r in installable_tools()]


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
        if fail:
            print("[!] 以下工具安装失败（知识库命令依赖它们，修复后单独重装）:")
            for r in fail:
                print(f"    python control/backend/services/detect_tools.py install --tool {r.name}")
            return 1
        return 0

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
