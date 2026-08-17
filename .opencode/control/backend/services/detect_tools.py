"""外部工具 + 编译器检测收口模块（ToolsScanner 类 + 强类型状态）。

其他模块禁止直接 shutil.which 检测工具（grep 唯一性，本模块是工具检测的唯一入口）。

注意：
  • IDA_PRO_HOME 通过 config_store 读（配置收口）
  • 其他工具（apktool/jadx 等）通过 shutil.which 检测 PATH
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from services import config_store


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
        return (resolved, True) if resolved else (tool.name, False)

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
                return (r.stdout.strip() or r.stderr.strip()).split("\n")[0] or None
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
