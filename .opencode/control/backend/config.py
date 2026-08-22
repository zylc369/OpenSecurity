"""控制台后端常量收口模块。

所有硬编码的魔法值（端口、模型名、超时时间、路径）统一在此声明，
其他模块只导入不重复定义。修改时只改这一处。
"""
from __future__ import annotations

from pathlib import Path
import os
import sys

# ─── 数据目录 ──────────────────────────────────────────────
# DATA_DIR 由 Plugin spawn 时通过环境变量传入，缺省回退到默认路径。
# 所有运行时状态（IPC socket、日志）都在此目录下。
DATA_DIR = os.environ.get("DATA_DIR", str(Path.home() / "bw-security-analysis"))

# OPENCODE_ROOT 由 Plugin spawn 时传入，用于定位 .ai_env 等项目级文件。
OPENCODE_ROOT = os.environ.get("OPENCODE_ROOT", "")

# ─── 运行时状态 ──────────────────────────────────────────
# opencode 引用计数 = 内存心跳表（services/heartbeat.py），无状态文件。

# ─── 心跳协议 ──────────────────────────────────────────────
# opencode 插件每 HEARTBEAT_INTERVAL_SEC（TS 侧常量，协议两端一致）POST /api/heartbeat；
# 控制台 HeartbeatTask 周期 sweep：超过 HEARTBEAT_TIMEOUT_SEC 未跳 → 移除；
# 表空且已过启动宽限（HEARTBEAT_GRACE_SEC，覆盖 spawn 者的就绪等待+首跳）→ 自杀。
# 各值 env 可覆盖，供测试注入小值加速验证。
HEARTBEAT_TIMEOUT_SEC = float(os.environ.get("HEARTBEAT_TIMEOUT_SEC", "60"))
HEARTBEAT_SWEEP_INTERVAL_SEC = float(os.environ.get("HEARTBEAT_SWEEP_INTERVAL_SEC", "10"))
HEARTBEAT_GRACE_SEC = float(os.environ.get("HEARTBEAT_GRACE_SEC", "90"))

# ─── IPC 与网络 ───────────────────────────────────────────
# 程序间通信（插件/MCP/vite 上报）走 IPC，无端口、无发现文件：
#   • macOS/Linux：Unix Domain Socket，路径编译期固定
#   • Windows：命名管道，名字编译期固定（随机后缀防其他程序撞名）
# 浏览器与 vite dev 代理走 TCP（浏览器只能 TCP，物理限制），
# 真实端口经 frontend_port 注册中心 + /api/console-url 对外。
# 单例互斥 = IPC bind 内核排他（EADDRINUSE / FIRST_PIPE_INSTANCE）；
# 并发启动的败者在 IpcListener.start 内轮询等待胜者就绪后复用，不报错。
IS_WINDOWS = sys.platform == "win32"
# 浏览器 TCP 通道：9776 起顺延候选段（起点被占自动 +1）。
# 真实端口唯一事实源 = services/frontend_port.py（bind 后注册，/api/console-url 对外）。
# CONTROL_TCP_PORT 环境变量仅供测试沙箱重定向起点。
CONTROL_TCP_PORT_START = 9776
TCP_CANDIDATE_COUNT = 10
BIND_HOST = "127.0.0.1"           # 仅本机访问（安全约束，禁止 0.0.0.0）
IPC_UNIX_SOCKET_NAME = "opensecurity-control.sock"
# 6 位随机后缀：写代码时一次性生成写死（来源 openssl rand），非运行期分配
IPC_WINDOWS_PIPE = r"\\.\pipe\opensecurity-control-482964"


def ipc_unix_socket_path() -> Path:
    """Unix socket 路径（macOS/Linux）。"""
    return Path(DATA_DIR) / IPC_UNIX_SOCKET_NAME


def ipc_addr() -> str:
    """当前平台的 IPC 会合地址（Unix: 文件路径 / Windows: 管道名）。"""
    if IS_WINDOWS:
        return IPC_WINDOWS_PIPE
    return str(ipc_unix_socket_path())

# ─── 模型 ─────────────────────────────────────────────────
EMBED_MODEL = "BAAI/bge-m3"
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"

# ─── 超时时间（毫秒/秒，按字段标注）──────────────────────
MODEL_LOAD_TIMEOUT_SEC = 60        # 模型加载超时（Plugin 端等待）
HEALTH_POLL_INTERVAL_SEC = 2       # /health 轮询间隔
IPC_BIND_WAIT_SEC = 8              # 并发启动败者等待胜者 bind 完成的轮询窗口

