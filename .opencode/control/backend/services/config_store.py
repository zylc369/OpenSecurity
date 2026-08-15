"""配置存储收口模块（.ai_env 唯一读写方）。

其他模块禁止直接 open(.ai_env)（grep 验证唯一性，唯一例外是 server.py 启动期 is_dev_mode）。

.ai_env 格式：
  KEY=VALUE（每行一个，#开头是注释，空行忽略）
  VALUE 不去引号（保留原始字符串）

未来如果要换 sqlite，只改本模块的实现，外部 API 不变。
"""
from __future__ import annotations

from pathlib import Path

from config import OPENCODE_ROOT, REQUIRED_CONFIGS
from services.process_lock import atomic_write


def _ai_env_path() -> Path:
    """返回 .ai_env 路径。"""
    return Path(OPENCODE_ROOT) / ".ai_env"


def _parse(content: str) -> dict[str, str]:
    """解析 .ai_env 内容。容错：格式错的行跳过。"""
    result = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key:
            result[key] = value
    return result


def _serialize(configs: dict[str, str]) -> str:
    """序列化为 .ai_env 格式（KEY=VALUE）。

    保留原有注释：调用方传入完整 dict，注释由调用方决定是否保留。
    本函数只负责格式化，不处理注释。
    """
    lines = []
    for key, value in configs.items():
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def _read_with_comments() -> tuple[dict[str, str], list[str]]:
    """读 .ai_env，返回 (configs, raw_lines)。

    raw_lines 包含注释和空行，用于写回时保留注释。
    """
    path = _ai_env_path()
    if not path.exists():
        return {}, []
    raw_lines = path.read_text(errors="ignore").splitlines()
    configs = _parse("\n".join(raw_lines))
    return configs, raw_lines


def read_all() -> dict[str, str]:
    """读全部配置。"""
    return _read_with_comments()[0]


def read(key: str) -> str | None:
    """读单个配置。"""
    return read_all().get(key)


def write(updates: dict[str, str]) -> dict[str, str]:
    """批量更新配置（保留原有注释 + 其他未改动的字段）。

    Args:
        updates: 要更新的 key-value 字典。value 统一 strip()
        （空格不可见，路径/密钥尾部空格是低级但难排查的问题——服务端兜底 trim）。

    Returns:
        更新后的完整配置。
    """
    updates = {k: v.strip() if isinstance(v, str) else v for k, v in updates.items()}
    configs, raw_lines = _read_with_comments()
    configs.update(updates)

    # 重写 raw_lines：找到对应行替换，找不到则追加
    new_lines = []
    updated_keys = set()
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

    # 新增的 key（原有 .ai_env 没有的）
    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}")

    # 原子写
    atomic_write(_ai_env_path(), "\n".join(new_lines) + "\n")
    return configs


def write_one(key: str, value: str) -> dict[str, str]:
    """更新单个配置。"""
    return write({key: value})


def delete(key: str) -> dict[str, str]:
    """删除单个配置。"""
    configs, raw_lines = _read_with_comments()
    if key not in configs:
        return configs

    # 重写 raw_lines：跳过要删除的 key
    new_lines = []
    for line in raw_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k == key:
                continue
        new_lines.append(line)

    atomic_write(_ai_env_path(), "\n".join(new_lines) + "\n")
    configs.pop(key, None)
    return configs


def required_status() -> dict[str, dict]:
    """返回必要配置的完整性状态（前端 banner 用）。

    Returns:
        {
            "DEEPSEEK_API_KEY": {"label": "...", "ok": true, "hint": "..."},
            ...
        }
    """
    configs = read_all()
    result = {}
    for field in REQUIRED_CONFIGS:
        value = configs.get(field.key, "")
        ok = bool(value)
        # 如果有 validator，进一步校验
        validator_msg = ""
        if ok and field.validator:
            v_ok, validator_msg = field.validator(value)
            ok = v_ok
        result[field.key] = {
            "label": field.label,
            "ok": ok,
            "hint": field.hint,
            "error": validator_msg if not ok and validator_msg else "",
        }
    return result


# ─── 内置 validator ──────────────────────────────────────


def validate_ida_pro_home(value: str) -> tuple[bool, str]:
    """校验 IDA_PRO_HOME：目录存在 + idat 可执行文件存在。"""
    import sys
    path = Path(value)
    if not path.exists():
        return False, f"目录不存在：{value}"
    exe = "idat.exe" if sys.platform == "win32" else "idat"
    if not (path / exe).exists():
        return False, f"目录下未找到 {exe}"
    return True, ""


def validate_api_key(value: str) -> tuple[bool, str]:
    """校验 API key 非空（具体格式不验证，DeepSeek 兼容多种格式）。"""
    if len(value) < 10:
        return False, "API key 长度异常（<10 字符）"
    return True, ""
