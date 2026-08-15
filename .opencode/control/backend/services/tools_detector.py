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
