"""外部工具检测收口模块。

迁移自 detect_env.py 的 EXTERNAL_TOOLS 和相关检测函数。
其他模块禁止直接 shutil.which 检测工具（grep 唯一性，本模块是工具检测的唯一入口）。

注意：
  • IDA_PRO_HOME 通过 config_store 读（不再读环境变量，配置收口）
  • 其他工具（apktool/jadx 等）通过 shutil.which 检测 PATH
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

from services import config_store


@dataclass
class ToolField:
    """工具元数据。迁移自 detect_env.py 的 Dependency（精简版，去掉 install 相关字段）。"""
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


# ─── 工具清单（迁移自 detect_env.py EXTERNAL_TOOLS）─────────
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


# ─── 公共函数 ─────────────────────────────────────────────


def _platform_matches(tool: ToolField) -> bool:
    """检查工具是否适用于当前 OS。空 platforms = 全平台。"""
    return not tool.platforms or sys.platform in tool.platforms


def get_platform_install_hint(tool: ToolField) -> str:
    """返回当前 OS 的安装提示。优先 platform_install_hint[sys.platform]，降级到 install_hint。"""
    if tool.platform_install_hint:
        hint = tool.platform_install_hint.get(sys.platform)
        if hint:
            return hint
    return tool.install_hint or f"{tool.name} 未安装，请参考官方文档"


def resolve_tool_path(tool: ToolField) -> tuple[str, bool]:
    """解析工具路径。

    env_var 模式（ida_pro）：从 config_store 读 env_var 指向的目录，拼接 executable。
    其他：靠 PATH which。

    Returns:
        (resolved_path, found)
    """
    if tool.env_var:
        # 通过 config_store 读，不直接读环境变量（配置收口）
        home = config_store.read(tool.env_var) or ""
        if home:
            exe = tool.executable
            if os.name == "nt" and exe and not exe.endswith(".exe"):
                exe += ".exe"
            cand = os.path.join(home, exe)
            if exe and os.path.isfile(cand):
                return (cand, True)
        return ("", False)
    resolved = shutil.which(tool.name)
    if resolved:
        return (resolved, True)
    return (tool.name, False)


def get_tool_version(resolved_path: str, version_cmd: list[str]) -> str | None:
    """执行 version_cmd 获取版本字符串。空命令返回 None。"""
    if not version_cmd:
        return None
    try:
        r = subprocess.run(
            [resolved_path] + version_cmd,
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            return (r.stdout.strip() or r.stderr.strip()).split("\n")[0] or None
    except (subprocess.TimeoutExpired, OSError):
        return None
    return None


def scan_tool(tool: ToolField) -> dict:
    """扫描单个工具，返回状态字典。"""
    if not _platform_matches(tool):
        return {
            "name": tool.name,
            "description": tool.description,
            "required": tool.required,
            "available": False,
            "skipped": True,  # 当前平台不适用
            "version": None,
            "path": None,
            "install_hint": get_platform_install_hint(tool),
        }

    path, found = resolve_tool_path(tool)
    version = get_tool_version(path, tool.version_cmd) if found else None
    return {
        "name": tool.name,
        "description": tool.description,
        "required": tool.required,
        "available": found,
        "skipped": False,
        "version": version,
        "path": path if found else None,
        "install_hint": get_platform_install_hint(tool),
    }


def scan_agent(agent_name: str) -> list[dict]:
    """扫描指定 agent 的所有工具。

    Args:
        agent_name: agent 标识（如 "mobile-analysis"）

    Returns:
        该 agent 的所有工具状态列表。
    """
    return [
        scan_tool(tool)
        for tool in EXTERNAL_TOOLS
        if agent_name in tool.agents and _platform_matches(tool)
]


# ─── Python 包清单（迁移自 detect_env.py PYTHON_PACKAGES 的检测侧）─────────
# detect_env.py 是安装器（install.sh 跑，venv 未建时用），控制台是状态检测方。
# 两份清单需同步维护（加包时两边都加；install.sh 的安装入口只有 detect_env）。
# 注意 pip_name 才是 install.py 白名单的数据源（排除 conda 安装器特例）。


@dataclass
class PyPkgField:
    """Python 包元数据。"""
    name: str                     # import 名（mcp / sentence_transformers / ...）
    pip_name: str                 # pip 安装名（sentence-transformers / ...）
    agents: list[str]             # 使用方（["all"] = 全部）
    description: str = ""
    required: bool = True
    platforms: list[str] = field(default_factory=list)  # 空=全平台
    installer: str = "pip"        # pip / conda（conda 的不走 pip 白名单）


PYTHON_PACKAGES: list[PyPkgField] = [
    PyPkgField(name="mcp", pip_name="mcp", agents=["all"],
               description="MCP 协议库，knowledge/events MCP server 依赖"),
    PyPkgField(name="sentence_transformers", pip_name="sentence-transformers", agents=["all"],
               description="嵌入模型库，加载 BGE-M3 模型依赖"),
    PyPkgField(name="psutil", pip_name="psutil", agents=["all"],
               description="进程/内存监控库"),
    PyPkgField(name="fastapi", pip_name="fastapi", agents=["all"],
               description="控制台 Web 框架"),
    PyPkgField(name="portalocker", pip_name="portalocker", agents=["all"],
               description="控制台跨平台文件锁"),
    PyPkgField(name="sse_starlette", pip_name="sse-starlette", agents=["all"],
               description="控制台 SSE 推送（docker pull 进度）"),
    PyPkgField(name="sqlite_vec", pip_name="sqlite-vec", agents=["all"],
               description="SQLite 向量扩展，knowledge MCP 向量存储依赖"),
    PyPkgField(name="graphiti_core", pip_name="graphiti-core", agents=["all"],
               description="Graphiti 时序知识图谱库，events MCP server 依赖"),
    PyPkgField(name="httpx", pip_name="httpx", agents=["all"],
               description="HTTP 客户端库，MCP/控制台测试依赖"),
    PyPkgField(name="angr", pip_name="angr",
               agents=["binary-analysis", "mobile-analysis", "web-analysis", "crypto-analysis"],
               description="二进制分析/符号执行框架"),
    PyPkgField(name="triton", pip_name="triton-library", platforms=["linux", "win32"],
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
    PyPkgField(name="pyautogui", pip_name="pyautogui", agents=["binary-analysis"],
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
    PyPkgField(name="sage", pip_name="sagemath-standard", installer="conda",
               required=False, agents=["crypto-analysis"],
               description="数学软件系统（格归约/椭圆曲线）—— conda 安装，不可 pip"),
]


def scan_all() -> dict[str, list[dict]]:
    """扫描所有 agent 的所有工具。

    Returns:
        {agent_name: [tool_status, ...], ...}
    """
    # 收集所有 agent 名
    all_agents = set()
    for tool in EXTERNAL_TOOLS:
        all_agents.update(tool.agents)

    return {agent: scan_agent(agent) for agent in sorted(all_agents)}


# ─── Python 包检测 ────────────────────────────────────────


def scan_python_packages() -> list[dict]:
    """检测 venv 内 Python 包安装状态。

    控制台进程就跑在 venv 里，importlib.metadata 直接查当前环境。
    sage（conda 安装器）用 import 探测兜底（pip metadata 可能没有）。
    """
    import importlib.metadata
    import importlib.util

    result = []
    for pkg in PYTHON_PACKAGES:
        if not _platform_matches_pkg(pkg):
            continue
        version: str | None = None
        try:
            version = importlib.metadata.version(pkg.pip_name)
        except importlib.metadata.PackageNotFoundError:
            # pip 名与 distribution 名不一致的特例（sage）→ import 探测
            if importlib.util.find_spec(pkg.name) is not None:
                try:
                    version = importlib.metadata.version(pkg.name)
                except importlib.metadata.PackageNotFoundError:
                    version = ""
        result.append({
            "name": pkg.name,
            "pip_name": pkg.pip_name,
            "kind": "python",
            "description": pkg.description,
            "required": pkg.required,
            "installer": pkg.installer,       # pip / conda
            "agents": pkg.agents,
            "available": version is not None,
            "version": version,
        })
    return result


def pip_installable_packages() -> set[str]:
    """可经 pip 安装的包名集合（install.py 白名单数据源）。

    排除：conda 安装器特例（sage）、当前平台不适用的包。
    """
    return {
        pkg.pip_name
        for pkg in PYTHON_PACKAGES
        if pkg.installer == "pip" and _platform_matches_pkg(pkg)
    }


def _platform_matches_pkg(pkg: PyPkgField) -> bool:
    return not pkg.platforms or sys.platform in pkg.platforms
