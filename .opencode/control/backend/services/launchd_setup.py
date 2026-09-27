"""macOS LaunchAgent 开机自启管理（远程节点部署用，darwin 限定）。

plist 契约:
  • Label: com.opensecurity.control
  • ProgramArguments: 当前解释器（sys.executable，venv python）+ server.py 绝对路径
  • RunAtLoad: 登录后自动拉起（LaunchAgent 语义——需开启系统自动登录）
  • StandardOut/ErrPath: DATA_DIR/logs/launchd.log（排查拉起失败）

部署提示（写入前端）: macOS 用户级 LaunchAgent 只在登录后运行——
Mac Mini 必须开启"自动登录"，否则重启后控制台不会起来。
"""
from __future__ import annotations

import logging
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AutostartStatus:
    """自启安装状态。"""

    supported: bool          # 平台支持（darwin）
    installed: bool          # plist 文件存在
    loaded: bool             # launchctl list 可见


class LaunchdManager:
    """LaunchAgent 安装/卸载/状态（全局单例）。"""

    _instance: "LaunchdManager | None" = None
    _instance_lock = __import__("threading").Lock()

    LABEL = "com.opensecurity.control"
    PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"

    def __new__(cls) -> "LaunchdManager":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> "LaunchdManager":
        return cls()

    @classmethod
    def _reset_for_tests(cls) -> None:
        with cls._instance_lock:
            cls._instance = None

    @staticmethod
    def _check_darwin() -> None:
        if platform.system() != "Darwin":
            raise RuntimeError(f"开机自启仅支持 macOS（当前 {platform.system()}）——"
                               "其他平台请用系统自带的服务管理器")

    @classmethod
    def _plist_content(cls) -> str:
        """生成 plist（解释器 + server.py 均绝对路径）。

        EnvironmentVariables 必带 OPENCODE_ROOT/DATA_DIR: LaunchAgent 无
        shell 环境，缺这两键时 ConfigManager 的 .ai_env 定位回退到相对
        路径（launchd 工作目录通常为 /）→ 节点以全默认配置启动并因
        心跳自杀退出（CONTROL_RESIDENT 等在 .ai_env 内可正常读到）。
        """
        import os
        from services.config_manager import ConfigManager
        cm = ConfigManager.get_instance()
        server_py = Path(__file__).resolve().parents[1] / "server.py"
        log_dir = Path(cm.data_dir) / "logs"
        oc_root = os.environ.get("OPENCODE_ROOT") or str(server_py.parents[2])
        data_dir = os.environ.get("DATA_DIR") or str(cm.data_dir)
        # 与 plugin spawn 白名单（buildSpawnEnv）语义对齐: launchd 默认 PATH 是
        # 系统安全路径（无 venv/node/brew），控制台子进程（vite/外部工具）需要
        # 完整 PATH; HOME 供 Path.home/expanduser 主路径。OFFLINE 不进 plist——
        # server.py setdefault 单一来源。PATH/HOME 缺失 = spawn 链异常（白名单
        # 必含），fail-fast 而非静默塞默认值（死 PATH 会让远程节点难排查）。
        env_path = os.environ.get("PATH")
        env_home = os.environ.get("HOME")
        if not env_path or not env_home:
            raise RuntimeError(
                f"生成 launchd plist 需要进程 env 含 PATH/HOME（当前: "
                f"PATH={'有' if env_path else '缺失'}, HOME={'有' if env_home else '缺失'}）"
                "——spawn 白名单链路异常，拒绝生成带默认死值的 plist"
            )
        # plist 是 XML: PATH 为自由格式用户文本，含 &/< 时须转义否则 launchctl load 失败
        from xml.sax.saxutils import escape as _xml_escape
        env_path = _xml_escape(env_path)
        env_home = _xml_escape(env_home)
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
        "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{cls.LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>{server_py}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>OPENCODE_ROOT</key>
        <string>{oc_root}</string>
        <key>DATA_DIR</key>
        <string>{data_dir}</string>
        <key>PATH</key>
        <string>{env_path}</string>
        <key>HOME</key>
        <string>{env_home}</string>
    </dict>
    <key>WorkingDirectory</key>
    <string>{server_py.parents[1]}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_dir}/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/launchd.log</string>
</dict>
</plist>
"""

    def install(self) -> dict:
        """安装 LaunchAgent（写 plist + launchctl load）。幂等（重复安装先卸载旧的）。"""
        self._check_darwin()
        if self.status().installed:
            self._unload()
        self.PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.PLIST_PATH.write_text(self._plist_content(), encoding="utf-8")
        self._load()
        logger.info("LaunchAgent 已安装: %s（提示: Mac 需开启自动登录）", self.PLIST_PATH)
        return {"installed": True, "plist": str(self.PLIST_PATH),
                "hint": "LaunchAgent 在登录后运行——设备需开启自动登录"}

    def uninstall(self) -> dict:
        """卸载 LaunchAgent（launchctl unload + 删 plist）。幂等。"""
        self._check_darwin()
        self._unload()
        if self.PLIST_PATH.exists():
            self.PLIST_PATH.unlink()
        logger.info("LaunchAgent 已卸载")
        return {"installed": False}

    def status(self) -> AutostartStatus:
        """查询安装状态（非 darwin 返回 supported=False 而非异常——供页面展示）。"""
        if platform.system() != "Darwin":
            return AutostartStatus(supported=False, installed=False, loaded=False)
        loaded = False
        try:
            r = subprocess.run(["launchctl", "list", self.LABEL],
                               capture_output=True, text=True, timeout=5)
            loaded = r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            loaded = False
        return AutostartStatus(supported=True, installed=self.PLIST_PATH.exists(), loaded=loaded)

    def _load(self) -> None:
        subprocess.run(["launchctl", "load", str(self.PLIST_PATH)],
                       capture_output=True, text=True, timeout=10, check=False)

    def _unload(self) -> None:
        if self.PLIST_PATH.exists():
            subprocess.run(["launchctl", "unload", str(self.PLIST_PATH)],
                           capture_output=True, text=True, timeout=10, check=False)
