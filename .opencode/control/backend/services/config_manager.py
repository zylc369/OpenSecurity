"""配置唯一权威（ConfigManager，Java 式全局单例）。

职责收口（原 config.py + services/config_store.py 全部合并）:
  • 引导参数: CONTROL_TCP_PORT / CONTROL_FRONTEND_DEV
    （路径类引导参数 OPENSECURITY_HOME / OPENCODE_ROOT 收口于 services.runtime_paths——
     .ai_env 路径本身由 OPENCODE_ROOT 决定，配置文件的位置无法从配置文件读取）
  • .ai_env 唯一读写: get/get_all/set/delete/ensure_template
  • 键名常量（Keys）/ 可调参数默认值（Defaults）/ 协议常量（Protocol）
  • 行为可调参数: remote/heartbeat/proxy 三组 tunables（.ai_env 优先，
    每次调用重读——改后即时生效; 非法值回退默认）
  • 配置元数据: ConfigField 四清单 + config_meta + required_status + validators

设计规则（后端 OOP 重构铁律）:
  • 单例模板: __new__ 双检锁 + _init_once（禁止 __init__）+ get_instance()
  • 常量只存在于嵌套静态类 / 服务类静态字段——模块级大写变量违规
  • 测试隔离: 修改引导 env 后 _reset_for_tests()/重建实例即得新快照（RuntimePaths.refresh 重读）
"""
from __future__ import annotations

import logging
import os
import re
import sys
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable, Literal, overload

from services.runtime_paths import RuntimePaths

logger = logging.getLogger(__name__)


class Surface(StrEnum):
    """配置渲染面（ConfigField 声明归属 + 接口请求参数值域）。

    请求参数值域仅 config|remote（Literal 校验，hidden 到不了 handler）;
    HIDDEN 是存储态: 无页面，手编 .ai_env 或专用端点管理。
    """

    CONFIG = "config"
    REMOTE = "remote"
    HIDDEN = "hidden"


class ConfigCategory(StrEnum):
    """配置分类（code=枚举值; desc 见 _DESC; 定义序=前端分组顺序）。

    分类描述由服务端权威下发（前端原样显示，不自行发挥）。
    """

    TOOLS = "tools"
    MODELS = "models"
    PROXY = "proxy"
    BEHAVIOR = "behavior"
    DEVELOPER = "developer"
    OTHER = "other"
    REMOTE = "remote"
    REMOTE_TUNING = "remote_tuning"
    SYSTEM = "system"

    @property
    def desc(self) -> str:
        return _CATEGORY_DESC[self]

    @classmethod
    def ordered(cls) -> "list[ConfigCategory]":
        """定义序（meta 响应 categories 的唯一顺序来源）。"""
        return list(cls)


_CATEGORY_DESC: dict[ConfigCategory, str] = {
    ConfigCategory.TOOLS: "工具",
    ConfigCategory.MODELS: "模型",
    ConfigCategory.PROXY: "代理",
    ConfigCategory.BEHAVIOR: "行为",
    ConfigCategory.DEVELOPER: "开发",
    ConfigCategory.OTHER: "其他",
    ConfigCategory.REMOTE: "远程",
    ConfigCategory.REMOTE_TUNING: "远程调参",
    ConfigCategory.SYSTEM: "系统",
}


@dataclass
class CategoryView:
    """分类视图（meta 响应内嵌; desc 为服务端权威文案）。"""

    code: str
    desc: str


@dataclass
class ConfigMetaView:
    """单 surface 的配置元数据视图（categories 只含有条目的分类，枚举序）。"""

    categories: list[CategoryView]
    entries: dict[str, "ConfigMetaEntry"]


@dataclass
class ConfigMetaEntry:
    """配置项元数据（config_meta 载荷; 字段名=JSON 键名）。

    不含 surface——整包响应已按请求面过滤（页面组成权在服务端）。
    """

    label: str
    type: str            # password / path / text / bool
    hint: str
    required: bool
    default_value: str
    category_code: str   # 分类 code（ConfigCategory 枚举值）
    category_desc: str   # 分类描述（服务端权威，前端原样显示）
    readonly: bool       # true = 任何页面禁用态渲染 + 写接口 422
    source: str


