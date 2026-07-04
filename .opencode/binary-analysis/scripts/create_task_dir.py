"""创建任务目录并注册 sessionID 映射

用法:
    python create_task_dir.py
    python create_task_dir.py --max-duration 2

行为:
    在 ~/bw-security-analysis/workspace/ 下创建时间戳+随机数命名的目录，
    同时注册 sessionID → task_dir 映射到 .task_sessions/{sessionID}.json，
    用于压缩后精确恢复。

    同时创建 .persistence.json 文件，记录分析持续性配置（最大持续时间等）。

    --max-duration: 指定最大持续分析时间（小时），默认 6 小时。
                    超过此时间后安全分析 Agent 不再自动恢复。
                    Agent 可在初始化时通过此参数传入用户指定的值。

    sessionID 从环境变量 SESSION_ID 读取（由 Plugin shell.env hook 注入）。
    如果 SESSION_ID 为空，则只创建目录不注册映射。

依赖: 仅标准库（os, json, random, datetime, argparse）
"""

import os
import json
import random
import argparse
from datetime import datetime

WORKSPACE = os.path.expanduser("~/bw-security-analysis/workspace")
TASK_SESSIONS = os.path.join(WORKSPACE, ".task_sessions")

# 分析持续性默认配置
DEFAULT_MAX_DURATION_HOURS = 6


def _register(session_id, task_dir):
    """注册 sessionID → task_dir 映射"""
    if not session_id:
        return
    os.makedirs(TASK_SESSIONS, exist_ok=True)
    mapping_file = os.path.join(TASK_SESSIONS, f"{session_id}.json")
    with open(mapping_file, "w") as f:
        json.dump({"task_dir": task_dir}, f)


def _init_persistence(task_dir, max_duration_hours=DEFAULT_MAX_DURATION_HOURS):
    """创建 .persistence.json 配置文件

    如果文件已存在则不覆盖（保留用户手动修改的值）。
    max_duration_hours: 最大持续分析时间（小时），范围 (0, 24]。
    """
    persistence_file = os.path.join(task_dir, ".persistence.json")
    if os.path.exists(persistence_file):
        return
    # 钳位到合理范围
    if max_duration_hours <= 0 or max_duration_hours > 24:
        max_duration_hours = DEFAULT_MAX_DURATION_HOURS
    data = {
        "max_duration_hours": max_duration_hours,
        "resume_count": 0,
        "last_resume_at": None,
    }
    with open(persistence_file, "w") as f:
        json.dump(data, f, indent=2)


def create(max_duration_hours=DEFAULT_MAX_DURATION_HOURS):
    """创建新任务目录并注册映射。

    幂等：同一 sessionID 重复调用时返回已映射的目录，不新建。
    防止 Plugin ensureTaskDir 和 agent prompt 命令双重触发时产生孤儿目录。
    映射文件损坏（非法 JSON / 路径失效）时降级到新建流程。
    """
    session_id = os.environ.get("SESSION_ID", "")

    # 幂等检查：sessionID 已有映射则直接返回已有目录
    if session_id:
        mapping_file = os.path.join(TASK_SESSIONS, f"{session_id}.json")
        if os.path.isfile(mapping_file):
            try:
                with open(mapping_file) as f:
                    existing = json.load(f)
                existing_dir = existing.get("task_dir", "")
                if existing_dir and os.path.isdir(existing_dir):
                    print(existing_dir)
                    return
            except (json.JSONDecodeError, OSError):
                pass  # 映射文件损坏，走新建流程覆盖

    os.makedirs(WORKSPACE, exist_ok=True)
    name = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + format(random.randint(0, 65535), "04x")
    task_dir = os.path.join(WORKSPACE, name)
    os.makedirs(task_dir, exist_ok=True)

    _register(session_id, task_dir)

    # 创建 .persistence.json 配置
    _init_persistence(task_dir, max_duration_hours)

    print(task_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="创建任务目录并注册 sessionID 映射"
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        default=DEFAULT_MAX_DURATION_HOURS,
        metavar="HOURS",
        help=f"最大持续分析时间（小时），默认 {DEFAULT_MAX_DURATION_HOURS}。超过此时间后不再自动恢复。",
    )
    args = parser.parse_args()
    create(max_duration_hours=args.max_duration)