# ─── 必要配置清单（缺一项则前端 banner 红色提醒）─────────
# 用 dataclass 而非裸 dict，便于 IDE 类型提示和后续扩展。
from dataclasses import dataclass
from typing import Callable

@dataclass
class ConfigField:
    """配置字段元数据。"""
    key: str                                # .ai_env 中的 key
    label: str                              # 前端展示的中文名
    type: str                               # password / path / text / bool
    hint: str = ""                          # 字段说明 / 获取地址
    required: bool = True                   # 是否必要（缺失时 banner 提醒）
    validator: Callable[[str], tuple[bool, str]] | None = None  # 校验函数
    default_value: str = ""                 # 后端消费方的默认值（不配置时的行为，收口回传前端）

REQUIRED_CONFIGS: list[ConfigField] = [
    ConfigField(
        key="DEEPSEEK_API_KEY",
        label="DeepSeek API 密钥",
        type="password",
        hint="获取地址：https://platform.deepseek.com/api-keys",
        # validator 在 config_store.validate_api_key 定义，避免循环 import
    ),
    ConfigField(
        key="IDA_PRO_HOME",
        label="IDA Pro 安装目录",
        type="path",
        hint="该目录下需有 idat 可执行文件",
    ),
]

# 非 REQUIRED_CONFIGS 键的元数据（.ai_env 中存在但不在必要清单里的配置）。
# /api/config/meta 对 REQUIRED_CONFIGS 与本表取并集；两边都没有的键按
# {"type": "text", "required": false, "label": key} 兜底。
EXTRA_CONFIG_META: list[ConfigField] = [
    ConfigField(
        key="DEEPSEEK_MODEL",
        label="DeepSeek 模型名",
        type="text",
        hint="不配置默认 deepseek-v4-flash（events MCP 提取模型；需要更强提取质量可改 deepseek-v4-pro）",
        required=False,
        default_value="deepseek-v4-flash",
    ),
    ConfigField(
        key="CONTROL_FRONTEND_DEV",
        label="前端开发模式",
        type="bool",
        hint="1=vite dev(5173)，0/删除=发布态(dist/)。改后需重启控制台生效",
        required=False,
    ),
    ConfigField(
        key="RESUME_ANALYSIS_ENABLED",
        label="分析续传开关",
        type="bool",
        hint="1=会话压缩后自动注入分析状态续传提示",
        required=False,
    ),
]


def _init_validators():
    """延迟绑定 validator（避免循环 import）。

    config_store 导入 config（ConfigField），所以 config 不能 import config_store。
    用延迟绑定：服务启动后由 server.py 调用一次。
    """
    from services import config_store
    for cfg_field in REQUIRED_CONFIGS:
        if cfg_field.key == "DEEPSEEK_API_KEY":
            cfg_field.validator = config_store.validate_api_key
        elif cfg_field.key == "IDA_PRO_HOME":
            cfg_field.validator = config_store.validate_ida_pro_home

# ─── 开发态开关 ───────────────────────────────────────────
# 控制台前端开发模式开关。优先级：环境变量 CONTROL_FRONTEND_DEV > .ai_env。
# 环境变量优先是为了让测试/CI 不落地修改 .ai_env（改文件在 kill -9 时无法还原，
# 会把开发机开关永久污染）。生产环境 Plugin 不注入此变量，走 .ai_env。
# 启用（1/true）→ 不挂载 dist/，走 Vite 5173；禁用 → 挂载 dist/。
def is_dev_mode() -> bool:
    """启动期一次性读取（不走 config_store，避免循环依赖）。"""
    env_val = os.environ.get("CONTROL_FRONTEND_DEV")
    if env_val is not None:
        return env_val.strip().lower() in ("1", "true")
    if not OPENCODE_ROOT:
        return False
    ai_env_path = Path(OPENCODE_ROOT) / ".ai_env"
    if not ai_env_path.exists():
        return False
    for line in ai_env_path.read_text(errors="ignore").splitlines():
        if line.strip().startswith("CONTROL_FRONTEND_DEV="):
            value = line.split("=", 1)[1].strip().lower()
            return value in ("1", "true")
    return False

# ─── exit code 约定（控制台进程退出码）───────────────────
# Plugin 通过 exit code 判断控制台状态。
EXIT_CODE_REUSE = 2          # 已有实例运行，本进程主动退出复用
EXIT_CODE_PORT_EXHAUSTED = 3 # 候选端口全部占用
EXIT_CODE_NORMAL = 0         # 正常退出（心跳表空，自杀）