class ConfigManager:
    """全项目配置唯一权威（get_instance() 获取; 全进程单例）。"""

    _instance: "ConfigManager | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "ConfigManager":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._init_once()
                    cls._instance = inst
        return cls._instance

    @classmethod
    def get_instance(cls) -> "ConfigManager":
        return cls()

    @classmethod
    def _reset_for_tests(cls) -> None:
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance._shutdown_for_tests()
            cls._instance = None

    def _shutdown_for_tests(self) -> None:
        """测试重置收尾（本类无外部资源，空实现）。"""

    # ═══════════════ 嵌套静态类: 常量收口 ═══════════════

    class Bootstrap:
        """进程引导参数（路径解析见 services.runtime_paths）。

        CONTROL_TCP_PORT 由 Plugin spawn 或测试进程注入;
        CONTROL_FRONTEND_DEV 仅在 .ai_env 未定义该键时读 env（CI/无文件环境
        注入通道——文件一旦定义即为权威，env 同名值不参与）;
        OPENSECURITY_AI_ENV 重定向 .ai_env 路径（测试沙箱隔离用——生产
        env 白名单不含它，天然到不了生产进程）。
        """

        TCP_PORT_ENV = "CONTROL_TCP_PORT"
        FRONTEND_DEV_ENV = "CONTROL_FRONTEND_DEV"
        AI_ENV_OVERRIDE_ENV = "OPENSECURITY_AI_ENV"

    class Keys:
        """全部 .ai_env 键名常量（ConfigField 与消费方统一引用）。"""

        # 必要/常规配置
        DEEPSEEK_API_KEY = "DEEPSEEK_API_KEY"
        DEEPSEEK_MODEL = "DEEPSEEK_MODEL"
        DEEPSEEK_SMALL_MODEL = "DEEPSEEK_SMALL_MODEL"
        IDA_PRO_HOME = "IDA_PRO_HOME"
        CONTROL_FRONTEND_DEV = "CONTROL_FRONTEND_DEV"
        RESUME_ANALYSIS_ENABLED = "RESUME_ANALYSIS_ENABLED"
        # 反思提醒（插件 lib/reflection.ts 经 /api/config 消费; 语义: 未配置=启用）
        REFLECT_NUDGE_ENABLED = "REFLECT_NUDGE_ENABLED"
        REFLECT_NUDGE_INTERVAL_MIN = "REFLECT_NUDGE_INTERVAL_MIN"
        JULIANG_TRADE_NO = "JULIANG_TRADE_NO"
        JULIANG_API_KEY = "JULIANG_API_KEY"
        GITHUB_TOKEN = "GITHUB_TOKEN"
        HF_ENDPOINT = "HF_ENDPOINT"
        # 远程模型卸载: 本地侧三键
        REMOTE_CONSOLE_URL = "REMOTE_CONSOLE_URL"
        REMOTE_CONSOLE_ENABLED = "REMOTE_CONSOLE_ENABLED"
        REMOTE_CONSOLE_TOKEN = "REMOTE_CONSOLE_TOKEN"
        # 远程模型卸载: 节点侧三键
        CONTROL_API_KEY = "CONTROL_API_KEY"
        CONTROL_RESIDENT = "CONTROL_RESIDENT"
        CONTROL_AUTOSTART = "CONTROL_AUTOSTART"
        # 远程链接可调参数
        REMOTE_HEARTBEAT_INTERVAL_SEC = "REMOTE_HEARTBEAT_INTERVAL_SEC"
        REMOTE_FAIL_THRESHOLD = "REMOTE_FAIL_THRESHOLD"
        REMOTE_RECOVER_THRESHOLD = "REMOTE_RECOVER_THRESHOLD"
        REMOTE_UNLOAD_DELAY_SEC = "REMOTE_UNLOAD_DELAY_SEC"
        REMOTE_INFER_TIMEOUT_SEC = "REMOTE_INFER_TIMEOUT_SEC"
        REMOTE_PROBE_TIMEOUT_SEC = "REMOTE_PROBE_TIMEOUT_SEC"
        # 心跳协议可调参数
        HEARTBEAT_TIMEOUT_SEC = "HEARTBEAT_TIMEOUT_SEC"
        HEARTBEAT_SWEEP_INTERVAL_SEC = "HEARTBEAT_SWEEP_INTERVAL_SEC"
        HEARTBEAT_GRACE_SEC = "HEARTBEAT_GRACE_SEC"
        # 代理池可调参数
        JULIANG_IP_TTL_SEC = "JULIANG_IP_TTL_SEC"
        JULIANG_TTL_MARGIN_SEC = "JULIANG_TTL_MARGIN_SEC"
        PROXY_ROTATE_CONN_THRESHOLD = "PROXY_ROTATE_CONN_THRESHOLD"
        DOMAIN_COOLDOWN_SEC = "DOMAIN_COOLDOWN_SEC"
        ROTATE_HISTORY_LIMIT = "ROTATE_HISTORY_LIMIT"

    class Protocol:
        """协议/物理常量（plugin ↔ console 两端一致，不进 .ai_env）。"""

        # exit code 约定（Plugin 通过 exit code 判断控制台状态）
        EXIT_CODE_REUSE = 2            # 已有实例运行，本进程主动退出复用
        EXIT_CODE_PORT_EXHAUSTED = 3   # 候选端口全部占用
        EXIT_CODE_NORMAL = 0           # 正常退出（心跳表空，自杀）
        # IPC 与网络
        IS_WINDOWS = sys.platform == "win32"
        CONTROL_TCP_PORT_START = 9776  # 浏览器 TCP 通道候选段起点（顺延 +1）
        TCP_CANDIDATE_COUNT = 10
        BIND_HOST = "127.0.0.1"        # 仅本机（安全约束; 节点模式经节点配置放开）
        IPC_UNIX_SOCKET_NAME = "opensecurity-control.sock"
        # 6 位随机后缀：一次性生成写死（openssl rand），非运行期分配
        IPC_WINDOWS_PIPE = r"\\.\pipe\opensecurity-control-482964"
        # 模型
        EMBED_MODEL = "BAAI/bge-m3"
        RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
        # 超时（Plugin 端等待/轮询——TS 侧一致）
        MODEL_LOAD_TIMEOUT_SEC = 60
        HEALTH_POLL_INTERVAL_SEC = 2
        IPC_BIND_WAIT_SEC = 8
        # 代理 relay 端口段（9676 起 = 9776−100 反顺延方向，与控制台 TCP 段隔离）
        PROXY_RELAY_PORT_START = 9676
        PROXY_RELAY_PORT_CANDIDATES = 10
        # 代理 IP 供应商 API 地址（凭证存 .ai_env）
        JULIANG_API_URL = "http://v2.api.juliangip.com/company/dynamic/getips"

    # ═══════════════ tunables dataclass（E2 豁免形态）═══════════════

    @dataclass(frozen=True)
    class RemoteTunables:
        """远程链接可调参数（默认值唯一来源; .ai_env 优先，每轮重读即时生效）。"""

        heartbeat_interval_sec: float = 5.0   # 心跳探测周期
        fail_threshold: int = 2               # 连续失败→降级
        recover_threshold: int = 3            # 连续成功→恢复
        unload_delay_sec: float = 300.0       # 恢复后稳定期
        infer_timeout_sec: float = 30.0       # 推理请求超时
        probe_timeout_sec: float = 3.0        # 健康探测超时

    @dataclass(frozen=True)
    class HeartbeatTunables:
        """心跳协议可调参数（opencode 插件每 10s POST /api/heartbeat）。"""

        timeout_sec: float = 60.0     # 超时未跳 → 移除条目
        sweep_interval_sec: float = 10.0  # 后台 sweep 周期
        grace_sec: float = 90.0      # 启动宽限（覆盖 spawn 就绪等待+首跳）

    @dataclass(frozen=True)
    class ProxyTunables:
        """代理池可调参数（实测依据: 2026-09-25-proxy-ip-manager.md 附录A）。"""

        ip_ttl_sec: float = 300.0          # 单 IP 存活（5 分钟档）
        ttl_margin_sec: float = 30.0       # 到期安全余量
        rotate_conn_threshold: int = 35    # 新建连接数满此值自动轮换
        domain_cooldown_sec: float = 600.0 # 域名限流冷却
        rotate_history_limit: int = 50     # rotate_history 上限

    @dataclass
    class ConfigField:
        """配置字段元数据。"""
        key: str                                # .ai_env 中的 key
        label: str                              # 前端展示的中文名
        type: str                               # password / path / text / bool
        hint: str = ""                          # 字段说明 / 获取地址
        required: bool = True                   # 是否必要（缺失时 banner 提醒）
        validator: Callable[[str], tuple[bool, str]] | None = None
        default_value: str = ""                 # 不配置时后端默认值（回传前端）
        category: ConfigCategory = ConfigCategory.OTHER  # 分类（分组归属）
        surface: Surface = Surface.CONFIG       # 渲染面（页面归属声明）
        readonly: bool = False                  # 只读（禁用渲染 + 写接口 422）
        source: str = "ai_env"                  # 配置来源: ai_env=文件权威
                                                # （env 同名值不参与读取）

    # ═══════════════ 实例状态与构造 ═══════════════

    def _init_once(self) -> None:
        # 路径消费一律直读 RuntimePaths 类属性；构造时先重算快照：
        # - 生产：env 启动后不变，此处等价于"进程级一次快照"；
        # - 测试：pytest 同一进程内切换沙箱（改进程版 os.environ 后 _reset_for_tests()
        #   置空 _instance、重建单例对象，无 fork/子进程）——refresh 重算类属性。
        RuntimePaths.refresh()
        self._dev_mode = self._read_dev_mode_once()

    def _read_dev_mode_once(self) -> bool:
        """启动期一次性读取（.ai_env 优先——source=ai_env 键的文件是权威，
        env 同名值不参与; 文件未定义时 env 兜底——CI/无 .ai_env 环境注入通道）。"""
        path = self.ai_env_path
        if path.exists():
            key = self.Keys.CONTROL_FRONTEND_DEV
            for line in path.read_text(errors="ignore").splitlines():
                if line.strip().startswith(key + "="):
                    return line.split("=", 1)[1].strip().lower() in ("1", "true")
        env_val = os.environ.get(self.Bootstrap.FRONTEND_DEV_ENV)
        if env_val is not None:
            return env_val.strip().lower() in ("1", "true")
        return False

    # ═══════════════ 引导属性 ═══════════════

    @property
    def opensecurity_home(self) -> str:
        return RuntimePaths.OPENSECURITY_HOME

    @property
    def opencode_root(self) -> str:
        return RuntimePaths.OPENCODE_ROOT

    @property
    def ai_env_path(self) -> Path:
        override = os.environ.get(self.Bootstrap.AI_ENV_OVERRIDE_ENV)
        if override:
            return Path(os.path.abspath(os.path.expanduser(override)))
        return Path(RuntimePaths.OPENCODE_ROOT) / ".ai_env"

    @property
    def is_dev_mode(self) -> bool:
        return self._dev_mode

    @property
    def is_windows(self) -> bool:
        return self.Protocol.IS_WINDOWS

    def tcp_port_start(self) -> int:
        """TCP 候选段起点（Bootstrap env 可重定向——测试沙箱隔离用）。"""
        env_val = os.environ.get(self.Bootstrap.TCP_PORT_ENV)
        if env_val and env_val.isdigit():
            return int(env_val)
        return self.Protocol.CONTROL_TCP_PORT_START

    def ipc_unix_socket_path(self) -> Path:
        return Path(RuntimePaths.OPENSECURITY_HOME) / self.Protocol.IPC_UNIX_SOCKET_NAME

    def ipc_addr(self) -> str:
        """当前平台的 IPC 会合地址（Unix: 文件路径 / Windows: 管道名）。"""
        if self.is_windows:
            return self.Protocol.IPC_WINDOWS_PIPE
        return str(self.ipc_unix_socket_path())

    # ═══════════════ .ai_env 读写（唯一方）═══════════════

    def get(self, key: str) -> str | None:
        return self.get_all().get(key)

    def get_all(self) -> dict[str, str]:
        path = self.ai_env_path
        if not path.exists():
            return {}
        configs = self._parse(path.read_text(errors="ignore"))
        # 路径型配置读时归一化（expanduser + abspath；写侧保留原文）——消费者拿到的即绝对展开路径
        for field in self.required_configs() + self.extra_configs():
            if field.type == "path" and configs.get(field.key):
                configs[field.key] = os.path.abspath(os.path.expanduser(configs[field.key]))
        return configs

    def set(self, updates: dict[str, str]) -> dict[str, str]:
        """批量更新（保留注释 + 未改字段; 值统一 strip）。"""
        updates = {k: v.strip() if isinstance(v, str) else v for k, v in updates.items()}
        configs, raw_lines = self._read_with_comments()
        configs.update(updates)
        new_lines: list[str] = []
        updated_keys: set[str] = set()
        for line in raw_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                new_lines.append(line)
                continue
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                updated_keys.add(key)
            else:
                new_lines.append(line)
        for key, value in updates.items():
            if key not in updated_keys:
                new_lines.append(f"{key}={value}")
        self._atomic_write(self.ai_env_path, "\n".join(new_lines) + "\n")
        return configs

    def set_one(self, key: str, value: str) -> dict[str, str]:
        """更新单个配置（等价 set({key: value}）; 测试 monkeypatch 锚点）。"""
        return self.set({key: value})

    def delete(self, key: str) -> dict[str, str]:
        configs, raw_lines = self._read_with_comments()
        if key not in configs:
            return configs
        new_lines = [line for line in raw_lines
                     if not (line.strip() and not line.strip().startswith("#")
                             and "=" in line and line.strip().split("=", 1)[0].strip() == key)]
        self._atomic_write(self.ai_env_path, "\n".join(new_lines) + "\n")
        configs.pop(key, None)
        return configs

    _TEMPLATE = """\
# bw-security-analysis 环境变量配置
# 填完保存即可（控制台配置页读取；也可直接在控制台配置页设置，无需手编此文件）

# IDA Pro 安装目录（该目录下需有 idat 可执行文件）
# macOS: /Applications/IDA Professional 9.1.app/Contents/MacOS
# Linux: /opt/ida-9.0
# Windows: C:\\Program Files\\IDA Pro 9.0
IDA_PRO_HOME=

# DeepSeek API Key（events MCP 实体提取用，https://platform.deepseek.com 申请）
DEEPSEEK_API_KEY=
# events MCP 模型配置（可选，按需修改）
# DEEPSEEK_MODEL=deepseek-flash      # 核心提取模型（需要更强提取质量改成 deepseek-v4-pro）
# DEEPSEEK_SMALL_MODEL=deepseek-flash # 时间戳推断模型

# GitHub API 令牌（可选，外部工具下载加速防 60 次/小时配额耗尽；未配置时兜底 gh auth token）
# GITHUB_TOKEN=
# HuggingFace 端点（可选，国内直连不稳时配置镜像，如 https://hf-mirror.com）
# HF_ENDPOINT=
"""

    def ensure_template(self) -> bool:
        """首次运行创建带注释模板（幂等; 已存在不重写）。"""
        path = self.ai_env_path
        if path.exists():
            return False
        try:
            self._atomic_write(path, self._TEMPLATE)
            return True
        except OSError:
            return False

    @staticmethod
    def _parse(content: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key:
                result[key] = value.strip()
        return result

    def _read_with_comments(self) -> tuple[dict[str, str], list[str]]:
        path = self.ai_env_path
        if not path.exists():
            return {}, []
        raw_lines = path.read_text(errors="ignore").splitlines()
        return self._parse("\n".join(raw_lines)), raw_lines

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        """原子写（迁移期桥接 services.process_lock; 批次 D 后直连 ProcessLockUtil）。"""
        from services.process_lock import ProcessLockUtil
        ProcessLockUtil.atomic_write(path, content)

    # ═══════════════ tunables 读取器（.ai_env 优先，非法回退默认）═══════════════

    @overload
    def _read_num(self, vals: dict[str, str], key: str, default: float | int, as_int: Literal[True]) -> int: ...
    @overload
    def _read_num(self, vals: dict[str, str], key: str, default: float | int, as_int: Literal[False]) -> float: ...
    def _read_num(self, vals: dict[str, str], key: str, default: float | int, as_int: bool) -> float | int:
        raw = (vals.get(key) or "").strip()
        if not raw:
            return default
        try:
            return int(float(raw)) if as_int else float(raw)
        except ValueError:
            logger.warning("配置 %s=%r 非法（应为数字），回退默认 %s", key, raw, default)
            return default

    def remote_tunables(self) -> RemoteTunables:
        """远程链接可调参数（每次调用重读——心跳周期取值，改配置即时生效）。"""
        vals = self.get_all()
        d = self.RemoteTunables()
        k = self.Keys
        return self.RemoteTunables(
            heartbeat_interval_sec=self._read_num(vals, k.REMOTE_HEARTBEAT_INTERVAL_SEC, d.heartbeat_interval_sec, False),
            fail_threshold=self._read_num(vals, k.REMOTE_FAIL_THRESHOLD, d.fail_threshold, True),
            recover_threshold=self._read_num(vals, k.REMOTE_RECOVER_THRESHOLD, d.recover_threshold, True),
            unload_delay_sec=self._read_num(vals, k.REMOTE_UNLOAD_DELAY_SEC, d.unload_delay_sec, False),
            infer_timeout_sec=self._read_num(vals, k.REMOTE_INFER_TIMEOUT_SEC, d.infer_timeout_sec, False),
            probe_timeout_sec=self._read_num(vals, k.REMOTE_PROBE_TIMEOUT_SEC, d.probe_timeout_sec, False),
        )

    def heartbeat_tunables(self) -> HeartbeatTunables:
        """心跳协议可调参数（每轮 sweep 重读）。"""
        vals = self.get_all()
        d = self.HeartbeatTunables()
        k = self.Keys
        return self.HeartbeatTunables(
            timeout_sec=self._read_num(vals, k.HEARTBEAT_TIMEOUT_SEC, d.timeout_sec, False),
            sweep_interval_sec=self._read_num(vals, k.HEARTBEAT_SWEEP_INTERVAL_SEC, d.sweep_interval_sec, False),
            grace_sec=self._read_num(vals, k.HEARTBEAT_GRACE_SEC, d.grace_sec, False),
        )

    def proxy_tunables(self) -> ProxyTunables:
        """代理池可调参数（消费时重读）。"""
        vals = self.get_all()
        d = self.ProxyTunables()
        k = self.Keys
        return self.ProxyTunables(
            ip_ttl_sec=self._read_num(vals, k.JULIANG_IP_TTL_SEC, d.ip_ttl_sec, False),
            ttl_margin_sec=self._read_num(vals, k.JULIANG_TTL_MARGIN_SEC, d.ttl_margin_sec, False),
            rotate_conn_threshold=self._read_num(vals, k.PROXY_ROTATE_CONN_THRESHOLD, d.rotate_conn_threshold, True),
            domain_cooldown_sec=self._read_num(vals, k.DOMAIN_COOLDOWN_SEC, d.domain_cooldown_sec, False),
            rotate_history_limit=self._read_num(vals, k.ROTATE_HISTORY_LIMIT, d.rotate_history_limit, True),
        )

    # ═══════════════ 配置元数据（ConfigField 清单）═══════════════

    def required_configs(self) -> list[ConfigField]:
        k = self.Keys
        return [
            self.ConfigField(
                key=k.DEEPSEEK_API_KEY, label="DeepSeek API 密钥", type="password",
                hint="获取地址：https://platform.deepseek.com/api-keys",
                validator=self.validate_api_key,
                category=ConfigCategory.MODELS,
            ),
            self.ConfigField(
                key=k.IDA_PRO_HOME, label="IDA Pro 安装目录", type="path",
                hint="该目录下需有 idat 可执行文件",
                validator=self.validate_ida_pro_home,
                category=ConfigCategory.TOOLS,
            ),
        ]

    def extra_configs(self) -> list[ConfigField]:
        k = self.Keys
        return [
            self.ConfigField(
                key=k.DEEPSEEK_MODEL, label="DeepSeek 模型名", type="text",
                hint="不配置默认 deepseek-flash（events MCP 提取模型；需要更强提取质量可改 deepseek-v4-pro）",
                required=False, default_value="deepseek-flash",
                category=ConfigCategory.MODELS,
            ),
            self.ConfigField(
                key=k.DEEPSEEK_SMALL_MODEL, label="DeepSeek 轻量模型名", type="text",
                hint="时间戳推断模型; 不配置默认 deepseek-flash",
                required=False, default_value="deepseek-flash",
                category=ConfigCategory.MODELS,
            ),
            self.ConfigField(
                key=k.HF_ENDPOINT, label="HuggingFace 端点", type="text",
                hint="国内直连不稳时配置镜像，如 https://hf-mirror.com",
                required=False,
                category=ConfigCategory.MODELS,
            ),
            self.ConfigField(
                key=k.GITHUB_TOKEN, label="GitHub API 令牌", type="password",
                hint="外部工具下载加速（防未认证 60 次/小时配额耗尽）；未配置时兜底 gh auth token",
                required=False,
                category=ConfigCategory.TOOLS,
            ),
            self.ConfigField(
                key=k.JULIANG_TRADE_NO, label="代理IP供应商订单号", type="text",
                hint="代理 IP 池用（juliangip.com 企业版套餐的业务编号，会员中心-业务管理获取）",
                required=False,
                category=ConfigCategory.PROXY,
            ),
            self.ConfigField(
                key=k.JULIANG_API_KEY, label="代理IP供应商 API 秘钥", type="password",
                hint="与订单号配套的 API Key（同页面获取）；两项都配置后 proxy MCP/代理池才可用",
                required=False,
                category=ConfigCategory.PROXY,
            ),
            self.ConfigField(
                key=k.RESUME_ANALYSIS_ENABLED, label="分析续传开关", type="bool",
                hint="未配置=开启（默认），0=关闭——会话压缩后自动注入分析状态续传提示",
                required=False,
                category=ConfigCategory.BEHAVIOR,
            ),
            self.ConfigField(
                key=k.REFLECT_NUDGE_ENABLED, label="反思提醒开关", type="bool",
                hint="反思纸条+反思唤醒两通道总开关; 未配置=开启（默认），0=关闭",
                required=False,
                category=ConfigCategory.BEHAVIOR,
            ),
            self.ConfigField(
                key=k.REFLECT_NUDGE_INTERVAL_MIN, label="反思提醒间隔（分钟）", type="text",
                hint="距上次反思超过该间隔即注入提醒; 默认 30 分钟，改后 30s 内生效",
                required=False, default_value="30",
                category=ConfigCategory.BEHAVIOR,
            ),
            self.ConfigField(
                key=k.CONTROL_FRONTEND_DEV, label="前端开发模式", type="bool",
                hint="1=vite dev(5173)，0/删除=发布态(dist/)。改后需重启控制台生效",
                required=False,
                category=ConfigCategory.DEVELOPER,
            ),
        ]

    def remote_link_configs(self) -> list[ConfigField]:
        """远程连接配置（surface=remote——远程资源页渲染）。

        ENABLED readonly=true: 写接口 422，只能经「切换远程」按钮
        （switch_to_remote 先校验后置位，见 routes/remote.py D10 守卫）。
        """
        k = self.Keys
        return [
            self.ConfigField(
                key=k.REMOTE_CONSOLE_URL, label="远程控制台链接", type="text",
                hint="远程节点（如 Mac Mini）控制台地址，如 http://192.168.1.20:9776",
                required=False,
                category=ConfigCategory.REMOTE, surface=Surface.REMOTE,
            ),
            self.ConfigField(
                key=k.REMOTE_CONSOLE_TOKEN, label="远程控制台令牌", type="password",
                hint="与远程节点 CONTROL_API_KEY 相同的值（Bearer 鉴权）",
                required=False,
                category=ConfigCategory.REMOTE, surface=Surface.REMOTE,
            ),
            self.ConfigField(
                key=k.REMOTE_CONSOLE_ENABLED, label="远程模型开关", type="bool",
                hint="只读——只能经「切换远程」按钮变更（先校验后置位）",
                required=False, readonly=True,
                category=ConfigCategory.REMOTE, surface=Surface.REMOTE,
            ),
        ]

    def node_side_configs(self) -> list[ConfigField]:
        """节点侧配置（surface=hidden——远程页节点管理卡片经专用端点管理）。

        写路径必须走 node-config 端点: CONTROL_API_KEY 变更触发重绑 0.0.0.0
        副作用，且支持转发远端节点（通用写接口到不了这些键，见 _guard_surface）。
        """
        k = self.Keys
        return [
            self.ConfigField(
                key=k.CONTROL_API_KEY, label="本机控制台鉴权令牌", type="password",
                hint="配置后本控制台对局域网开放推理类 API（Bearer 校验）并绑 0.0.0.0；远程节点（Mac Mini）用",
                required=False,
                category=ConfigCategory.REMOTE, surface=Surface.HIDDEN,
            ),
            self.ConfigField(
                key=k.CONTROL_RESIDENT, label="控制台常驻", type="bool",
                hint="1=禁用心跳自杀机制（无 opencode 连接也不退出）；远程节点用",
                required=False,
                category=ConfigCategory.REMOTE, surface=Surface.HIDDEN,
            ),
            self.ConfigField(
                key=k.CONTROL_AUTOSTART, label="开机自动启动", type="bool",
                hint="1=安装 LaunchAgent 开机自启（macOS，需开启自动登录）；远程节点用",
                required=False,
                category=ConfigCategory.REMOTE, surface=Surface.HIDDEN,
            ),
        ]

    # tunables 配置声明（拆三组; default_value 与 tunables dataclass 默认同源生成）

    def _tunable_field(self, key: str, label: str, default: "float | int", hint: str,
                       category: ConfigCategory, surface: Surface,
                       readonly: bool = False) -> "ConfigManager.ConfigField":
        return self.ConfigField(key=key, label=label, type="text", required=False,
                                category=category, surface=surface, readonly=readonly,
                                default_value=str(default), hint=hint)

    def proxy_tunable_configs(self) -> list[ConfigField]:
        """代理池调参（surface=config——配置页代理分类，可改，消费方重读即生效）。"""
        k = self.Keys
        pt = self.ProxyTunables()
        c, s = ConfigCategory.PROXY, Surface.CONFIG
        return [
            self._tunable_field(k.JULIANG_IP_TTL_SEC, "代理单 IP 存活（秒）", pt.ip_ttl_sec,
                                "单 IP 寿命（5 分钟档）", c, s),
            self._tunable_field(k.JULIANG_TTL_MARGIN_SEC, "代理到期余量（秒）", pt.ttl_margin_sec,
                                "到期安全余量", c, s),
            self._tunable_field(k.PROXY_ROTATE_CONN_THRESHOLD, "代理轮换连接阈值", pt.rotate_conn_threshold,
                                "proxy 模式下新建连接数满此值自动轮换", c, s),
            self._tunable_field(k.DOMAIN_COOLDOWN_SEC, "域名限流冷却（秒）", pt.domain_cooldown_sec,
                                "域名冷却 10 分钟档", c, s),
            self._tunable_field(k.ROTATE_HISTORY_LIMIT, "轮换历史上限", pt.rotate_history_limit,
                                "rotate_history 条数上限", c, s),
        ]

    def remote_tunable_configs(self) -> list[ConfigField]:
        """远程调参（surface=remote + readonly——远程页只读展示，写接口 422）。"""
        k = self.Keys
        rt = self.RemoteTunables()
        c, s = ConfigCategory.REMOTE_TUNING, Surface.REMOTE
        return [
            self._tunable_field(k.REMOTE_HEARTBEAT_INTERVAL_SEC, "远程心跳间隔（秒）", rt.heartbeat_interval_sec,
                                "远程节点健康探测周期; 修改后下个周期生效", c, s, readonly=True),
            self._tunable_field(k.REMOTE_FAIL_THRESHOLD, "远程降级阈值（连续失败次数）", rt.fail_threshold,
                                "连续失败达此次数 → 降级本地", c, s, readonly=True),
            self._tunable_field(k.REMOTE_RECOVER_THRESHOLD, "远程恢复阈值（连续成功次数）", rt.recover_threshold,
                                "降级后连续成功达此次数 → 切回远程", c, s, readonly=True),
            self._tunable_field(k.REMOTE_UNLOAD_DELAY_SEC, "恢复后稳定期（秒）", rt.unload_delay_sec,
                                "切回远程后稳定此时长才卸载本地模型（释放内存）", c, s, readonly=True),
            self._tunable_field(k.REMOTE_INFER_TIMEOUT_SEC, "远程推理超时（秒）", rt.infer_timeout_sec,
                                "远程 embed/rerank/ocr 请求超时", c, s, readonly=True),
            self._tunable_field(k.REMOTE_PROBE_TIMEOUT_SEC, "远程探测超时（秒）", rt.probe_timeout_sec,
                                "健康探测请求超时（应远小于心跳间隔）", c, s, readonly=True),
        ]

    def heartbeat_tunable_configs(self) -> list[ConfigField]:
        """心跳协议调参（surface=hidden——无页面; 手编 .ai_env，每轮 sweep 重读）。"""
        k = self.Keys
        ht = self.HeartbeatTunables()
        c, s = ConfigCategory.SYSTEM, Surface.HIDDEN
        return [
            self._tunable_field(k.HEARTBEAT_TIMEOUT_SEC, "心跳超时（秒）", ht.timeout_sec,
                                "opencode 超此时长未跳心跳 → 移除条目", c, s),
            self._tunable_field(k.HEARTBEAT_SWEEP_INTERVAL_SEC, "心跳 sweep 周期（秒）", ht.sweep_interval_sec,
                                "后台周期清理间隔", c, s),
            self._tunable_field(k.HEARTBEAT_GRACE_SEC, "心跳启动宽限（秒）", ht.grace_sec,
                                "表空超过此时长才自杀（覆盖 spawn 就绪等待+首跳）", c, s),
        ]

    def _all_fields(self) -> list[ConfigField]:
        """全部声明字段（config_meta 过滤与 _guard_surface 校验的数据源）。"""
        return [*self.required_configs(), *self.extra_configs(),
                *self.remote_link_configs(), *self.node_side_configs(),
                *self.proxy_tunable_configs(), *self.remote_tunable_configs(),
                *self.heartbeat_tunable_configs()]

    def field_of(self, key: str) -> "ConfigField | None":
        """按键名查声明字段（未声明返回 None——写校验兜底语义用）。"""
        for field in self._all_fields():
            if field.key == key:
                return field
        return None

    def config_meta(self, surface: Surface) -> ConfigMetaView:
        """单 surface 的配置元数据（页面组成权威; 分类序=枚举定义序）。

        未知 .ai_env 键兜底: 仅 config 面，OTHER 分类（label=键名）;
        remote 面不兜底（远程页只渲染已声明配置）。
        """
        entries: dict[str, ConfigMetaEntry] = {}
        cats_with_entries: set[ConfigCategory] = set()
        for field in self._all_fields():
            if field.surface != surface:
                continue
            entries[field.key] = ConfigMetaEntry(
                label=field.label, type=field.type, hint=field.hint,
                required=field.required, default_value=field.default_value,
                category_code=field.category.value,
                category_desc=field.category.desc,
                readonly=field.readonly, source=field.source,
            )
            cats_with_entries.add(field.category)
        if surface == Surface.CONFIG:
            declared = {f.key for f in self._all_fields()}
            for key in self.get_all():
                if key not in declared:
                    entries[key] = ConfigMetaEntry(
                        label=key, type="text", hint="",
                        required=False, default_value="",
                        category_code=ConfigCategory.OTHER.value,
                        category_desc=ConfigCategory.OTHER.desc,
                        readonly=False, source="ai_env",
                    )
                    cats_with_entries.add(ConfigCategory.OTHER)
        categories = [CategoryView(code=c.value, desc=c.desc)
                      for c in ConfigCategory.ordered() if c in cats_with_entries]
        return ConfigMetaView(categories=categories, entries=entries)

    @dataclass(frozen=True)
    class ConfigStatusView:
        """单个必要配置的完整性状态（前端 banner 用）。"""
        key: str
        label: str
        ok: bool
        hint: str
        error: str

    def required_status(self) -> list[ConfigStatusView]:
        configs = self.get_all()
        result: list[ConfigManager.ConfigStatusView] = []
        for field in self.required_configs():
            value = configs.get(field.key, "")
            ok = bool(value)
            validator_msg = ""
            if ok and field.validator:
                v_ok, validator_msg = field.validator(value)
                ok = v_ok
            result.append(self.ConfigStatusView(
                key=field.key, label=field.label, ok=ok, hint=field.hint,
                error=validator_msg if not ok and validator_msg else "",
            ))
        return result

    # ═══════════════ validators ═══════════════

    def validate_ida_pro_home(self, value: str) -> tuple[bool, str]:
        """校验 IDA_PRO_HOME: 目录存在 + idat 可执行文件存在。"""
        path = Path(os.path.abspath(os.path.expanduser(value)))
        if not path.exists():
            return False, f"目录不存在：{value}"
        exe = "idat.exe" if self.is_windows else "idat"
        if not (path / exe).exists():
            return False, f"目录下未找到 {exe}"
        return True, ""

    def validate_api_key(self, value: str) -> tuple[bool, str]:
        """校验 API key 非空（具体格式不验证，DeepSeek 兼容多种格式）。"""
        if len(value) < 10:
            return False, "API key 长度异常（<10 字符）"
        return True, ""
