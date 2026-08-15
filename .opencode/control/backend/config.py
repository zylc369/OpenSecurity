"""控制台后端常量收口模块。

所有硬编码的魔法值（端口、模型名、超时时间、路径）统一在此声明，
其他模块只导入不重复定义。修改时只改这一处。
"""
from __future__ import annotations

from pathlib import Path
import os

# ─── 数据目录 ──────────────────────────────────────────────
# DATA_DIR 由 Plugin spawn 时通过环境变量传入，缺省回退到默认路径。
# 所有运行时文件（端口文件、users 文件、lock 文件）都在此目录下。
DATA_DIR = os.environ.get("DATA_DIR", str(Path.home() / "bw-security-analysis"))

# OPENCODE_ROOT 由 Plugin spawn 时传入，用于定位 .ai_env 等项目级文件。
OPENCODE_ROOT = os.environ.get("OPENCODE_ROOT", "")

# ─── 运行时文件路径（统一命名，避免散落）─────────────────
PORT_FILE = Path(DATA_DIR) / ".opencode-control.port"
USERS_FILE = Path(DATA_DIR) / ".opencode-control.users"
LOCK_FILE = Path(DATA_DIR) / ".opencode-control.lock"

# ─── 网络 ─────────────────────────────────────────────────
# 候选端口列表：第一个候选失败则递增尝试，全部失败则报错。
# 用户可在 .ai_env 设置 CONTROL_PORT 覆盖默认起始端口。
DEFAULT_PORT_START = 9776
PORT_CANDIDATE_COUNT = 5  # 候选数量（含起始端口）
BIND_HOST = "127.0.0.1"   # 仅本机访问（安全约束，禁止 0.0.0.0）

def get_port_candidates() -> list[int]:
    """返回候选端口列表。优先级：CONTROL_PORT 环境变量 > .ai_env 的 CONTROL_PORT > 默认。

    环境变量优先是为了让测试在不落地改 .ai_env 的情况下注入随机高位起始端口
    （避免和生产控制台的 9776 冲突）。
    """
    start = DEFAULT_PORT_START
    env_val = os.environ.get("CONTROL_PORT")
    if env_val and env_val.isdigit():
        start = int(env_val)
    elif OPENCODE_ROOT:
        ai_env_path = Path(OPENCODE_ROOT) / ".ai_env"
        if ai_env_path.exists():
            for line in ai_env_path.read_text(errors="ignore").splitlines():
                if line.strip().startswith("CONTROL_PORT="):
                    try:
                        start = int(line.split("=", 1)[1].strip())
                    except ValueError:
                        pass
                    break
    return list(range(start, start + PORT_CANDIDATE_COUNT))

# ─── 模型 ─────────────────────────────────────────────────
EMBED_MODEL = "BAAI/bge-m3"
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"

# ─── 超时时间（毫秒/秒，按字段标注）──────────────────────
MODEL_LOAD_TIMEOUT_SEC = 60        # 模型加载超时（Plugin 端等待）
HEALTH_POLL_INTERVAL_SEC = 2       # /health 轮询间隔
PORT_FILE_WAIT_SEC = 5             # 端口文件出现等待
USERS_CLEANUP_INTERVAL_SEC = int(os.environ.get("USERS_CLEANUP_INTERVAL_SEC", "60"))  # users 文件周期清洗间隔

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
EXIT_CODE_NORMAL = 0         # 正常退出（users 空，自杀）
